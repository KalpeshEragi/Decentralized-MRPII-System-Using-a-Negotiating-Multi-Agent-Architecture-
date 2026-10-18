"""004 Supplier Service, Purchasing Agent and Negotiation Engine schemas (dev_docs/OVERALL_DATABASE_SCHEMA.md §5 and §8).

Creates only `supplier_service`, `purchasing_agent` and `negotiation_engine`. Legacy schemas (`purchasing`,
`negotiation`, ...) and the Sales Agent are untouched. References between the three schemas are logical (no database
foreign key); each module checks them through the owning module's interface. Contract overlap is enforced by the
contract write service, not here, so bad seeded data stays testable.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None

SUPPLIER = "supplier_service"
PURCHASING = "purchasing_agent"
ENGINE = "negotiation_engine"
TS = sa.DateTime(timezone=True)
UUID = pg.UUID(as_uuid=True)


def pk() -> sa.Column:
    return sa.Column("id", UUID, primary_key=True)


def ref(name: str, nullable: bool = False) -> sa.Column:
    """A logical reference to another module's record: a UUID without a database foreign key."""
    return sa.Column(name, UUID, nullable=nullable)


def fk(name: str, target: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, UUID, sa.ForeignKey(target), nullable=nullable)


def now(name: str) -> sa.Column:
    return sa.Column(name, TS, server_default=sa.func.now(), nullable=False)


def one_of(table: str, column: str, values: tuple[str, ...]) -> sa.CheckConstraint:
    """The column may only hold one of these values (NULL is allowed unless the column is NOT NULL)."""
    quoted = ", ".join(f"'{value}'" for value in values)
    return sa.CheckConstraint(f"{column} IN ({quoted})", name=f"ck_{table}_{column}")


def upgrade() -> None:
    for schema in (SUPPLIER, PURCHASING, ENGINE):
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

    # -- supplier_service -------------------------------------------------------------------------------------------
    op.create_table(
        "items", pk(),
        sa.Column("sku", sa.String, nullable=False, unique=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("unit", sa.String, nullable=False),
        schema=SUPPLIER,
    )
    op.create_table(
        "suppliers", pk(),
        sa.Column("name", sa.String, nullable=False, unique=True),
        sa.Column("contact_info", pg.JSONB),
        sa.Column("rating_data", pg.JSONB),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        schema=SUPPLIER,
    )
    op.create_table(
        "supplier_items", pk(),
        fk("supplier_id", f"{SUPPLIER}.suppliers.id", nullable=False),
        fk("item_id", f"{SUPPLIER}.items.id", nullable=False),
        sa.Column("lead_time_days", sa.Integer, nullable=False),
        sa.Column("min_order_qty", sa.Numeric, nullable=False),
        sa.Column("available_qty", sa.Numeric, nullable=False),
        sa.UniqueConstraint("supplier_id", "item_id", name="uq_supplier_items_supplier_item"),
        sa.CheckConstraint("lead_time_days >= 0", name="ck_supplier_items_lead_time_days"),
        sa.CheckConstraint("min_order_qty > 0", name="ck_supplier_items_min_order_qty"),
        sa.CheckConstraint("available_qty >= 0", name="ck_supplier_items_available_qty"),
        schema=SUPPLIER,
    )
    op.create_index("ix_supplier_items_item", "supplier_items", ["item_id"], schema=SUPPLIER)

    # -- negotiation_engine -----------------------------------------------------------------------------------------
    op.create_table(
        "negotiation_sessions", pk(),
        sa.Column("session_type", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("status_reason", sa.Text),
        sa.Column("correlation_id", UUID, nullable=False),
        sa.Column("objective", pg.JSONB, nullable=False),
        sa.Column("round_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_rounds", sa.Integer, nullable=False, server_default="3"),
        sa.Column("response_deadline", TS),
        sa.Column("started_at", TS, nullable=False),
        sa.Column("completed_at", TS),
        one_of("negotiation_sessions", "session_type", ("PURCHASING_SUPPLIER",)),
        one_of("negotiation_sessions", "status", ("OPEN", "AGREED", "REJECTED", "TIMED_OUT", "CANCELLED")),
        sa.CheckConstraint("round_count >= 0 AND round_count <= max_rounds", name="ck_negotiation_sessions_round_count"),
        schema=ENGINE,
    )
    op.create_index("ix_negotiation_sessions_correlation", "negotiation_sessions", ["correlation_id"], schema=ENGINE)
    op.create_table(
        "negotiation_participants", pk(),
        fk("session_id", f"{ENGINE}.negotiation_sessions.id", nullable=False),
        sa.Column("participant_type", sa.String, nullable=False),
        sa.Column("participant_ref", sa.String, nullable=False),
        sa.Column("role", sa.String, nullable=False),
        sa.Column("joined_at", TS, nullable=False),
        sa.UniqueConstraint("session_id", "participant_type", "participant_ref", name="uq_negotiation_participants"),
        one_of("negotiation_participants", "participant_type", ("AGENT", "SUPPLIER")),
        one_of("negotiation_participants", "role", ("INITIATOR", "RESPONDENT")),
        schema=ENGINE,
    )
    op.create_table(
        "negotiation_messages", pk(),
        fk("session_id", f"{ENGINE}.negotiation_sessions.id", nullable=False),
        sa.Column("message_id", UUID, nullable=False, unique=True),
        sa.Column("sequence_number", sa.Integer, nullable=False),
        sa.Column("round_number", sa.Integer, nullable=False),
        sa.Column("sender_type", sa.String, nullable=False),
        sa.Column("sender_ref", sa.String, nullable=False),
        sa.Column("message_type", sa.String, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("terms", pg.JSONB),
        sa.Column("interpretation_source", sa.String),
        sa.Column("causation_id", UUID),
        now("created_at"),
        sa.UniqueConstraint("session_id", "sequence_number", name="uq_negotiation_messages_sequence"),
        one_of("negotiation_messages", "sender_type", ("AGENT", "SUPPLIER")),
        sa.CheckConstraint(
            "(sender_type = 'AGENT' AND message_type IN ('OFFER', 'COUNTER_OFFER', 'CLARIFICATION_REQUEST', 'CANCEL')) "
            "OR (sender_type = 'SUPPLIER' AND message_type IN ('ACCEPT', 'COUNTER_OFFER', 'REJECT', 'UNCLEAR'))",
            name="ck_negotiation_messages_type_matches_sender",
        ),
        one_of("negotiation_messages", "interpretation_source", ("LLM", "FALLBACK_PARSER")),
        sa.CheckConstraint("sender_type = 'SUPPLIER' OR interpretation_source IS NULL",
                           name="ck_negotiation_messages_interpretation_only_supplier"),
        schema=ENGINE,
    )

    # -- purchasing_agent -------------------------------------------------------------------------------------------
    op.create_table(
        "purchasing_contracts", pk(),
        ref("supplier_id"), ref("item_id"),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("valid_from", sa.Date, nullable=False),
        sa.Column("valid_until", sa.Date),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        now("created_at"),
        sa.CheckConstraint("unit_price > 0", name="ck_purchasing_contracts_unit_price"),
        sa.CheckConstraint("valid_until IS NULL OR valid_until >= valid_from", name="ck_purchasing_contracts_validity"),
        schema=PURCHASING,
    )
    op.create_index("ix_purchasing_contracts_supplier_item", "purchasing_contracts", ["supplier_id", "item_id"],
                    schema=PURCHASING)
    op.create_table(
        "procurement_requests", pk(),
        ref("item_id"),
        sa.Column("shortage_quantity", sa.Numeric, nullable=False),
        sa.Column("required_date", sa.Date, nullable=False),
        sa.Column("priority", sa.Integer, nullable=False),
        sa.Column("requested_by", sa.String, nullable=False),
        sa.Column("request_ref", sa.String, nullable=False, unique=True),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("split_type", sa.String),
        sa.Column("cost_ranking_available", sa.Boolean),
        sa.Column("constrained_quantity", sa.Numeric),
        sa.Column("status_reason", sa.Text),
        sa.Column("decided_at", TS),
        now("created_at"), now("updated_at"),
        sa.CheckConstraint("shortage_quantity > 0", name="ck_procurement_requests_shortage_quantity"),
        one_of("procurement_requests", "status", (
            "RECEIVED", "NEGOTIATING", "AGREEMENT_PROPOSED", "COMMITTED", "APPROVAL_REJECTED", "FAILED")),
        one_of("procurement_requests", "split_type", ("SINGLE", "NECESSARY_SPLIT", "COST_SAVING_SPLIT")),
        schema=PURCHASING,
    )
    op.create_table(
        "purchase_requisitions", pk(),
        fk("procurement_request_id", f"{PURCHASING}.procurement_requests.id", nullable=False),
        ref("supplier_id"),
        fk("purchasing_contract_id", f"{PURCHASING}.purchasing_contracts.id"),
        sa.Column("unit_price_at_selection", sa.Numeric(12, 2)),
        sa.Column("allocated_quantity", sa.Numeric, nullable=False),
        sa.Column("quantity_cap", sa.Numeric),
        sa.Column("agreed_quantity", sa.Numeric),
        sa.Column("agreed_delivery_date", sa.Date),
        sa.Column("negotiation_session_id", UUID, nullable=False, unique=True),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("status_reason", sa.Text),
        now("created_at"), now("updated_at"),
        one_of("purchase_requisitions", "status", ("PENDING", "AGREED", "FAILED", "ABORTED", "COMMITTED")),
        sa.CheckConstraint("allocated_quantity > 0", name="ck_purchase_requisitions_allocated_quantity"),
        # A Not Registered Leg has neither a contract nor a price snapshot; a priced Leg has both.
        sa.CheckConstraint("(purchasing_contract_id IS NULL) = (unit_price_at_selection IS NULL)",
                           name="ck_purchase_requisitions_price_matches_contract"),
        schema=PURCHASING,
    )
    op.create_index("ix_purchase_requisitions_request", "purchase_requisitions", ["procurement_request_id"],
                    schema=PURCHASING)
    op.create_index("ix_purchase_requisitions_supplier_status", "purchase_requisitions", ["supplier_id", "status"],
                    schema=PURCHASING)
    op.create_table(
        "decision_audit", pk(),
        fk("procurement_request_id", f"{PURCHASING}.procurement_requests.id"),
        sa.Column("decision_type", sa.String, nullable=False),
        sa.Column("context", pg.JSONB, nullable=False),
        sa.Column("decision", pg.JSONB, nullable=False),
        sa.Column("reasoning_summary", sa.Text, nullable=False),
        sa.Column("llm_explanation", sa.Text),
        now("created_at"),
        schema=PURCHASING,
    )
    op.create_index("ix_decision_audit_request", "decision_audit", ["procurement_request_id"], schema=PURCHASING)


def downgrade() -> None:
    for table in ("decision_audit", "purchase_requisitions", "procurement_requests", "purchasing_contracts"):
        op.drop_table(table, schema=PURCHASING)
    for table in ("negotiation_messages", "negotiation_participants", "negotiation_sessions"):
        op.drop_table(table, schema=ENGINE)
    for table in ("supplier_items", "suppliers", "items"):
        op.drop_table(table, schema=SUPPLIER)
    for schema in (PURCHASING, ENGINE, SUPPLIER):
        op.execute(f'DROP SCHEMA "{schema}"')
