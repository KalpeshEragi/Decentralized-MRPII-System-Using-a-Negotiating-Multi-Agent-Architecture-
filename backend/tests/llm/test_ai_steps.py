"""Step 7e, no database: the agents' AI steps only ever add words or pick among code-made alternatives, and fall back
to code when the model is wrong or down (IN-4, HR-4, WH-5, PL-4, PL-6)."""

import json
from datetime import date
from decimal import Decimal as D

from app.llm import wording
from app.llm.client import FakeLLMClient
from app.mrpii.ranking import Alternative, check_ai_choice
from app.planning_agent import ai as planning_ai


class Log:
    """Stands in for the database session: keeps the AI-call log rows."""

    def __init__(self):
        self.rows = []

    def add(self, row):
        self.rows.append(row)


ENVELOPE = {"sender": "INVENTORY", "message_type": "OFFER", "case_id": "C-1", "text": "Offer: 200 by 2026-11-03.",
            "terms": {"resource_type": "STOCK", "quantity": "200", "needed_by": "2026-11-03"}}


def test_wording_keeps_the_terms_or_falls_back_to_the_template():
    log = Log()
    good = "We can offer 200 units by 2026-11-03."
    assert wording.word(log, ENVELOPE, FakeLLMClient([good])) == good
    wrong = FakeLLMClient(["We can offer 250 units by 2026-11-03."])  # a changed number, twice
    assert wording.word(log, ENVELOPE, wrong) == ENVELOPE["text"] and len(wrong.calls) == 2
    assert wording.word(log, ENVELOPE, FakeLLMClient([])) == ENVELOPE["text"]  # model down
    assert [r.outcome for r in log.rows] == ["OK", "FALLBACK_USED", "ERROR"]
    invented = FakeLLMClient(["We offer 200 units by 2026-11-03 at a rate of 200 per hour."])  # right numbers, made-up rate
    assert wording.word(log, ENVELOPE, invented) == ENVELOPE["text"]


def alternative(key: str, days_moved: int, room: bool = True) -> Alternative:
    return Alternative(key=key, quantity=D(100), target_quantity=D(100), completion_date=date(2026, 11, 7),
                       hard_ok=room, touches_protected=False, firm_changes=1, full_on_target=True, days_late=0,
                       orders_moved=0, days_moved=days_moved, safety_stock_used=D(0), extra_worker_hours=D(0),
                       negotiations=1)


def test_the_ai_may_only_pick_an_allowed_alternative():
    options = [alternative("day 4", 1), alternative("day 3", 2), alternative("day 6", 1, room=False)]
    answer = json.dumps({"chosen_key": "day 3", "rationale": "Earlier is safer."})
    key, rationale = planning_ai.rank_with_ai(Log(), "C-1", "keep the order on time", options, FakeLLMClient([answer]))
    assert (key, rationale) == ("day 3", "Earlier is safer.")
    assert check_ai_choice(key, options).key == "day 3"  # allowed: the AI's choice stands
    assert check_ai_choice("day 6", options).key == "day 4"  # no room (hard constraint): the fixed ranking decides
    assert check_ai_choice(None, options).key == "day 4"  # no answer: the fixed ranking decides
