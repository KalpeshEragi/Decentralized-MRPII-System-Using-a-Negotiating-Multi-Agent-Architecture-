"""Registering and listing Purchasing Contracts through the Purchasing API on the test database. The write rules
(dev_docs/purchasing_agent/purchasing_agent_architecture.md §6.2) are enforced here, not by the database.
"""

from app.supplier_service.seed import ITEM_IDS, SUPPLIER_IDS


def register(client, supplier="Beta Optics", item="DSP-100", unit_price="1199.50", valid_from="2027-01-01",
             valid_until=None, is_active=True):
    return client.post("/purchasing/contracts", json={
        "supplier_id": str(SUPPLIER_IDS[supplier]), "item_id": str(ITEM_IDS[item]), "unit_price": unit_price,
        "valid_from": valid_from, "valid_until": valid_until, "is_active": is_active})


def contracts_of(client, supplier, item):
    response = client.get("/purchasing/contracts", params={
        "supplier_id": str(SUPPLIER_IDS[supplier]), "item_id": str(ITEM_IDS[item])})
    assert response.status_code == 200
    return response.json()


def error(response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


def test_a_registered_contract_is_listed_with_its_supplier_item_price_and_validity(client):
    response = register(client)

    assert response.status_code == 201
    created = response.json()
    assert created["supplier"] == {"id": str(SUPPLIER_IDS["Beta Optics"]), "name": "Beta Optics"}
    assert created["item"] == {"id": str(ITEM_IDS["DSP-100"]), "sku": "DSP-100", "name": "Display Panel"}
    assert (created["unit_price"], created["currency"]) == ("1199.50", "INR")
    assert (created["valid_from"], created["valid_until"], created["is_active"]) == ("2027-01-01", None, True)

    # Historical and future contracts for the same pair live side by side, oldest first.
    listed = contracts_of(client, "Beta Optics", "DSP-100")
    assert [(c["unit_price"], c["valid_from"], c["valid_until"]) for c in listed] == [
        ("1250.00", "2026-01-01", "2026-12-31"), ("1199.50", "2027-01-01", None)]
    assert listed[1] == created


def test_the_list_shows_every_contract_including_inactive_and_bad_seeded_ones(client):
    everything = client.get("/purchasing/contracts").json()
    assert len(everything) == 18  # the fixture's contracts (dev_docs/purchasing_agent/seed_data.md §4)

    assert len(contracts_of(client, "Pixel Boards", "MBD-300")) == 2  # the overlapping pair is still visible
    [orbit] = contracts_of(client, "Orbit Circuits", "MBD-300")
    assert orbit["is_active"] is False


def test_price_and_validity_dates_are_checked_on_write(client):
    for bad in ({"unit_price": "0"}, {"unit_price": "-1.00"}, {"unit_price": "10.005"}, {"unit_price": None},
                {"valid_from": "2027-02-01", "valid_until": "2027-01-31"}, {"valid_from": None},
                {"is_active": "yes"}):
        assert error(register(client, **bad)) == (422, "VALIDATION_ERROR"), bad

    # A one-day contract (valid_until = valid_from) is fine.
    assert register(client, valid_from="2027-01-01", valid_until="2027-01-01").status_code == 201


def test_the_supplier_must_supply_the_item_in_the_supplier_service(client):
    unknown_supplier = client.post("/purchasing/contracts", json={
        "supplier_id": "00000000-0000-0000-0000-000000000000", "item_id": str(ITEM_IDS["DSP-100"]),
        "unit_price": "10.00", "valid_from": "2027-01-01"})
    assert error(unknown_supplier) == (422, "VALIDATION_ERROR")

    unknown_item = client.post("/purchasing/contracts", json={
        "supplier_id": str(SUPPLIER_IDS["Beta Optics"]), "item_id": "00000000-0000-0000-0000-000000000000",
        "unit_price": "10.00", "valid_from": "2027-01-01"})
    assert error(unknown_item) == (422, "VALIDATION_ERROR")

    not_supplied = register(client, supplier="Beta Optics", item="BAT-200")  # Beta does not sell batteries
    assert error(not_supplied) == (422, "VALIDATION_ERROR")
    assert not_supplied.json()["error"]["details"] == [{"field": "item_id", "issue": "not supplied by this supplier"}]


def test_t_con_2_an_active_contract_overlapping_another_active_one_for_the_pair_is_rejected(client):
    # Beta's seeded contract runs 2026-01-01..2026-12-31. Touching it on its last day is an overlap.
    for valid_from, valid_until in (("2026-12-31", None), ("2026-06-01", "2026-06-30"), ("2025-01-01", None)):
        response = register(client, valid_from=valid_from, valid_until=valid_until)
        assert error(response) == (409, "CONFLICT"), (valid_from, valid_until)

    # The bad seeded Pixel Boards pair blocks any new active contract it covers.
    assert error(register(client, supplier="Pixel Boards", item="MBD-300", valid_from="2030-01-01")) == (409, "CONFLICT")

    # Refused contracts are not stored.
    assert len(contracts_of(client, "Beta Optics", "DSP-100")) == 1


def test_inactive_contracts_never_overlap(client):
    # An inactive contract may overlap an active one ...
    assert register(client, valid_from="2026-06-01", is_active=False).status_code == 201
    # ... and an inactive one never blocks a new active one: Orbit's seeded contract is inactive and open-ended.
    assert register(client, supplier="Orbit Circuits", item="MBD-300", unit_price="1080.00",
                    valid_from="2026-11-01").status_code == 201
    # Historical contracts before the existing one are fine too.
    assert register(client, valid_from="2025-01-01", valid_until="2025-12-31").status_code == 201


def test_a_newly_registered_contract_prices_the_supplier_on_the_selection_date(client):
    # Orbit Circuits is Not Registered on 2026-11-02 (its only contract is inactive). A contract from that day on
    # gives it a price, so in C1 (MBD-300, 300 by 11-12) it becomes the only priced usable supplier.
    assert register(client, supplier="Orbit Circuits", item="MBD-300", unit_price="1080.00",
                    valid_from="2026-11-02").status_code == 201

    created = client.post("/purchasing/procurement-requests", json={
        "request_ref": "REQ-C1", "item_id": str(ITEM_IDS["MBD-300"]), "shortage_quantity": 300,
        "required_date": "2026-11-12", "priority": 1, "requested_by": "test"}).json()

    assert created["cost_ranking_available"] is True
    [leg] = created["legs"]
    assert (leg["supplier"]["name"], leg["unit_price_at_selection"]) == ("Orbit Circuits", "1080.00")
    assert {o["supplier_name"]: (o["price_kind"], o["reason"]) for o in created["selection"]["options"]} == {
        "Nova Silicon": ("NOT_REGISTERED", "not_registered"),
        "Orbit Circuits": ("PRICED", "selected"),
        "Pixel Boards": ("CONTRACT_OVERLAP", "contract_overlap"),
        "Quartz Electronics": ("PRICED", "arrives_too_late"),
    }
