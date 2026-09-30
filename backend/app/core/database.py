"""SQLAlchemy engine and session factory. The database is PostgreSQL on Neon, reached through `DATABASE_URL`."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode


def make_engine(url: str) -> Engine:
    # pool_pre_ping: Neon serverless closes idle connections.
    return create_engine(url, pool_pre_ping=True)


@lru_cache
def get_engine() -> Engine:
    url = get_settings().database_url
    if not url:
        raise AppError(ErrorCode.SERVICE_UNAVAILABLE, "the database is not configured")
    return make_engine(url)


class _LazySession(Session):
    """Binds to the engine on first use, so request validation errors are reported before any database error."""

    def get_bind(self, *args, **kwargs):
        return get_engine()


def new_session() -> Session:
    """A session on the configured database; the caller commits and closes it."""
    return sessionmaker(class_=_LazySession, expire_on_commit=False)()


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    db = new_session()
    try:
        yield db
    finally:
        db.close()
