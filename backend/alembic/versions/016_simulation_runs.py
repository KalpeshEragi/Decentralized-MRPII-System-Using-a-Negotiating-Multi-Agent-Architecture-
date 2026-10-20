"""016 Runs and run reports (demo.md §12, DM-4, step 7), created from the models like 014."""

from alembic import op

from app.simulation.models import Run, RunReport

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Run.__table__.create(op.get_bind())
    RunReport.__table__.create(op.get_bind())


def downgrade() -> None:
    RunReport.__table__.drop(op.get_bind())
    Run.__table__.drop(op.get_bind())
