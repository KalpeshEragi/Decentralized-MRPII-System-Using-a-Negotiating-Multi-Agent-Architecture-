"""021 Planning's quote rounds (DC-1, QD-1), created from the model like 016."""

from alembic import op

from app.planning_agent.models import QuoteRound

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    QuoteRound.__table__.create(op.get_bind())


def downgrade() -> None:
    QuoteRound.__table__.drop(op.get_bind())
