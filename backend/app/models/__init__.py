"""ORM of the shared reference schema `core` (items, routings, BOM). Importing this package registers its tables on
`Base.metadata`. Agent and infrastructure tables use their own bases (`PlatformBase`, the Sales Agent's base)."""

from app.models import core  # noqa: F401
from app.models.base import Base

__all__ = ["Base"]
