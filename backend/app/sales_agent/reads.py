"""Sales' read module (IB-2): the only thing other agents may import from the Sales Agent. Read-only; plain data."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.sales_agent.models import Inquiry, Order, Product


def product_sku(db: Session, product_id: str) -> str | None:
    """The SKU of a Sales product: the link to the factory item (`core.items.sku`)."""
    try:
        product = db.get(Product, uuid.UUID(str(product_id)))
    except ValueError:
        return None
    return product.sku if product else None


def inquiry_status(db: Session, inquiry_id: str) -> dict | None:
    """Where the customer conversation stands: inquiry stage, and the order once confirmed."""
    try:
        inquiry = db.get(Inquiry, uuid.UUID(str(inquiry_id)))
    except ValueError:
        return None
    if inquiry is None:
        return None
    order = db.scalar(select(Order).where(Order.inquiry_id == inquiry.id))
    return {"inquiry_id": str(inquiry.id), "stage": inquiry.stage,
            "order_number": order.order_number if order else None, "order_status": order.status if order else None}


def active_products(db: Session) -> list[dict]:
    return [{"product_id": str(p.id), "sku": p.sku, "name": p.name}
            for p in db.scalars(select(Product).where(Product.active.is_(True)).order_by(Product.sku))]


def simulated_inquiries_answered(db: Session) -> list[dict]:
    """Structured simulated customers' inquiries that Planning has answered and nobody has decided on yet (DM-7)."""
    from app.sales_agent.models import Conversation, Option

    rows = db.execute(select(Inquiry, Conversation).join(Conversation, Conversation.id == Inquiry.conversation_id)
                      .where(Conversation.channel == "SIMULATED", Inquiry.stage == "WAITING_FOR_PLANNING",
                             Inquiry.planning_result.is_not(None)).order_by(Inquiry.created_at)).all()
    found = []
    for inquiry, _ in rows:
        offered = db.scalars(select(Option).where(Option.inquiry_id == inquiry.id, Option.status == "OFFERED")
                             .order_by(Option.created_at, Option.id)).all()
        found.append({"inquiry_id": str(inquiry.id), "requested_date": inquiry.requested_date.isoformat(),
                      "status": inquiry.planning_result["status"],
                      "options": [{"option_id": str(o.id), "kind": o.kind, "quantity": str(o.quantity),
                                   "delivery_date": o.delivery_date.isoformat()} for o in offered]})
    return found


def chat_inquiries(db: Session, phone_prefix: str) -> list[dict]:
    """Current inquiries of test-chat conversations whose phone starts with `phone_prefix` (the chat-mode simulated
    customers, DM-7): stage and open options in the letter order the customer was shown."""
    from app.sales_agent.models import Conversation, Option

    found = []
    for conversation in db.scalars(select(Conversation).where(Conversation.channel == "TEST",
                                                              Conversation.sender_ref.startswith(phone_prefix))
                                   .order_by(Conversation.created_at)):
        inquiry = db.get(Inquiry, conversation.current_inquiry_id) if conversation.current_inquiry_id else None
        if inquiry is None:
            continue
        offered = db.scalars(select(Option).where(Option.inquiry_id == inquiry.id,
                                                  Option.status.in_(("OFFERED", "SELECTED")))
                             .order_by(Option.created_at, Option.id)).all()
        found.append({"phone": conversation.sender_ref, "inquiry_id": str(inquiry.id), "stage": inquiry.stage,
                      "requested_date": inquiry.requested_date.isoformat() if inquiry.requested_date else None,
                      "options": [{"letter": "ABCDEFG"[i], "kind": o.kind, "quantity": str(o.quantity),
                                   "delivery_date": o.delivery_date.isoformat()} for i, o in enumerate(offered)]})
    return found
