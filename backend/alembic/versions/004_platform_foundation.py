"""004 Platform foundation (implementation step 1, dev_docs/ROADMAP.md).

- core (shared reference, PD-2): items gain `sourcing` (MAKE/BUY) and `space_per_unit`; new `core.routings`.
- events (pubsub_event_channel.md §5): `events` and `event_deliveries` (standard queue shape, system_design.md §4.2).
- simulation (demo.md §6, SD-2): `clock` (one row) and `settings` (versioned factory settings). The old tables of this
  schema are untouched.
- observability (SD-3): `llm_calls`.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
QUEUE_STATUSES = "('PENDING', 'RUNNING', 'DONE', 'FAILED', 'IGNORED_STALE')"


def queue_columns() -> list[sa.Column]:
    """The standard queue shape (system_design.md §4.2)."""
    return [
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("seq", sa.BigInteger, sa.Identity(), nullable=False, unique=True),
        sa.Column("scope_key", sa.String, nullable=False),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("payload", pg.JSONB, nullable=False, server_default="{}"),
        sa.Column("status", sa.String, nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("next_attempt_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("locked_by", sa.String),
        sa.Column("locked_until", TS),
        sa.Column("last_error", sa.Text),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("done_at", TS),
    ]


def queue_constraints(table: str) -> list:
    return [
        sa.CheckConstraint(f"status IN {QUEUE_STATUSES}", name=f"ck_{table}_status"),
        sa.CheckConstraint("attempts >= 0", name=f"ck_{table}_attempts"),
    ]


def upgrade() -> None:
    # -- core (shared reference) ---------------------------------------------------------------------------------
    op.add_column("items", sa.Column("sourcing", sa.String, nullable=False, server_default="BUY"), schema="core")
    op.add_column("items", sa.Column("space_per_unit", sa.Numeric, nullable=False, server_default="0"), schema="core")
    op.create_check_constraint("ck_items_sourcing", "items", "sourcing IN ('MAKE', 'BUY')", schema="core")
    op.create_check_constraint("ck_items_space_per_unit", "items", "space_per_unit >= 0", schema="core")
    op.create_table(
        "routings",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("item_id", pg.UUID(as_uuid=True), sa.ForeignKey("core.items.id"), nullable=False),
        sa.Column("step_no", sa.Integer, nullable=False),
        sa.Column("work_center_code", sa.String, nullable=False),
        sa.Column("skill", sa.String, nullable=False),
        sa.Column("crew_size", sa.Integer, nullable=False, server_default="1"),
        sa.Column("setup_hours", sa.Numeric, nullable=False),
        sa.Column("run_hours_per_unit", sa.Numeric, nullable=False),
        sa.UniqueConstraint("item_id", "step_no", name="uq_routings_item_step"),
        sa.CheckConstraint("step_no >= 1 AND crew_size >= 1 AND setup_hours >= 0 AND run_hours_per_unit >= 0",
                           name="ck_routings_values"),
        schema="core",
    )

    # -- events ----------------------------------------------------------------------------------------------------
    op.execute('CREATE SCHEMA IF NOT EXISTS "events"')
    op.create_table(
        "events",
        sa.Column("event_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("seq", sa.BigInteger, sa.Identity(), nullable=False, unique=True),
        sa.Column("event_type", sa.String, nullable=False),
        sa.Column("schema_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("publisher", sa.String, nullable=False),
        sa.Column("entity_type", sa.String, nullable=False),
        sa.Column("entity_id", sa.String, nullable=False),
        sa.Column("entity_version", sa.Integer, nullable=False),
        sa.Column("correlation_id", sa.String, nullable=False),
        sa.Column("causation_id", pg.UUID(as_uuid=True)),
        sa.Column("occurred_at", TS, nullable=False),
        sa.Column("published_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("payload", pg.JSONB, nullable=False, server_default="{}"),
        schema="events",
    )
    op.create_index("ix_events_correlation", "events", ["correlation_id"], schema="events")
    op.create_table(
        "event_deliveries",
        *queue_columns(),
        sa.Column("event_id", pg.UUID(as_uuid=True), sa.ForeignKey("events.events.event_id"), nullable=False),
        sa.Column("subscriber", sa.String, nullable=False),
        sa.UniqueConstraint("event_id", "subscriber", name="uq_event_deliveries_event_subscriber"),
        *queue_constraints("event_deliveries"),
        schema="events",
    )
    op.create_index("ix_event_deliveries_due", "event_deliveries", ["status", "next_attempt_at"], schema="events")
    op.create_index("ix_event_deliveries_scope", "event_deliveries", ["scope_key", "seq"], schema="events")

    # -- simulation (new tables) -------------------------------------------------------------------------------------
    op.execute('CREATE SCHEMA IF NOT EXISTS "simulation"')
    op.create_table(
        "clock",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("current_day", sa.Date, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="PAUSED"),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 1", name="ck_clock_single_row"),
        sa.CheckConstraint("status IN ('RUNNING', 'PAUSED')", name="ck_clock_status"),
        schema="simulation",
    )
    op.create_table(
        "settings",
        sa.Column("key", sa.String, primary_key=True),
        sa.Column("value", pg.JSONB, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        schema="simulation",
    )

    # -- observability -----------------------------------------------------------------------------------------------
    op.execute('CREATE SCHEMA IF NOT EXISTS "observability"')
    op.create_table(
        "llm_calls",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", sa.String),
        sa.Column("agent", sa.String, nullable=False),
        sa.Column("purpose", sa.String, nullable=False),
        sa.Column("case_id", sa.String),
        sa.Column("queued_at", TS, nullable=False),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
        sa.Column("outcome", sa.String, nullable=False),
        sa.Column("prompt_chars", sa.Integer),
        sa.Column("output_chars", sa.Integer),
        sa.Column("model", sa.String),
        sa.CheckConstraint("outcome IN ('OK', 'TIMEOUT', 'INVALID', 'ERROR', 'FALLBACK_USED')",
                           name="ck_llm_calls_outcome"),
        schema="observability",
    )


def downgrade() -> None:
    op.drop_table("llm_calls", schema="observability")
    op.execute('DROP SCHEMA IF EXISTS "observability"')
    op.drop_table("settings", schema="simulation")
    op.drop_table("clock", schema="simulation")
    op.drop_table("event_deliveries", schema="events")
    op.drop_table("events", schema="events")
    op.execute('DROP SCHEMA IF EXISTS "events"')
    op.drop_table("routings", schema="core")
    op.drop_constraint("ck_items_space_per_unit", "items", schema="core")
    op.drop_constraint("ck_items_sourcing", "items", schema="core")
    op.drop_column("items", "space_per_unit", schema="core")
    op.drop_column("items", "sourcing", schema="core")
