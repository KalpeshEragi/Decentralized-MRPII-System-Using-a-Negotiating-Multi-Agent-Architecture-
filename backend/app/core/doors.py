"""Machine-to-machine door keys (backend_api.md §3): header `X-Door-Key`, compared in constant time with the key
configured for that door. No key configured -> nobody gets in."""

import hmac
from collections.abc import Callable

from fastapi import Header

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode


def require_door_key(setting_name: str) -> Callable[..., None]:
    """FastAPI dependency for a door whose key is the setting `setting_name` (e.g. "simulation_door_key")."""

    def check(x_door_key: str | None = Header(default=None)) -> None:
        expected = getattr(get_settings(), setting_name)
        if not expected or not x_door_key or not hmac.compare_digest(x_door_key, expected):
            raise AppError(ErrorCode.FORBIDDEN, "wrong or missing door key")

    return check
