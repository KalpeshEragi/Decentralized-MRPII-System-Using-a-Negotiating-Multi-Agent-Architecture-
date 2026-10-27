"""The event catalogue and its checks, no database (EM-1, EM-3): the catalogue matches the agents' handlers, payloads are
checked against their models, and unknown, retired or wrongly published events are refused."""

from dataclasses import replace

import pytest

from app.core import workers
from app.events import catalogue, channel, manager


@pytest.fixture
def registered():
    channel.unsubscribe_all()
    workers.runner.registrations.clear()
    workers.register_all()
    yield
    channel.unsubscribe_all()
    workers.runner.registrations.clear()


def test_the_catalogue_and_the_agents_handlers_fit(registered):
    found = manager.report()
    assert found["missing_handlers"] == [] and found["unknown_events"] == [] and found["retired_handlers"] == []
    assert found["not_built"] == ["StockAvailabilityChanged: not built: no publisher yet",
                                  "SupplierQuantityReduced: not built: no publisher yet"]
    names = [d.name for d in catalogue.DEFINITIONS]
    assert len(names) == len(set(names)) == len(channel.CATALOGUE)


def test_payloads_are_checked_against_their_models():
    assert channel.check_payload("SimulatedDayStarted", {"date": "2026-11-02"}) is None
    assert "date" in channel.check_payload("SimulatedDayStarted", {})                     # missing field
    assert "extra" in channel.check_payload("SimulatedDayStarted", {"date": "x", "day": 1}).lower()  # unknown field
    assert channel.check_payload("OrderCancelled", {"order_number": "SO-1"}) is None
    assert "not built" in channel.check_payload("SupplierQuantityReduced", {})


def test_definitions_show_handlers_and_payload_fields(registered):
    delayed = next(d for d in manager.definitions() if d["name"] == "SupplierDeliveryDelayed")
    assert delayed["publisher"] == "PURCHASING" and delayed["built"] and delayed["status"] == "ACTIVE"
    assert {(s["agent"], s["required"], s["handler"]) for s in delayed["subscribers"]} == {
        ("PLANNING", True, True), ("INVENTORY", True, True), ("WAREHOUSE", True, True)}
    fields = {f["name"]: f["required"] for f in delayed["payload"]}
    assert fields["old_date"] and fields["new_date"] and "for_ref" in fields


def test_unknown_retired_and_wrong_publisher_are_refused(monkeypatch):
    with pytest.raises(channel.EventRefused, match="not a subscriber"):
        channel.subscribe("HR", "OrderConfirmed", lambda db, e: None)
    retired = replace(catalogue.BY_NAME["PlanAtRisk"], status=catalogue.RETIRED)
    monkeypatch.setitem(catalogue.BY_NAME, "PlanAtRisk", retired)
    with pytest.raises(channel.EventRefused, match="retired"):
        channel.subscribe("SALES", "PlanAtRisk", lambda db, e: None)
    with pytest.raises(channel.EventRefused, match="retired"):
        channel.publish(None, event_type="PlanAtRisk", publisher="PLANNING", entity_type="x", entity_id="1",
                        entity_version=1, correlation_id="c", payload={})
    with pytest.raises(channel.EventRefused, match="unknown event"):
        channel.publish(None, event_type="NoSuchEvent", publisher="SALES", entity_type="x", entity_id="1",
                        entity_version=1, correlation_id="c")
    with pytest.raises(channel.EventRefused, match="published by SALES"):
        channel.publish(None, event_type="OrderCancelled", publisher="PLANNING", entity_type="x", entity_id="1",
                        entity_version=1, correlation_id="c", payload={"order_number": "SO-1"})
    with pytest.raises(channel.EventRefused, match="payload does not match"):  # strict in tests (conftest)
        channel.publish(None, event_type="OrderCancelled", publisher="SALES", entity_type="x", entity_id="1",
                        entity_version=1, correlation_id="c", payload={"order": "SO-1"})


def test_every_event_has_a_story_whose_event_names_exist():
    for d in catalogue.DEFINITIONS:
        assert d.explanation, d.name
        assert all(name in catalogue.BY_NAME for name in d.leads_to), d.name
        for cause in d.caused_by:  # a cause is either an event or an outside cause written in words
            assert cause in catalogue.BY_NAME or not cause.isidentifier(), (d.name, cause)


def test_removing_an_event_names_who_loses_what_and_the_safe_way(registered):
    impact = manager.impact_of_removing("SupplierDeliveryDelayed")
    assert impact["risk"] == "high"
    assert {x["agent"] for x in impact["losing_input"]} == {"PLANNING", "INVENTORY", "WAREHOUSE"}
    assert all(x["reaction"] for x in impact["losing_input"])  # taken from the handlers' own descriptions
    assert impact["steps"][0].startswith("Set status DEPRECATED") and "RETIRED" in impact["steps"][-1]
    assert manager.impact_of_removing("StockAvailabilityChanged")["risk"] == "low"  # nobody handles it


def test_a_proposed_new_event_is_checked_against_the_rules():
    good = manager.check_new_event("ReplenishmentNeeded", "INVENTORY", ["PLANNING", "PURCHASING"], ["item_id"])
    assert good["ok"] and not good["problems"]
    bad = manager.check_new_event("sendStock", "PLANNING", ["PLANNING", "BOSS"])
    assert not bad["ok"]
    assert any("PascalCase" in p for p in bad["problems"]) and any("BOSS" in p for p in bad["problems"])
    assert any("own event" in w for w in bad["warnings"])
    assert not manager.check_new_event("OrderConfirmed", "SALES", ["PLANNING"])["ok"]  # already exists


class _Log:
    def add(self, row):
        self.rows = [*getattr(self, "rows", []), row]

    def commit(self):
        pass


def test_the_assistant_is_grounded_in_the_checks_and_falls_back_without_the_model(registered):
    from app.events import assistant
    from app.llm.client import FakeLLMClient, LLMError

    model = FakeLLMClient(["Removing it is risky: Planning, Inventory and Warehouse depend on it."])
    log = _Log()
    answer = assistant.ask(log, "What breaks if I remove SupplierDeliveryDelayed?", client=model)
    assert answer["by"] == "MODEL" and "risky" in answer["answer"]
    facts = model.calls[0][1]["content"]  # the checks went into the prompt
    assert '"if_removed"' in facts and '"risk": "high"' in facts and log.rows[0].purpose == "EVENT_ASSISTANT"

    class Down:
        def complete(self, messages):
            raise LLMError("Ollama call failed: timed out")

    fallback = assistant.ask(_Log(), "I want to add ReplenishmentNeeded from INVENTORY to PLANNING", client=Down())
    assert fallback["by"] == "CHECKS" and "ReplenishmentNeeded can be added" in fallback["answer"]
