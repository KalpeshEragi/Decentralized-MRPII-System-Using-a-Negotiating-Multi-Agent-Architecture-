"""Planning's decision point D7, no database: which choices the check allows after a counter-offer or a reject, and the
deterministic policy (QD-6: re-ask a stale answer while tries are left, otherwise today's rule)."""

from datetime import date
from decimal import Decimal as D

from app.negotiation.envelope import ResourceType, Terms
from app.planning_agent.decisions import MAX_REASKS, Setback, fallback, validate

NEED = date(2026, 11, 10)


def stock(qty, day=NEED, for_kind="PRODUCTION_ORDER") -> Terms:
    return Terms(resource_type=ResourceType.STOCK, resource_ref="bat", quantity=D(qty), needed_by=NEED,
                 available_from=day, order_id="po-1", extra={"for_kind": for_kind})


def setback(reply="REJECT", reason="STALE", counter=None, tries=0, sourcing="BUY", owner="INVENTORY",
            replanned=False, asked=None) -> Setback:
    return Setback(owner=owner, need="stock bat", reply=reply, reason=reason, asked=asked or stock(100),
                   counter=counter, tries=tries, sourcing=sourcing, options_left=1, replanned=replanned)


def test_a_stale_reject_is_asked_again_until_the_limit_then_todays_rule():
    assert validate(setback(), "RE_ASK", {}) is None
    assert fallback(setback()) == ("RE_ASK", {})
    worn = setback(tries=MAX_REASKS)
    assert "already re-asked" in validate(worn, "RE_ASK", {})
    assert fallback(worn) == ("NEXT_OPTION", {})
    plain = setback(reason="INSUFFICIENT")  # re-asking cannot create stock
    assert validate(plain, "RE_ASK", {}) is not None and fallback(plain) == ("NEXT_OPTION", {})


def test_a_counter_is_accepted_only_when_the_customer_date_still_holds():
    full_in_time = setback(reply="COUNTER_OFFER", reason="TOO_LATE", counter=stock(100, day=NEED))
    assert validate(full_in_time, "ACCEPT_COUNTER", {}) is None
    late = setback(reply="COUNTER_OFFER", reason="TOO_LATE", counter=stock(100, day=date(2026, 11, 13)))
    assert "would not hold" in validate(late, "ACCEPT_COUNTER", {})
    smaller = setback(reply="COUNTER_OFFER", reason="INSUFFICIENT", counter=stock(40))
    assert "plan needs 100" in validate(smaller, "ACCEPT_COUNTER", {})
    assert fallback(late) == ("NEXT_OPTION", {})  # today's rule for any counter


def test_partial_and_buy_only_for_bought_material_of_a_production_order():
    smaller = setback(reply="COUNTER_OFFER", reason="INSUFFICIENT", counter=stock(40))
    assert validate(smaller, "PARTIAL_AND_BUY", {}) is None
    assert "bought materials" in validate(setback(reply="COUNTER_OFFER", reason="INSUFFICIENT", counter=stock(40),
                                                  sourcing="MAKE"), "PARTIAL_AND_BUY", {})
    finished = setback(reply="COUNTER_OFFER", reason="INSUFFICIENT", counter=stock(40, for_kind="CUSTOMER_DEMAND"),
                       asked=stock(100, for_kind="CUSTOMER_DEMAND"))
    assert validate(finished, "PARTIAL_AND_BUY", {}) is not None
    hours = setback(reply="COUNTER_OFFER", reason="NO_WORKFORCE", owner="HR", counter=stock(40))
    assert "only a stock counter-offer" in validate(hours, "PARTIAL_AND_BUY", {})
    too_late = setback(reply="COUNTER_OFFER", reason="INSUFFICIENT", counter=stock(40, day=date(2026, 11, 12)))
    assert "too late" in validate(too_late, "PARTIAL_AND_BUY", {})


def test_replan_only_once_and_giving_up_is_always_allowed():
    assert validate(setback(), "REPLAN", {}) is None
    assert "already replanned" in validate(setback(replanned=True), "REPLAN", {})
    assert validate(setback(replanned=True), "NEXT_OPTION", {}) is None
    assert "unknown action" in validate(setback(), "BUY_EVERYTHING", {})
