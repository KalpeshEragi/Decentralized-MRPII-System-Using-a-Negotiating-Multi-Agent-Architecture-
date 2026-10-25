"""006 Retire the old 25% tables (IMP-1, API-4; Phase 2 folded into step 4).

The old three-agent design's tables are dropped together with its code: sales orders, old inventory and planning
tables, old purchasing tables, agent state, decision audit, the old negotiation tables and the old simulation tables.
The shared reference tables `core.items`, `core.bom`, `core.bom_items` and `core.routings` stay. The emptied schemas
`sales`, `agent` and `audit` are dropped; `inventory`, `planning`, `purchasing`, `negotiation` and `simulation` stay for
the new tables. Not reversible: the old design is gone (its history is in git).
"""

from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None

OLD_TABLES = [
    "negotiation.negotiation_agreements", "negotiation.negotiation_offers", "negotiation.negotiation_messages",
    "negotiation.negotiation_participants", "negotiation.negotiation_sessions",
    "purchasing.purchase_requisitions", "purchasing.supplier_items", "purchasing.suppliers",
    "planning.mrp_requirements", "planning.mps_plans",
    "inventory.inventory_reservations", "inventory.inventory_balance", "inventory.warehouses",
    "sales.customer_order_items", "sales.customer_orders", "sales.customers",
    "audit.decision_audit", "agent.agent_state", "agent.agents",
    "simulation.simulation_events", "simulation.simulation_scenarios",
]


def upgrade() -> None:
    for table in OLD_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    for schema in ("sales", "agent", "audit"):
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def downgrade() -> None:
    raise NotImplementedError("the old 25% tables are retired; restore them from git history if ever needed")
