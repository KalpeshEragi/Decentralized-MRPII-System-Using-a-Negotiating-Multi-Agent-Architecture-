"""Phase 2 manual verification against a real database. Run from backend/ with DATABASE_URL set and migrated:

    alembic upgrade head
    python scripts/verify_phase2.py

WARNING: this RESETS the database to the X1 baseline (all rows in the 24 tables are deleted first).
It does not start the API server; it calls the services directly and prints what was persisted.
"""

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402

from app.core.database import new_session  # noqa: E402
from app.data import x1_fixture as x1  # noqa: E402
from app.data.seed_data import BASELINE_ORDER_ID, reset_and_seed  # noqa: E402
from app.models import audit, planning  # noqa: E402
from app.services import negotiation_service, planning_service  # noqa: E402


def main() -> None:
    with new_session() as db:
        reset_and_seed(db)
        print("== seeded X1 baseline (order SO-0001, 1000 units, NEW) ==")
        plan = planning_service.run_plan(db, BASELINE_ORDER_ID)
        stored = planning_service.get_plan(db, BASELINE_ORDER_ID)
        print(f"plan status: {stored.status}; identical after reading back: "
              f"{stored.model_dump(mode='json') == plan.model_dump(mode='json')}")
        mps = stored.mps[0]
        print(f"MPS: qty {mps.planned_quantity}, {mps.planned_start} -> {mps.planned_end}")
        for row in stored.requirements:
            print(f"  {x1.component_name(row.item_id):<14} gross {row.gross_requirement:>5} avail {row.available_quantity:>5} "
                  f"net {row.net_requirement:>4} {row.status}")
        print(f"rows: mps_plans={db.scalar(select(func.count()).select_from(planning.MpsPlan))}, "
              f"mrp_requirements={db.scalar(select(func.count()).select_from(planning.MrpRequirement))}, "
              f"audit={db.scalar(select(func.count()).select_from(audit.DecisionAudit))}")

        print("\n== negotiation session for the Display shortage ==")
        view = negotiation_service.open_session(db, BASELINE_ORDER_ID, uuid.UUID(x1.COMPONENT_IDS["Display"]))
        print(f"session {view['id']}: {view['status']}, objective shortage {view['objective']['shortage_quantity']} "
              f"by {view['objective']['required_by']}")
        print("Send messages with tests/db/test_negotiation_persistence.py, the API, or scripts/a2a_spike_client.py.")


if __name__ == "__main__":
    main()
