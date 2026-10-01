"""001 core business persistence: core, sales, inventory, planning, purchasing, agent (C2 section 2).

Differences from database_schema.md, all decided in Phase 2 (P0-16): planning.mps_plans.planned_start/planned_end,
planning.mrp_requirements.required_by and purchasing.purchase_requisitions.required_by are DATE, not TIMESTAMP.
TIMESTAMP columns are created as timestamptz.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMAS = ["core", "sales", "inventory", "planning", "purchasing", "agent", "negotiation", "simulation", "audit"]
TS = sa.DateTime(timezone=True)


def pk() -> sa.Column:
    return sa.Column("id", pg.UUID(as_uuid=True), primary_key=True)


def fk(name: str, target: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, pg.UUID(as_uuid=True), sa.ForeignKey(target), nullable=nullable)


def created() -> sa.Column:
    return sa.Column("created_at", TS, server_default=sa.func.now())


def upgrade() -> None:
    for schema in SCHEMAS:  # 002 needs negotiation/simulation/audit; creating every schema here keeps 002 tables-only
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

    # agent (referenced by purchasing.purchase_requisitions and, in 002, by negotiation and audit)
    op.create_table(
        "agents", pk(),
        sa.Column("agent_code", sa.String, unique=True),
        sa.Column("agent_type", sa.String, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("status", sa.String),
        created(),
        schema="agent",
    )

    # core
    op.create_table(
        "items", pk(),
        sa.Column("sku", sa.String, nullable=False, unique=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("item_type", sa.Enum("FINISHED_PRODUCT", "COMPONENT", "RAW_MATERIAL", name="item_type", schema="core"),
                  nullable=False),
        sa.Column("unit", sa.String, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("is_active", sa.Boolean, server_default=sa.true()),
        created(),
        sa.Column("updated_at", TS, server_default=sa.func.now()),
        schema="core",
    )
    op.create_table(
        "bom", pk(), fk("parent_item_id", "core.items.id"),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("is_active", sa.Boolean, server_default=sa.true()),
        created(),
        schema="core",
    )
    op.create_table(
        "bom_items", pk(), fk("bom_id", "core.bom.id"), fk("component_item_id", "core.items.id"),
        sa.Column("quantity_required", sa.Numeric, nullable=False),
        schema="core",
    )

    # sales
    op.create_table(
        "customers", pk(),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("location", sa.String, nullable=False),
        sa.Column("contact_info", pg.JSONB, nullable=False),
        created(),
        schema="sales",
    )
    op.create_table(
        "customer_orders", pk(), fk("customer_id", "sales.customers.id"),
        sa.Column("order_number", sa.String, nullable=False, unique=True),
        sa.Column("order_date", sa.Date, nullable=False),
        sa.Column("due_date", sa.Date, nullable=False),
        sa.Column("priority", sa.Integer, nullable=False),
        sa.Column("status", sa.String),
        created(),
        schema="sales",
    )
    op.create_table(
        "customer_order_items", pk(), fk("order_id", "sales.customer_orders.id"), fk("item_id", "core.items.id"),
        sa.Column("quantity", sa.Numeric, nullable=False),
        schema="sales",
    )

    # inventory
    op.create_table(
        "warehouses", pk(),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("location", sa.String, nullable=False),
        schema="inventory",
    )
    op.create_table(
        "inventory_balance", pk(), fk("item_id", "core.items.id"), fk("warehouse_id", "inventory.warehouses.id"),
        sa.Column("on_hand", sa.Numeric, nullable=False),
        sa.Column("reserved", sa.Numeric, server_default="0"),
        sa.Column("safety_stock", sa.Numeric, server_default="0"),
        sa.Column("updated_at", TS, server_default=sa.func.now()),
        schema="inventory",
    )
    op.create_table(
        "inventory_reservations", pk(), fk("item_id", "core.items.id"), fk("warehouse_id", "inventory.warehouses.id"),
        fk("order_id", "sales.customer_orders.id"),
        sa.Column("quantity", sa.Numeric, nullable=False),
        sa.Column("status", sa.String),
        created(),
        schema="inventory",
    )

    # planning
    op.create_table(
        "mps_plans", pk(), fk("order_id", "sales.customer_orders.id"), fk("item_id", "core.items.id"),
        sa.Column("planned_quantity", sa.Numeric, nullable=False),
        sa.Column("planned_start", sa.Date, nullable=False),
        sa.Column("planned_end", sa.Date, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        created(),
        schema="planning",
    )
    op.create_table(
        "mrp_requirements", pk(), fk("mps_plan_id", "planning.mps_plans.id"), fk("item_id", "core.items.id"),
        sa.Column("gross_requirement", sa.Numeric, nullable=False),
        sa.Column("available_inventory", sa.Numeric, nullable=False),
        sa.Column("scheduled_receipts", sa.Numeric, nullable=False),
        sa.Column("projected_available_quantity", sa.Numeric, nullable=False),
        sa.Column("net_requirement", sa.Numeric, nullable=False),
        sa.Column("required_by", sa.Date, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        schema="planning",
    )

    # purchasing (no purchase_orders / purchase_order_items in the 25%)
    op.create_table(
        "suppliers", pk(),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("contact_info", pg.JSONB),
        sa.Column("rating_data", pg.JSONB),
        sa.Column("is_active", sa.Boolean, server_default=sa.true()),
        schema="purchasing",
    )
    op.create_table(
        "supplier_items", pk(), fk("supplier_id", "purchasing.suppliers.id"), fk("item_id", "core.items.id"),
        sa.Column("lead_time_days", sa.Integer, nullable=False),
        sa.Column("min_order_qty", sa.Numeric, nullable=False),
        sa.Column("available_qty", sa.Numeric, nullable=False),
        schema="purchasing",
    )
    op.create_table(
        "purchase_requisitions", pk(), fk("item_id", "core.items.id"),
        sa.Column("quantity_required", sa.Numeric, nullable=False),
        sa.Column("required_by", sa.Date, nullable=False),
        sa.Column("priority", sa.Integer, nullable=False),
        sa.Column("status", sa.String),
        fk("created_by_agent", "agent.agents.id"),
        created(),
        schema="purchasing",
    )

    # agent_state
    op.create_table(
        "agent_state",
        sa.Column("agent_id", pg.UUID(as_uuid=True), sa.ForeignKey("agent.agents.id"), primary_key=True),
        sa.Column("current_goal", pg.JSONB),
        sa.Column("preferred_terms", pg.JSONB),
        sa.Column("reserved_limits", pg.JSONB),
        sa.Column("initial_proposal", pg.JSONB),
        sa.Column("own_offer_history", pg.JSONB),
        sa.Column("opponent_offer_history", pg.JSONB),
        sa.Column("dialogue_history", pg.JSONB),
        sa.Column("negotiation_rules", pg.JSONB),
        sa.Column("current_task", pg.JSONB),
        sa.Column("updated_at", TS, server_default=sa.func.now()),
        schema="agent",
    )


def downgrade() -> None:
    for schema, table in [
        ("agent", "agent_state"),
        ("purchasing", "purchase_requisitions"),
        ("purchasing", "supplier_items"),
        ("purchasing", "suppliers"),
        ("planning", "mrp_requirements"),
        ("planning", "mps_plans"),
        ("inventory", "inventory_reservations"),
        ("inventory", "inventory_balance"),
        ("inventory", "warehouses"),
        ("sales", "customer_order_items"),
        ("sales", "customer_orders"),
        ("sales", "customers"),
        ("core", "bom_items"),
        ("core", "bom"),
        ("core", "items"),
        ("agent", "agents"),
    ]:
        op.drop_table(table, schema=schema)
    op.execute("DROP TYPE IF EXISTS core.item_type")
    for schema in reversed(SCHEMAS):
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}"')
