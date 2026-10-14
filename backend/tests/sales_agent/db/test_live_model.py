"""One whole conversation with the REAL language model (Ollama). Skipped unless RUN_LIVE_MODEL=1, because it needs
Ollama running with the configured model and the answers of a small model can vary. Run it by hand before a demo:

    RUN_LIVE_MODEL=1 python -m pytest tests/sales_agent/db/test_live_model.py -s
"""

import functools
import os
import uuid
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.llm.client import OllamaClient
from app.sales_agent import api, manager, models
from app.sales_agent.planning import FakePlanning

pytestmark = pytest.mark.skipif(os.environ.get("RUN_LIVE_MODEL") != "1", reason="set RUN_LIVE_MODEL=1 to use the real model")

TODAY = date(2026, 10, 15)
PHONE = "+919000000001"


def test_a_whole_order_with_the_real_model(db, engine):
    db.add_all([models.Product(sku="X1-PHONE", name="SmartPhone X1"), models.Product(sku="X2-PHONE", name="SmartPhone X2")])
    db.commit()
    model = OllamaClient.from_settings()
    planning = FakePlanning(delay_seconds=0)
    planning.deliver = functools.partial(api.deliver_planning_result, sessionmaker(bind=engine, expire_on_commit=False), model, planning)

    def say(text):
        accepted = manager.accept_message(db, "TEST", PHONE, str(uuid.uuid4()), text)
        manager.process_conversation(db, accepted.conversation_id, model, TODAY, planning)
        db.expire_all()
        chat = db.scalars(select(models.Message).where(models.Message.conversation_id == accepted.conversation_id)
                          .order_by(models.Message.created_at)).all()
        print(f"\ncustomer: {text}\nagent:    {chat[-1].text}")
        return db.scalar(select(models.Inquiry))

    say("Hello, I need 800 SmartPhone X1 delivered by 2026-11-10")
    inquiry = say("Which options do I have?")
    assert inquiry.stage == "OPTIONS_PRESENTED"  # Planning answered with two options for 800 phones
    inquiry = say("I will take option B please")
    assert inquiry.stage == "AWAITING_CONFIRMATION"
    say("Yes, please confirm")
    order = db.scalar(select(models.Order))
    assert order is not None and order.quantity == 500
