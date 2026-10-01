"""Run the deterministic plan for an order and persist / read the result.

Flow: order -> finished-goods availability -> net production requirement -> MPS -> capacity -> BOM -> MRP -> shortages.
The calculations are `app.mrpii.plan.plan_orders` (source of truth); this module only loads its inputs and stores its
outputs.

Several orders (Phase 5): an order is planned together with every order already planned (status PLANNED), so the MPS
and MRP reflect the combined demand (rules in `mrpii/plan.py`). Every included order's rows are stored again. With a
single order the result is the Phase 1-4 single-order plan. Stock already reserved for included orders (D8, after
approval) is counted as available to them again, so re-planning never double-counts an order's own reservation. MPS and MRP rows go to `planning.*`. The parts of a PlanSnapshot with no table (finished-goods netting,
capacity checks, validation, planning date) are stored in the PLAN_CREATED audit record and read back from it.
"""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.mrpii.mrp import find_shortages
from app.mrpii.plan import plan_orders
from app.models.audit import DecisionAudit
from app.models.planning import MpsPlan, MrpRequirement
from app.schemas import domain
from app.services import audit_service, bom_service, capacity_service, inventory_service, negotiation_service, order_service
from app.services.audit_service import DecisionType


def run_plan(db: Session, order_id: uuid.UUID) -> domain.PlanSnapshot:
    """Plan (or re-plan) the order, together with the orders already planned, from current persisted state; store the
    result of every included order and return this order's plan."""
    order = order_service.get_order(db, order_id)
    orders = [o for o in order_service.list_orders(db) if o.status == domain.OrderStatus.PLANNED and o.id != order.id]
    orders.append(order)
    product_ids = list(dict.fromkeys(uuid.UUID(line.item_id) for o in orders for line in o.lines))
    bom = bom_service.get_boms(db, product_ids)
    for product_id in product_ids:
        if not any(line.parent_item_id == str(product_id) for line in bom):
            raise AppError(ErrorCode.BUSINESS_RULE_VIOLATION, f"product {product_id} has no active BOM")
    production = capacity_service.production_parameters([str(p) for p in product_ids])
    component_ids = {line.component_item_id for line in bom}
    credit = inventory_service.reserved_for_orders(db, [uuid.UUID(o.id) for o in orders])

    def positions(item_ids):
        return {
            item_id: p.model_copy(update={"reserved": max(p.reserved - credit.get(item_id, 0), 0)})
            for item_id, p in inventory_service.get_positions(db, item_ids).items()
        }

    plans = plan_orders(
        orders,
        bom,
        production,
        positions(component_ids),
        negotiation_service.scheduled_receipts(db, component_ids),
        finished_goods=positions(product_ids),
    )
    for plan in plans:
        _persist(db, uuid.UUID(plan.order_id), plan)
    return get_plan(db, order_id)  # what was stored, in the stored (deterministic) order


def _persist(db: Session, order_id: uuid.UUID, plan: domain.PlanSnapshot) -> None:
    old = list(db.scalars(select(MpsPlan.id).where(MpsPlan.order_id == order_id)))
    if old:
        db.execute(delete(MrpRequirement).where(MrpRequirement.mps_plan_id.in_(old)))
        db.execute(delete(MpsPlan).where(MpsPlan.id.in_(old)))
        db.flush()

    for entry in plan.mps:
        db.add(
            MpsPlan(
                id=uuid.UUID(entry.id),
                order_id=order_id,
                item_id=uuid.UUID(entry.item_id),
                planned_quantity=entry.planned_quantity,
                planned_start=entry.planned_start,
                planned_end=entry.planned_end,
                status=plan.status.value,
            )
        )
    db.flush()
    for row in plan.requirements:
        db.add(
            MrpRequirement(
                id=uuid.uuid5(uuid.UUID(row.mps_entry_id), row.item_id),
                mps_plan_id=uuid.UUID(row.mps_entry_id),
                item_id=uuid.UUID(row.item_id),
                gross_requirement=row.gross_requirement,
                available_inventory=row.available_quantity,
                scheduled_receipts=row.scheduled_receipts,
                projected_available_quantity=row.projected_available_quantity,
                net_requirement=row.net_requirement,
                required_by=row.required_by,
                status=row.status.value,
            )
        )
    order_service.set_status(db, order_id, domain.OrderStatus.PLANNED)
    db.flush()

    audit_service.record(
        db,
        audit_service.AGENT_PLANNING,
        DecisionType.PLAN_CREATED,
        {"order_id": plan.order_id},
        {
            "status": plan.status,
            "planning_date": plan.planning_date,
            "finished_goods": plan.finished_goods,
            "capacity_checks": plan.capacity_checks,
            "validation": plan.validation,
        },
        f"Plan {plan.status.value}: {len(plan.mps)} MPS entries, {len(plan.shortages)} component shortages.",
    )
    for shortage in plan.shortages:  # Inventory detects shortages from the same deterministic figures (P0-02)
        audit_service.record(
            db,
            audit_service.AGENT_INVENTORY,
            DecisionType.SHORTAGE_DETECTED,
            {"order_id": plan.order_id, "item_id": shortage.item_id, "mps_entry_id": shortage.mps_entry_id},
            {"shortage": shortage},
            f"Short by {shortage.shortage_quantity} of item {shortage.item_id}, required by {shortage.required_by}.",
        )
    db.commit()


def get_plan(db: Session, order_id: uuid.UUID) -> domain.PlanSnapshot:
    """The persisted plan: MPS / MRP rows from `planning.*`, the rest from the latest PLAN_CREATED audit record."""
    order = order_service.get_order(db, order_id)
    audit = db.scalars(
        select(DecisionAudit)
        .where(
            DecisionAudit.decision_type == DecisionType.PLAN_CREATED.value,
            DecisionAudit.context["order_id"].astext == str(order_id),
        )
        .order_by(DecisionAudit.created_at.desc())
    ).first()
    if audit is None:
        raise AppError(ErrorCode.NOT_FOUND, "order has not been planned")

    mps_rows = list(db.scalars(select(MpsPlan).where(MpsPlan.order_id == order_id).order_by(MpsPlan.planned_start, MpsPlan.id)))
    mps = [
        domain.MPSEntry(
            id=str(row.id),
            order_id=str(order_id),
            item_id=str(row.item_id),
            planned_quantity=row.planned_quantity,
            planned_start=row.planned_start,
            planned_end=row.planned_end,
            priority=order.priority,
        )
        for row in mps_rows
    ]
    mrp_rows = list(
        db.scalars(
            select(MrpRequirement)
            .where(MrpRequirement.mps_plan_id.in_([row.id for row in mps_rows]))
            .order_by(MrpRequirement.required_by, MrpRequirement.item_id)
        )
    ) if mps_rows else []
    requirements = [
        domain.MaterialRequirement(
            mps_entry_id=str(row.mps_plan_id),
            item_id=str(row.item_id),
            gross_requirement=row.gross_requirement,
            available_quantity=row.available_inventory,
            scheduled_receipts=row.scheduled_receipts,
            projected_available_quantity=row.projected_available_quantity,
            net_requirement=row.net_requirement,
            required_by=row.required_by,
            status=domain.RequirementStatus(row.status),
        )
        for row in mrp_rows
    ]
    stored = audit.decision
    return domain.PlanSnapshot(
        order_id=str(order_id),
        planning_date=stored["planning_date"],
        status=domain.PlanStatus(stored["status"]),
        finished_goods=stored["finished_goods"],
        mps=mps,
        requirements=requirements,
        shortages=find_shortages(requirements, mps),  # derived from the stored rows, not stored twice
        capacity_checks=stored["capacity_checks"],
        validation=stored["validation"],
    )
