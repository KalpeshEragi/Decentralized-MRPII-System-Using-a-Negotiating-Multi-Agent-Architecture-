"""ORM base and column helpers. Tables follow the earlier 25% schema design (C2 subset)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def created_at() -> Mapped[datetime | None]:
    # TIMESTAMP columns are stored as timestamptz (UTC).
    return mapped_column(DateTime(timezone=True), server_default=func.now())
