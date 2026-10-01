"""002 negotiation, simulation and audit persistence (C2 section 3).

negotiation_messages differs from database_schema.md by the P1-07 decision: sender_agent_id / receiver_agent_id are
nullable and sender_type / receiver_type are added, because the supplier interface and the approval workflow are not
agents. The negotiation, simulation and audit schemas are created by 001.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
SESSION = "negotiation.negotiation_sessions.id"


def pk() -> sa.Column:
    return sa.Column("id", pg.UUID(as_uuid=True), primary_key=True)


def fk(name: str, target: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, pg.UUID(as_uuid=True), sa.ForeignKey(target), nullable=nullable)


def created() -> sa.Column:
    return sa.Column("created_at", TS, server_default=sa.func.now())


def upgrade() -> None:
    op.create_table(
        "negotiation_sessions", pk(),
        sa.Column("negotiation_type", sa.String, nullable=False),
        fk("initiator_agent_id", "agent.agents.id"),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("objective", pg.JSONB, nullable=False),
        sa.Column("started_at", TS, nullable=False),
        sa.Column("deadline", TS, nullable=False),
        sa.Column("completed_at", TS),
        schema="negotiation",
    )
    op.create_table(
        "negotiation_participants", pk(), fk("negotiation_id", SESSION), fk("agent_id", "agent.agents.id"),
        sa.Column("role", sa.String, nullable=False),
        sa.Column("joined_at", TS),
        schema="negotiation",
    )
    op.create_table(
        "negotiation_messages", pk(), fk("negotiation_id", SESSION),
        sa.Column("message_id", pg.UUID(as_uuid=True), unique=True),
        sa.Column("sender_type", sa.String, nullable=False),
        fk("sender_agent_id", "agent.agents.id"),
        sa.Column("receiver_type", sa.String, nullable=False),
        fk("receiver_agent_id", "agent.agents.id"),
        sa.Column("message_type", sa.String),
        sa.Column("sequence_number", sa.Integer),
        sa.Column("correlation_id", pg.UUID(as_uuid=True)),
        sa.Column("payload", pg.JSONB),
        sa.Column("created_at", TS),
        schema="negotiation",
    )
    op.create_table(
        "negotiation_offers", pk(), fk("negotiation_id", SESSION),
        fk("message_id", "negotiation.negotiation_messages.id"),
        sa.Column("offer_number", sa.Integer, nullable=False),
        sa.Column("offer_type", sa.String, nullable=False),
        sa.Column("terms", pg.JSONB, nullable=False),
        sa.Column("valid_until", TS),
        sa.Column("status", sa.String, nullable=False),
        created(),
        schema="negotiation",
    )
    op.create_table(
        "negotiation_agreements", pk(), fk("negotiation_id", SESSION),
        sa.Column("agreed_terms", pg.JSONB, nullable=False),
        sa.Column("validated", sa.Boolean, server_default=sa.false()),
        sa.Column("committed", sa.Boolean, server_default=sa.false()),
        created(),
        schema="negotiation",
    )

    op.create_table(
        "simulation_scenarios", pk(),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("configuration", pg.JSONB, nullable=False),
        created(),
        schema="simulation",
    )
    op.create_table(
        "simulation_events", pk(), fk("scenario_id", "simulation.simulation_scenarios.id"),
        sa.Column("event_type", sa.String, nullable=False),
        sa.Column("event_time", TS, nullable=False),
        sa.Column("parameters", pg.JSONB, nullable=False),
        sa.Column("status", sa.String),
        schema="simulation",
    )

    op.create_table(
        "decision_audit", pk(), fk("agent_id", "agent.agents.id"),
        sa.Column("decision_type", sa.String, nullable=False),
        sa.Column("context", pg.JSONB, nullable=False),
        sa.Column("decision", pg.JSONB, nullable=False),
        sa.Column("reasoning_summary", sa.Text, nullable=False),
        created(),
        schema="audit",
    )


def downgrade() -> None:
    for schema, table in [
        ("audit", "decision_audit"),
        ("simulation", "simulation_events"),
        ("simulation", "simulation_scenarios"),
        ("negotiation", "negotiation_agreements"),
        ("negotiation", "negotiation_offers"),
        ("negotiation", "negotiation_messages"),
        ("negotiation", "negotiation_participants"),
        ("negotiation", "negotiation_sessions"),
    ]:
        op.drop_table(table, schema=schema)
