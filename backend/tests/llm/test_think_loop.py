"""The shared think loop (QD-7, QD-11), no database: the agent proposes its own action and numbers, code checks them,
one revision is allowed, and the deterministic fallback decides whenever the model is off, wrong or down."""

import json

from app.agent_decisions.record import details
from app.agent_decisions.think import MAX_CALLS, Situation, think
from app.llm.client import FakeLLMClient, LLMError

FREE = 50  # what the check allows: Inventory has 50 batteries free


def situation(**extra) -> Situation:
    return Situation(
        agent="INVENTORY", point="D2", goal="Serve the most urgent order first; keep safety stock.",
        facts={"free_now": FREE, "requests": [{"order": "O1", "qty": 120, "due": "2026-11-08"},
                                              {"order": "O3", "qty": 60, "due": "2026-11-06"}]},
        actions={"allocate": "params: {order: str, now: int, later: int, later_day: YYYY-MM-DD}"},
        hints=[{"key": "fifo", "order": "O1", "now": 50}], case_id="C1", order_id="O3", **extra)


def validate(action: str, params: dict) -> str | None:
    if int(params["now"]) > FREE:
        return f"only {FREE} are free now, you proposed {params['now']}"
    return None


FALLBACK = ("allocate", {"order": "O1", "now": 50, "later": 0})


def answer(now: int, **more) -> str:
    return json.dumps({"thinking": "O3 is due first.", "action": "allocate",
                       "params": {"order": "O3", "now": now, "later": 10, "later_day": "2026-11-07"},
                       "reason": "O3 is the most urgent.", **more})


def test_ai_off_uses_the_fallback_without_any_call():
    decision = think(situation(), validate, FALLBACK, client=None)
    assert (decision.chosen_by, decision.fallback_reason, decision.calls) == ("FALLBACK", "AI_OFF", [])
    assert (decision.action, decision.params) == FALLBACK


def test_the_agent_proposes_its_own_numbers_and_the_check_accepts_them():
    model = FakeLLMClient([answer(now=50)])
    decision = think(situation(), validate, FALLBACK, model)
    assert decision.chosen_by == "MODEL" and len(model.calls) == 1
    assert decision.params == {"order": "O3", "now": 50, "later": 10, "later_day": "2026-11-07"}
    assert decision.thinking == "O3 is due first." and decision.reason == "O3 is the most urgent."
    prompt = model.calls[0][1]["content"]  # facts, actions and hints went into the one prompt
    assert '"free_now": 50' in prompt and '"allocate"' in prompt and '"fifo"' in prompt


def test_a_refused_proposal_gets_one_revision_with_the_reason():
    model = FakeLLMClient([answer(now=60), answer(now=50)])
    decision = think(situation(), validate, FALLBACK, model)
    assert decision.chosen_by == "MODEL_REVISED" and decision.params["now"] == 50
    assert decision.refusals == ["only 50 are free now, you proposed 60"]
    assert "only 50 are free now" in model.calls[1][-1]["content"]


def test_refused_twice_falls_back():
    decision = think(situation(), validate, FALLBACK, FakeLLMClient([answer(now=60)]))
    assert (decision.chosen_by, decision.fallback_reason) == ("FALLBACK", "NOT_VALID")
    assert (decision.action, decision.params) == FALLBACK and len(decision.refusals) == 2


def test_an_unknown_action_or_broken_params_are_refused_not_crashed():
    bad = json.dumps({"action": "delete_stock", "params": {}})
    broken = json.dumps({"action": "allocate", "params": {"now": "lots"}})
    decision = think(situation(), validate, FALLBACK, FakeLLMClient([bad, broken]))
    assert decision.chosen_by == "FALLBACK"
    assert "not one of your actions" in decision.refusals[0] and "not usable" in decision.refusals[1]


def test_one_lookup_round_then_a_decision():
    asked = []
    extra = {"incoming": lambda: asked.append(1) or [{"day": "2026-11-07", "qty": 100}]}
    model = FakeLLMClient([json.dumps({"thinking": "Is more coming?", "need_facts": ["incoming", "unknown"]}),
                           answer(now=50)])
    decision = think(situation(lookups=extra), validate, FALLBACK, model)
    assert decision.chosen_by == "MODEL" and asked == [1]
    assert decision.looked_up == {"incoming": [{"day": "2026-11-07", "qty": 100}]}
    assert '"qty": 100' in model.calls[1][-1]["content"]


def test_garbage_or_a_dead_model_falls_back_and_says_why():
    garbage = think(situation(), validate, FALLBACK, FakeLLMClient(["I think O3, maybe."]))
    assert (garbage.chosen_by, garbage.fallback_reason) == ("FALLBACK", "INVALID")

    class Down:
        def complete(self, messages):
            raise LLMError("Ollama call failed: timed out")

    down = think(situation(), validate, FALLBACK, Down())
    assert (down.fallback_reason, [c.outcome for c in down.calls]) == ("TIMEOUT", ["TIMEOUT"])


def test_the_loop_always_ends():
    model = FakeLLMClient([json.dumps({"need_facts": ["incoming"]})])  # never proposes
    decision = think(situation(lookups={"incoming": lambda: []}), validate, FALLBACK, model)
    assert decision.chosen_by == "FALLBACK" and len(model.calls) <= MAX_CALLS


def test_the_record_is_plain_json():
    decision = think(situation(), validate, FALLBACK, FakeLLMClient([answer(now=60), answer(now=50)]))
    record = details(situation(), decision, ["call-1", "call-2"])
    assert json.loads(json.dumps(record)) == record  # storable in the JSONB audit details
    assert record["chosen_by"] == "MODEL_REVISED" and record["refusals"] and record["fallback"][0] == "allocate"
