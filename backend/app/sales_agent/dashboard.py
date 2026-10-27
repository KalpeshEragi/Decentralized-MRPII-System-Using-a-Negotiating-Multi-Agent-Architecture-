"""Read-only views for the Sales control page in the frontend: counts, lists and the agent's rules.

Nothing here changes data. Every number is counted from the Sales Agent's own tables; production and shipping
progress is not Sales' data, so the page reads it from the observer instead.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.sales_agent import manager, prompts, rules
from app.sales_agent.models import AuditLog, Conversation, Customer, CustomerMemory, Inquiry, Option, Order, Product
from app.simulation.settings import setting

LIST_LIMIT = 200


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _num(value) -> float | None:
    return float(value) if value is not None else None


def _counts(db: Session, column) -> dict[str, int]:
    return {key or "NONE": n for key, n in db.execute(select(column, func.count()).group_by(column))}


def overview(db: Session) -> dict[str, Any]:
    """Headline numbers: inquiries by stage, why inquiries closed, orders by status, options by kind and status."""
    stages = _counts(db, Inquiry.stage)
    orders = _counts(db, Order.status)
    inquiries = sum(stages.values())
    placed = sum(orders.values())
    return {
        "customers": db.scalar(select(func.count()).select_from(Customer)) or 0,
        "conversations": _counts(db, Conversation.status),
        "channels": _counts(db, Conversation.channel),
        "inquiries": inquiries,
        "inquiry_stages": stages,
        "closed_reasons": {k: v for k, v in _counts(db, Inquiry.closed_reason).items() if k != "NONE"},
        "orders_placed": placed,
        "order_statuses": orders,
        "conversion_rate": round(placed / inquiries, 3) if inquiries else None,
        "units_ordered": _num(db.scalar(select(func.coalesce(func.sum(Order.quantity), 0))
                                        .where(Order.status == "CONFIRMED"))),
        "option_kinds": _counts(db, Option.kind),
        "option_statuses": _counts(db, Option.status),
        "ai_failures": db.scalar(select(func.count()).select_from(AuditLog)
                                 .where(AuditLog.event_type.in_(("MODEL_FAILED", "AI_FAILED", "CHECK_FAILED")))) or 0,
        "audit_types": _counts(db, AuditLog.event_type),
    }


def orders(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Order, Customer, Product, Inquiry)
        .join(Customer, Customer.id == Order.customer_id)
        .join(Product, Product.id == Order.product_id)
        .join(Inquiry, Inquiry.id == Order.inquiry_id)
        .order_by(Order.confirmed_at.desc()).limit(LIST_LIMIT))
    return [{
        "order_number": o.order_number, "status": o.status, "payment_status": o.payment_status,
        "customer": c.name or c.phone, "customer_id": str(c.id), "phone": c.phone,
        "product": p.name, "sku": p.sku, "quantity": _num(o.quantity),
        "requested_date": _iso(i.requested_date), "delivery_date": _iso(o.delivery_date),
        "confirmed_at": _iso(o.confirmed_at), "inquiry_id": str(i.id),
    } for o, c, p, i in rows]


def inquiries(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Inquiry, Conversation, Customer, Product)
        .join(Conversation, Conversation.id == Inquiry.conversation_id)
        .outerjoin(Customer, Customer.id == Inquiry.customer_id)
        .outerjoin(Product, Product.id == Inquiry.product_id)
        .order_by(Inquiry.created_at.desc()).limit(LIST_LIMIT))
    return [{
        "id": str(i.id), "stage": i.stage, "closed_reason": i.closed_reason, "channel": conv.channel,
        "customer": (c.name or c.phone) if c else conv.sender_ref, "customer_id": str(c.id) if c else None,
        "product": p.name if p else None, "quantity": _num(i.quantity), "requested_date": _iso(i.requested_date),
        "offer_valid_until": _iso(i.offer_valid_until), "planning_answer": (i.planning_result or {}).get("status"),
        "created_at": _iso(i.created_at), "confirmed_at": _iso(i.confirmed_at),
    } for i, conv, c, p in rows]


def customers(db: Session) -> list[dict[str, Any]]:
    order_count = select(Order.customer_id, func.count().label("n"), func.max(Order.confirmed_at).label("last")) \
        .group_by(Order.customer_id).subquery()
    memory_count = select(CustomerMemory.customer_id, func.count().label("m")) \
        .where(CustomerMemory.status == "ACTIVE").group_by(CustomerMemory.customer_id).subquery()
    rows = db.execute(
        select(Customer, order_count.c.n, order_count.c.last, memory_count.c.m)
        .outerjoin(order_count, order_count.c.customer_id == Customer.id)
        .outerjoin(memory_count, memory_count.c.customer_id == Customer.id)
        .order_by(Customer.created_at).limit(LIST_LIMIT))
    return [{"id": str(c.id), "name": c.name, "phone": c.phone, "orders": n or 0, "last_order_at": _iso(last),
             "memories": m or 0, "created_at": _iso(c.created_at)} for c, n, last, m in rows]


def memories(db: Session, customer_id) -> list[dict[str, Any]]:
    return [{"kind": m.kind, "type": m.type, "value": m.value, "scope": m.scope, "source": m.source,
             "strength": m.strength, "status": m.status, "evidence": m.evidence, "updated_at": _iso(m.updated_at)}
            for m in db.scalars(select(CustomerMemory).where(CustomerMemory.customer_id == customer_id)
                                .order_by(CustomerMemory.updated_at.desc()))]


def audit(db: Session, event_type: str | None = None, inquiry_id: str | None = None) -> list[dict[str, Any]]:
    query = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(LIST_LIMIT)
    if event_type:
        query = query.where(AuditLog.event_type == event_type)
    if inquiry_id:
        query = query.where(AuditLog.inquiry_id == inquiry_id)
    return [{"id": str(a.id), "actor": a.actor, "event_type": a.event_type, "details": a.details,
             "conversation_id": str(a.conversation_id) if a.conversation_id else None,
             "inquiry_id": str(a.inquiry_id) if a.inquiry_id else None, "created_at": _iso(a.created_at)}
            for a in db.scalars(query)]


def rule_book(db: Session) -> dict[str, Any]:
    """The rules the Sales Agent works by, read from the code itself so the page can never show stale values.
    Read-only in this first pass."""
    return {
        "tuning": [
            {"name": "Offer validity", "value": f"{setting(db, 'sales_offer_validity_hours')} h",
             "meaning": "How long options shown to a customer stay open."},
            {"name": "Planning wait limit", "value": f"{setting(db, 'sales_planning_wait_minutes')} min",
             "meaning": "After this, an unanswered request is reported to the customer and staff."},
            {"name": "AI failures before staff", "value": setting(db, "sales_ai_failures_before_staff"),
             "meaning": "Model failures in a row before the conversation is handed to staff."},
            {"name": "Questions per reply", "value": rules.MAX_QUESTIONS_PER_REPLY,
             "meaning": "Most questions the agent may ask in one message."},
            {"name": "Chat history length", "value": manager.MAX_HISTORY_MESSAGES,
             "meaning": "Messages the model sees (a short history works better with a small model)."},
            {"name": "Recent orders in summary", "value": manager.RECENT_ORDERS_IN_SUMMARY,
             "meaning": "Past orders mentioned to the model when it talks to a known customer."},
            {"name": "Frequent product", "value": f"{rules.FREQUENT_PRODUCT_MIN_ORDERS} of last {rules.FREQUENT_PRODUCT_WINDOW} orders",
             "meaning": "When a customer gets the FREQUENT_PRODUCT insight."},
            {"name": "Words in a plain yes", "value": rules.MAX_WORDS_IN_A_PLAIN_YES,
             "meaning": "Longest message still read as a plain confirmation."},
        ],
        "safety": [
            {"name": "Allowed next steps by stage",
             "value": {stage: sorted(steps) for stage, steps in rules.ALLOWED_STEPS.items()},
             "meaning": "What the AI may choose at each stage. Only GATHERING may send a request to Planning; "
                        "choosing, confirming and declining are decided by a separate check, never by the chat model."},
            {"name": "Preferences a customer can ask us to remember", "value": list(rules.PREFERENCE_TYPES),
             "meaning": "Deliberately no 'tolerates delay': accepting a delay once must never lead to worse treatment."},
            {"name": "Order details are checked by code",
             "value": "product must match one active product; quantity a positive number; date valid and not in the past",
             "meaning": "The model only suggests details; rules.py decides whether they are valid."},
            {"name": "Payment", "value": "ASSUMED_PAID", "meaning": "Prototype: no real payments."},
        ],
        "prompts": {"rules": prompts.RULES_PROMPT, "answer_format": prompts.ANSWER_FORMAT_PROMPT,
                    "decision": prompts.DECISION_PROMPT},
    }
