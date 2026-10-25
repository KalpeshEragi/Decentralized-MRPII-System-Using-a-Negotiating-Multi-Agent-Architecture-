"""013 Sales: the channel `SIMULATED` for structured simulated customers (DM-7, step 7)."""

from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None

NAME = "ck_conversations_channel"


def upgrade() -> None:
    op.drop_constraint(NAME, "conversations", schema="sales_agent", type_="check")
    op.create_check_constraint(NAME, "conversations", "channel IN ('TEST', 'WHATSAPP', 'SIMULATED')",
                               schema="sales_agent")


def downgrade() -> None:
    op.execute("DELETE FROM sales_agent.conversations WHERE channel = 'SIMULATED'")
    op.drop_constraint(NAME, "conversations", schema="sales_agent", type_="check")
    op.create_check_constraint(NAME, "conversations", "channel IN ('TEST', 'WHATSAPP')", schema="sales_agent")
