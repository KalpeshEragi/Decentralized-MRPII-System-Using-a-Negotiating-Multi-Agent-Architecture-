"""Starting states (demo.md §5, DM-2): save the whole run state when the factory is quiet, restore it exactly.

Save copies every run table (every agent schema, `core`, events, negotiation, the Purchasing schemas, the simulation
clock, settings and trigger log) into one `simulation.snapshots` row, one JSON document per table. The copy is made
inside PostgreSQL (`jsonb_agg`), so nothing travels row by row. Failed work items are not saved.

Restore, in one transaction: empty every run table, load the snapshot back (`jsonb_populate_recordset`), set the
identity counters past the restored rows, pause the clock. Then every owner's reconcile check runs (balances against
their ledger sums) and must find no difference. This is the only place the simulator writes agents' tables, and it
only loads an exact copy of a state the agents themselves produced.
"""

import json

from sqlalchemy import Table, text
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.simulation.clock import get_clock, today
from app.simulation.models import RuleChange, RuleValue, Run, RunReport, Snapshot

KEPT = (Snapshot.__table__, Run.__table__, RunReport.__table__,  # survive a restore: not part of a run's state
        RuleValue.__table__, RuleChange.__table__)  # the user's rule profile and its history (RE-6)


def run_tables() -> list[Table]:
    """Every table of a run, parents before children. Snapshots, runs and run reports are not part of a run."""
    from app.core.platform_base import PlatformBase
    from app.models import Base
    from app.negotiation_engine.models import NegotiationEngineBase
    from app.purchasing_agent.models import PurchasingAgentBase
    from app.sales_agent.models import SalesAgentBase
    from app.supplier_service.models import SupplierServiceBase

    tables = []
    for base in (Base, SupplierServiceBase, PlatformBase, SalesAgentBase, PurchasingAgentBase, NegotiationEngineBase):
        tables += [t for t in base.metadata.sorted_tables if t not in KEPT]
    return tables


def _name(table: Table) -> str:
    return f'"{table.schema}"."{table.name}"'


def _key(table: Table) -> str:
    return f"{table.schema}.{table.name}"


def _queue_tables() -> set[str]:
    from app.simulation.runner import queue_models

    return {_key(model.__table__) for model in queue_models()}


def save(db: Session, name: str, description: str | None = None) -> dict:
    """Save the current state under `name` (replacing a state of that name). Only when the factory is quiet."""
    from app.simulation.runner import waiting

    if left := waiting(db):
        raise AppError(ErrorCode.CONFLICT, f"the factory is not quiet: {left}")
    queues = _queue_tables()
    tables = {}
    for table in run_tables():
        where = " WHERE status <> 'FAILED'" if _key(table) in queues else ""
        tables[_key(table)] = db.execute(text(
            f"SELECT coalesce(jsonb_agg(to_jsonb(t)), '[]'::jsonb) FROM {_name(table)} t{where}")).scalar_one()
    db.merge(Snapshot(name=name, description=description, simulated_day=today(db), tables=tables))
    return {"name": name, "simulated_day": today(db).isoformat(),
            "rows": sum(len(rows) for rows in tables.values())}


def restore(db: Session, name: str) -> dict:
    """Replace the whole run state with the saved one, in this transaction (caller commits)."""
    snapshot = db.get(Snapshot, name)
    if snapshot is None:
        raise AppError(ErrorCode.NOT_FOUND, f"no state named {name}")
    tables = clear(db)
    later: list[tuple[Table, list[str], str]] = []
    for table in tables:
        rows = snapshot.tables.get(_key(table), [])
        if not rows:
            continue
        circular = [c.name for c in table.columns if any(fk.use_alter for fk in c.foreign_keys)]
        columns = [c.name for c in table.columns]
        target = ", ".join(f'"{c}"' for c in columns)
        selected = ", ".join("NULL" if c in circular else f'"{c}"' for c in columns)
        data = json.dumps(rows)
        db.execute(text(f"INSERT INTO {_name(table)} ({target}) SELECT {selected} "
                        f"FROM jsonb_populate_recordset(NULL::{_name(table)}, CAST(:rows AS jsonb))"), {"rows": data})
        if circular:  # links that point back and forth between tables are set once every row exists
            later.append((table, circular, data))
    for table, circular, data in later:
        keys = [c.name for c in table.primary_key.columns]
        db.execute(text(
            f"UPDATE {_name(table)} AS t SET " + ", ".join(f'"{c}" = s."{c}"' for c in circular)
            + f" FROM jsonb_populate_recordset(NULL::{_name(table)}, CAST(:rows AS jsonb)) AS s WHERE "
            + " AND ".join(f't."{k}" = s."{k}"' for k in keys)), {"rows": data})
    _reset_counters(db, tables)
    get_clock(db, lock=True).status = "PAUSED"
    from app.rules.service import reapply_profile

    reapply_profile(db)  # RE-6: the user's business rules survive a restore
    db.flush()
    return {"name": name, "simulated_day": today(db).isoformat(), "reconcile": reconcile(db)}


def clear(db: Session) -> list[Table]:
    """Empty every run table (an empty factory: no items, stock, events, negotiations, clock or settings)."""
    tables = run_tables()
    db.execute(text("TRUNCATE " + ", ".join(_name(t) for t in tables) + " CASCADE"))
    return tables


def _reset_counters(db: Session, tables: list[Table]) -> None:
    """Identity / serial counters continue after the restored rows (so new rows never reuse an id)."""
    schemas = sorted({t.schema for t in tables})
    columns = db.execute(text(
        "SELECT table_schema, table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = ANY(:schemas) AND (is_identity = 'YES' OR column_default LIKE 'nextval%')"),
        {"schemas": schemas}).all()
    wanted = {_key(t) for t in tables}
    for schema, table, column in columns:
        if f"{schema}.{table}" not in wanted:
            continue
        db.execute(text(
            f"SELECT setval(pg_get_serial_sequence('\"{schema}\".\"{table}\"', '{column}'), "
            f"coalesce((SELECT max(\"{column}\") FROM \"{schema}\".\"{table}\"), 0) + 1, false)"))


def reconcile(db: Session) -> dict[str, list[str]]:
    """Every owner's own check: balances against its ledger sums. Empty lists = no difference."""
    from app.hr_agent import reads as hr
    from app.inventory_agent import reads as inventory
    from app.planning_agent import reads as planning
    from app.warehouse_agent import reads as warehouse

    return {"inventory": inventory.reconcile(db), "hr": hr.reconcile(db), "warehouse": warehouse.reconcile(db),
            "planning": planning.reconcile(db)}


def listing(db: Session) -> list[dict]:
    rows = db.execute(text("SELECT name, description, simulated_day, created_at FROM simulation.snapshots "
                           "ORDER BY created_at")).all()
    return [{"name": n, "description": d, "simulated_day": day.isoformat(), "created_at": c.isoformat()}
            for n, d, day, c in rows]
