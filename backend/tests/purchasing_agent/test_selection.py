"""Choosing the best priced single supplier. Plain code: no database. Data follows docs/purchasing_agent_fixture.md."""

import uuid
from datetime import date
from decimal import Decimal

from app.purchasing_agent.selection import Contract, SupplierOption, price_state, select_single_supplier

D = date(2026, 11, 2)  # selection date of the fixture


def contract(price, valid_from=date(2026, 1, 1), valid_until=None, is_active=True) -> Contract:
    return Contract(id=uuid.uuid4(), unit_price=Decimal(price), valid_from=valid_from, valid_until=valid_until,
                    is_active=is_active)


def option(name, lead, moq, available, contracts=(), is_active=True) -> SupplierOption:
    return SupplierOption(supplier_id=uuid.uuid4(), supplier_name=name, is_active=is_active, lead_time_days=lead,
                          min_order_qty=Decimal(moq), available_qty=Decimal(available), price=price_state(contracts, D))


DISPLAY_SUPPLIERS = [
    option("Alpha Displays", 10, 200, 1000, [contract("1200.00")]),
    option("Beta Optics", 6, 100, 800, [contract("1250.00", valid_until=date(2026, 12, 31))]),
    option("Gamma Screens", 4, 50, 2000),  # no contract: Not Registered
    option("Dormant Displays", 1, 10, 5000, is_active=False),
]


def considered(selection) -> dict[str, str]:
    return {o.supplier_name: o.reason for o in selection.options}


def test_a1_the_cheapest_priced_single_supplier_wins_and_every_option_says_why():
    selection = select_single_supplier(Decimal(500), date(2026, 11, 20), DISPLAY_SUPPLIERS, D)

    assert selection.outcome == "SINGLE"
    winner = selection.winner
    assert (winner.supplier_name, winner.order_quantity, winner.unit_price, winner.total_cost) == (
        "Alpha Displays", Decimal(500), Decimal("1200.00"), Decimal("600000.00"))
    assert winner.arrival == date(2026, 11, 12)
    assert considered(selection) == {
        "Alpha Displays": "selected",
        "Beta Optics": "higher_cost",  # 625,000
        "Gamma Screens": "not_registered",  # faster, but no price: never chosen over a priced supplier
        "Dormant Displays": "inactive_supplier",
    }


def test_a2_moq_surplus_counts_against_a_supplier():
    selection = select_single_supplier(Decimal(150), date(2026, 11, 20), DISPLAY_SUPPLIERS, D)

    # Alpha must order its MOQ of 200 = 240,000 despite the lower unit price; Beta 150 = 187,500.
    assert (selection.winner.supplier_name, selection.winner.total_cost) == ("Beta Optics", Decimal("187500.00"))
    alpha = next(o for o in selection.options if o.supplier_name == "Alpha Displays")
    assert (alpha.order_quantity, alpha.total_cost) == (Decimal(200), Decimal("240000.00"))


def test_no_priced_single_supplier_in_time_fails_the_selection():
    selection = select_single_supplier(Decimal(300), date(2026, 11, 5), DISPLAY_SUPPLIERS, D)

    assert (selection.outcome, selection.winner) == ("FAILED", None)
    assert considered(selection) == {
        "Alpha Displays": "arrives_too_late", "Beta Optics": "arrives_too_late",
        "Gamma Screens": "arrives_too_late", "Dormant Displays": "inactive_supplier",
    }


def test_suppliers_that_cannot_cover_alone_or_meet_their_moq_are_unusable():
    suppliers = [
        option("Small Stock", 1, 100, 300, [contract("1.00")]),  # covers 300 of 500
        option("Below MOQ", 1, 400, 350, [contract("1.00")]),  # cannot even supply its MOQ
        option("Covers", 1, 100, 600, [contract("2.00")]),
    ]
    selection = select_single_supplier(Decimal(500), date(2026, 11, 20), suppliers, D)

    assert considered(selection) == {
        "Small Stock": "cannot_cover_alone", "Below MOQ": "availability_below_moq", "Covers": "selected"}


def test_equal_cost_is_decided_by_earlier_arrival_then_larger_availability_then_name():
    def pick(*suppliers):
        return select_single_supplier(Decimal(100), date(2026, 11, 20), list(suppliers), D).winner.supplier_name

    assert pick(option("B", 5, 10, 500, [contract("1")]), option("A", 6, 10, 500, [contract("1")])) == "B"
    assert pick(option("B", 5, 10, 900, [contract("1")]), option("A", 5, 10, 500, [contract("1")])) == "B"
    assert pick(option("B", 5, 10, 500, [contract("1")]), option("A", 5, 10, 500, [contract("1")])) == "A"


def test_only_one_active_contract_covering_the_selection_date_gives_a_price():
    assert price_state([contract("10.00")], D).unit_price == Decimal("10.00")
    assert price_state([contract("10.00", valid_from=D, valid_until=D)], D).kind == "PRICED"  # boundary dates
    assert price_state([], D).kind == "NOT_REGISTERED"
    assert price_state([contract("10.00", valid_until=date(2026, 10, 31))], D).kind == "NOT_REGISTERED"  # expired
    assert price_state([contract("10.00", valid_from=date(2026, 12, 1))], D).kind == "NOT_REGISTERED"  # future
    assert price_state([contract("10.00", is_active=False)], D).kind == "NOT_REGISTERED"
    overlap = price_state([contract("14.00"), contract("13.50", valid_from=date(2026, 10, 1))], D)
    assert (overlap.kind, overlap.unit_price) == ("CONTRACT_OVERLAP", None)
