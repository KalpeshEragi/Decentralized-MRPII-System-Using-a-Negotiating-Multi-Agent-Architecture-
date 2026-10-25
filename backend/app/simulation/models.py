"""`simulation` schema (new tables): the simulated clock and the factory settings (demo.md §6, §14; SD-2).

The old tables of this schema (`simulation_scenarios`, `simulation_events`) belong to the old design and stay in
`app.models.simulation` until the Phase 2 retirement.
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.platform_base import PlatformBase

SCHEMA = "simulation"


class Clock(PlatformBase):
    """One row (id = 1): the current simulated day."""

    __tablename__ = "clock"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    current_day: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PAUSED")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())


class Setting(PlatformBase):
    """One factory setting. `version` is the settings version in which this value was last changed."""

    __tablename__ = "settings"
    __table_args__ = {"schema": SCHEMA}

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)  # {"value": <number or text>}
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())


class TriggerLog(PlatformBase):
    """Every trigger the operator (or a scenario) fires, now or scheduled for a simulated day (demo.md §7)."""

    __tablename__ = "trigger_log"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # WORKER_ABSENT, SUPPLIER_DELAY, ...
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    scheduled_day: Mapped[date | None] = mapped_column(Date)  # empty = fired at once
    status: Mapped[str] = mapped_column(String, nullable=False, default="SCHEDULED")  # SCHEDULED, DONE, FAILED
    result: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Snapshot(PlatformBase):
    """A saved starting state (DM-2): one JSON document per run table, taken when the factory was quiet."""

    __tablename__ = "snapshots"
    __table_args__ = {"schema": SCHEMA}

    name: Mapped[str] = mapped_column(String, primary_key=True)
    description: Mapped[str | None] = mapped_column(String)
    simulated_day: Mapped[date] = mapped_column(Date, nullable=False)
    tables: Mapped[dict] = mapped_column(JSONB, nullable=False)  # {"schema.table": [row, ...]}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Run(PlatformBase):
    """One run of a scenario (demo.md §12): CONFIGURING -> RUNNING -> FINISHED. Kept across restores."""

    __tablename__ = "runs"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scenario: Mapped[str] = mapped_column(String, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)  # the starting state it was restored from
    start_day: Mapped[date] = mapped_column(Date, nullable=False)
    end_day: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String, nullable=False, default="RUNNING")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunReport(PlatformBase):
    """What a run did (DM-4): metrics, the final factory state and the timeline, kept after the run is reset."""

    __tablename__ = "run_reports"
    __table_args__ = {"schema": SCHEMA}

    run_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
