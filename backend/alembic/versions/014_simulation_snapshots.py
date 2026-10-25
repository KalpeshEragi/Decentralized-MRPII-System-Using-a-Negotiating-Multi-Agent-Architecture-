"""014 Starting states (DM-2, step 7): `simulation.snapshots`, created from the model like 012."""

from alembic import op

from app.simulation.models import Snapshot

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Snapshot.__table__.create(op.get_bind())


def downgrade() -> None:
    Snapshot.__table__.drop(op.get_bind())
