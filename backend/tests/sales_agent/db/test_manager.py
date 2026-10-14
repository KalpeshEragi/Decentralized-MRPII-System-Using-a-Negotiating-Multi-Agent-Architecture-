"""The conversation manager, tested with a fake language model whose answers we script, on the test database."""

import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.llm.client import FakeLLMClient, LLMError
from app.sales_agent import manager, models, views

TODAY = date(2026, 10, 15)
PHONE = "+919876543210"


# -- helpers --------------------------------------------------------------------------------------------------------


def ai(reply="Which product do you need?", step="ask_more", **details) -> str:
    """One scripted answer of the language model, in the fixed JSON form."""
    return json.dumps({"reply": reply, "next_step": step, "details": details, "reason": "test"})


class BrokenModel:
    def complete(self, messages):
        raise LLMError("Ollama is not running")


@pytest.fixture
def products(db):
    x1, x2 = models.Product(sku="X1-PHONE", name="SmartPhone X1"), models.Product(sku="X2-PHONE", name="SmartPhone X2")
    db.add_all([x1, x2])
    db.commit()
    return x1, x2


def talk(db, model, text="Hi", phone=PHONE) -> str:
    """The customer writes, the agent answers; returns the newest reply."""
    accepted = manager.accept_message(db, "TEST", phone, str(uuid.uuid4()), text)
    manager.process_conversation(db, accepted.conversation_id, model, TODAY)
    replies = [m for m in messages_of(db, accepted.conversation_id) if m.direction == "OUT"]
    return replies[-1].text


def messages_of(db, conversation_id):
    return list(db.scalars(
        select(models.Message).where(models.Message.conversation_id == conversation_id)
        .order_by(models.Message.created_at, models.Message.id)
    ))


def all_rows(db, model_class):
    return list(db.scalars(select(model_class)))


def audit_events(db, event_type):
    return [a for a in all_rows(db, models.AuditLog) if a.event_type == event_type]


def the_inquiry(db) -> models.Inquiry:
    return all_rows(db, models.Inquiry)[0]


def what_the_model_was_told(model, call_number=0) -> str:
    return model.calls[call_number][0]["content"]  # the instructions, with the situation at the end


# -- the tests ------------------------------------------------------------------------------------------------------


def test_details_are_collected_over_several_messages_and_planning_is_told_only_when_complete(db, products):
    x1, _ = products
    model = FakeLLMClient([
        ai("Which quantity?", product="SmartPhone X1"),
        ai("By what date?", quantity="500"),
        ai("Noted."),  # says nothing about the details: they must not be erased
        ai("So 500 SmartPhone X1 by November 10. I will check with the planning team.", "send_request",
           product="SmartPhone X1", quantity=500, requested_date="2026-11-10"),
        ai("Noted.", quantity=300),  # the customer changes their mind
    ])

    talk(db, model, "X1 phones please")
    talk(db, model, "500")

    # On the second turn the model was told what is known, what is missing, and saw the conversation so far.
    situation = what_the_model_was_told(model, 1)
    assert "Today's date: 2026-10-15." in situation
    assert "Products we sell: SmartPhone X1; SmartPhone X2." in situation
    assert "product = SmartPhone X1; quantity = not yet known; requested delivery date = not yet known" in situation
    assert "Still missing: quantity, delivery date." in situation
    assert [m["role"] for m in model.calls[1][1:]] == ["user", "assistant", "user"]
    assert audit_events(db, "READY_FOR_PLANNING") == []  # a detail is still missing

    talk(db, model, "thanks")
    assert the_inquiry(db).quantity == Decimal("500")

    talk(db, model, "by November 10")
    inquiry = the_inquiry(db)
    assert (inquiry.product_id, inquiry.quantity, inquiry.requested_date) == (x1.id, Decimal("500"), date(2026, 11, 10))
    ready = audit_events(db, "READY_FOR_PLANNING")
    assert [a.details for a in ready] == [{"product": "SmartPhone X1", "quantity": 500, "requested_date": "2026-11-10"}]

    talk(db, model, "actually 300")
    assert the_inquiry(db).quantity == Decimal("300")


def test_a_wrong_detail_is_never_saved_or_repeated_back_as_if_it_was_fine(db, products):
    x1, _ = products
    model = FakeLLMClient([ai("You'd like 5 phones on October 1, 2020.", product="SmartPhone X1", quantity=5,
                              requested_date="2020-10-01")])

    reply = talk(db, model, "5 X1 by October 1 2020")

    assert reply.startswith("I could not use that delivery date.") and "2020" not in reply
    assert len(model.calls) == 1  # the model cannot fix what the customer wrote, so it is not asked again
    inquiry = the_inquiry(db)
    assert (inquiry.product_id, inquiry.quantity, inquiry.requested_date) == (x1.id, Decimal("5"), None)
    assert audit_events(db, "AI_TURN")[0].details["used_fallback"] is True


def test_unusable_model_answers_get_safe_replies_and_a_false_planning_claim_is_not_passed_on(db, products):
    # 1. Not valid JSON, twice: the model is asked once more, then our own reply is used.
    model = FakeLLMClient(["Sure, I can help!"])
    reply = talk(db, model, phone="+100")
    assert reply.startswith("Sorry, I did not quite get that.")
    assert "We offer: SmartPhone X1, SmartPhone X2." in reply
    assert len(model.calls) == 2

    # 2. The model says "I will check with the planning team" while a detail is still missing: that claim would be
    #    false, so it never reaches the customer and nothing is marked ready for planning.
    model = FakeLLMClient([ai("I will check with the planning team.", "send_request", product="SmartPhone X1")])
    reply = talk(db, model, phone="+200")
    assert "planning team" not in reply
    assert audit_events(db, "READY_FOR_PLANNING") == []

    # 3. Too many questions: the model is told, answers again, and the better answer is used.
    model = FakeLLMClient([ai("Which model? How many? By when?"), ai("Which model? How many?")])
    assert talk(db, model, phone="+300") == "Which model? How many?"
    assert "Your reply has 3 questions" in model.calls[1][-1]["content"]
    assert any(a.details["asked_again"] for a in audit_events(db, "AI_TURN"))


def test_a_model_that_is_down_gets_an_apology_keeps_the_messages_and_flags_staff_after_two_failures(db, products):
    # The customer gets an apology, their message is kept unanswered, and nothing stays locked.
    assert talk(db, BrokenModel(), "Hello?") == manager.SAFE_APOLOGY
    assert [(m.direction, m.processed) for m in all_rows(db, models.Message)] == [("IN", False), ("OUT", False)]
    assert all_rows(db, models.Conversation)[0].busy is False
    assert audit_events(db, "STAFF_FLAGGED") == []

    # The second failure in a row flags staff, once. A third does not flag again.
    talk(db, BrokenModel(), "Anyone there?")
    assert len(audit_events(db, "STAFF_FLAGGED")) == 1
    talk(db, BrokenModel(), "Hello???")
    assert len(audit_events(db, "AI_FAILED")) == 3 and len(audit_events(db, "STAFF_FLAGGED")) == 1

    # When the model is back, it sees everything the customer wrote meanwhile and answers it.
    model = FakeLLMClient([ai("Sorry for the wait. Which product?")])
    assert talk(db, model, "I need phones") == "Sorry for the wait. Which product?"
    said_by_customer = [m["content"] for m in model.calls[0][1:] if m["role"] == "user"]
    assert said_by_customer == ["Hello?", "Anyone there?", "Hello???", "I need phones"]
    db.expire_all()
    assert all(m.processed for m in all_rows(db, models.Message) if m.direction == "IN")


def test_messages_that_arrive_while_the_model_thinks_are_answered_together_by_one_worker(db, products, engine):
    other_session = sessionmaker(bind=engine, expire_on_commit=False)()
    second_worker_model = FakeLLMClient([ai("this must never be used")])

    class ModelThatTakesTime:
        """On its first call the customer writes again, and a second worker tries to answer the same conversation."""

        def __init__(self, conversation_id_holder):
            self.calls, self.holder = [], conversation_id_holder

        def complete(self, messages):
            self.calls.append(messages)
            if len(self.calls) == 1:
                manager.accept_message(other_session, "TEST", PHONE, "m2", "and I need them quickly")
                manager.process_conversation(other_session, self.holder["id"], second_worker_model, TODAY)
            return ai(f"reply {len(self.calls)}")

    holder = {}
    model = ModelThatTakesTime(holder)
    first = manager.accept_message(db, "TEST", PHONE, "m1", "X1 phones please")
    holder["id"] = first.conversation_id

    manager.process_conversation(db, first.conversation_id, model, TODAY)
    other_session.close()

    assert second_worker_model.calls == []  # the conversation was taken, so the second worker did nothing
    assert len(model.calls) == 2  # the message that arrived meanwhile got its own turn
    first_turn_users = [m["content"] for m in model.calls[0][1:]]
    assert first_turn_users == ["X1 phones please"]  # the first turn did not see it, so it must not mark it answered
    assert "and I need them quickly" in [m["content"] for m in model.calls[1][1:]]
    assert [(m.direction, m.text) for m in messages_of(db, first.conversation_id)] == [
        ("IN", "X1 phones please"), ("IN", "and I need them quickly"), ("OUT", "reply 1"), ("OUT", "reply 2")]
    db.expire_all()
    assert all(m.processed for m in all_rows(db, models.Message) if m.direction == "IN")
    assert all_rows(db, models.Conversation)[0].busy is False


def test_a_returning_customers_background_is_given_to_the_model_but_nothing_is_assumed(db, products):
    x1, _ = products
    customer = models.Customer(phone=PHONE, name="Asha")
    db.add(customer)
    db.flush()
    old_chat = models.Conversation(customer_id=customer.id, channel="TEST", sender_ref=PHONE, status="CLOSED")
    db.add(old_chat)
    db.flush()
    inquiry = models.Inquiry(conversation_id=old_chat.id, customer_id=customer.id, stage="CONFIRMED",
                             product_id=x1.id, quantity=500, requested_date=date(2026, 10, 31))
    db.add(inquiry)
    db.flush()
    option = models.Option(inquiry_id=inquiry.id, kind="LATER_DATE", quantity=500, delivery_date=date(2026, 11, 7))
    db.add(option)
    db.flush()
    db.add_all([
        models.Order(order_number="SA-1", customer_id=customer.id, inquiry_id=inquiry.id, option_id=option.id,
                     product_id=x1.id, quantity=500, delivery_date=date(2026, 11, 7),
                     confirmed_at=datetime(2026, 10, 2, tzinfo=timezone.utc)),
        models.CustomerMemory(customer_id=customer.id, kind="PREFERENCE", type="PREFERS_WHATSAPP_UPDATES",
                              source="STATED"),
        models.CustomerMemory(customer_id=customer.id, kind="INSIGHT", type="FREQUENT_PRODUCT", source="INFERRED",
                              strength="MEDIUM"),
    ])
    db.commit()
    model = FakeLLMClient([ai("Welcome back! Which product do you need?")])

    talk(db, model, "I need another 500 units", phone="+91 98765-43210")  # the same number, written differently

    situation = what_the_model_was_told(model)
    assert "Name: Asha" in situation
    assert "- 500 x SmartPhone X1, asked for 2026-10-31, delivery 2026-11-07" in situation
    assert "Saved preferences (the customer said these):\n- prefers whatsapp updates (general)" in situation
    assert "Insights (found by our rules, not certain):\n- frequent product" in situation
    assert "product = not yet known" in situation  # the old product is background, not an assumption
    open_chat = [c for c in all_rows(db, models.Conversation) if c.status == "OPEN"][0]
    assert open_chat.customer_id == customer.id

    # A different, unknown number is a new customer with a conversation of its own.
    stranger = FakeLLMClient([ai()])
    talk(db, stranger, phone="+100")
    assert "New customer: nothing is known about them." in what_the_model_was_told(stranger)
    assert len([c for c in all_rows(db, models.Conversation) if c.status == "OPEN"]) == 2


def test_history_survives_a_restart_clearing_starts_fresh_and_staff_questions_are_noted(db, products, engine):
    model = FakeLLMClient([ai("Hello!"), ai("A team member will follow up.", "pass_to_staff")])
    talk(db, model, "Hi")
    talk(db, model, "I want to cancel my order SO-1")

    notes = audit_events(db, "PASSED_TO_STAFF")
    assert [n.details for n in notes] == [{"message": "I want to cancel my order SO-1"}]

    fresh_session = sessionmaker(bind=engine, expire_on_commit=False)()  # like the backend after a restart
    history = views.chat_of_sender(fresh_session, "TEST", PHONE)["messages"]
    fresh_session.close()
    assert [(m["role"], m["text"]) for m in history] == [
        ("user", "Hi"), ("assistant", "Hello!"),
        ("user", "I want to cancel my order SO-1"), ("assistant", "A team member will follow up."),
    ]

    manager.clear_chat(db, "TEST", PHONE)
    assert views.chat_of_sender(db, "TEST", PHONE)["messages"] == []
    assert (the_inquiry(db).stage, the_inquiry(db).closed_reason) == ("CLOSED", "ABANDONED")
    talk(db, model, "Hi again")
    assert sorted(c.status for c in all_rows(db, models.Conversation)) == ["CLOSED", "OPEN"]
