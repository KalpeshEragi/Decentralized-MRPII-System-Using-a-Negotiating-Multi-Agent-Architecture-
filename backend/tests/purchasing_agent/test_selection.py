"""Supplier selection: singles, splits, fallbacks and failure. Plain code: no database. Data follows dev_docs/purchasing_agent/seed_data.md."""

import uuid
from datetime import date
from decimal import Decimal

from app.core.config import Settings
from app.purchasing_agent.selection import Contract, SupplierOption, price_state, reallocate, select_suppliers

D = date(2026, 11, 2)  # selection date of the fixture
THRESHOLD = Settings.model_fields["purchasing_cost_saving_split_threshold"].default  # the working 10%


def select(*args, saving_threshold=THRESHOLD):
    return select_suppliers(*args, saving_threshold=saving_threshold)


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


def legs(selection) -> dict[str, tuple]:
    """Each selected supplier's quantity and cost (None: Not Registered)."""
    return {leg.supplier_name: (leg.quantity, leg.cost) for leg in selection.legs}


def combinations(selection) -> dict[tuple[str, ...], str]:
    return {c.supplier_names: c.reason for c in selection.combinations}


def test_a1_the_cheapest_priced_single_supplier_wins_and_every_option_says_why():
    selection = select(Decimal(500), date(2026, 11, 20), DISPLAY_SUPPLIERS, D)

    assert selection.outcome == "SINGLE"
    [winner] = selection.legs
    assert (winner.supplier_name, winner.quantity, winner.unit_price, winner.cost) == (
        "Alpha Displays", Decimal(500), Decimal("1200.00"), Decimal("600000.00"))
    assert winner.arrival == date(2026, 11, 12)
    assert considered(selection) == {
        "Alpha Displays": "selected",
        "Beta Optics": "higher_cost",  # 625,000
        "Gamma Screens": "not_registered",  # faster, but no price: never chosen over a priced supplier
        "Dormant Displays": "inactive_supplier",
    }
    assert combinations(selection) == {
        ("Alpha Displays", "Beta Optics"): "saving_below_threshold",
        ("Alpha Displays", "Gamma Screens"): "not_registered",  # never a Cost-Saving Split with an unpriced supplier
        ("Beta Optics", "Gamma Screens"): "not_registered",
        ("Alpha Displays", "Beta Optics", "Gamma Screens"): "not_registered",
    }
    best_split = next(c for c in selection.combinations if c.supplier_names == ("Alpha Displays", "Beta Optics"))
    assert best_split.total_cost == Decimal("605000.00")  # {Alpha 400, Beta 100}


def test_a2_moq_surplus_counts_against_a_supplier():
    selection = select(Decimal(150), date(2026, 11, 20), DISPLAY_SUPPLIERS, D)

    # Alpha must order its MOQ of 200 = 240,000 despite the lower unit price; Beta 150 = 187,500.
    assert legs(selection) == {"Beta Optics": (Decimal(150), Decimal("187500.00"))}
    alpha = next(o for o in selection.options if o.supplier_name == "Alpha Displays")
    assert (alpha.order_quantity, alpha.total_cost) == (Decimal(200), Decimal("240000.00"))


def test_a4_no_supplier_in_time_fails_with_a_constrained_quantity_of_zero():
    selection = select(Decimal(300), date(2026, 11, 5), DISPLAY_SUPPLIERS, D)

    assert (selection.outcome, selection.legs, selection.constrained_quantity) == ("FAILED", [], Decimal(0))
    assert considered(selection) == {
        "Alpha Displays": "arrives_too_late", "Beta Optics": "arrives_too_late",
        "Gamma Screens": "arrives_too_late", "Dormant Displays": "inactive_supplier",
    }


def test_suppliers_that_cannot_cover_alone_or_meet_their_moq_are_unusable():
    suppliers = [
        option("Small Stock", 1, 100, 300, [contract("1.00")]),  # covers 300 of 500
        option("Below MOQ", 1, 400, 350, [contract("1.00")]),  # cannot even supply its MOQ
        option("Covers", 1, 100, 600, [contract("1.00")]),  # a split with Small Stock saves nothing
    ]
    selection = select(Decimal(500), date(2026, 11, 20), suppliers, D)

    assert considered(selection) == {
        "Small Stock": "cannot_cover_alone", "Below MOQ": "availability_below_moq", "Covers": "selected"}


def test_equal_cost_is_decided_by_earlier_arrival_then_larger_availability_then_name():
    def pick(*suppliers):
        return select(Decimal(100), date(2026, 11, 20), list(suppliers), D).legs[0].supplier_name

    assert pick(option("B", 5, 10, 500, [contract("1")]), option("A", 6, 10, 500, [contract("1")])) == "B"
    assert pick(option("B", 5, 10, 900, [contract("1")]), option("A", 5, 10, 500, [contract("1")])) == "B"
    assert pick(option("B", 5, 10, 500, [contract("1")]), option("A", 5, 10, 500, [contract("1")])) == "A"

    tied = select(Decimal(100), date(2026, 11, 20), [
        option("B", 5, 10, 500, [contract("1")]), option("A", 6, 10, 500, [contract("1")])], D)
    assert considered(tied) == {"B": "selected", "A": "outranked"}  # same cost: lost the tie-break, not on cost


MAIN_BOARD_SUPPLIERS = [
    option("Nova Silicon", 5, 50, 600, [contract("1100.00", valid_until=date(2026, 10, 31)),  # expired on D
                                        contract("1150.00", valid_from=date(2026, 12, 1))]),  # future on D
    option("Orbit Circuits", 6, 50, 600, [contract("1050.00", is_active=False)]),
    option("Pixel Boards", 8, 100, 600, [contract("1400.00"), contract("1350.00", valid_from=date(2026, 10, 1))]),
    option("Quartz Electronics", 15, 100, 1000, [contract("1500.00")]),
]


def test_a3_only_an_unpriced_supplier_arrives_in_time_so_it_is_the_fallback_without_cost_ranking():
    selection = select(Decimal(300), date(2026, 11, 7), DISPLAY_SUPPLIERS, D)

    assert (selection.outcome, selection.cost_ranking_available) == ("SINGLE", False)
    [winner] = selection.legs
    assert (winner.supplier_name, winner.quantity) == ("Gamma Screens", Decimal(300))
    assert (winner.unit_price, winner.cost, winner.contract_id) == (None, None, None)  # never zero
    assert considered(selection) == {
        "Alpha Displays": "arrives_too_late", "Beta Optics": "arrives_too_late",
        "Gamma Screens": "selected", "Dormant Displays": "inactive_supplier",
    }
    assert "cost ranking unavailable" in selection.reasoning_summary


def test_c1_expired_future_and_inactive_contracts_are_not_registered_and_an_overlap_excludes_the_supplier():
    selection = select(Decimal(300), date(2026, 11, 12), MAIN_BOARD_SUPPLIERS, D)

    assert (selection.outcome, selection.cost_ranking_available) == ("SINGLE", False)
    assert legs(selection) == {"Nova Silicon": (Decimal(300), None)}
    assert considered(selection) == {
        "Nova Silicon": "selected",  # arrives earliest of the unpriced suppliers
        "Orbit Circuits": "outranked",  # arrives a day later
        "Pixel Boards": "contract_overlap",
        "Quartz Electronics": "arrives_too_late",
    }
    assert {o.supplier_name: o.price_kind for o in selection.options} == {
        "Nova Silicon": "NOT_REGISTERED", "Orbit Circuits": "NOT_REGISTERED",
        "Pixel Boards": "CONTRACT_OVERLAP", "Quartz Electronics": "PRICED",
    }
    pixel = next(o for o in selection.options if o.supplier_name == "Pixel Boards")
    assert (pixel.unit_price, pixel.total_cost) == (None, None)  # neither overlapping price is used


def test_c2_the_only_priced_usable_supplier_wins_over_faster_unpriced_ones():
    selection = select(Decimal(300), date(2026, 11, 20), MAIN_BOARD_SUPPLIERS, D)

    assert (selection.outcome, selection.cost_ranking_available) == ("SINGLE", True)
    assert legs(selection) == {"Quartz Electronics": (Decimal(300), Decimal("450000.00"))}
    assert considered(selection) == {
        "Nova Silicon": "not_registered", "Orbit Circuits": "not_registered",
        "Pixel Boards": "contract_overlap", "Quartz Electronics": "selected",
    }


def test_the_unpriced_fallback_breaks_ties_by_larger_availability_then_name():
    def pick(*suppliers):
        return select(Decimal(100), date(2026, 11, 20), list(suppliers), D).legs[0].supplier_name

    assert pick(option("B", 5, 10, 900), option("A", 5, 10, 500)) == "B"
    assert pick(option("B", 5, 10, 500), option("A", 5, 10, 500)) == "A"


def test_only_one_active_contract_covering_the_selection_date_gives_a_price():
    assert price_state([contract("10.00")], D).unit_price == Decimal("10.00")
    assert price_state([contract("10.00", valid_from=D, valid_until=D)], D).kind == "PRICED"  # boundary dates
    assert price_state([], D).kind == "NOT_REGISTERED"
    assert price_state([contract("10.00", valid_until=date(2026, 10, 31))], D).kind == "NOT_REGISTERED"  # expired
    assert price_state([contract("10.00", valid_from=date(2026, 12, 1))], D).kind == "NOT_REGISTERED"  # future
    assert price_state([contract("10.00", is_active=False)], D).kind == "NOT_REGISTERED"
    overlap = price_state([contract("14.00"), contract("13.50", valid_from=date(2026, 10, 1))], D)
    assert (overlap.kind, overlap.unit_price) == ("CONTRACT_OVERLAP", None)


BATTERY_SUPPLIERS = [
    option("Volt Power", 7, 100, 400, [contract("800.00", valid_from=date(2026, 6, 1))]),
    option("Cell Works", 9, 200, 500, [contract("900.00", valid_from=date(2026, 6, 1))]),
    option("Ion Supply", 12, 300, 1500, [contract("1000.00", valid_from=date(2026, 6, 1))]),
]


def test_b1_no_single_covers_so_the_best_priced_combination_is_a_necessary_split():
    selection = select(Decimal(800), date(2026, 11, 12), BATTERY_SUPPLIERS, D)

    assert (selection.outcome, selection.cost_ranking_available) == ("NECESSARY_SPLIT", True)
    # MOQ first (100 + 200), then the rest from the cheapest: Volt up to 400, then Cell.
    assert legs(selection) == {"Volt Power": (Decimal(400), Decimal("320000.00")),
                               "Cell Works": (Decimal(400), Decimal("360000.00"))}
    assert selection.total_cost == Decimal("680000.00")
    assert max(leg.arrival for leg in selection.legs) == date(2026, 11, 11)
    assert considered(selection) == {
        "Volt Power": "selected", "Cell Works": "selected", "Ion Supply": "arrives_too_late"}
    assert combinations(selection) == {("Cell Works", "Volt Power"): "selected"}


def test_b2_a_split_saving_at_least_10_percent_beats_the_best_priced_single():
    selection = select(Decimal(800), date(2026, 11, 20), BATTERY_SUPPLIERS, D)

    assert (selection.outcome, selection.cost_ranking_available) == ("COST_SAVING_SPLIT", True)
    assert legs(selection) == {"Volt Power": (Decimal(400), Decimal("320000.00")),
                               "Cell Works": (Decimal(400), Decimal("360000.00"))}
    assert selection.total_cost == Decimal("680000.00")
    assert considered(selection) == {
        "Volt Power": "selected", "Cell Works": "selected", "Ion Supply": "cost_saving_split_cheaper"}  # 800,000
    assert combinations(selection) == {
        ("Cell Works", "Volt Power"): "selected",
        ("Ion Supply", "Volt Power"): "higher_cost",  # 720,000
        ("Cell Works", "Ion Supply"): "higher_cost",  # 750,000
        ("Cell Works", "Ion Supply", "Volt Power"): "higher_cost",  # 720,000
    }
    assert "15.00%" in selection.reasoning_summary


def test_b3_a_split_saving_less_than_10_percent_keeps_the_single():
    selection = select(Decimal(450), date(2026, 11, 20), BATTERY_SUPPLIERS, D)

    assert (selection.outcome, selection.total_cost) == ("SINGLE", Decimal("405000.00"))
    assert legs(selection) == {"Cell Works": (Decimal(450), Decimal("405000.00"))}
    assert considered(selection) == {
        "Volt Power": "cannot_cover_alone", "Cell Works": "selected", "Ion Supply": "higher_cost"}
    volt_cell = next(c for c in selection.combinations if c.supplier_names == ("Cell Works", "Volt Power"))
    assert (volt_cell.total_cost, volt_cell.reason) == (Decimal("380000.00"), "saving_below_threshold")  # 6.2%


def test_b4_nothing_feasible_fails_with_the_constrained_quantity():
    selection = select(Decimal(1000), date(2026, 11, 12), BATTERY_SUPPLIERS, D)

    assert (selection.outcome, selection.legs, selection.cost_ranking_available) == ("FAILED", [], None)
    assert selection.constrained_quantity == Decimal(900)  # Volt 400 + Cell 500; Ion is too late
    assert considered(selection) == {
        "Volt Power": "cannot_cover_alone", "Cell Works": "cannot_cover_alone", "Ion Supply": "arrives_too_late"}
    assert combinations(selection) == {("Cell Works", "Volt Power"): "insufficient_quantity"}
    assert "900" in selection.reasoning_summary

    # The combination that falls short shows each supplier and why it can't fulfil the request.
    [short] = selection.combinations
    assert short.legs == ()
    assert [(m.supplier_name, m.available_qty, m.min_order_qty, m.arrival, m.price_kind, m.unit_price)
            for m in short.members] == [
        ("Cell Works", Decimal(500), Decimal(200), date(2026, 11, 11), "PRICED", Decimal("900.00")),
        ("Volt Power", Decimal(400), Decimal(100), date(2026, 11, 9), "PRICED", Decimal("800.00")),
    ]
    assert short.reason_detail == "Together they can supply at most 900 of 1000 (short by 100)."


def test_d1_a_necessary_split_with_an_unpriced_supplier_fills_the_earliest_arrival_first():
    suppliers = [
        option("Lumen Optics", 6, 100, 300, [contract("2000.00")]),
        option("Focal Point", 5, 100, 300),  # Not Registered
        option("Prism Labs", 20, 100, 2000, [contract("1800.00")]),
    ]
    selection = select(Decimal(500), date(2026, 11, 10), suppliers, D)

    assert (selection.outcome, selection.cost_ranking_available) == ("NECESSARY_SPLIT", False)
    assert legs(selection) == {"Focal Point": (Decimal(300), None), "Lumen Optics": (Decimal(200), Decimal("400000.00"))}
    assert selection.total_cost is None  # no cost claim with an unpriced supplier
    assert considered(selection) == {
        "Lumen Optics": "selected", "Focal Point": "selected", "Prism Labs": "arrives_too_late"}
    assert "cost ranking unavailable" in selection.reasoning_summary


def test_e1_three_suppliers_are_used_when_every_pair_falls_short():
    suppliers = [
        option("Sonic Audio", 4, 100, 500, [contract("300.00")]),
        option("EchoTech", 5, 100, 300, [contract("320.00")]),
        option("Wave Acoustics", 6, 100, 300, [contract("340.00")]),
    ]
    selection = select(Decimal(1000), date(2026, 11, 12), suppliers, D)

    assert selection.outcome == "NECESSARY_SPLIT"
    assert legs(selection) == {"Sonic Audio": (Decimal(500), Decimal("150000.00")),
                               "EchoTech": (Decimal(300), Decimal("96000.00")),
                               "Wave Acoustics": (Decimal(200), Decimal("68000.00"))}
    assert selection.total_cost == Decimal("314000.00")
    assert combinations(selection) == {
        ("EchoTech", "Sonic Audio"): "insufficient_quantity",
        ("Sonic Audio", "Wave Acoustics"): "insufficient_quantity",
        ("EchoTech", "Wave Acoustics"): "insufficient_quantity",
        ("EchoTech", "Sonic Audio", "Wave Acoustics"): "selected",
    }


def test_e2_a_supplier_held_by_another_request_offers_only_its_effective_availability():
    # E2b while E2a holds Sonic Audio 400 of 500: Sonic's effective availability is 100.
    suppliers = [
        option("Sonic Audio", 4, 100, 100, [contract("300.00")]),
        option("EchoTech", 5, 100, 300, [contract("320.00")]),
        option("Wave Acoustics", 6, 100, 300, [contract("340.00")]),
    ]
    selection = select(Decimal(300), date(2026, 11, 12), suppliers, D)

    assert selection.outcome == "SINGLE"
    assert legs(selection) == {"EchoTech": (Decimal(300), Decimal("96000.00"))}
    assert considered(selection)["Sonic Audio"] == "cannot_cover_alone"
    # The split {Sonic 100, EchoTech 200} = 94,000 saves only 2.08%.
    assert combinations(selection)[("EchoTech", "Sonic Audio")] == "saving_below_threshold"


def test_f1_a_saving_of_exactly_10_percent_qualifies():
    suppliers = [option("PlugCo", 5, 100, 1000, [contract("100.00")]),
                 option("ConnectRite", 5, 100, 400, [contract("87.50")])]
    selection = select(Decimal(500), date(2026, 11, 20), suppliers, D)

    assert selection.outcome == "COST_SAVING_SPLIT"  # 45,000 vs PlugCo 500 = 50,000
    assert legs(selection) == {"ConnectRite": (Decimal(400), Decimal("35000.00")),
                               "PlugCo": (Decimal(100), Decimal("10000.00"))}


def threshold_case(split_price):
    """Single S: 100 x 100.00 = 10,000. Split X + Y: 50 + 50 at `split_price`."""
    return [option("S", 5, 10, 100, [contract("100.00")]),
            option("X", 5, 10, 50, [contract(split_price)]), option("Y", 5, 10, 50, [contract(split_price)])]


def test_the_saving_threshold_boundary_is_exact():
    exactly_10 = select(Decimal(100), date(2026, 11, 20), threshold_case("90.00"), D)  # 9,000
    just_below = select(Decimal(100), date(2026, 11, 20), threshold_case("90.01"), D)  # 9,001: 9.99%

    assert exactly_10.outcome == "COST_SAVING_SPLIT"
    assert (just_below.outcome, legs(just_below)) == ("SINGLE", {"S": (Decimal(100), Decimal("10000.00"))})


def test_the_saving_threshold_is_configurable():
    selection = select(Decimal(100), date(2026, 11, 20), threshold_case("90.01"), D,
                                 saving_threshold=Decimal("0.05"))

    assert selection.outcome == "COST_SAVING_SPLIT"


def test_a_cost_saving_split_is_never_formed_with_an_unpriced_supplier():
    suppliers = [option("S", 5, 10, 100, [contract("100.00")]), option("X", 5, 10, 50), option("Y", 5, 10, 50)]
    selection = select(Decimal(100), date(2026, 11, 20), suppliers, D)

    assert (selection.outcome, list(legs(selection))) == ("SINGLE", ["S"])
    assert combinations(selection)[("X", "Y")] == "not_registered"


def test_an_unpriced_single_that_covers_beats_a_priced_split():
    suppliers = [option("U", 5, 10, 100), option("X", 5, 10, 50, [contract("1.00")]),
                 option("Y", 5, 10, 50, [contract("1.00")])]
    selection = select(Decimal(100), date(2026, 11, 20), suppliers, D)

    assert (selection.outcome, selection.cost_ranking_available, list(legs(selection))) == ("SINGLE", False, ["U"])
    assert combinations(selection)[("X", "Y")] == "single_covers"


def test_moq_surplus_in_a_split_is_ordered_and_counted_in_the_cost():
    suppliers = [option("X", 5, 80, 100, [contract("1.00")]), option("Y", 5, 80, 100, [contract("1.00")])]
    selection = select(Decimal(150), date(2026, 11, 20), suppliers, D)

    assert legs(selection) == {"X": (Decimal(80), Decimal("80.00")), "Y": (Decimal(80), Decimal("80.00"))}


def test_priced_combinations_tie_break_on_latest_arrival_then_fewer_suppliers_then_availability_then_names():
    def pick(*suppliers):
        selection = select(Decimal(100), date(2026, 11, 20), list(suppliers), D)
        assert selection.outcome == "NECESSARY_SPLIT"
        return sorted(legs(selection))

    def priced(name, lead, available):
        return option(name, lead, 10, available, [contract("1.00")])

    # Every combination costs 100. {A, B} arrives a day before any combination with C.
    assert pick(priced("A", 5, 60), priced("B", 5, 60), priced("C", 6, 60)) == ["A", "B"]
    # Same arrival: a pair beats the triple; {A, C} has the most total availability.
    assert pick(priced("A", 5, 60), priced("B", 5, 60), priced("C", 5, 70)) == ["A", "C"]
    # Fully tied pairs: by names.
    assert pick(priced("A", 5, 60), priced("B", 5, 60), priced("C", 5, 60)) == ["A", "B"]


def test_a_priced_combination_fills_by_lower_price_then_earlier_arrival_then_larger_availability_then_name():
    def fill(x_price, x_lead, x_available, y_price, y_lead, y_available):
        suppliers = [option("X", x_lead, 10, x_available, [contract(x_price)]),
                     option("Y", y_lead, 10, y_available, [contract(y_price)])]
        return {name: q for name, (q, _) in legs(select(Decimal(100), date(2026, 11, 20), suppliers, D)).items()}

    # MOQ 10 each, then the remaining 80 goes to the first supplier in fill order.
    assert fill("2.00", 5, 90, "1.00", 6, 90) == {"X": Decimal(10), "Y": Decimal(90)}  # lower price
    assert fill("1.00", 6, 80, "1.00", 5, 80) == {"X": Decimal(20), "Y": Decimal(80)}  # earlier arrival
    assert fill("1.00", 5, 85, "1.00", 5, 80) == {"X": Decimal(85), "Y": Decimal(15)}  # larger availability
    assert fill("1.00", 5, 80, "1.00", 5, 80) == {"X": Decimal(80), "Y": Decimal(20)}  # name


def test_combinations_with_an_unpriced_supplier_prefer_the_smaller_total_quantity():
    suppliers = [option("A", 5, 10, 60), option("B", 5, 95, 95), option("C", 5, 10, 60)]  # all Not Registered
    selection = select(Decimal(100), date(2026, 11, 20), suppliers, D)

    # {A, B} and {B, C} must order 105 (MOQ surplus); {A, C} orders exactly 100.
    assert (selection.outcome, sorted(legs(selection))) == ("NECESSARY_SPLIT", ["A", "C"])
    assert combinations(selection)[("A", "B")] == "outranked"


def test_the_best_priced_single_is_kept_as_what_a_split_saving_is_measured_against():
    b2 = select(Decimal(800), date(2026, 11, 20), BATTERY_SUPPLIERS, D)
    b1 = select(Decimal(800), date(2026, 11, 12), BATTERY_SUPPLIERS, D)

    assert (b2.best_priced_single.supplier_name, b2.best_priced_single.total_cost) == ("Ion Supply", Decimal("800000.00"))
    assert b1.best_priced_single is None  # no single covers a Necessary Split


# -- reallocation (§7.4): the same rules over only the already-selected suppliers, each limited by its cap ----------
# The caller passes each selected supplier with `available` = min(effective availability, cap).


def speakers(echo_available=300, wave_available=300):
    return [option("Sonic Audio", 4, 100, 500, [contract("300.00")]),
            option("EchoTech", 5, 100, echo_available, [contract("320.00")]),
            option("Wave Acoustics", 6, 100, wave_available, [contract("340.00")])]


def test_n2_a_cap_reallocates_the_rest_among_the_selected_suppliers():
    # E1 selected Sonic 500 + EchoTech 300 + Wave 200; EchoTech can only do 250.
    reallocation = reallocate(Decimal(1000), date(2026, 11, 12), speakers(echo_available=250), D)

    assert reallocation.outcome == "NECESSARY_SPLIT"
    assert legs(reallocation) == {"Sonic Audio": (Decimal(500), Decimal("150000.00")),
                                  "EchoTech": (Decimal(250), Decimal("80000.00")),
                                  "Wave Acoustics": (Decimal(250), Decimal("85000.00"))}
    assert reallocation.total_cost == Decimal("315000.00")


def plug_and_connect(connect_available):
    return [option("PlugCo", 5, 100, 1000, [contract("100.00")]),
            option("ConnectRite", 5, 100, connect_available, [contract("87.50")])]


def test_a_better_ranked_split_is_kept_without_re_checking_the_saving_threshold():
    # F1 selected ConnectRite 400 + PlugCo 100; ConnectRite can only do 300.
    reallocation = reallocate(Decimal(500), date(2026, 11, 20), plug_and_connect(300), D)

    # 46,250 against PlugCo 500 = 50,000 saves only 7.5%: still the better-ranked choice.
    assert reallocation.outcome == "COST_SAVING_SPLIT"
    assert legs(reallocation) == {"ConnectRite": (Decimal(300), Decimal("26250.00")),
                                  "PlugCo": (Decimal(200), Decimal("20000.00"))}
    assert "7.50%" in reallocation.reasoning_summary and "not re-checked" in reallocation.reasoning_summary
    assert reallocation.best_priced_single.supplier_name == "PlugCo"


def test_a_split_collapses_to_a_single_supplier_and_the_other_is_dropped():
    # ConnectRite's cap of 50 is below its MOQ of 100: it is unusable, and PlugCo alone covers.
    reallocation = reallocate(Decimal(500), date(2026, 11, 20), plug_and_connect(50), D)

    assert (reallocation.outcome, legs(reallocation)) == ("SINGLE", {"PlugCo": (Decimal(500), Decimal("50000.00"))})
    assert considered(reallocation)["ConnectRite"] == "availability_below_moq"


def test_on_reallocation_a_single_beats_an_equally_ranked_split_with_fewer_suppliers():
    # The pair costs the same as S alone, arrives the same day: fewer suppliers wins.
    suppliers = [option("S", 5, 10, 100, [contract("1.00")]),
                 option("X", 5, 10, 50, [contract("1.00")]), option("Y", 5, 10, 50, [contract("1.00")])]
    reallocation = reallocate(Decimal(100), date(2026, 11, 20), suppliers, D)

    assert (reallocation.outcome, list(legs(reallocation))) == ("SINGLE", ["S"])
    assert combinations(reallocation)[("X", "Y")] == "outranked"


def test_a_selected_supplier_that_is_no_longer_needed_is_left_out():
    # Three selected suppliers; with Y capped at 200, {Y 200, Z 300} = 43,000 beats {X, Y, Z} = 45,000 and
    # {X 300, Y 200} = 46,000, so X is no longer needed.
    suppliers = [option("X", 5, 100, 400, [contract("100.00")]),
                 option("Y", 5, 100, 200, [contract("80.00")]),
                 option("Z", 5, 300, 300, [contract("90.00")])]
    reallocation = reallocate(Decimal(500), date(2026, 11, 20), suppliers, D)

    assert legs(reallocation) == {"Y": (Decimal(200), Decimal("16000.00")), "Z": (Decimal(300), Decimal("27000.00"))}
    assert combinations(reallocation)[("X", "Y", "Z")] == "higher_cost"


def test_n3_no_allocation_fits_the_caps():
    # B1 selected Volt 400 + Cell 400; Cell caps itself at 300.
    volt_and_cell = [option("Volt Power", 7, 100, 400, [contract("800.00")]),
                     option("Cell Works", 9, 200, 300, [contract("900.00")])]
    reallocation = reallocate(Decimal(800), date(2026, 11, 12), volt_and_cell, D)

    assert (reallocation.outcome, reallocation.legs, reallocation.constrained_quantity) == ("FAILED", [], Decimal(700))


def test_n9_a_single_supplier_capped_below_the_shortage_has_no_allocation():
    alpha = [option("Alpha Displays", 10, 200, 450, [contract("1200.00")])]
    reallocation = reallocate(Decimal(500), date(2026, 11, 20), alpha, D)

    assert (reallocation.outcome, reallocation.constrained_quantity) == ("FAILED", Decimal(450))


def test_rule_3_a_priced_combination_is_preferred_over_a_faster_one_with_an_unpriced_supplier():
    suppliers = [option("Priced A", 10, 100, 300, [contract("10.00")]),
                 option("Priced B", 10, 100, 300, [contract("12.00")]),
                 option("Unpriced C", 2, 100, 300)]  # faster, but Not Registered
    selection = select(Decimal(500), date(2026, 11, 20), suppliers, D)

    assert (selection.outcome, selection.cost_ranking_available) == ("NECESSARY_SPLIT", True)
    assert sorted(legs(selection)) == ["Priced A", "Priced B"]
    assert selection.total_cost == Decimal("5400.00")  # A 300 × 10 + B 200 × 12


def test_unpriced_combinations_tie_break_on_latest_arrival_then_fewer_suppliers_then_availability_then_names():
    def pick(*suppliers):
        selection = select(Decimal(100), date(2026, 11, 20), list(suppliers), D)
        assert (selection.outcome, selection.cost_ranking_available) == ("NECESSARY_SPLIT", False)
        return sorted(legs(selection))

    def unpriced(name, lead, available):
        return option(name, lead, 10, available)

    # {A, B} arrives a day before any combination with C.
    assert pick(unpriced("A", 5, 60), unpriced("B", 5, 60), unpriced("C", 6, 60)) == ["A", "B"]
    # Same arrival and total quantity: a pair beats the triple; {A, C} has the most total availability.
    assert pick(unpriced("A", 5, 60), unpriced("B", 5, 60), unpriced("C", 5, 70)) == ["A", "C"]
    # Fully tied pairs: by names.
    assert pick(unpriced("A", 5, 60), unpriced("B", 5, 60), unpriced("C", 5, 60)) == ["A", "B"]
