"""008 Planning Agent tables, and the need in the NG-5 key (implementation step 5).

Planning tables are created from the ORM models (`app/planning_agent/models.py`), like 007.

NG-5 says "one open negotiation per need and resource". 005 keyed it by case and resource only, so one case could not
ask for the same component (or skill) for two different production orders. The need is what the resource is for
(`terms.order_id`); it is now stored on the session (`need_ref`) and part of the unique index.
"""

import sqlalchemy as sa
from alembic import op

from app.planning_agent import models as planning

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None

TABLES = [
    planning.WorkCenter, planning.WorkCenterDay, planning.MachineHoursLedger, planning.CustomerDemand,
    planning.Option, planning.Case, planning.ProductionOrder, planning.WorkItem, planning.SalesOutbox,
    planning.ShopFloorReport, planning.EventVersion, planning.AuditLog,
]
OPEN = sa.text("status IN ('NEGOTIATING', 'AGREEMENT_PROPOSED')")


def upgrade() -> None:
    bind = op.get_bind()
    op.execute('CREATE SCHEMA IF NOT EXISTS "planning"')
    for model in TABLES:
        model.__table__.create(bind)
    op.add_column("sessions", sa.Column("need_ref", sa.String), schema="negotiation")
    op.drop_index("uq_sessions_one_open_per_need", "sessions", schema="negotiation")
    op.create_index("uq_sessions_one_open_per_need", "sessions",
                    ["case_id", "resource_type", "resource_ref", sa.text("coalesce(need_ref, '')"), "starter", "owner"],
                    unique=True, schema="negotiation", postgresql_where=OPEN)


def downgrade() -> None:
    op.drop_index("uq_sessions_one_open_per_need", "sessions", schema="negotiation")
    op.create_index("uq_sessions_one_open_per_need", "sessions",
                    ["case_id", "resource_type", "resource_ref", "starter", "owner"], unique=True,
                    schema="negotiation", postgresql_where=OPEN)
    op.drop_column("sessions", "need_ref", schema="negotiation")
    bind = op.get_bind()
    for model in reversed(TABLES):
        model.__table__.drop(bind)
    op.execute('DROP SCHEMA IF EXISTS "planning"')
