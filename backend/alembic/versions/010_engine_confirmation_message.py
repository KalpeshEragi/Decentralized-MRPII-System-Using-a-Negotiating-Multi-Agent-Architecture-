"""010 (005 on the purchasing-agent branch) Negotiation Engine: Purchasing may send a CONFIRMATION message (dev_docs/OVERALL_DATABASE_SCHEMA.md §8).

A CONFIRMATION closes a negotiation from Purchasing's side (agreement reached, or the Leg failed) and echoes how
Purchasing read the supplier's last reply. It does not count as a round. Only the message-type CHECK changes.
"""

from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None

ENGINE = "negotiation_engine"
NAME = "ck_negotiation_messages_type_matches_sender"
SUPPLIER_TYPES = "sender_type = 'SUPPLIER' AND message_type IN ('ACCEPT', 'COUNTER_OFFER', 'REJECT', 'UNCLEAR')"


def _replace_check(agent_types: str) -> None:
    op.drop_constraint(NAME, "negotiation_messages", schema=ENGINE, type_="check")
    op.create_check_constraint(
        NAME, "negotiation_messages",
        f"(sender_type = 'AGENT' AND message_type IN ({agent_types})) OR ({SUPPLIER_TYPES})", schema=ENGINE,
    )


def upgrade() -> None:
    _replace_check("'OFFER', 'COUNTER_OFFER', 'CLARIFICATION_REQUEST', 'CANCEL', 'CONFIRMATION'")


def downgrade() -> None:
    op.execute(f"DELETE FROM {ENGINE}.negotiation_messages WHERE message_type = 'CONFIRMATION'")
    _replace_check("'OFFER', 'COUNTER_OFFER', 'CLARIFICATION_REQUEST', 'CANCEL'")
