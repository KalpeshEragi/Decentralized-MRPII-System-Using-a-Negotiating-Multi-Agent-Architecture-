"""Quotes (QD-1, DC-1), no database: a quote is its own short session (QUOTE_REQUEST -> QUOTE), never binding; owners
send availability as steps; Planning reads stock, hours, dock and supplier options back from the quotes."""

from datetime import date, datetime, timezone
from decimal import Decimal as D

import pytest

from app.negotiation.envelope import Envelope, MessageType as M, ResourceType, Terms
from app.negotiation.quoting import steps, value_on
from app.negotiation.state import ProtocolError, apply
from app.planning_agent.models import QuoteRound
from app.planning_agent.quotes import QuoteFacts

ASK = Terms(resource_type=ResourceType.STOCK, resource_ref="bat", quantity=D(100), date_from=date(2026, 11, 3),
            date_to=date(2026, 11, 8))


def envelope(kind, sender="PLANNING", receiver="INVENTORY", **extra) -> Envelope:
    return Envelope(message_id=f"m-{kind}-{sender}", session_id="s-1", case_id="QUOTE-1", sender=sender,
                    receiver=receiver, message_type=kind, sent_at=datetime.now(timezone.utc), **extra)


def test_a_quote_session_opens_with_quote_request_and_ends_with_quote():
    state = apply(None, envelope(M.QUOTE_REQUEST, terms=ASK))
    assert (state.status, state.turn) == ("QUOTING", "OWNER")
    quoted = apply(state, envelope(M.QUOTE, sender="INVENTORY", receiver="PLANNING", options=[ASK]))
    assert quoted.status == "QUOTED"
    with pytest.raises(ProtocolError):  # nothing binding can happen in a quote session
        apply(state, envelope(M.ACCEPT))
    with pytest.raises(ProtocolError):
        apply(quoted, envelope(M.QUOTE, sender="INVENTORY", receiver="PLANNING", options=[]))
    with pytest.raises(ValueError):  # options only on QUOTE
        envelope(M.QUOTE, sender="INVENTORY", receiver="PLANNING")


def test_availability_is_quoted_as_steps_and_read_back_per_day():
    values = {date(2026, 11, 3): 250, date(2026, 11, 4): 250, date(2026, 11, 5): 350, date(2026, 11, 6): 350,
              date(2026, 11, 7): 350, date(2026, 11, 8): 350}
    quoted = steps(ASK, date(2026, 11, 3), date(2026, 11, 8), lambda day: D(values[day]), "AVAILABLE_FROM")
    assert [(o.available_from, o.quantity) for o in quoted] == [(date(2026, 11, 3), 250), (date(2026, 11, 5), 350)]
    assert value_on(quoted, date(2026, 11, 4)) == 250 and value_on(quoted, date(2026, 11, 7)) == 350
    assert value_on(quoted, date(2026, 11, 2)) == 0


class _Item:
    def __init__(self, item_id, sourcing="BUY"):
        self.id, self.sourcing = item_id, sourcing


def test_planning_reads_the_owners_facts_from_their_quotes():
    def opt(qty, day=None, **extra):
        return Terms(resource_type=ResourceType.STOCK, resource_ref="x", quantity=D(qty),
                     available_from=day, extra=extra).model_dump(mode="json")

    quote = QuoteRound(id="QUOTE-1", demand_id=None, sessions={
        "a": {"owner": "INVENTORY", "ref": "bat", "options": [opt(250, date(2026, 11, 3)), opt(350, date(2026, 11, 5))]},
        "b": {"owner": "PURCHASING", "ref": "bat", "options": [opt(60, lead_time_days=5), opt(500, lead_time_days=9)]},
        "c": {"owner": "HR", "ref": "ASSEMBLY", "options": [opt(24, date(2026, 11, 3)), opt(16, date(2026, 11, 6))]},
        "d": {"owner": "WAREHOUSE", "ref": "RECEIVING", "options": [opt(1500, date(2026, 11, 3))]},
    })
    facts = QuoteFacts(quote)
    bat = facts.item_data(_Item("bat"))
    assert bat.on_hand == 250 and [(i.day, i.quantity) for i in bat.incoming] == [(date(2026, 11, 5), 100)]
    assert bat.safety_stock == 0  # Inventory kept its safety stock out of the quote itself
    assert facts.item_data(_Item("unknown")).on_hand == 0
    assert facts.free_worker("ASSEMBLY", date(2026, 11, 7)) == 16 and facts.free_receiving(date(2026, 11, 9)) == 1500
    assert facts.supply_lead_time_days("bat", D(50)) == 5     # the fastest supplier has enough
    assert facts.supply_lead_time_days("bat", D(400)) == 9    # needs the slower one too
    assert facts.supply_lead_time_days("bat", D(9999)) is None
