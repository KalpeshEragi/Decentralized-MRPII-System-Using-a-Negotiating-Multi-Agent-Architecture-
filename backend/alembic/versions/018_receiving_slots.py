"""018 WH-1: Purchasing negotiates a receiving slot with Warehouse before it offers supply to Planning.

- `purchasing_link.receiving_slots`: the adapter's slot negotiations (one per agreed delivery), created from the model.
- `warehouse.space_commitments.receiving_units`: the receiving capacity a delivery commitment holds on its arrival day
  (moved with the delivery when a supplier is late).
"""

from alembic import op

from app.purchasing_agent.link_models import ReceivingSlotLink

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ReceivingSlotLink.__table__.create(op.get_bind())
    # IF NOT EXISTS: 007 creates the table from the current model, which already has this column on a new database
    op.execute("ALTER TABLE warehouse.space_commitments ADD COLUMN IF NOT EXISTS receiving_units NUMERIC NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.drop_column("space_commitments", "receiving_units", schema="warehouse")
    ReceivingSlotLink.__table__.drop(op.get_bind())
