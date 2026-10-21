"""Re-sourcing (§7.4.1, ADR-003) as plain code: how a supplier without an open Leg enters, and the selection rules over
the open Legs plus those candidates, with the saving threshold re-checked. No database. Data follows
dev_docs/purchasing_agent/seed_data.md (N9, N12, N13).
"""

import uuid
from datetime import date
from decimal import Decimal

from app.core.config import Settings
from app.purchasing_agent.re_sourcing import candidate_option
from app.purchasing_agent.selection import PriceState, SupplierOption, select_suppliers
from app.supplier_service.service import SupplierItemRecord

D = date(2026, 11, 2)  # selection date of the fixture
THRESHOLD = Settings.model_fields["purchasing_cost_saving_split_threshold"].default  # the working 10%


def priced(price: str) -> PriceState:
    return PriceState("PRICED", Decimal(price), uuid.uuid4())


def supplier(name, lead, moq, available) -> SupplierItemRecord:
    return SupplierItemRecord(uuid.uuid4(), name, True, lead, Decimal(moq), Decimal(available))


def open_leg(name, lead, moq, available, price) -> SupplierOption:
    """An open Leg as re-sourcing sees it: its price snapshot, availability limited by its cap."""
    return SupplierOption(uuid.uuid4(), name, True, lead, Decimal(moq), Decimal(available), priced(price))


def candidate(record, price, cap=None, remembered_date=None) -> SupplierOption:
    return candidate_option(record, record.available_qty, priced(price), D, cap, remembered_date)


def reasons(selection) -> dict[str, str]:
    return {o.supplier_name: o.reason for o in selection.options}


def legs(selection) -> dict[str, Decimal]:
    return {leg.supplier_name: leg.quantity for leg in selection.legs}


CELL = supplier("Cell Works", 9, 200, 500)


def test_a_returning_supplier_is_limited_by_its_remembered_cap_and_date():
    returning = candidate(CELL, "900.00", cap=Decimal(300), remembered_date=date(2026, 11, 15))

    assert returning.available_qty == Decimal(300)  # min(500 effective, cap 300)
    assert returning.lead_time_days == 13  # arrives on the remembered 11-15, later than D + 9
    assert returning.price.unit_price == Decimal("900.00")  # the current contract price


def test_a_remembered_date_earlier_than_the_lead_time_is_not_a_promise():
    returning = candidate(CELL, "900.00", remembered_date=date(2026, 11, 5))

    assert returning.lead_time_days == 9  # D + lead time is the earliest it can arrive


def test_a_returning_supplier_whose_cap_is_below_its_moq_or_whose_date_is_too_late_is_unusable():
    below_moq = candidate(CELL, "900.00", cap=Decimal(150))  # MOQ 200
    too_late = candidate(CELL, "900.00", remembered_date=date(2026, 11, 21))
    selection = select_suppliers(Decimal(100), date(2026, 11, 20), [below_moq], D, saving_threshold=THRESHOLD)
    assert reasons(selection) == {"Cell Works": "availability_below_moq"}
    selection = select_suppliers(Decimal(100), date(2026, 11, 20), [too_late], D, saving_threshold=THRESHOLD)
    assert reasons(selection) == {"Cell Works": "arrives_too_late"}


def test_n9_the_threshold_is_re_checked_so_a_split_saving_3_percent_loses_to_a_new_single():
    alpha = open_leg("Alpha Displays", 10, 200, 450, "1200.00")  # capped at 450
    beta = candidate(supplier("Beta Optics", 6, 100, 800), "1250.00")
    selection = select_suppliers(Decimal(500), date(2026, 11, 20), [alpha, beta], D, saving_threshold=THRESHOLD)

    # Alpha 400 + Beta 100 = 605,000 saves only 3.2% against Beta 500 = 625,000.
    assert (selection.outcome, legs(selection)) == ("SINGLE", {"Beta Optics": Decimal(500)})
    assert selection.total_cost == Decimal("625000.00")


def test_n12_a_split_exactly_10_percent_under_the_new_single_qualifies():
    volt = open_leg("Volt Power", 7, 100, 400, "800.00")
    cell = open_leg("Cell Works", 9, 200, 300, "900.00")  # "max 300"
    ion = candidate(supplier("Ion Supply", 12, 300, 1500), "1000.00")
    selection = select_suppliers(Decimal(800), date(2026, 11, 20), [volt, cell, ion], D, saving_threshold=THRESHOLD)

    # Ion 800 = 800,000; {Volt, Ion} and {Volt, Cell, Ion} both 720,000: fewer suppliers wins.
    assert (selection.outcome, legs(selection)) == (
        "COST_SAVING_SPLIT", {"Ion Supply": Decimal(400), "Volt Power": Decimal(400)})
    assert selection.total_cost == Decimal("720000.00")


def test_n13_a_returning_supplier_makes_the_only_feasible_combination():
    volt = open_leg("Volt Power", 7, 100, 400, "800.00")
    ion = open_leg("Ion Supply", 12, 300, 350, "1000.00")  # "max 350"
    cell = candidate(CELL, "900.00", cap=Decimal(300))  # dropped in N12, cap remembered
    selection = select_suppliers(Decimal(800), date(2026, 11, 20), [volt, ion, cell], D, saving_threshold=THRESHOLD)

    assert (selection.outcome, legs(selection)) == ("NECESSARY_SPLIT", {
        "Cell Works": Decimal(200), "Ion Supply": Decimal(300), "Volt Power": Decimal(300)})
    assert selection.total_cost == Decimal("720000.00")
