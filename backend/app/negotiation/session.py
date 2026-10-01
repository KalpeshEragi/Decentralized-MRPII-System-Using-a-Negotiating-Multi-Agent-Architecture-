"""In-memory negotiation session: state machine, sequence tracking and the 3-round limit.

One session per shortage. Inventory opens it with REQUEST; Purchasing then runs up to MAX_ROUNDS supplier rounds.
A round = one Purchasing OFFER (round 1) or COUNTER_OFFER (rounds 2-3) plus the supplier interface's response.

    INITIATED --REQUEST--> NEGOTIATING
    NEGOTIATING: Purchasing OFFER / COUNTER_OFFER -> supplier ACCEPT | COUNTER_OFFER | REJECT
        supplier REJECT, or Purchasing REJECT on its turn (any time before round 3 ends) -> REJECTED
        Purchasing AGREEMENT_PROPOSED (after a supplier ACCEPT or COUNTER_OFFER) -> AGREEMENT_PROPOSED
        Purchasing COUNTER_OFFER after round MAX_ROUNDS (no acceptable response) -> FAILED
    AGREEMENT_PROPOSED --COMMIT (approval workflow, after human approval)--> COMMITTED
    AGREEMENT_PROPOSED --ABORT (approval workflow, after human rejection of the plan, C8)--> ABORTED

The session never decides whether terms are acceptable or feasible. Purchasing decides; deterministic validation
of an agreement happens outside this module. COMMIT is only representable here: Inventory and Purchasing cannot
send it, and the human approval workflow itself belongs to C8.
"""

from app.negotiation.messages import validate_message
from app.negotiation.protocol import ProtocolError, ProtocolErrorCode
from app.schemas.negotiation import (
    END_STATUSES,
    MAX_ROUNDS,
    AgentType,
    MessageType,
    NegotiationMessage,
    OfferTerms,
    SessionStatus,
)

Code = ProtocolErrorCode


class NegotiationSession:
    def __init__(
        self,
        negotiation_id: str,
        inventory_id: str,
        purchasing_id: str,
        supplier_interface_id: str,
        approval_workflow_id: str = "approval-workflow",
    ):
        self.negotiation_id = negotiation_id
        self._participants = {
            AgentType.INVENTORY: inventory_id,
            AgentType.PURCHASING: purchasing_id,
            AgentType.SUPPLIER_INTERFACE: supplier_interface_id,
            AgentType.APPROVAL_WORKFLOW: approval_workflow_id,
        }
        self.status = SessionStatus.INITIATED
        self.round_number = 0  # supplier rounds opened so far ("Round N of 3")
        self.messages: list[NegotiationMessage] = []
        self.agreed_terms: OfferTerms | None = None
        self._offer_terms: OfferTerms | None = None  # Purchasing's latest OFFER / COUNTER_OFFER terms
        self._supplier_counter: OfferTerms | None = None
        self._supplier_response: MessageType | None = None  # ACCEPT or COUNTER_OFFER, awaiting Purchasing
        self._awaiting_supplier = False
        self._seen_ids: set[str] = set()

    @property
    def awaiting_supplier(self) -> bool:
        """True while a Purchasing OFFER / COUNTER_OFFER waits for the supplier interface's response."""
        return self._awaiting_supplier

    @property
    def is_ended(self) -> bool:
        return self.status in END_STATUSES

    @property
    def outcome(self) -> str | None:
        """What is reported to Planning (C4 section 7): AGREEMENT, or FAILED when no agreement is reached."""
        if self.status in (SessionStatus.AGREEMENT_PROPOSED, SessionStatus.COMMITTED):
            return "AGREEMENT"
        if self.status in (SessionStatus.REJECTED, SessionStatus.FAILED):
            return "FAILED"
        return None

    def submit(self, message: NegotiationMessage) -> SessionStatus:
        """Apply one message. Raises ProtocolError and leaves the session unchanged if it is refused."""
        validate_message(message)
        self._check_envelope(message)
        new_status = self._apply(message)
        self.status = new_status
        self.messages.append(message)
        self._seen_ids.add(message.message_id)
        return self.status

    # -- envelope checks (no business meaning) ---------------------------------------------------------------

    def _check_envelope(self, message: NegotiationMessage) -> None:
        if message.negotiation_id != self.negotiation_id:
            raise ProtocolError(Code.WRONG_SESSION, f"message is for session {message.negotiation_id}")
        for ref in (message.sender, message.receiver):
            if self._participants[ref.agent_type] != ref.agent_id:
                raise ProtocolError(Code.UNKNOWN_PARTICIPANT, f"{ref.agent_id} is not the session's {ref.agent_type}")
        if self.is_ended:
            raise ProtocolError(Code.SESSION_ENDED, f"session is {self.status}")
        if message.message_id in self._seen_ids:
            raise ProtocolError(Code.DUPLICATE_MESSAGE, f"message_id {message.message_id} already used")
        expected = len(self.messages) + 1
        if message.sequence_number != expected:
            raise ProtocolError(Code.INVALID_SEQUENCE, f"expected sequence {expected}, got {message.sequence_number}")

    # -- state machine ---------------------------------------------------------------------------------------

    def _apply(self, message: NegotiationMessage) -> SessionStatus:
        kind = message.message_type
        terms = message.payload.terms

        def refuse(text: str) -> ProtocolError:
            return ProtocolError(Code.INVALID_STATE_TRANSITION, f"{kind} not allowed: {text} (status {self.status})")

        if self.status == SessionStatus.INITIATED:
            if kind != MessageType.REQUEST:
                raise refuse("session must start with REQUEST")
            return SessionStatus.NEGOTIATING

        if self.status == SessionStatus.AGREEMENT_PROPOSED:
            if kind == MessageType.COMMIT:
                return SessionStatus.COMMITTED
            if kind == MessageType.ABORT:
                return SessionStatus.ABORTED
            raise refuse("only COMMIT or ABORT (by the approval workflow) follows AGREEMENT_PROPOSED")

        # status NEGOTIATING
        if self._awaiting_supplier:
            if message.sender.agent_type != AgentType.SUPPLIER_INTERFACE:
                raise refuse("waiting for the supplier response")
            if kind == MessageType.REJECT:
                self._awaiting_supplier = False
                return SessionStatus.REJECTED
            if kind in (MessageType.ACCEPT, MessageType.COUNTER_OFFER):
                self._awaiting_supplier = False
                self._supplier_response = kind
                self._supplier_counter = terms if kind == MessageType.COUNTER_OFFER else None
                return SessionStatus.NEGOTIATING
            raise refuse("supplier may only ACCEPT, COUNTER_OFFER or REJECT")

        # Purchasing's turn
        if message.sender.agent_type != AgentType.PURCHASING:
            raise refuse("waiting for Purchasing")
        if kind == MessageType.REJECT:
            return SessionStatus.REJECTED  # Purchasing has no acceptable proposal; no need to run all rounds
        if kind == MessageType.OFFER:
            if self.round_number != 0:
                raise refuse("OFFER opens round 1 only")
            self._open_round(terms)
            return SessionStatus.NEGOTIATING
        if kind == MessageType.COUNTER_OFFER:
            if self._supplier_response != MessageType.COUNTER_OFFER:
                raise refuse("Purchasing can counter only a supplier COUNTER_OFFER")
            if self.round_number >= MAX_ROUNDS:
                return SessionStatus.FAILED  # rounds exhausted without an acceptable response
            self._open_round(terms)
            return SessionStatus.NEGOTIATING
        if kind == MessageType.AGREEMENT_PROPOSED:
            if self._supplier_response is None:
                raise refuse("no supplier response to agree to")
            on_table = self._supplier_counter or self._offer_terms
            if (terms.quantity, terms.delivery_date) != (on_table.quantity, on_table.delivery_date):
                raise ProtocolError(Code.TERMS_MISMATCH, "agreement terms differ from the terms on the table")
            self.agreed_terms = terms
            return SessionStatus.AGREEMENT_PROPOSED
        raise refuse("Purchasing must send OFFER, COUNTER_OFFER, AGREEMENT_PROPOSED or REJECT")

    def _open_round(self, terms: OfferTerms) -> None:
        self.round_number += 1
        self._offer_terms = terms
        self._supplier_counter = None
        self._supplier_response = None
        self._awaiting_supplier = True
