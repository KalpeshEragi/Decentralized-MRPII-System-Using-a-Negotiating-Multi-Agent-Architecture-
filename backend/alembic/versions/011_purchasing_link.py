"""011 Connect the Purchasing Agent (PI-1 to PI-6, implementation step 6).

- Schema `purchasing_link`: the adapter's tables (links between Planning's SUPPLY negotiations and Procurement
  Requests, its work queue, event versions), created from the models like 007/008.
- `inventory.incoming_receipts` gets `for_kind` / `for_ref`: a delivery bought for one order is pegged to it, so other
  requests do not count on it (like produced goods, RD-5).
"""

import sqlalchemy as sa
from alembic import op

from app.purchasing_agent import link_models as link

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None

TABLES = [link.PlanningLink, link.AdapterWork, link.EventVersion]


def upgrade() -> None:
    bind = op.get_bind()
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{link.SCHEMA}"')
    for model in TABLES:
        model.__table__.create(bind)
    op.add_column("incoming_receipts", sa.Column("for_kind", sa.String), schema="inventory")
    op.add_column("incoming_receipts", sa.Column("for_ref", sa.String), schema="inventory")


def downgrade() -> None:
    op.drop_column("incoming_receipts", "for_ref", schema="inventory")
    op.drop_column("incoming_receipts", "for_kind", schema="inventory")
    bind = op.get_bind()
    for model in reversed(TABLES):
        model.__table__.drop(bind)
    op.execute(f'DROP SCHEMA IF EXISTS "{link.SCHEMA}"')
