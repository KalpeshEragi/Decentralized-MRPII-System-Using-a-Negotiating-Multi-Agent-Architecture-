"""The Purchasing Agent's API (routes only; the work is in `service.py`, `negotiation.py`, `approval.py`, `abort.py`,
`deadlines.py`, `views.py` and `contracts.py`).

The LLM (the shared Ollama client, `get_llm_client`) reads supplier replies and words Purchasing's offers and the
selection explanation; it is never required: unavailable or invalid output falls back to the parser or templates.

Response deadlines are checked lazily: every route that reads or acts on a negotiating request or its Legs first records
any Leg past its deadline as timed out (`deadlines.py`). Approve/reject skip it: an AGREEMENT_PROPOSED request has no
PENDING Leg. Submitting a request, a supplier reply and re-sourcing (which may reallocate) also first time out other
requests' overdue Legs on the same item, so stale holds never reduce availability. A read never re-sources (ADR-003):
a supplier reply re-sources its request first, or `POST .../re-source` does.

    POST /purchasing/procurement-requests        submit a Procurement Request (idempotent by request_ref):
                                                 201 new; 200 the existing request for a known request_ref with
                                                 the same data; 409 for a known request_ref with different data
    GET  /purchasing/procurement-requests/{id}   status, selection, Legs and their negotiation
    GET  /purchasing/procurement-requests/{id}/audit   every decision recorded for the request, oldest first
    POST /purchasing/procurement-requests/{id}/approve  a human approves the proposed agreement: every Leg COMMITTED
    POST /purchasing/procurement-requests/{id}/reject   a human rejects it: APPROVAL_REJECTED, every Leg ABORTED;
                                                        both 409 unless AGREEMENT_PROPOSED with every Leg AGREED
    POST /purchasing/procurement-requests/{id}/abort    a tester stops it: FAILED, every open Leg ABORTED;
                                                        409 unless NEGOTIATING; never re-sources
    POST /purchasing/procurement-requests/{id}/re-source   re-source a request whose open Legs no longer cover the
                                                        shortage (after a recorded timeout); idempotent: 200 and
                                                        the request always, unchanged when nothing is pending
    GET  /purchasing/scheduled-receipts          one per committed Leg, optionally by item_id
    POST /purchasing/contracts                   register a Purchasing Contract: 201; overlapping active contract 409
    GET  /purchasing/contracts                   list contracts, optionally by supplier_id and/or item_id

  Supplier chat (test channel; the tester plays the supplier of a Leg; never shows a price):
    GET  /purchasing/test-channel                                   the chat page
    GET  /purchasing/test-channel/conversations                     one conversation per Leg, newest first
    GET  /purchasing/test-channel/conversations/{leg_id}/messages   one conversation and its messages
    POST /purchasing/test-channel/conversations/{leg_id}/messages   a supplier reply: 201 handled; 200 a duplicate
                                                                    message_id, ignored; 409 negotiation closed
                                                                    (also after its response deadline), or
                                                                    `offer: superseded` when re-sourcing first
                                                                    changed this Leg's offer
"""

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.responses import FileResponse
from pydantic import AfterValidator, BaseModel, BeforeValidator, Field, StrictBool, StringConstraints
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.llm.client import LLMClient, OllamaClient
from app.purchasing_agent import abort, approval, contracts, deadlines, negotiation, service, views

CHAT_PAGE = Path(__file__).parent / "test_channel" / "supplier_chat.html"

router = APIRouter(prefix="/purchasing", tags=["purchasing agent"])

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


def _not_a_boolean(value):
    if isinstance(value, bool):  # true would otherwise count as 1
        raise ValueError("must be a number")
    return value


def _whole_units(value: Decimal) -> Decimal:
    if value != value.to_integral_value():
        raise ValueError("must be a whole number of units")
    return value.to_integral_value()


# Whole units. 500 and 500.0 are both 500; 500.5 is refused.
Quantity = Annotated[Decimal, BeforeValidator(_not_a_boolean), Field(gt=0), AfterValidator(_whole_units)]


class SubmitProcurementRequest(BaseModel):
    request_ref: Text  # the requester's own reference; resubmitting the same data returns the existing request
    item_id: uuid.UUID
    shortage_quantity: Quantity
    required_date: date
    priority: Annotated[int, Field(strict=True)]
    requested_by: Text


def get_clock() -> Callable[[], datetime]:
    """The current time. Tests replace this with a fixed clock."""
    return lambda: datetime.now(UTC)


def get_llm_client() -> LLMClient:
    """The model that reads supplier replies and words Purchasing's text. Tests replace this with a fake model."""
    return OllamaClient.from_settings()


@router.post("/procurement-requests", status_code=201)
def submit_procurement_request(
    body: SubmitProcurementRequest, response: Response, db: Session = Depends(get_db),
    clock: Callable[[], datetime] = Depends(get_clock), llm_client: LLMClient = Depends(get_llm_client),
):
    now, settings = clock(), get_settings()
    deadlines.expire_holds_on_item(db, body.item_id, now)  # overdue Legs of other requests release holds
    submitted = service.submit_request(db, service.NewProcurementRequest(
        request_ref=body.request_ref, item_id=body.item_id, shortage_quantity=body.shortage_quantity,
        required_date=body.required_date, priority=body.priority, requested_by=body.requested_by,
    ), now, settings, llm_client)
    if not submitted.created:
        response.status_code = 200
    return views.request_view(db, submitted.request_id)


@router.get("/procurement-requests/{request_id}")
def get_procurement_request(request_id: uuid.UUID, db: Session = Depends(get_db),
                            clock: Callable[[], datetime] = Depends(get_clock)):
    deadlines.expire_overdue(db, request_id, clock())
    return views.request_view(db, request_id)


@router.get("/procurement-requests/{request_id}/audit")
def get_procurement_audit(request_id: uuid.UUID, db: Session = Depends(get_db),
                          clock: Callable[[], datetime] = Depends(get_clock)):
    deadlines.expire_overdue(db, request_id, clock())
    return views.audit_view(db, request_id)


class ApprovalDecision(BaseModel):
    decided_by: Text  # the human approver, recorded in the audit


@router.post("/procurement-requests/{request_id}/approve")
def approve_procurement(request_id: uuid.UUID, body: ApprovalDecision, db: Session = Depends(get_db),
                        clock: Callable[[], datetime] = Depends(get_clock)):
    approval.approve(db, request_id, body.decided_by, clock())
    return views.request_view(db, request_id)


@router.post("/procurement-requests/{request_id}/reject")
def reject_procurement(request_id: uuid.UUID, body: ApprovalDecision, db: Session = Depends(get_db),
                       clock: Callable[[], datetime] = Depends(get_clock)):
    approval.reject(db, request_id, body.decided_by, clock())
    return views.request_view(db, request_id)


class AbortProcurement(BaseModel):
    aborted_by: Text  # the tester, recorded in the audit
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


@router.post("/procurement-requests/{request_id}/abort")
def abort_procurement(request_id: uuid.UUID, body: AbortProcurement, db: Session = Depends(get_db),
                      clock: Callable[[], datetime] = Depends(get_clock)):
    now = clock()
    deadlines.expire_overdue(db, request_id, now)  # recorded only: the request is still NEGOTIATING and is aborted
    abort.abort(db, request_id, body.aborted_by, body.reason, now)
    return views.request_view(db, request_id)


@router.post("/procurement-requests/{request_id}/re-source")
def re_source_procurement(request_id: uuid.UUID, db: Session = Depends(get_db),
                          clock: Callable[[], datetime] = Depends(get_clock),
                          llm_client: LLMClient = Depends(get_llm_client)):
    now, settings = clock(), get_settings()
    deadlines.expire_overdue(db, request_id, now)
    views.request_view(db, request_id)  # 404 for an unknown request
    deadlines.expire_holds_for_request(db, request_id, now)  # before re-sourcing reads availability
    negotiation.re_source(db, request_id, now, settings, llm_client)
    return views.request_view(db, request_id)


@router.get("/scheduled-receipts")
def list_scheduled_receipts(item_id: uuid.UUID | None = None, db: Session = Depends(get_db)):
    return views.scheduled_receipts(db, item_id)


# INR per unit: more than zero, at most two decimals.
UnitPrice = Annotated[Decimal, BeforeValidator(_not_a_boolean), Field(gt=0, max_digits=12, decimal_places=2)]


class RegisterContract(BaseModel):
    supplier_id: uuid.UUID
    item_id: uuid.UUID
    unit_price: UnitPrice
    valid_from: date
    valid_until: date | None = None  # empty = open-ended; must not be before valid_from (checked by the service)
    is_active: StrictBool = True


@router.post("/contracts", status_code=201)
def register_contract(body: RegisterContract, db: Session = Depends(get_db)):
    contract_id = contracts.register(db, contracts.NewContract(
        supplier_id=body.supplier_id, item_id=body.item_id, unit_price=body.unit_price, valid_from=body.valid_from,
        valid_until=body.valid_until, is_active=body.is_active,
    ))
    return contracts.get_contract(db, contract_id)


@router.get("/contracts")
def list_contracts(supplier_id: uuid.UUID | None = None, item_id: uuid.UUID | None = None,
                   db: Session = Depends(get_db)):
    return contracts.list_contracts(db, supplier_id, item_id)


# -- supplier chat (test channel) -----------------------------------------------------------------------------------


class SupplierMessage(BaseModel):
    message_id: uuid.UUID  # chosen by the sender; a repeated delivery of the same ID is ignored
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


@router.get("/test-channel", include_in_schema=False)
def chat_page():
    return FileResponse(CHAT_PAGE)


@router.get("/test-channel/conversations")
def list_conversations(db: Session = Depends(get_db), clock: Callable[[], datetime] = Depends(get_clock)):
    deadlines.expire_all_overdue(db, clock())
    return views.conversations(db)


@router.get("/test-channel/conversations/{leg_id}/messages")
def read_conversation(leg_id: uuid.UUID, db: Session = Depends(get_db),
                      clock: Callable[[], datetime] = Depends(get_clock)):
    deadlines.expire_overdue_for_leg(db, leg_id, clock())
    return views.conversation(db, leg_id)


@router.post("/test-channel/conversations/{leg_id}/messages", status_code=201)
def post_supplier_message(
    leg_id: uuid.UUID, body: SupplierMessage, response: Response, db: Session = Depends(get_db),
    clock: Callable[[], datetime] = Depends(get_clock), llm_client: LLMClient = Depends(get_llm_client),
):
    now, settings = clock(), get_settings()
    deadlines.expire_overdue_for_leg(db, leg_id, now)  # a reply after the deadline finds the Leg closed
    deadlines.expire_holds_for_leg(db, leg_id, now)  # before a reallocation reads availability
    negotiation.re_source_before_reply(db, leg_id, now, settings, llm_client)  # pending re-sourcing runs first
    received = negotiation.receive_supplier_message(db, leg_id, body.message_id, body.text, now, settings,
                                                    llm_client)
    if received.duplicate:
        response.status_code = 200
    return {"status": "duplicate" if received.duplicate else "received", "conversation": views.conversation(db, leg_id)}
