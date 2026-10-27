"""022 Negotiation sessions may be quotes (DC-1, QD-1): statuses QUOTING and QUOTED."""

from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None

OLD = ("NEGOTIATING", "AGREEMENT_PROPOSED", "COMMITTED", "REJECTED", "ABORTED", "EXPIRED", "FAILED")
NEW = (*OLD, "QUOTING", "QUOTED")


def _statuses(allowed: tuple[str, ...]) -> None:
    op.drop_constraint("ck_sessions_status", "sessions", schema="negotiation")
    op.create_check_constraint("ck_sessions_status", "sessions", f"status IN {allowed}", schema="negotiation")


def upgrade() -> None:
    _statuses(NEW)


def downgrade() -> None:
    op.execute("DELETE FROM negotiation.sessions WHERE status IN ('QUOTING', 'QUOTED')")
    _statuses(OLD)
