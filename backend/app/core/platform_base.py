"""ORM base for the shared infrastructure tables of the six-agent design (events, simulation clock and settings,
observability).

It is separate from the old `app.models.Base`, so the old demo reset (`/simulation/reset`, which truncates every
table of that base) cannot delete infrastructure data. The Sales Agent does the same with its own base.
"""

from sqlalchemy.orm import DeclarativeBase


class PlatformBase(DeclarativeBase):
    pass
