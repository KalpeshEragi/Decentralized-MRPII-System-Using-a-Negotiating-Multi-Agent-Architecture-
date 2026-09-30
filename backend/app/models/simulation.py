"""simulation schema: tables only. The Scenario Manager (C9) is Phase 4."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, uuid_pk


class SimulationScenario(Base):
    __tablename__ = "simulation_scenarios"
    __table_args__ = {"schema": "simulation"}

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    configuration: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime | None] = created_at()


class SimulationEvent(Base):
    __tablename__ = "simulation_events"
    __table_args__ = {"schema": "simulation"}

    id: Mapped[uuid.UUID] = uuid_pk()
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("simulation.simulation_scenarios.id")
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str | None] = mapped_column(String)
