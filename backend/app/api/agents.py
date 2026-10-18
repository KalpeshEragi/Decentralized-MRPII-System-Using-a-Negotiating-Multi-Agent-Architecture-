"""Agents API (Phase 3, legacy): hand an order to the Production Planning Agent, and read procurement results, agent
state (C6) and the decision log (C7). Routes only; the agents decide. (The legacy `/supplier-interface` route was
removed on 2026-10-18.)
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agents.base import load_state
from app.agents import workflow
from app.agents.planning.planning_agent import PlanningAgent
from app.core.database import get_db
from app.services import audit_service, order_service

router = APIRouter(prefix="/agents", tags=["agents"])

AgentCode = Literal["PRODUCTION_PLANNING_AGENT", "INVENTORY_AGENT", "PURCHASING_AGENT"]  # audit_service.AGENT_*


@router.post("/planning/orders/{order_id}")
def handle_order(order_id: uuid.UUID, db: Session = Depends(get_db)):
    """Planning plans the order; Inventory assesses it and opens Inventory -> Purchasing negotiations over A2A for
    each shortage; Purchasing makes its round-1 offer. Returns the plan status and the procurement state per shortage."""
    return workflow.handle_order(db, order_id)


@router.post("/planning/run")
def run_planning(db: Session = Depends(get_db)):
    """Run / Replan: plan every order together (combined MPS / MRP); new orders go through Planning -> Inventory ->
    Purchasing negotiations, in priority order."""
    return workflow.run_planning(db)


@router.get("/planning/orders/{order_id}/procurement-results")
def procurement_results(order_id: uuid.UUID, db: Session = Depends(get_db)):
    """What Planning received per shortage: outcome AGREEMENT, FAILED (session REJECTED or FAILED), or null (open)."""
    order_service.get_order(db, order_id)  # 404 for an unknown order
    return PlanningAgent().procurement_results(db, order_id)


@router.get("/decisions")
def decisions(order_id: uuid.UUID | None = None, negotiation_id: uuid.UUID | None = None, db: Session = Depends(get_db)):
    return audit_service.list_decisions(db, order_id, negotiation_id)


@router.get("/{agent_code}/state")
def agent_state(agent_code: AgentCode, db: Session = Depends(get_db)):
    """The agent's C6 state (read-only)."""
    return load_state(db, agent_code).model_dump(mode="json")

