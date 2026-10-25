"""017 Sales follows Planning's `PlanRevised` (a confirmed quantity changed): its own event-version table for the
stale check, created from the model like 011."""

from alembic import op

from app.sales_agent.models import EventVersion

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    EventVersion.__table__.create(op.get_bind())


def downgrade() -> None:
    EventVersion.__table__.drop(op.get_bind())
