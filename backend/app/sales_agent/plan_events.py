"""Sales follows Planning's plan events (pubsub catalogue): when Planning has decided on a customer's quantity change,
the confirmed order shows the quantity Planning now commits. Sales only repeats Planning's validated result; it never
decides the quantity itself."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.events import channel
from app.events.models import Event
from app.sales_agent import data_access
from app.sales_agent.models import EventVersion, Order

AGENT = channel.SALES
# PlanRevised reasons that answer a customer's quantity change (planning_agent/manager.py, S7)
QUANTITY_CHANGED = ("QUANTITY_INCREASED", "QUANTITY_DECREASED", "QUANTITY_DECREASED_DAMPENED")


def on_plan_revised(db: Session, event: Event) -> None:
    reason, number = event.payload.get("reason"), event.payload.get("order_number")
    if reason not in (*QUANTITY_CHANGED, "CHANGE_REJECTED") or not number:
        return  # other revisions (repairs, cancellations, completion) do not change what the customer ordered
    if not channel.is_newer(db, EventVersion, event):
        return
    order = db.scalar(select(Order).where(Order.order_number == number).with_for_update())
    if order is None or order.status != "CONFIRMED":
        return
    inquiry = data_access.get_inquiry(db, order.inquiry_id)
    if reason in QUANTITY_CHANGED:
        order.quantity = Decimal(str(event.payload["quantity"]))
    data_access.save_audit_note(db, "SYSTEM", "ORDER_CHANGE_REJECTED" if reason == "CHANGE_REJECTED"
                                else "ORDER_QUANTITY_CHANGED",
                                {"order_number": number, "quantity": str(order.quantity), "reason": reason},
                                conversation_id=inquiry.conversation_id, inquiry_id=inquiry.id)


def register(runner_register) -> None:
    channel.subscribe(AGENT, "PlanRevised", on_plan_revised)
