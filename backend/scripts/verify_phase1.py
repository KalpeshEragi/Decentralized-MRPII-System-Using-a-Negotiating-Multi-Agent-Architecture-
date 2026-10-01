"""Phase 1 manual verification: prints the X1 plan and two negotiation flows. Run from backend/:

    python scripts/verify_phase1.py

Read-only demo: no database, no network, no LLM.
"""

import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data import x1_fixture as x1  # noqa: E402
from app.mrpii.plan import plan_order  # noqa: E402
from app.mrpii.suppliers import arrival_date, covers_alone, is_usable  # noqa: E402
from app.negotiation.protocol import ProtocolError  # noqa: E402
from app.negotiation.session import NegotiationSession  # noqa: E402
from app.schemas.negotiation import (  # noqa: E402
    AgentRef, AgentType, MessagePayload, MessageType, NegotiationMessage, OfferTerms,
)


def show_plan() -> None:
    order, inventory = x1.x1_order(), x1.x1_inventory()
    plan = plan_order(order, x1.x1_bom(), x1.PRODUCTION, inventory)
    print("== X1 baseline ==")
    print(f"order {order.order_number}: {order.lines[0].quantity} x {x1.PRODUCT}, priority {order.priority}, due {order.due_date}")
    for fg in plan.finished_goods:
        print(f"finished goods: available {fg.available_finished_goods}, net production requirement {fg.net_production_requirement}")
    for entry in plan.mps:
        print(f"MPS: qty {entry.planned_quantity}, start {entry.planned_start}, end {entry.planned_end}, priority {entry.priority}")
    for check in plan.capacity_checks:
        print(f"capacity: {check.required_days} days needed / {check.working_days} available -> feasible={check.feasible}")
    print(f"{'component':<14}{'gross':>6}{'avail':>7}{'sched':>6}{'proj':>6}{'net':>6}  status")
    for row in plan.requirements:
        print(f"{x1.component_name(row.item_id):<14}{row.gross_requirement:>6}{row.available_quantity:>7}"
              f"{row.scheduled_receipts:>6}{row.projected_available_quantity:>6}{row.net_requirement:>6}  {row.status}")
    print(f"plan status: {plan.status}; shortages: "
          f"{[(x1.component_name(s.item_id), int(s.shortage_quantity)) for s in plan.shortages]}")

    print("\n== Supplier feasibility (required_by", plan.mps[0].planned_start, ") ==")
    suppliers = x1.x1_suppliers()
    for shortage in plan.shortages:
        print(f"{x1.component_name(shortage.item_id)} {shortage.shortage_quantity}:")
        for option in (s for s in suppliers if s.item_id == shortage.item_id):
            print(f"  {option.supplier:<15} arrives {arrival_date(option, plan.planning_date)} "
                  f"usable={is_usable(option, plan.planning_date, shortage.required_by)} "
                  f"covers_alone={covers_alone(option, plan.planning_date, shortage.required_by, shortage.shortage_quantity)}")


class Flow:
    """Builds correctly numbered messages for one session."""

    def __init__(self, negotiation_id: str):
        self.session = NegotiationSession(negotiation_id, "inv-1", "pur-1", "sup-1")
        self.id = negotiation_id
        self.refs = {
            "INV": AgentRef(agent_id="inv-1", agent_type=AgentType.INVENTORY),
            "PUR": AgentRef(agent_id="pur-1", agent_type=AgentType.PURCHASING),
            "SUP": AgentRef(agent_id="sup-1", agent_type=AgentType.SUPPLIER_INTERFACE),
        }

    def send(self, sender: str, receiver: str, kind: MessageType, qty: int | None = None,
             delivery: date | None = None, seq: int | None = None) -> None:
        terms = None
        if qty is not None:
            terms = OfferTerms(quantity=Decimal(qty), delivery_date=delivery,
                               required_date=date(2026, 10, 26) if kind == MessageType.REQUEST else None)
        n = seq or len(self.session.messages) + 1
        message = NegotiationMessage(
            message_id=f"{self.id}-{n}-{kind}", negotiation_id=self.id, sender=self.refs[sender],
            receiver=self.refs[receiver], message_type=kind, sequence_number=n,
            timestamp=datetime(2026, 10, 1, tzinfo=timezone.utc), payload=MessagePayload(terms=terms),
        )
        try:
            status = self.session.submit(message)
            print(f"  #{n} {sender}->{receiver} {kind:<18} => {status} (round {self.session.round_number} of 3)")
        except ProtocolError as exc:
            print(f"  #{n} {sender}->{receiver} {kind:<18} => REFUSED {exc.code}")


def show_negotiations() -> None:
    d = date(2026, 10, 15)
    print("\n== Negotiation: agreement (Display 500, Alpha) ==")
    f = Flow("neg-ok")
    f.send("INV", "PUR", MessageType.REQUEST, 500)
    f.send("PUR", "SUP", MessageType.OFFER, 500, d)
    f.send("SUP", "PUR", MessageType.ACCEPT)
    f.send("PUR", "INV", MessageType.AGREEMENT_PROPOSED, 500, d)
    print(f"  outcome: {f.session.outcome}, agreed: {f.session.agreed_terms.quantity} by {f.session.agreed_terms.delivery_date}")

    print("\n== Negotiation: FAILED after 3 rounds ==")
    f = Flow("neg-failed")
    f.send("INV", "PUR", MessageType.REQUEST, 500)
    f.send("PUR", "SUP", MessageType.OFFER, 500, d)
    f.send("SUP", "PUR", MessageType.COUNTER_OFFER, 300, date(2026, 10, 25))
    f.send("PUR", "SUP", MessageType.COUNTER_OFFER, 400, d)
    f.send("SUP", "PUR", MessageType.COUNTER_OFFER, 300, date(2026, 10, 25))
    f.send("PUR", "SUP", MessageType.COUNTER_OFFER, 450, d)
    f.send("SUP", "PUR", MessageType.COUNTER_OFFER, 300, date(2026, 10, 25))
    f.send("PUR", "SUP", MessageType.COUNTER_OFFER, 450, d)  # would be round 4
    print(f"  outcome: {f.session.outcome}")

    print("\n== Negotiation: supplier REJECT ==")
    f = Flow("neg-rejected")
    f.send("INV", "PUR", MessageType.REQUEST, 500)
    f.send("PUR", "SUP", MessageType.OFFER, 500, d)
    f.send("SUP", "PUR", MessageType.REJECT)
    print(f"  status: {f.session.status}, outcome: {f.session.outcome}")

    print("\n== Negotiation: invalid messages refused ==")
    f = Flow("neg-invalid")
    f.send("PUR", "SUP", MessageType.OFFER, 500, d)                      # must start with REQUEST
    f.send("INV", "PUR", MessageType.REQUEST, 500, seq=2)                # wrong sequence
    f.send("INV", "PUR", MessageType.REQUEST, 500)
    f.send("PUR", "INV", MessageType.AGREEMENT_PROPOSED, 500, d)         # nothing to agree to yet


if __name__ == "__main__":
    show_plan()
    show_negotiations()
