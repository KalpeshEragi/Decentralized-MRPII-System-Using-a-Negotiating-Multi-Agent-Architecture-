"""The Purchasing Agent's API (routes only; the work is in `service.py` and `views.py`).

    POST /purchasing/procurement-requests        submit a Procurement Request (idempotent by request_ref):
                                                 201 new, 200 the existing request for a known request_ref
    GET  /purchasing/procurement-requests/{id}   status, selection, Legs and their negotiation
"""

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.purchasing_agent import service, views

router = APIRouter(prefix="/purchasing", tags=["purchasing agent"])

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class SubmitProcurementRequest(BaseModel):
    request_ref: Text  # the requester's own reference; submitting it again returns the existing request
    item_id: uuid.UUID
    shortage_quantity: Annotated[int, Field(gt=0, strict=True)]  # whole units
    required_date: date
    priority: Annotated[int, Field(strict=True)]
    requested_by: Text


def get_clock() -> Callable[[], datetime]:
    """The current time. Tests replace this with a fixed clock."""
    return lambda: datetime.now(UTC)


@router.post("/procurement-requests", status_code=201)
def submit_procurement_request(
    body: SubmitProcurementRequest, response: Response, db: Session = Depends(get_db),
    clock: Callable[[], datetime] = Depends(get_clock),
):
    submitted = service.submit_request(db, service.NewProcurementRequest(
        request_ref=body.request_ref, item_id=body.item_id, shortage_quantity=Decimal(body.shortage_quantity),
        required_date=body.required_date, priority=body.priority, requested_by=body.requested_by,
    ), clock(), get_settings())
    if not submitted.created:
        response.status_code = 200
    return views.request_view(db, submitted.request_id)


@router.get("/procurement-requests/{request_id}")
def get_procurement_request(request_id: uuid.UUID, db: Session = Depends(get_db)):
    return views.request_view(db, request_id)
