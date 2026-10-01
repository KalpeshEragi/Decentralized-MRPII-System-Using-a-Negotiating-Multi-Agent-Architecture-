"""Simulation controls (Phase 5 demo): reset the database to the deterministic X1 baseline.

Only the reset exists; C9 simulation events (the Scenario Manager) are not implemented.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.data.seed_data import BASELINE_ORDER_ID, reset_and_seed

router = APIRouter(prefix="/simulation", tags=["simulation"])


@router.post("/reset")
def reset(include_order: bool = True, db: Session = Depends(get_db)):
    """Empty every table and load the X1 baseline: master data, stock, suppliers, agents and (unless
    include_order=false) order SO-0001, not yet planned. Destroys all current data."""
    reset_and_seed(db, include_order)
    return {"status": "reset", "order_id": str(BASELINE_ORDER_ID) if include_order else None}
