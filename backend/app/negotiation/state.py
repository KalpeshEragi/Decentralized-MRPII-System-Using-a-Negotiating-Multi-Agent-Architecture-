"""The session state machine of the six-agent design (negotiation.md §4). Pure: no database, no business decisions.

    starter REQUEST                                   -> NEGOTIATING (owner's turn)
    owner OFFER | COUNTER_OFFER (one round each)      -> starter's turn
    starter ACCEPT                                    -> owner's turn (must hold or reject)
    starter COUNTER_OFFER (after round 3 -> FAILED)   -> owner's turn
    owner AGREEMENT_PROPOSED (same terms + hold)      -> AGREEMENT_PROPOSED
    starter COMMIT                                    -> owner re-checks: owner ACCEPT -> COMMITTED,
                                                         owner REJECT (STALE/UNAVAILABLE) -> REJECTED
    owner REJECT HOLD_EXPIRED (hold ran out)          -> EXPIRED
    starter QUOTE_REQUEST -> QUOTING; owner QUOTE      -> QUOTED   (QD-1: non-binding, no hold, nothing reserved)
    REJECT by either side                             -> REJECTED
    starter ABORT while open                          -> ABORTED
"""

from dataclasses import dataclass, replace

from app.negotiation.envelope import Envelope, MessageType, ReasonCode, Terms

MAX_ROUNDS = 3
OPEN = ("NEGOTIATING", "AGREEMENT_PROPOSED")
ENDED = ("COMMITTED", "REJECTED", "ABORTED", "EXPIRED", "FAILED", "QUOTED")


class ProtocolError(Exception):
    """A message the protocol refuses; the session stays unchanged."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


@dataclass(frozen=True)
class SessionState:
    session_id: str
    case_id: str
    starter: str
    owner: str
    status: str
    turn: str  # "STARTER" or "OWNER"
    round: int = 0
    last_offer: Terms | None = None
    accepted: bool = False
    commit_requested: bool = False
    agreed_terms: Terms | None = None
    hold_id: str | None = None


def apply(state: SessionState | None, message: Envelope) -> SessionState:
    kind = message.message_type

    def refuse(text: str) -> ProtocolError:
        return ProtocolError("INVALID_STATE_TRANSITION", f"{kind} not allowed: {text}")

    if state is None:
        if kind == MessageType.QUOTE_REQUEST:  # QD-1: a quote session, outside the binding lifecycle
            return SessionState(message.session_id, message.case_id, message.sender, message.receiver, "QUOTING",
                                "OWNER")
        if kind != MessageType.REQUEST:
            raise ProtocolError("WRONG_SESSION", "unknown session; a session starts with REQUEST or QUOTE_REQUEST")
        return SessionState(message.session_id, message.case_id, message.sender, message.receiver, "NEGOTIATING",
                            "OWNER")
    if kind in (MessageType.REQUEST, MessageType.QUOTE_REQUEST):
        raise ProtocolError("CONFLICT", "the session already exists")
    if {message.sender, message.receiver} != {state.starter, state.owner}:
        raise ProtocolError("UNKNOWN_PARTICIPANT", "sender and receiver are not this session's starter and owner")
    if message.case_id != state.case_id:
        raise ProtocolError("WRONG_SESSION", "case_id differs from the session's case")
    if state.status in ENDED:
        raise ProtocolError("SESSION_ENDED", f"session is {state.status}")

    by_starter = message.sender == state.starter

    if kind == MessageType.ABORT:
        if not by_starter:
            raise refuse("only the starter aborts")
        return replace(state, status="ABORTED")
    if kind == MessageType.REJECT and not by_starter:
        status = "EXPIRED" if message.reason_code == ReasonCode.HOLD_EXPIRED else "REJECTED"
        return replace(state, status=status)

    if state.status == "QUOTING":  # the owner answers with its options (or REJECT, handled above); nothing else
        if kind == MessageType.QUOTE and not by_starter:
            return replace(state, status="QUOTED")
        raise refuse("a quote session only takes QUOTE from the owner, REJECT, or ABORT from the starter")
    if kind == MessageType.QUOTE:
        raise refuse("QUOTE answers a QUOTE_REQUEST")

    if state.status == "AGREEMENT_PROPOSED":
        if kind == MessageType.COMMIT and by_starter and not state.commit_requested:
            return replace(state, commit_requested=True, turn="OWNER")
        if kind == MessageType.ACCEPT and not by_starter and state.commit_requested:
            return replace(state, status="COMMITTED")
        raise refuse("after AGREEMENT_PROPOSED only COMMIT (starter), then ACCEPT or REJECT (owner)")

    # NEGOTIATING
    expected = "STARTER" if by_starter else "OWNER"
    if state.turn != expected:
        raise refuse(f"it is the {state.turn.lower()}'s turn")
    if by_starter:
        if kind == MessageType.REJECT:
            return replace(state, status="REJECTED")
        if kind == MessageType.ACCEPT:
            if state.last_offer is None:
                raise refuse("nothing to accept")
            return replace(state, accepted=True, turn="OWNER")
        if kind == MessageType.COUNTER_OFFER:
            if state.round >= MAX_ROUNDS:
                return replace(state, status="FAILED")  # rounds exhausted without agreement
            return replace(state, last_offer=message.terms, turn="OWNER")
        raise refuse("the starter may ACCEPT, COUNTER_OFFER, REJECT or ABORT")
    # owner's turn
    if state.accepted:
        if kind != MessageType.AGREEMENT_PROPOSED:
            raise refuse("after ACCEPT the owner proposes the agreement (with a hold) or rejects")
        if not message.terms.same_deal(state.last_offer):
            raise ProtocolError("TERMS_MISMATCH", "agreement terms differ from the accepted offer")
        return replace(state, status="AGREEMENT_PROPOSED", agreed_terms=message.terms, hold_id=message.hold.hold_id,
                       turn="STARTER")
    if kind in (MessageType.OFFER, MessageType.COUNTER_OFFER):
        if state.round >= MAX_ROUNDS:
            raise refuse(f"at most {MAX_ROUNDS} rounds")
        return replace(state, round=state.round + 1, last_offer=message.terms, turn="STARTER")
    raise refuse("the owner may OFFER, COUNTER_OFFER or REJECT")
