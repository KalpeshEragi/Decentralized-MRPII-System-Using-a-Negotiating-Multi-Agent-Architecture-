"""015 Sales: an order may be CANCELLED by the customer (S6, step 7)."""

from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None

NAME = "ck_orders_status"


def upgrade() -> None:
    op.drop_constraint(NAME, "orders", schema="sales_agent", type_="check")
    op.create_check_constraint(NAME, "orders", "status IN ('CONFIRMED', 'CANCELLED')", schema="sales_agent")


def downgrade() -> None:
    op.execute("UPDATE sales_agent.orders SET status = 'CONFIRMED' WHERE status = 'CANCELLED'")
    op.drop_constraint(NAME, "orders", schema="sales_agent", type_="check")
    op.create_check_constraint(NAME, "orders", "status IN ('CONFIRMED')", schema="sales_agent")
