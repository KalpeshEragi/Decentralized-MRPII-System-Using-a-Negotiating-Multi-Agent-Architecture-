"""012 Simulator triggers (step 7): `simulation.trigger_log`, created from the model like 007/008/011."""

from alembic import op

from app.simulation.models import TriggerLog

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    TriggerLog.__table__.create(op.get_bind())


def downgrade() -> None:
    TriggerLog.__table__.drop(op.get_bind())
