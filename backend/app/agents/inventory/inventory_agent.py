"""Inventory Agent (Phase 3). Owns availability, allocation and safety stock; detects shortages and starts procurement.

    assess_requirements   Planning's material requirements -> availability from inventory_service (C1 rule
                          available = on_hand - reserved - safety_stock). A covered requirement gets an allocation
                          proposal (informational; nothing is reserved before COMMIT). A shortage (the same deterministic
                          figure MRP produced, P0-02) gets one negotiation session and a REQUEST to Purchasing over A2A.
    on_negotiation_result AGREEMENT_PROPOSED / REJECTED / FAILED -> recorded, then passed to Planning (by the workflow).
    reserve_for_order     Phase 4 (D8): after the human approved and COMMIT happened, reserve the plan's stock.

How Planning's request reaches this agent is P1-06 (still open): for now an in-process call, not a negotiation session.
The agent never selects suppliers, negotiates supplier terms, changes plans or reserves stock before COMMIT (C8, D8).
"""

import uuid

from sqlalchemy.orm import Session

from app.agents.base import (
    SUMMARY_MAX,
    Agent,
    AgentStateData,
    DialogueEntry,
    Goal,
    NegotiationRules,
    Refs,
    Task,
    build_message,
    now,
    offer_history,
    plain,
)
from app.schemas.domain import InventoryPosition, PlanSnapshot, Shortage
from app.schemas.negotiation import AgentType, MessageType, OfferTerms, SessionStatus
from app.services import inventory_service, negotiation_service
from app.services.audit_service import AGENT_INVENTORY, DecisionType


ACTIVE_STATUSES = {SessionStatus.INITIATED.value, SessionStatus.NEGOTIATING.value, SessionStatus.AGREEMENT_PROPOSED.value}


def _request_terms(shortage: Shortage) -> OfferTerms:
    return OfferTerms(
        quantity=shortage.shortage_quantity, required_date=shortage.required_by, priority=shortage.priority
    )


class InventoryAgent(Agent):
    agent_code = AGENT_INVENTORY

    def assess_requirements(self, db: Session, plan: PlanSnapshot) -> list[dict]:
        """Decide per requirement: allocate from stock, or procure (one session per shortage, REQUEST over A2A)."""
        order_id = uuid.UUID(plan.order_id)
        positions = inventory_service.get_positions(db, {r.item_id for r in plan.requirements})
        existing = {  # active sessions only: an ended one (e.g. of a rejected attempt) allows a new negotiation
            (v["objective"]["mps_entry_id"], v["objective"]["item_id"])
            for v in negotiation_service.sessions_for_order(db, order_id)
            if v["status"] in ACTIVE_STATUSES
        }
        assessment = []
        for row in plan.requirements:
            position = positions.get(row.item_id) or inventory_service.get_position(db, row.item_id)
            if row.net_requirement == 0:
                action = "ALLOCATE_FROM_STOCK"
            elif (row.mps_entry_id, row.item_id) in existing:
                action = "NEGOTIATION_EXISTS"
            else:
                action = "PROCUREMENT_REQUESTED"
            assessment.append({
                "item_id": row.item_id,
                "mps_entry_id": row.mps_entry_id,
                "gross_requirement": row.gross_requirement,
                "available_quantity": position.available_quantity,
                "safety_stock": position.safety_stock,
                "proposed_allocation": min(row.gross_requirement, position.available_quantity),
                "shortage_quantity": row.net_requirement,
                "required_by": row.required_by,
                "action": action,
            })
        requested = sum(1 for a in assessment if a["action"] == "PROCUREMENT_REQUESTED")
        self.audit(
            db, DecisionType.AVAILABILITY_ASSESSED, {"order_id": plan.order_id}, {"requirements": assessment},
            f"{len(assessment)} requirements assessed; {requested} shortages sent to Purchasing. "
            "Allocations are proposals only; nothing is reserved before COMMIT.",
        )
        db.commit()
        for shortage in plan.shortages:
            if (shortage.mps_entry_id, shortage.item_id) not in existing:
                position = positions.get(shortage.item_id) or inventory_service.get_position(db, shortage.item_id)
                self._request_procurement(db, shortage, position)
        return plain(assessment)

    def _request_procurement(self, db: Session, shortage: Shortage, position: InventoryPosition) -> None:
        view = negotiation_service.open_session(db, uuid.UUID(shortage.order_id), uuid.UUID(shortage.item_id))
        note = (
            f"Shortage for order {shortage.order_id}: {shortage.shortage_quantity} of item {shortage.item_id} "
            f"required by {shortage.required_by}, priority {shortage.priority} (available {shortage.available_quantity}, "
            f"projected {shortage.projected_available_quantity})."
        )
        self._record(db, view, shortage, position, "PURCHASING",
                     f"Requested {shortage.shortage_quantity} by {shortage.required_by} from Purchasing.")
        ack = self.send(db, build_message(view, AgentType.INVENTORY, AgentType.PURCHASING, MessageType.REQUEST,
                                          _request_terms(shortage), note))
        if not ack["accepted"]:
            view = negotiation_service.get_session_view(db, uuid.UUID(view["id"]))
            self._record(db, view, shortage, position, "PURCHASING", f"REQUEST refused: {ack['error']['message']}")

    def reserve_for_order(self, db: Session, plan: PlanSnapshot) -> list[dict]:
        """D8, after COMMIT only: reserve the stock the approved plan uses, through inventory_service (never safety
        stock). Per requirement: min(gross requirement, available quantity the MRP used)."""
        reservations = []
        for row in plan.requirements:
            quantity = min(row.gross_requirement, row.available_quantity)
            if quantity > 0:
                reservation_id = inventory_service.reserve(db, uuid.UUID(row.item_id), uuid.UUID(plan.order_id), quantity)
                reservations.append({"item_id": row.item_id, "quantity": quantity, "reservation_id": str(reservation_id)})
        self.audit(db, DecisionType.STOCK_RESERVED, {"order_id": plan.order_id}, {"reservations": reservations},
                   f"Reserved stock for {len(reservations)} components of the approved plan (after COMMIT).")
        db.commit()
        return plain(reservations)

    def on_negotiation_result(self, db: Session, negotiation_id: uuid.UUID) -> dict:
        """Record the session result and return what goes to Planning (outcome AGREEMENT, or FAILED for REJECTED/FAILED)."""
        view = negotiation_service.get_session_view(db, negotiation_id)
        shortage = Shortage.model_validate(view["objective"])
        result = {
            "negotiation_id": view["id"],
            "order_id": shortage.order_id,
            "item_id": shortage.item_id,
            "shortage_quantity": shortage.shortage_quantity,
            "required_by": shortage.required_by,
            "session_status": view["status"],
            "outcome": view["outcome"],
            "rounds": view["round_number"],
            "agreement": view["agreement"],
        }
        if view["outcome"] == "AGREEMENT":
            terms = view["agreement"]["agreed_terms"]
            summary = (f"Purchasing proposed {terms['quantity']} by {terms['delivery_date']}; passed to Planning. "
                       "Nothing is reserved or committed before human approval (COMMIT, C8).")
        else:
            summary = f"Negotiation ended {view['status']} without agreement; passed to Planning as FAILED."
        context = {"order_id": shortage.order_id, "item_id": shortage.item_id, "negotiation_id": view["id"]}
        self.audit(db, DecisionType.NEGOTIATION_RESULT_RECEIVED, context, result, summary)
        position = inventory_service.get_position(db, shortage.item_id)
        self._record(db, view, shortage, position, "PURCHASING", summary)
        return plain(result)

    def _record(self, db: Session, view: dict, shortage: Shortage, position: InventoryPosition, counterpart: str,
                summary: str) -> None:
        """C6 state for this negotiation, then commit."""
        waiting = view["outcome"] is None
        state = self.load_state(db)
        entry = DialogueEntry(round=view["round_number"] or None, counterpart=counterpart, summary=summary[:SUMMARY_MAX], at=now())
        refs = Refs(order_id=shortage.order_id, mps_entry_id=shortage.mps_entry_id, item_id=shortage.item_id,
                    negotiation_id=view["id"])
        self.save_state(db, AgentStateData(
            current_goal=Goal(
                goal_type="ALLOCATE_WITHIN_CONSTRAINTS",
                description=f"Cover item {shortage.item_id} for order {shortage.order_id}: "
                            f"{position.available_quantity} from stock, {shortage.shortage_quantity} via procurement",
                refs=refs,
            ),
            current_task=Task(
                task_type="AWAIT_NEGOTIATION_RESULT" if waiting else "RESULT_PASSED_TO_PLANNING",
                status="WAITING" if waiting else "DONE",
                refs=Refs(negotiation_id=view["id"]),
                started_at=view["started_at"],
            ),
            preferred_terms=_request_terms(shortage),
            reserved_limits=plain({"minimum_reserve": position.safety_stock,
                                   "max_allocation": position.available_quantity}),
            initial_proposal=_request_terms(shortage),
            own_offer_history=[],  # REQUEST opens the session; it is not a supplier round
            opponent_offer_history=offer_history(view)["AGREEMENT"],
            dialogue_history=self.dialogue(state, "negotiation_id", view["id"], entry),
            negotiation_rules=NegotiationRules(policy=plain({
                "allocation_policy": "priority then required date",
                "safety_stock_policy": "never allocate below safety stock",
                "minimum_reserve": position.safety_stock,
                "acceptable_allocation_range": {"min": 0, "max": position.available_quantity},
            })),
        ))
        db.commit()
