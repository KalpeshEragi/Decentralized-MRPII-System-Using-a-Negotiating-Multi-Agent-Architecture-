"""Rule editor doors (RE-1): list business rules by owner, change one, reset one, read the history. Changing needs
the simulator's door key, like the other simulator write doors."""

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.doors import require_door_key
from app.rules import service

router = APIRouter(prefix="/rules", tags=["rule editor"])
WRITE = [Depends(require_door_key("simulation_door_key"))]


class Change(BaseModel):
    value: float | int | str
    note: str | None = Field(default=None, max_length=300)


@router.get("")
def list_rules(db: Session = Depends(get_db)) -> dict:
    """Every business rule, grouped General / Sales / Planning / Inventory / Purchasing / Warehouse / HR."""
    return service.list_rules(db)


@router.get("/history")
def rule_history(key: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    return service.history(db, key)


@router.put("/{key}", dependencies=WRITE)
def change_rule(key: str, body: Change, db: Session = Depends(get_db),
                x_changed_by: str | None = Header(default=None)) -> dict:
    result = service.change_rule(db, key, body.value, x_changed_by or "developer", body.note)
    db.commit()
    return result


@router.delete("/{key}", dependencies=WRITE)
def reset_rule(key: str, db: Session = Depends(get_db), x_changed_by: str | None = Header(default=None)) -> dict:
    result = service.reset_rule(db, key, x_changed_by or "developer")
    db.commit()
    return result
