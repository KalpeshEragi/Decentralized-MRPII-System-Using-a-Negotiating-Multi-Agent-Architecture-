"""Routing of accepted A2A deliveries to the agents (Phase 3). Routes only; makes no decision (C4 section 9).

    message to PURCHASING (Inventory's REQUEST, a supplier ACCEPT / COUNTER_OFFER / REJECT)
        -> the Purchasing Agent reacts (it may send the next message over A2A)
    the message that moved the session to AGREEMENT_PROPOSED, REJECTED or FAILED (whichever endpoint received it)
        -> the Inventory Agent (initiator) receives the result and passes it to the Planning Agent

Called by `app/api/a2a.py` after the protocol accepted and stored the message, inside the same request: everything is
synchronous (no event bus, no background jobs). Planning -> Inventory is an in-process call (P1-06, still open).

Phase 4 (C8, D8): the human's decision goes to the approval workflow (`approval_service`, not an agent), then:
    approve  -> COMMIT -> Planning plans again with the committed receipts -> Inventory reserves the stock it uses
    reject   -> ABORT of uncommitted agreements -> Planning replans as the next attempt (at most 2 attempts);
                rejecting the last attempt -> HUMAN_INTERVENTION_REQUIRED, no replanning
"""

import threading
import uuid
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode

from app.agents.inventory.inventory_agent import InventoryAgent
from app.agents.planning.planning_agent import PlanningAgent
from app.agents.purchasing.purchasing_agent import PurchasingAgent
from app.schemas.negotiation import AgentType, NegotiationMessage, SessionStatus
from app.services import approval_service

RESULT_STATUSES = frozenset(
    {SessionStatus.AGREEMENT_PROPOSED.value, SessionStatus.REJECTED.value, SessionStatus.FAILED.value}
)


def after_delivery(db: Session, receiver_type: AgentType, message: NegotiationMessage, ack: dict) -> None:
    if receiver_type == AgentType.PURCHASING:
        PurchasingAgent().on_message(db, message)
    if ack["session_status"] in RESULT_STATUSES:
        result = InventoryAgent().on_negotiation_result(db, uuid.UUID(message.negotiation_id))
        PlanningAgent().on_procurement_result(db, result)


_order_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
_locks_guard = threading.Lock()


@contextmanager
def order_action(order_id: uuid.UUID) -> Iterator[None]:
    """One workflow action (hand-over, approve, reject) per order at a time in this process. A second request while one
    runs gets CONFLICT instead of planning twice. (Single-process demo server; no distributed locking.)"""
    with _locks_guard:
        lock = _order_locks[str(order_id)]
    if not lock.acquire(blocking=False):
        raise AppError(ErrorCode.CONFLICT, "another action for this order is still running; wait for it to finish")
    try:
        yield
    finally:
        lock.release()


def run_planning(db: Session) -> dict:
    """Run / Replan for all orders (Phase 5). New orders are handed to the Planning Agent one by one in planning
    order (priority 1 first, then due date, then order number): each is planned with the orders before it, and Inventory
    / Purchasing negotiate its shortages. If there is no new order, the planned orders are recomputed from current state
    (deterministic; no new negotiations). Returns every order's plan status."""
    from app.services import approval_service, order_service, planning_service

    orders = sorted(order_service.list_orders(db), key=lambda o: (o.priority, o.due_date, o.order_number))
    if not orders:
        raise AppError(ErrorCode.BUSINESS_RULE_VIOLATION, "there is no customer order to plan")
    new = [o for o in orders if approval_service.current(db, uuid.UUID(o.id)) is None]
    for order in new:
        handle_order(db, uuid.UUID(order.id))
    if not new:
        with order_action(uuid.UUID(orders[0].id)):
            planning_service.run_plan(db, uuid.UUID(orders[0].id))
    return {
        "new_orders": [o.order_number for o in new],
        "plans": [
            {"order_id": o.id, "order_number": o.order_number,
             "plan_status": planning_service.get_plan(db, uuid.UUID(o.id)).status.value}
            for o in orders
        ],
    }


def handle_order(db: Session, order_id: uuid.UUID) -> dict:
    with order_action(order_id):
        return PlanningAgent().handle_order(db, order_id)


def approve_plan(db: Session, order_id: uuid.UUID, attempt_number: int) -> dict:
    with order_action(order_id):
        attempt = approval_service.approve(db, order_id, attempt_number)
        result = PlanningAgent().on_plan_approved(db, order_id)
        return {"attempt": attempt, **result}


def reject_plan(db: Session, order_id: uuid.UUID, attempt_number: int, reason: str | None) -> dict:
    with order_action(order_id):
        rejected = approval_service.reject(db, order_id, attempt_number, reason)
        if rejected["approval_status"] != "REJECTED":  # the last attempt: human intervention required, no replanning
            return {"rejected": rejected, "next_attempt": None}
        replanned = PlanningAgent().replan(db, order_id, attempt_number + 1)
        return {"rejected": rejected, "next_attempt": replanned}
