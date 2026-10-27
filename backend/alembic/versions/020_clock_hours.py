"""020 The simulated clock gets hours (SIM-1): `simulation.clock.current_hour`."""

import sqlalchemy as sa
from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clock", sa.Column("current_hour", sa.Integer(), server_default="8", nullable=True),
                  schema="simulation")


def downgrade() -> None:
    op.drop_column("clock", "current_hour", schema="simulation")
