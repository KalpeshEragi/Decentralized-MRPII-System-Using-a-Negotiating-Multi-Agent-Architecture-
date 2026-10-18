"""007 Tables of the owner agents: Inventory, HR, Warehouse (implementation step 4).

Unlike 001–006, this migration creates the tables from the ORM model definitions (`app/<agent>/models.py`), so the
models and the database cannot drift apart while the design is still moving. Consequence: a fresh database migrated
later gets the models as they are then; a later change to these tables still needs its own migration.
Status values are checked in code for now (not by CHECK constraints).
"""

from alembic import op

from app.hr_agent import models as hr
from app.inventory_agent import models as inventory
from app.warehouse_agent import models as warehouse

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None

TABLES = [
    inventory.StockBalance, inventory.StockLedger, inventory.Hold, inventory.Reservation, inventory.IncomingReceipt,
    inventory.EventVersion, inventory.AuditLog,
    hr.Worker, hr.Absence, hr.PoolDay, hr.WorkerMove, hr.OvertimeEntry, hr.Hold, hr.Commitment, hr.Assignment,
    hr.HoursLedger, hr.EventVersion, hr.AuditLog,
    warehouse.Zone, warehouse.DailyCapacity, warehouse.ReceivingDay, warehouse.ShippingDay, warehouse.Hold,
    warehouse.SpaceCommitment, warehouse.SpaceMovement, warehouse.SpaceLedger, warehouse.EventVersion,
    warehouse.AuditLog,
]


def upgrade() -> None:
    bind = op.get_bind()
    for schema in ("inventory", "hr", "warehouse"):
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    for model in TABLES:
        model.__table__.create(bind)


def downgrade() -> None:
    bind = op.get_bind()
    for model in reversed(TABLES):
        model.__table__.drop(bind)
    for schema in ("hr", "warehouse"):
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}"')
