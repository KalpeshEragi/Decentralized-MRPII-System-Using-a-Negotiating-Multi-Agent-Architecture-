"""Protocol constants and errors. The protocol enforces form and order only; it makes no business decisions.

Terminal results: REJECTED = a participant (supplier interface or Purchasing) explicitly rejected;
FAILED = the 3-round limit was reached without agreement. Planning receives both as the normalized outcome FAILED.
"""

from enum import StrEnum

from app.schemas.negotiation import MAX_ROUNDS, MessageType, SessionStatus  # noqa: F401  (re-exported)


class ProtocolErrorCode(StrEnum):
    INVALID_MESSAGE = "INVALID_MESSAGE"  # malformed envelope, wrong route, missing/forbidden terms
    WRONG_SESSION = "WRONG_SESSION"
    UNKNOWN_PARTICIPANT = "UNKNOWN_PARTICIPANT"
    INVALID_SEQUENCE = "INVALID_SEQUENCE"
    DUPLICATE_MESSAGE = "DUPLICATE_MESSAGE"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    SESSION_ENDED = "SESSION_ENDED"
    TERMS_MISMATCH = "TERMS_MISMATCH"


class ProtocolError(Exception):
    """A message the protocol refuses. The session is left unchanged."""

    def __init__(self, code: ProtocolErrorCode, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
