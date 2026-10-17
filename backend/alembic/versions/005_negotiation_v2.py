"""005 Negotiation tables of the six-agent design (implementation step 3, negotiation.md §4, §10.3).

New tables in the existing `negotiation` schema (the old 25% tables there are untouched until step 5):
`sessions` (starter/owner, case_id), `messages` (stored messages = receivers' inbox queue) and `outbox`.
NG-5 is enforced by a partial unique index: one open negotiation per case, resource, starter and owner.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
SCHEMA = "negotiation"
AGENTS = "('SALES', 'PLANNING', 'INVENTORY', 'PURCHASING', 'WAREHOUSE', 'HR')"
STATUSES = "('NEGOTIATING', 'AGREEMENT_PROPOSED', 'COMMITTED', 'REJECTED', 'ABORTED', 'EXPIRED', 'FAILED')"
QUEUE_STATUSES = "('PENDING', 'RUNNING', 'DONE', 'FAILED')"


def queue_columns() -> list[sa.Column]:
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


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("case_id", sa.String, nullable=False),
        sa.Column("resource_type", sa.String, nullable=False),
        sa.Column("resource_ref", sa.String, nullable=False),
        sa.Column("starter", sa.String, nullable=False),
        sa.Column("owner", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("turn", sa.String, nullable=False),
        sa.Column("round", sa.Integer, nullable=False, server_default="0"),
        sa.Column("accepted", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("commit_requested", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("last_offer", pg.JSONB),
        sa.Column("agreed_terms", pg.JSONB),
        sa.Column("hold_id", sa.String),
        sa.Column("hold_expires_at", TS),
        sa.Column("last_reason_code", sa.String),
        sa.Column("message_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("closed_at", TS),
        sa.CheckConstraint(f"status IN {STATUSES}", name="ck_sessions_status"),
        sa.CheckConstraint(f"starter IN {AGENTS} AND owner IN {AGENTS} AND starter <> owner",
                           name="ck_sessions_participants"),
        sa.CheckConstraint("turn IN ('STARTER', 'OWNER')", name="ck_sessions_turn"),
        sa.CheckConstraint("round BETWEEN 0 AND 3", name="ck_sessions_round"),
        schema=SCHEMA,
    )
    op.create_index("ix_sessions_case", "sessions", ["case_id"], schema=SCHEMA)
    op.create_index("uq_sessions_one_open_per_need", "sessions",
                    ["case_id", "resource_type", "resource_ref", "starter", "owner"], unique=True, schema=SCHEMA,
                    postgresql_where=sa.text("status IN ('NEGOTIATING', 'AGREEMENT_PROPOSED')"))
    op.create_table(
        "messages",
        *queue_columns(),
        sa.Column("message_id", sa.String, nullable=False, unique=True),
        sa.Column("session_id", pg.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.sessions.id"), nullable=False),
        sa.Column("sequence_number", sa.Integer, nullable=False),
        sa.Column("sender", sa.String, nullable=False),
        sa.Column("receiver", sa.String, nullable=False),
        sa.Column("envelope", pg.JSONB, nullable=False),
        sa.UniqueConstraint("session_id", "sequence_number", name="uq_messages_session_sequence"),
        sa.CheckConstraint(f"status IN {QUEUE_STATUSES}", name="ck_messages_status"),
        schema=SCHEMA,
    )
    op.create_index("ix_messages_due", "messages", ["receiver", "status", "next_attempt_at"], schema=SCHEMA)
    op.create_index("ix_messages_scope", "messages", ["scope_key", "seq"], schema=SCHEMA)
    op.create_table(
        "outbox",
        *queue_columns(),
        sa.Column("message_id", sa.String, nullable=False, unique=True),
        sa.Column("receiver", sa.String, nullable=False),
        sa.Column("envelope", pg.JSONB, nullable=False),
        sa.CheckConstraint(f"status IN {QUEUE_STATUSES}", name="ck_outbox_status"),
        schema=SCHEMA,
    )
    op.create_index("ix_outbox_due", "outbox", ["status", "next_attempt_at"], schema=SCHEMA)
    op.create_index("ix_outbox_scope", "outbox", ["scope_key", "seq"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("outbox", schema=SCHEMA)
    op.drop_table("messages", schema=SCHEMA)
    op.drop_table("sessions", schema=SCHEMA)
