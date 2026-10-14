"""003 Sales Agent tables, in their own schema `sales_agent` (dev_docs/sales_agent/4_sales_agent_database.md).

The tables do not point at any table of the other schemas, so the Sales Agent can be built and tested on its own.
Allowed values for statuses and similar fields are enforced by CHECK constraints (decision D4.7), and the rules
from section 5 of the design (one active inquiry per conversation, one order per inquiry, ...) are enforced by
unique constraints and unique indexes.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None

SCHEMA = "sales_agent"
TS = sa.DateTime(timezone=True)

# An inquiry in one of these stages is "active": a conversation may have only one at a time.
FINISHED_STAGES = "('CONFIRMED', 'CLOSED')"

PREFERENCE_TYPES = ("PREFERS_WHATSAPP_UPDATES", "WANTS_EARLY_DATE_CHANGE_NOTICE")
INSIGHT_TYPES = ("FREQUENT_PRODUCT",)


def pk() -> sa.Column:
    return sa.Column("id", pg.UUID(as_uuid=True), primary_key=True)


def fk(name: str, target: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, pg.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.{target}"), nullable=nullable)


def created() -> sa.Column:
    return sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False)


def updated() -> sa.Column:
    return sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False)


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def one_of(table: str, column: str, values: tuple[str, ...]) -> sa.CheckConstraint:
    """The column may only hold one of these values (NULL is allowed unless the column is NOT NULL)."""
    return sa.CheckConstraint(f"{column} IN ({quoted(values)})", name=f"ck_{table}_{column}")


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')

    op.create_table(
        "customers", pk(),
        sa.Column("phone", sa.String, nullable=False, unique=True),
        sa.Column("name", sa.String),
        created(), updated(),
        schema=SCHEMA,
    )

    op.create_table(
        "products", pk(),
        sa.Column("sku", sa.String, nullable=False, unique=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        schema=SCHEMA,
    )

    # current_inquiry_id points at inquiries, which does not exist yet: its foreign key is added further down.
    op.create_table(
        "conversations", pk(), fk("customer_id", "customers.id"),
        sa.Column("channel", sa.String, nullable=False),
        sa.Column("sender_ref", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="OPEN"),
        sa.Column("current_inquiry_id", pg.UUID(as_uuid=True)),
        sa.Column("busy", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("last_message_at", TS),
        created(),
        one_of("conversations", "channel", ("TEST", "WHATSAPP")),
        one_of("conversations", "status", ("OPEN", "IDLE", "CLOSED")),
        schema=SCHEMA,
    )

    op.create_table(
        "messages", pk(), fk("conversation_id", "conversations.id", nullable=False),
        sa.Column("direction", sa.String, nullable=False),
        sa.Column("provider_message_id", sa.String),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("processed", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("delivery_status", sa.String),
        created(),
        one_of("messages", "direction", ("IN", "OUT")),
        one_of("messages", "delivery_status", ("QUEUED", "SENT", "FAILED")),
        sa.CheckConstraint("direction = 'OUT' OR delivery_status IS NULL", name="ck_messages_delivery_status_only_out"),
        # A message the channel delivers twice is the same row. Rows without a provider id (our own replies) are not limited.
        sa.UniqueConstraint("conversation_id", "provider_message_id", name="uq_messages_provider_message_id"),
        schema=SCHEMA,
    )
    op.create_index("ix_messages_conversation_created", "messages", ["conversation_id", "created_at"], schema=SCHEMA)

    # selected_option_id points at options, which does not exist yet: its foreign key is added further down.
    op.create_table(
        "inquiries", pk(),
        fk("conversation_id", "conversations.id", nullable=False),
        fk("customer_id", "customers.id"),
        sa.Column("stage", sa.String, nullable=False, server_default="GATHERING"),
        sa.Column("closed_reason", sa.String),
        fk("product_id", "products.id"),
        sa.Column("quantity", sa.Numeric),
        sa.Column("requested_date", sa.Date),
        sa.Column("offer_valid_until", TS),
        sa.Column("selected_option_id", pg.UUID(as_uuid=True)),
        sa.Column("confirmed_at", TS),
        fk("confirmation_message_id", "messages.id"),
        sa.Column("planning_request_ref", sa.String, unique=True),
        sa.Column("planning_request", pg.JSONB),
        sa.Column("planning_result", pg.JSONB),
        created(), updated(),
        one_of("inquiries", "stage", (
            "GATHERING", "WAITING_FOR_PLANNING", "OPTIONS_PRESENTED", "AWAITING_CONFIRMATION",
            "CONFIRMED", "NEEDS_STAFF", "CLOSED",
        )),
        one_of("inquiries", "closed_reason", ("NO_OPTION", "DECLINED", "EXPIRED", "ABANDONED", "REPLACED")),
        # A closed inquiry always says why, and an inquiry that is not closed never has a reason.
        sa.CheckConstraint("(stage = 'CLOSED') = (closed_reason IS NOT NULL)", name="ck_inquiries_closed_reason_matches_stage"),
        sa.CheckConstraint("quantity > 0", name="ck_inquiries_quantity"),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_inquiries_one_active_per_conversation", "inquiries", ["conversation_id"], unique=True, schema=SCHEMA,
        postgresql_where=sa.text(f"stage NOT IN {FINISHED_STAGES}"),
    )

    op.create_table(
        "options", pk(), fk("inquiry_id", "inquiries.id", nullable=False),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("quantity", sa.Numeric, nullable=False),
        sa.Column("delivery_date", sa.Date, nullable=False),
        sa.Column("valid_until", TS),
        sa.Column("reason_code", sa.String),
        sa.Column("status", sa.String, nullable=False, server_default="OFFERED"),
        created(),
        one_of("options", "kind", ("REQUESTED", "LATER_DATE", "LESS_QUANTITY", "PART_NOW_REST_LATER")),
        one_of("options", "status", ("OFFERED", "SELECTED", "EXPIRED", "RELEASED")),
        sa.CheckConstraint("quantity > 0", name="ck_options_quantity"),
        schema=SCHEMA,
    )
    op.create_index("ix_options_inquiry", "options", ["inquiry_id"], schema=SCHEMA)

    # The two foreign keys that had to wait for the tables they point at.
    op.create_foreign_key(
        "fk_conversations_current_inquiry", "conversations", "inquiries", ["current_inquiry_id"], ["id"],
        source_schema=SCHEMA, referent_schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_inquiries_selected_option", "inquiries", "options", ["selected_option_id"], ["id"],
        source_schema=SCHEMA, referent_schema=SCHEMA,
    )

    op.create_table(
        "orders", pk(),
        sa.Column("order_number", sa.String, nullable=False, unique=True),
        fk("customer_id", "customers.id", nullable=False),
        # unique: an inquiry becomes at most one order, and a chosen option becomes at most one order
        sa.Column("inquiry_id", pg.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.inquiries.id"), nullable=False, unique=True),
        sa.Column("option_id", pg.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.options.id"), nullable=False, unique=True),
        fk("product_id", "products.id", nullable=False),
        sa.Column("quantity", sa.Numeric, nullable=False),
        sa.Column("delivery_date", sa.Date, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="CONFIRMED"),
        sa.Column("payment_status", sa.String, nullable=False, server_default="ASSUMED_PAID"),
        sa.Column("confirmed_at", TS, nullable=False),
        created(),
        one_of("orders", "status", ("CONFIRMED",)),
        one_of("orders", "payment_status", ("ASSUMED_PAID",)),
        sa.CheckConstraint("quantity > 0", name="ck_orders_quantity"),
        schema=SCHEMA,
    )

    op.create_table(
        "customer_memory", pk(), fk("customer_id", "customers.id", nullable=False),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("type", sa.String, nullable=False),
        sa.Column("value", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("scope", sa.String, nullable=False, server_default="GENERAL"),
        fk("inquiry_id", "inquiries.id"),
        sa.Column("source", sa.String, nullable=False),
        sa.Column("strength", sa.String),
        sa.Column("status", sa.String, nullable=False, server_default="ACTIVE"),
        sa.Column("evidence", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        created(), updated(),
        one_of("customer_memory", "kind", ("PREFERENCE", "INSIGHT")),
        one_of("customer_memory", "scope", ("GENERAL", "THIS_ORDER")),
        one_of("customer_memory", "source", ("STATED", "INFERRED")),
        one_of("customer_memory", "strength", ("LOW", "MEDIUM", "HIGH")),
        one_of("customer_memory", "status", ("ACTIVE", "SUPERSEDED", "RETIRED")),
        # Only types from this fixed list can be saved. There is no "tolerates delay" or "flexible" type on purpose
        # (fairness rule). To allow a new type, add it here in a new migration.
        sa.CheckConstraint(
            f"(kind = 'PREFERENCE' AND type IN ({quoted(PREFERENCE_TYPES)})) "
            f"OR (kind = 'INSIGHT' AND type IN ({quoted(INSIGHT_TYPES)}))",
            name="ck_customer_memory_type_matches_kind",
        ),
        # What the customer said is a preference; what our rules found is an insight.
        sa.CheckConstraint(
            "(kind = 'PREFERENCE' AND source = 'STATED') OR (kind = 'INSIGHT' AND source = 'INFERRED')",
            name="ck_customer_memory_source_matches_kind",
        ),
        sa.CheckConstraint("(scope = 'THIS_ORDER') = (inquiry_id IS NOT NULL)", name="ck_customer_memory_scope_matches_inquiry"),
        sa.CheckConstraint("source = 'INFERRED' OR strength IS NULL", name="ck_customer_memory_strength_only_inferred"),
        schema=SCHEMA,
    )
    op.create_index("ix_customer_memory_customer_status", "customer_memory", ["customer_id", "status"], schema=SCHEMA)

    op.create_table(
        "audit_log", pk(),
        sa.Column("actor", sa.String, nullable=False),
        sa.Column("event_type", sa.String, nullable=False),
        fk("conversation_id", "conversations.id"),
        fk("inquiry_id", "inquiries.id"),
        sa.Column("details", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        created(),
        one_of("audit_log", "actor", ("SALES_AI", "SYSTEM", "PLANNING", "HUMAN")),
        schema=SCHEMA,
    )
    op.create_index("ix_audit_log_conversation", "audit_log", ["conversation_id"], schema=SCHEMA)
    op.create_index("ix_audit_log_inquiry", "audit_log", ["inquiry_id"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_constraint("fk_inquiries_selected_option", "inquiries", schema=SCHEMA, type_="foreignkey")
    op.drop_constraint("fk_conversations_current_inquiry", "conversations", schema=SCHEMA, type_="foreignkey")
    for table in (
        "audit_log", "customer_memory", "orders", "options", "inquiries", "messages", "conversations", "products",
        "customers",
    ):
        op.drop_table(table, schema=SCHEMA)
    op.execute(f'DROP SCHEMA "{SCHEMA}"')
