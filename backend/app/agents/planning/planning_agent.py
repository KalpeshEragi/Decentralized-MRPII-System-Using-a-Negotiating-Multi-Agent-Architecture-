"""Production Planning Agent (Phase 3 core). Owns the production plan and material requirements.

    handle_order           order intake -> deterministic plan (planning_service: finished goods -> MPS -> capacity ->
                           BOM -> MRP) -> material requirements to the Inventory Agent (P1-06 still open: in-process
                           request, no negotiation session). Returns once every new session has had its first round.
    on_procurement_result  the negotiated result passed on by Inventory: AGREEMENT, or FAILED (session REJECTED or
                           FAILED). Recorded only. After FAILED the shortage stays unresolved and the plan is not
                           updated; an agreement is not committed (human approval and COMMIT are Phase 4, C8).

    replan                 Phase 4 (C8): after the human rejects attempt 1, plan again as attempt 2; Inventory opens
                           new negotiations for the shortages that remain.
    on_plan_approved       Phase 4 (D8): after COMMIT, plan again (committed agreements are now scheduled receipts)
                           and pass the requirements to Inventory for reservation.

Each planning run is a C8 attempt, recorded through `approval_service`. Handing an order that already has an attempt
to Planning again does not replan; replanning happens only after an explicit rejection.
Planning never opens negotiations, creates requisitions, selects suppliers, reserves stock or approves plans.
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
    now,
    plain,
)
from app.agents.inventory.inventory_agent import InventoryAgent
from app.schemas.domain import CustomerOrder
from app.schemas.negotiation import OfferTerms
from app.services import approval_service, negotiation_service, order_service, planning_service
from app.services.audit_service import AGENT_PLANNING, DecisionType


class PlanningAgent(Agent):
    agent_code = AGENT_PLANNING

    def handle_order(self, db: Session, order_id: uuid.UUID) -> dict:
        existing = approval_service.current(db, order_id)
        if existing is not None:  # already planned: no replan without an explicit rejection (C8)
            plan = planning_service.get_plan(db, order_id)
            return self._summary(db, order_id, plan, None, existing)
        return self._plan_attempt(db, order_id, 1)

    def replan(self, db: Session, order_id: uuid.UUID, attempt_number: int) -> dict:
        """C8: the human rejected the previous attempt; plan again from the current persisted state."""
        return self._plan_attempt(db, order_id, attempt_number)

    def on_plan_approved(self, db: Session, order_id: uuid.UUID) -> dict:
        """D8 after COMMIT: the committed agreements are scheduled receipts now; plan again and hand the requirements
        to Inventory, which reserves the stock the plan uses."""
        order = order_service.get_order(db, order_id)
        plan = planning_service.run_plan(db, order_id)
        reservations = InventoryAgent().reserve_for_order(db, plan)
        summary = f"Plan approved and committed; re-planned with committed receipts: {plan.status.value}."
        self._refresh(db, order, DialogueEntry(counterpart="INVENTORY", summary=summary, at=now()), approved=True)
        return {"plan_status": plan.status.value, "reservations": reservations}

    def _plan_attempt(self, db: Session, order_id: uuid.UUID, attempt_number: int) -> dict:
        order = order_service.get_order(db, order_id)
        self.save_state(db, self._state(order, self.load_state(db), "RUN_PLAN", "IN_PROGRESS", {}, None))
        db.commit()
        before = {view["id"] for view in negotiation_service.sessions_for_order(db, order_id)}

        plan = planning_service.run_plan(db, order_id)
        assessment = InventoryAgent().assess_requirements(db, plan)
        opened = [view["id"] for view in negotiation_service.sessions_for_order(db, order_id) if view["id"] not in before]
        approval_service.record_attempt_started(db, order_id, attempt_number, opened, plan.status.value)
        db.commit()
        summary = (f"Attempt {attempt_number}: plan {plan.status.value}, {len(plan.shortages)} component shortages; "
                   "material requirements sent to Inventory.")
        self._refresh(db, order, DialogueEntry(counterpart="INVENTORY", summary=summary, at=now()))
        return self._summary(db, order_id, plan, assessment, approval_service.current(db, order_id))

    def _summary(self, db: Session, order_id: uuid.UUID, plan, assessment, attempt: dict | None) -> dict:
        return plain({
            "order_id": str(order_id),
            "plan_status": plan.status.value,
            "shortages": [shortage.model_dump(mode="json") for shortage in plan.shortages],
            "inventory_assessment": assessment,
            "procurement": self.procurement_results(db, order_id),
            "attempt": attempt,
        })

    def on_procurement_result(self, db: Session, result: dict) -> None:
        order = order_service.get_order(db, uuid.UUID(result["order_id"]))
        if result["outcome"] == "AGREEMENT":
            terms = result["agreement"]["agreed_terms"]
            summary = (f"Agreement proposed: {terms['quantity']} of item {result['item_id']} by "
                       f"{terms['delivery_date']}; not committed, awaiting human approval.")
        else:
            summary = (f"Procurement FAILED (session {result['session_status']}): {result['shortage_quantity']} of item "
                       f"{result['item_id']} stays unresolved; plan not updated.")
        context = {"order_id": result["order_id"], "item_id": result["item_id"], "negotiation_id": result["negotiation_id"]}
        self.audit(db, DecisionType.NEGOTIATION_RESULT_RECEIVED, context,
                   {"outcome": result["outcome"], "session_status": result["session_status"],
                    "agreement": result["agreement"]}, summary)
        entry = DialogueEntry(round=result["rounds"] or None, counterpart="INVENTORY", summary=summary[:SUMMARY_MAX],
                              at=now())
        self._refresh(db, order, entry)

    def procurement_results(self, db: Session, order_id: uuid.UUID) -> list[dict]:
        """One entry per shortage session of the order; `outcome` is AGREEMENT, FAILED (REJECTED or FAILED) or null."""
        return plain([
            {
                "negotiation_id": view["id"],
                "item_id": view["objective"]["item_id"],
                "shortage_quantity": view["objective"]["shortage_quantity"],
                "required_by": view["objective"]["required_by"],
                "session_status": view["status"],
                "round_number": view["round_number"],
                "awaiting_supplier": view["awaiting_supplier"],
                "outcome": view["outcome"],
                "agreement": view["agreement"],
            }
            for view in negotiation_service.sessions_for_order(db, order_id)
        ])

    def _refresh(self, db: Session, order: CustomerOrder, entry: DialogueEntry, approved: bool = False) -> None:
        """State from the persisted plan and sessions of the order, then commit."""
        results = self.procurement_results(db, uuid.UUID(order.id))
        waiting = any(r["session_status"] in ("INITIATED", "NEGOTIATING") for r in results)
        context = {
            "plan_status": planning_service.get_plan(db, uuid.UUID(order.id)).status.value,
            "negotiations": [{k: r[k] for k in ("negotiation_id", "item_id", "session_status", "outcome")} for r in results],
        }
        if approved:
            task = ("PLAN_APPROVED", "DONE")
        elif waiting:
            task = ("AWAIT_NEGOTIATION_RESULT", "WAITING")
        else:
            task = ("AWAIT_HUMAN_APPROVAL", "WAITING")
        self.save_state(db, self._state(order, self.load_state(db), *task, context, entry))
        db.commit()

    def _state(self, order: CustomerOrder, state: AgentStateData, task_type: str, status: str, context: dict,
               entry: DialogueEntry | None) -> AgentStateData:
        quantity = sum(line.quantity for line in order.lines)
        return AgentStateData(
            current_goal=Goal(goal_type="FULFIL_ORDER",
                              description=f"Fulfil {order.order_number} ({quantity} units) by {order.due_date}",
                              refs=Refs(order_id=order.id)),
            current_task=Task(task_type=task_type, status=status, refs=Refs(order_id=order.id), started_at=now()),
            preferred_terms=OfferTerms(quantity=quantity, required_date=order.due_date, priority=order.priority),
            reserved_limits=plain({"latest_completion_date": order.due_date, "min_quantity": quantity}),
            dialogue_history=self.dialogue(state, "order_id", order.id, *([entry] if entry else [])),
            negotiation_rules=NegotiationRules(policy=plain({
                "priority_policy": "minimize production delay",
                "planning_preferences": {},
                "planning_constraints": {"capacity": "planned quantity <= capacity_per_day x production lead time"},
                "decision_context": context,
            })),
        )
