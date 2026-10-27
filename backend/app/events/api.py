"""Event manager doors (EM-1, EM-2, EM-4): read-only views of the event catalogue, impact checks and the advisory
assistant for the Events page. Nothing here changes the catalogue or the code. No door key (views and advice)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AppError, ErrorCode
from app.events import assistant, catalogue, manager

router = APIRouter(prefix="/events", tags=["event manager"])


@router.get("/catalogue")
def catalogue_view(db: Session = Depends(get_db)) -> dict:
    """Every event (publisher, subscribers with their handlers, payload fields, status) with its live numbers."""
    numbers = manager.stats(db)
    empty = {"published": 0, "last_published": None, "deliveries": {}}
    return {"events": [{**d, "stats": numbers.get(d["name"], empty)} for d in manager.definitions()],
            "agents": manager.agents(), "report": manager.report()}


@router.get("/report")
def report_view() -> dict:
    """What does not fit between the catalogue and the registered handlers (empty lists = all wired)."""
    return manager.report()


@router.get("/{name}/impact")
def impact_view(name: str) -> dict:
    """What removing this event would break and the safe way to do it (deterministic)."""
    if name not in catalogue.BY_NAME:
        raise AppError(ErrorCode.NOT_FOUND, f"no event {name}")
    return manager.impact_of_removing(name)


class NewEvent(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    publisher: str
    subscribers: list[str] = []
    fields: list[str] | None = None


@router.post("/check")
def check_view(body: NewEvent) -> dict:
    """Check a proposed new event against the catalogue's rules (nothing is changed)."""
    return manager.check_new_event(body.name, body.publisher, body.subscribers, body.fields)


class Question(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[dict[str, str]] = []
    focus: str | None = None


@router.post("/assistant")
def assistant_view(body: Question, db: Session = Depends(get_db)) -> dict:
    """Talk with the event manager assistant (EM-4, advisory only). May take up to two minutes on the local model."""
    return assistant.ask(db, body.message, body.history, body.focus)
