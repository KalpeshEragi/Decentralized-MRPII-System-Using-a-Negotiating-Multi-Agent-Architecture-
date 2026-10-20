"""Observer doors (backend_api.md §7): read-only, for the demo frontend. No door key (local demo, views only)."""

from datetime import date, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AppError, ErrorCode
from app.observer import views
from app.simulation.clock import today

router = APIRouter(prefix="/observer", tags=["observer"])


@router.get("/orders")
def orders(db: Session = Depends(get_db)) -> list[dict]:
    return views.orders(db)


@router.get("/orders/{order_ref}")
def order_story(order_ref: str, db: Session = Depends(get_db)) -> dict:
    story = views.order_story(db, order_ref)
    if story is None:
        raise AppError(ErrorCode.NOT_FOUND, "no such order")
    return story


@router.get("/timeline")
def timeline(after: datetime | None = None, case: str | None = None, db: Session = Depends(get_db)) -> dict:
    return views.timeline(db, after, case)


@router.get("/factory-state")
def factory_state(day: date | None = None, db: Session = Depends(get_db)) -> dict:
    return views.factory_state(db, day or today(db))
