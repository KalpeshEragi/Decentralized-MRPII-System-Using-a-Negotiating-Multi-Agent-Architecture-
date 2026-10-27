"""019 Rule profile and rule change history (RE-1, RE-6), created from the models like 016."""

from alembic import op

from app.simulation.models import RuleChange, RuleValue

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    RuleValue.__table__.create(op.get_bind())
    RuleChange.__table__.create(op.get_bind())


def downgrade() -> None:
    RuleChange.__table__.drop(op.get_bind())
    RuleValue.__table__.drop(op.get_bind())
