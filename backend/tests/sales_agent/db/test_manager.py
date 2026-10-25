"""The conversation manager, tested with a fake language model and a fake Planning whose answers we script, on the
test database."""

import functools
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.errors import AppError, ErrorCode
from app.llm.client import FakeLLMClient, LLMError
from app.sales_agent import api, manager, models, planning as planning_module, views
from app.sales_agent.planning import FakePlanning, OfferedOption, PlanningResult

TODAY = date(2026, 10, 15)
PHONE = "+919876543210"
ASKED_FOR = "2026-11-10"  # the requested date used in the scenarios below
ASKED_FOR_DATE = date.fromisoformat(ASKED_FOR)


# -- helpers --------------------------------------------------------------------------------------------------------


def ai(reply="Which product do you need?", step="ask_more", **details) -> str:
    """One scripted answer of the language model, in the fixed JSON form."""
    return json.dumps({"reply": reply, "next_step": step, "details": details, "reason": "test"})


def dec(decision, option=None) -> str:
    """One scripted answer of the small classification question ("what does the customer's reply mean?")."""
    return json.dumps({"decision": decision, "option": option})


def ask_planning(quantity: int, reply="I will check with the planning team.") -> str:
    """The model's answer when it has all three details and sends the request to Planning."""
    return ai(reply, "send_request", product="SmartPhone X1", quantity=quantity, requested_date=ASKED_FOR)


class BrokenModel:
    def complete(self, messages):
        raise LLMError("Ollama is not running")


class ModelThatFailsAfterTheFirstCall:
    def __init__(self, first_answer):
        self.first_answer, self.calls = first_answer, 0

    def complete(self, messages):
        self.calls += 1
        if self.calls > 1:
            raise LLMError("Ollama stopped")
        return self.first_answer


@pytest.fixture
def products(db):
    x1, x2 = models.Product(sku="X1-PHONE", name="SmartPhone X1"), models.Product(sku="X2-PHONE", name="SmartPhone X2")
    db.add_all([x1, x2])
    db.commit()
    return x1, x2


QUIET_PLANNING = FakePlanning(delay_seconds=0)  # computes an answer but has nowhere to deliver it: it never answers


def planning_that_answers(engine, model) -> FakePlanning:
    """A fake Planning that answers at once, through the same path as the real door 3 (its own sessions, then the
    customer is told). It calls back while the first worker still has the conversation, like in real life."""
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    planning = FakePlanning(delay_seconds=0)
    planning.deliver = functools.partial(api.deliver_planning_result, factory, model, planning)
    return planning


def messages_of(db, conversation_id):
    return list(db.scalars(
        select(models.Message).where(models.Message.conversation_id == conversation_id)
        .order_by(models.Message.created_at, models.Message.id)
    ))


def talk(db, model, text="Hi", phone=PHONE, planning=QUIET_PLANNING) -> str:
    """The customer writes, the agent answers; returns the newest reply."""
    accepted = manager.accept_message(db, "TEST", phone, str(uuid.uuid4()), text)
    manager.process_conversation(db, accepted.conversation_id, model, TODAY, planning)
    db.expire_all()
    return [m for m in messages_of(db, accepted.conversation_id) if m.direction == "OUT"][-1].text


def all_rows(db, model_class):
    return list(db.scalars(select(model_class)))


def audit_events(db, event_type):
    return [a for a in all_rows(db, models.AuditLog) if a.event_type == event_type]


def the_inquiry(db) -> models.Inquiry:
    return all_rows(db, models.Inquiry)[0]


def what_the_model_was_told(model, call_number=0) -> str:
    return model.calls[call_number][0]["content"]  # the instructions, with the situation at the end


def options_of(db, inquiry):
    db.expire_all()
    return [(o.kind, o.quantity, o.delivery_date.isoformat(), o.status) for o in
            db.scalars(select(models.Option).where(models.Option.inquiry_id == inquiry.id)
                       .order_by(models.Option.created_at))]


# -- collecting the details -----------------------------------------------------------------------------------------


def test_details_are_collected_over_several_messages_and_the_request_goes_to_planning_only_when_complete(db, products):
    x1, _ = products
    model = FakeLLMClient([
        ai("Which quantity?", product="SmartPhone X1"),
        ai("By what date?", quantity="500"),
        ai("Noted."),  # says nothing about the details: they must not be erased
        # All three details are known but the model only says ask_more: our rule sends the request anyway.
        ai("So 500 SmartPhone X1 by November 10.", "ask_more", product="SmartPhone X1", quantity=500, requested_date=ASKED_FOR),
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
    assert audit_events(db, "PLANNING_REQUEST_SENT") == [] and the_inquiry(db).stage == "GATHERING"

    talk(db, model, "thanks")
    assert the_inquiry(db).quantity == Decimal("500")

    reply = talk(db, model, "by November 10")
    assert reply.endswith("I am checking this with the planning team.")
    inquiry = the_inquiry(db)
    assert (inquiry.product_id, inquiry.quantity, inquiry.requested_date) == (x1.id, Decimal("500"), date(2026, 11, 10))
    assert inquiry.stage == "WAITING_FOR_PLANNING" and inquiry.planning_request_ref
    assert [a.details["order"]["quantity"] for a in audit_events(db, "PLANNING_REQUEST_SENT")] == [500]


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
    #    false, so it never reaches the customer and nothing is sent to Planning.
    model = FakeLLMClient([ai("I will check with the planning team.", "send_request", product="SmartPhone X1")])
    reply = talk(db, model, phone="+200")
    assert "planning team" not in reply
    assert audit_events(db, "PLANNING_REQUEST_SENT") == []

    # 3. Too many questions: the model is told, answers again, and the better answer is used.
    model = FakeLLMClient([ai("Which model? How many? By when?"), ai("Which model? How many?")])
    assert talk(db, model, phone="+300") == "Which model? How many?"
    assert "Your reply has 3 questions" in model.calls[1][-1]["content"]
    assert any(a.details["asked_again"] for a in audit_events(db, "AI_TURN"))

    # 4. The model invents a date nobody gave it: it is told, and when it does it again our own reply is used.
    model = FakeLLMClient([ai("Sure, we can deliver by December 12!")])
    reply = talk(db, model, phone="+400")
    assert "December 12" not in reply and reply.startswith("Sorry, I did not quite get that.")
    assert "not one of the dates you were given" in model.calls[1][-1]["content"]


# -- Planning answers, and the options are explained ----------------------------------------------------------------


def test_the_options_planning_gives_are_explained_with_exactly_its_dates_and_quantities(db, products, engine):
    options_reply = ("Here are your options. A) 800 x SmartPhone X1 by November 24, 2026. "
                     "B) 500 x SmartPhone X1 by November 10, 2026. Which would you like?")
    model = FakeLLMClient([ask_planning(800), ai(options_reply)])
    planning = planning_that_answers(engine, model)

    talk(db, model, "800 X1 phones by November 10 please", planning=planning)

    inquiry = the_inquiry(db)
    db.expire_all()
    # The customer was told "checking" first, then got the options in the model's words.
    assert [m.text for m in messages_of(db, inquiry.conversation_id) if m.direction == "OUT"] == [
        "I will check with the planning team.", options_reply]
    # Planning's options are saved in its order, copied exactly, with a validity time. Nothing is confirmed.
    assert options_of(db, inquiry) == [("LATER_DATE", 800, "2026-11-24", "OFFERED"),
                                       ("LESS_QUANTITY", 500, "2026-11-10", "OFFERED")]
    assert inquiry.stage == "OPTIONS_PRESENTED" and inquiry.offer_valid_until > datetime.now(timezone.utc)
    assert inquiry.planning_result["announced"] is True
    # The model was told it may only use these options, and Planning received no price and no priority.
    told = what_the_model_was_told(model, 1)
    assert "A) 800 x SmartPhone X1 by 2026-11-24" in told and "B) 500 x SmartPhone X1 by 2026-11-10" in told
    assert "price" not in json.dumps(inquiry.planning_request).lower()
    assert audit_events(db, "OPTIONS_PRESENTED")[0].details["used_own_text"] is False


def test_an_invented_date_or_a_missing_option_never_reaches_the_customer_and_our_own_text_is_used(db, products, engine):
    own_text = ("Here is what we can offer:\n"
                "A) 800 x SmartPhone X1 by 2026-11-24 (the full quantity, but later than you asked)\n"
                "B) 500 x SmartPhone X1 by 2026-11-10 (a smaller quantity, on the date you asked for)\n"
                "Which option would you like?")

    # The model invents a date for the options, twice.
    invented = FakeLLMClient([ask_planning(800), ai("A) 800 by November 30, B) 500 by November 10. Which one?")])
    assert talk(db, invented, phone="+100", planning=planning_that_answers(engine, invented)) == own_text

    # The model leaves out an option, twice.
    forgetful = FakeLLMClient([ask_planning(800), ai("I can do 800 units by November 24. Would that suit you?")])
    assert talk(db, forgetful, phone="+200", planning=planning_that_answers(engine, forgetful)) == own_text
    assert "must present the option of 500" in forgetful.calls[2][-1]["content"]

    # The model goes down just when the options must be explained: the customer still gets them.
    down = ModelThatFailsAfterTheFirstCall(ask_planning(800))
    assert talk(db, down, phone="+300", planning=planning_that_answers(engine, down)) == own_text
    assert len(audit_events(db, "AI_FAILED")) == 1
    assert [i.stage for i in all_rows(db, models.Inquiry)] == ["OPTIONS_PRESENTED"] * 3


def test_nothing_feasible_and_staff_answers_are_told_plainly_and_waiting_is_not_hidden(db, products, engine):
    def start(quantity, phone):
        model = FakeLLMClient([ask_planning(quantity), ai("Still checking, thank you for waiting.")])
        reply = talk(db, model, f"{quantity} X1 phones by November 10", phone=phone,
                     planning=planning_that_answers(engine, model))
        return model, reply

    # Nothing feasible: said honestly, and the inquiry is closed so a new request can start.
    _, reply = start(9000, "+100")
    assert reply == planning_module.nothing_feasible_reply("SmartPhone X1")
    nothing = all_rows(db, models.Inquiry)[0]
    assert (nothing.stage, nothing.closed_reason) == ("CLOSED", "NO_OPTION")

    # Planning needs a team member: the customer is told, and staff is flagged.
    _, reply = start(77, "+200")
    assert reply == planning_module.needs_staff_reply()
    assert [i.stage for i in all_rows(db, models.Inquiry) if i.id != nothing.id] == ["NEEDS_STAFF"]
    assert [a.details["reason"] for a in audit_events(db, "STAFF_FLAGGED")] == ["Planning asked for a team member"]

    # Planning does not answer: the customer asks, and the model is told we are still waiting (it may not promise).
    model, _ = start(13, "+300")
    talk(db, model, "any news?", phone="+300")
    assert "waiting for their answer" in what_the_model_was_told(model, 1)
    waiting = [i for i in all_rows(db, models.Inquiry) if i.stage == "WAITING_FOR_PLANNING"]
    assert len(waiting) == 1 and waiting[0].planning_result is None


def test_planning_answers_that_are_duplicate_unknown_inconsistent_or_late_change_nothing(db, products):
    talk(db, FakeLLMClient([ask_planning(800)]))
    inquiry = the_inquiry(db)
    ref = inquiry.planning_request_ref
    good = PlanningResult(request_ref=ref, status="READY", options=[
        OfferedOption(kind="LATER_DATE", quantity=800, delivery_date=date(2026, 11, 24))])

    # An answer for a request we never sent, and one that does not fit what we asked.
    with pytest.raises(AppError) as unknown:
        manager.handle_planning_result(db, PlanningResult(request_ref="REQ-NOPE", status="NOTHING_FEASIBLE"))
    assert unknown.value.code == ErrorCode.NOT_FOUND
    wrong = PlanningResult(request_ref=ref, status="READY", options=[
        OfferedOption(kind="LATER_DATE", quantity=800, delivery_date=ASKED_FOR_DATE)])  # not later than asked
    with pytest.raises(AppError) as inconsistent:
        manager.handle_planning_result(db, wrong)
    assert inconsistent.value.code == ErrorCode.BUSINESS_RULE_VIOLATION
    db.expire_all()
    assert the_inquiry(db).planning_result is None and options_of(db, inquiry) == []

    # A "still working" note does not stop the real answer, and the first real answer wins.
    assert manager.handle_planning_result(db, PlanningResult(request_ref=ref, status="WORKING")).status == "received"
    assert manager.handle_planning_result(db, good).status == "received"
    assert manager.handle_planning_result(db, good).status == "duplicate"
    other = PlanningResult(request_ref=ref, status="NOTHING_FEASIBLE")
    assert manager.handle_planning_result(db, other).status == "duplicate"
    db.expire_all()
    assert the_inquiry(db).planning_result["status"] == "READY" and len(options_of(db, inquiry)) == 1

    # An answer for a request that is no longer waiting (the inquiry was closed) is ignored.
    stale = the_inquiry(db)
    stale.planning_result, stale.stage, stale.closed_reason = None, "CLOSED", "ABANDONED"
    db.commit()
    assert manager.handle_planning_result(db, good).status == "ignored"


def test_changing_the_request_replaces_the_inquiry_and_sends_a_new_request(db, products, engine):
    model = FakeLLMClient([
        ask_planning(13),  # Planning never answers this one
        ai("Noted, 300 instead. I will check with the planning team.", quantity=300),
        ai("Here is what we can offer: 300 x SmartPhone X1 by November 10. Which option would you like?"),
    ])
    planning = planning_that_answers(engine, model)
    talk(db, model, "13 X1 phones by November 10", planning=planning)
    first = the_inquiry(db)
    first_ref = first.planning_request_ref
    assert first.stage == "WAITING_FOR_PLANNING"

    talk(db, model, "actually make it 300", planning=planning)

    db.expire_all()
    inquiries = {i.id: i for i in all_rows(db, models.Inquiry)}
    assert (inquiries[first.id].stage, inquiries[first.id].closed_reason) == ("CLOSED", "REPLACED")
    new = [i for i in inquiries.values() if i.id != first.id][0]
    assert (new.stage, new.quantity) == ("OPTIONS_PRESENTED", Decimal("300"))
    assert new.planning_request_ref != first_ref
    assert options_of(db, new) == [("REQUESTED", 300, ASKED_FOR, "OFFERED")]
    # The old request can still be answered by Planning, but nothing happens with it.
    late = PlanningResult(request_ref=first_ref, status="NOTHING_FEASIBLE")
    assert manager.handle_planning_result(db, late).status == "ignored"
    assert len(audit_events(db, "INQUIRY_REPLACED")) == 1


# -- failures, duplicates and the customer's background -------------------------------------------------------------


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
                manager.process_conversation(other_session, self.holder["id"], second_worker_model, TODAY, QUIET_PLANNING)
            return ai("First reply." if len(self.calls) == 1 else "Second reply.")

    holder = {}
    model = ModelThatTakesTime(holder)
    first = manager.accept_message(db, "TEST", PHONE, "m1", "X1 phones please")
    holder["id"] = first.conversation_id

    manager.process_conversation(db, first.conversation_id, model, TODAY, QUIET_PLANNING)
    other_session.close()

    assert second_worker_model.calls == []  # the conversation was taken, so the second worker did nothing
    assert len(model.calls) == 2  # the message that arrived meanwhile got its own turn
    first_turn_users = [m["content"] for m in model.calls[0][1:]]
    assert first_turn_users == ["X1 phones please"]  # the first turn did not see it, so it must not mark it answered
    assert "and I need them quickly" in [m["content"] for m in model.calls[1][1:]]
    assert [(m.direction, m.text) for m in messages_of(db, first.conversation_id)] == [
        ("IN", "X1 phones please"), ("IN", "and I need them quickly"), ("OUT", "First reply."), ("OUT", "Second reply.")]
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


# -- choosing and confirming ----------------------------------------------------------------------------------------

OPTIONS_TEXT = ("Here are your options. A) 800 x SmartPhone X1 by November 24, 2026. "
                "B) 500 x SmartPhone X1 by November 10, 2026. Which would you like?")


def reach_options(db, engine, *next_answers, phone=PHONE):
    """A customer asks for 800 phones and Planning offers A) all 800 later, B) 500 on time. Returns the scripted model,
    the fake Planning (which keeps the confirmation notices) and the question that follows a choice of B."""
    model = FakeLLMClient([ask_planning(800), ai(OPTIONS_TEXT), *next_answers])
    planning = planning_that_answers(engine, model)
    talk(db, model, "800 X1 phones by November 10 please", phone=phone, planning=planning)
    question = planning_module.confirmation_question(500, ASKED_FOR_DATE, "SmartPhone X1")
    return model, planning, question


def test_a_choice_and_a_clear_yes_make_the_order_and_only_then(db, products, engine):
    model, planning, question = reach_options(
        db, engine, dec("choose", "B"), dec("yes"))

    # Choosing does not order anything: our own question repeats the exact quantity, date and payment note.
    assert talk(db, model, "B please", planning=planning) == question
    assert "payment is assumed" in question and all_rows(db, models.Order) == []
    inquiry = the_inquiry(db)
    assert inquiry.stage == "AWAITING_CONFIRMATION"
    assert [o[3] for o in options_of(db, inquiry)] == ["OFFERED", "SELECTED"]

    # The clear yes makes the order. The customer reads our words, not the model's.
    reply = talk(db, model, "yes", planning=planning)
    (order,) = all_rows(db, models.Order)
    db.refresh(inquiry)
    assert (order.quantity, order.delivery_date.isoformat(), order.status, order.payment_status) == (
        500, "2026-11-10", "CONFIRMED", "ASSUMED_PAID")
    assert reply == planning_module.order_confirmed_reply(order.order_number, 500, ASKED_FOR_DATE, "SmartPhone X1")
    assert inquiry.stage == "CONFIRMED" and inquiry.confirmation_message_id is not None and order.inquiry_id == inquiry.id
    assert [o[3] for o in options_of(db, inquiry)] == ["RELEASED", "SELECTED"]
    # The new customer is saved, and Planning is told what was decided.
    (customer,) = all_rows(db, models.Customer)
    assert order.customer_id == customer.id and customer.phone == PHONE
    (notice,) = planning.confirmations
    assert (notice["order_number"], notice["quantity"], notice["payment"]) == (order.order_number, 500, "ASSUMED_PAID")
    assert audit_events(db, "CONFIRMATION_ACCEPTED")


def test_a_yes_that_is_early_unclear_changed_or_late_never_makes_an_order(db, products, engine):
    # A "yes" while two options are on the table does not say which one: nothing is chosen, the customer is asked.
    model, planning, _ = reach_options(db, engine, dec("yes"), ai("Which option would you like, A or B?"), phone="+1001")
    assert talk(db, model, "ok", phone="+1001", planning=planning) == "Which option would you like, A or B?"
    assert all_rows(db, models.Order) == [] and the_inquiry(db).stage == "OPTIONS_PRESENTED"

    # A choice the model cannot name (letter Z) selects nothing.
    model, planning, _ = reach_options(db, engine, dec("choose", "Z"), ai("Which option, A or B?"), phone="+1002")
    talk(db, model, "the last one", phone="+1002", planning=planning)
    assert not [o for o in all_rows(db, models.Option) if o.status == "SELECTED"]

    # A "yes" that does not answer our question (we said something else in between) is not enough: we ask again.
    model, planning, question = reach_options(
        db, engine, dec("choose", "B"), dec("question"), ai("You can ask me anything."), dec("yes"), dec("yes"),
        phone="+1003")
    talk(db, model, "B", phone="+1003", planning=planning)
    talk(db, model, "can I ask something?", phone="+1003", planning=planning)
    assert talk(db, model, "yes", phone="+1003", planning=planning) == question
    assert all_rows(db, models.Order) == [] and audit_events(db, "CONFIRMATION_REFUSED")
    # Now our question was the last thing said, so the next yes counts.
    talk(db, model, "yes", phone="+1003", planning=planning)
    assert len(all_rows(db, models.Order)) == 1

    # Two messages at once are not one clear answer to the question.
    model, planning, question = reach_options(
        db, engine, dec("choose", "B"), dec("yes"), phone="+1004")
    talk(db, model, "B", phone="+1004", planning=planning)
    first = manager.accept_message(db, "TEST", "+1004", str(uuid.uuid4()), "yes")
    manager.accept_message(db, "TEST", "+1004", str(uuid.uuid4()), "yes")
    manager.process_conversation(db, first.conversation_id, model, TODAY, planning)
    assert len(all_rows(db, models.Order)) == 1  # still only the one from the scenario before

    # A "yes" together with a changed quantity is a new request, not a confirmation (even if the model says "yes").
    model, planning, _ = reach_options(
        db, engine, dec("choose", "B"), dec("yes"),
        ai("Okay, 300 then.", product="SmartPhone X1", quantity=300, requested_date=ASKED_FOR), phone="+1005")
    talk(db, model, "B", phone="+1005", planning=planning)
    talk(db, model, "yes but make it 300", phone="+1005", planning=QUIET_PLANNING)
    assert len(all_rows(db, models.Order)) == 1  # still only the one from an earlier scenario
    assert "REPLACED" in [i.closed_reason for i in all_rows(db, models.Inquiry)]


def test_declining_an_expired_offer_and_a_staff_case_are_handled_without_an_order(db, products, engine):
    # "No thanks" closes the inquiry and releases the options.
    model, planning, _ = reach_options(
        db, engine, dec("choose", "A"), dec("no"), phone="+1101")
    talk(db, model, "A", phone="+1101", planning=planning)
    assert talk(db, model, "no, forget it", phone="+1101", planning=planning) == planning_module.declined_reply()
    inquiry = all_rows(db, models.Inquiry)[0]
    assert (inquiry.stage, inquiry.closed_reason) == ("CLOSED", "DECLINED")
    assert {o[3] for o in options_of(db, inquiry)} == {"RELEASED"} and all_rows(db, models.Order) == []

    # A "yes" after the offer ran out is not accepted: the same request goes to Planning again.
    model, planning, _ = reach_options(db, engine, dec("choose", "B"), phone="+1102")
    talk(db, model, "B", phone="+1102", planning=planning)
    waiting = next(i for i in all_rows(db, models.Inquiry) if i.stage == "AWAITING_CONFIRMATION")
    waiting.offer_valid_until = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db.commit()
    calls_before = len(model.calls)
    assert talk(db, model, "yes", phone="+1102", planning=QUIET_PLANNING) == planning_module.offer_expired_reply()
    db.expire_all()
    renewed = next(i for i in all_rows(db, models.Inquiry) if i.stage == "WAITING_FOR_PLANNING")
    assert (waiting.closed_reason, renewed.quantity, renewed.requested_date) == ("EXPIRED", Decimal("800"), ASKED_FOR_DATE)
    assert len(model.calls) == calls_before and all_rows(db, models.Order) == []  # the model was not even asked

    # After Planning asks for a team member, the customer can still write and is answered, but nothing is ordered.
    model = FakeLLMClient([ask_planning(77), ai("Thank you, a team member will be in touch.")])
    planning = planning_that_answers(engine, model)
    talk(db, model, "77 X1 phones by November 10", phone="+1103", planning=planning)
    assert talk(db, model, "any news?", phone="+1103", planning=planning) == "Thank you, a team member will be in touch."
    assert all_rows(db, models.Order) == []


# -- memory and fairness --------------------------------------------------------------------------------------------


def give_history(db, product, phone, orders, delay_days=0):
    """A returning customer with this many past confirmed orders of the product, each delivered `delay_days` late."""
    customer = models.Customer(phone=phone)
    db.add(customer)
    db.flush()
    old_chat = models.Conversation(customer_id=customer.id, channel="TEST", sender_ref=phone, status="CLOSED")
    db.add(old_chat)
    db.flush()
    for number in range(orders):
        asked = date(2026, 6, 1 + number)
        inquiry = models.Inquiry(conversation_id=old_chat.id, customer_id=customer.id, stage="CONFIRMED",
                                 product_id=product.id, quantity=100, requested_date=asked)
        db.add(inquiry)
        db.flush()
        option = models.Option(inquiry_id=inquiry.id, kind="LATER_DATE", quantity=100,
                               delivery_date=asked + timedelta(days=delay_days))
        db.add(option)
        db.flush()
        db.add(models.Order(order_number=f"OLD-{phone}-{number}", customer_id=customer.id, inquiry_id=inquiry.id,
                            option_id=option.id, product_id=product.id, quantity=100, delivery_date=option.delivery_date,
                            confirmed_at=datetime(2026, 7, 1 + number, tzinfo=timezone.utc)))
    db.commit()
    return customer


def memory_rows(db):
    db.expire_all()
    return all_rows(db, models.CustomerMemory)


def test_only_allowed_preferences_the_customer_asked_for_are_saved_with_the_message_as_evidence(db, products):
    x1, _ = products
    customer = give_history(db, x1, PHONE, 1)
    ask = {"type": "PREFERS_WHATSAPP_UPDATES", "applies_to": "always"}
    answers = [
        json.dumps({**json.loads(ai("Noted, I will update you on WhatsApp.")), "preference": ask}),
        json.dumps({**json.loads(ai("Noted.")), "preference": ask}),  # said again: not saved twice
        json.dumps({**json.loads(ai("Noted.")), "preference": {"type": "TOLERATES_DELAY", "applies_to": "always"}}),
        json.dumps({**json.loads(ai("Noted.")), "preference": {"type": "WANTS_EARLY_DATE_CHANGE_NOTICE", "applies_to": "this_order"}}),
    ]
    model = FakeLLMClient(answers)

    talk(db, model, "please update me on WhatsApp")
    talk(db, model, "yes, WhatsApp please")
    talk(db, model, "and I am fine with any delay")
    talk(db, model, "warn me early if the date changes for this order")

    saved = {(m.type, m.scope): m for m in memory_rows(db)}
    assert set(saved) == {("PREFERS_WHATSAPP_UPDATES", "GENERAL"), ("WANTS_EARLY_DATE_CHANGE_NOTICE", "THIS_ORDER")}
    whatsapp = saved[("PREFERS_WHATSAPP_UPDATES", "GENERAL")]
    assert (whatsapp.kind, whatsapp.source, whatsapp.customer_id) == ("PREFERENCE", "STATED", customer.id)
    stating_message = next(m for m in all_rows(db, models.Message) if m.text == "please update me on WhatsApp")
    assert whatsapp.evidence == [{"message_id": str(stating_message.id)}]
    assert saved[("WANTS_EARLY_DATE_CHANGE_NOTICE", "THIS_ORDER")].inquiry_id is not None
    assert audit_events(db, "PREFERENCE_REFUSED")  # the delay "preference" was refused and nothing was saved for it

    # A first-time customer has no record yet, so nothing is saved (and that is noted).
    talk(db, FakeLLMClient([answers[0]]), "please update me on WhatsApp", phone="+200")
    assert len(memory_rows(db)) == 2 and audit_events(db, "PREFERENCE_NOT_SAVED")

    # Even if code asked for it, the database itself refuses a type that is not on the list.
    db.add(models.CustomerMemory(customer_id=customer.id, kind="PREFERENCE", type="TOLERATES_DELAY", source="STATED"))
    with pytest.raises(Exception):
        db.commit()
    db.rollback()


def test_the_frequent_product_insight_is_found_by_our_rule_after_an_order_and_never_by_the_model(db, products, engine):
    x1, _ = products
    give_history(db, x1, PHONE, 2)  # two earlier X1 orders: the third makes it frequent
    model, planning, _ = reach_options(
        db, engine, dec("choose", "B"), dec("yes"))
    talk(db, model, "B", planning=planning)
    assert memory_rows(db) == []  # choosing is not ordering

    talk(db, model, "yes", planning=planning)
    (insight,) = memory_rows(db)
    assert (insight.kind, insight.type, insight.source, insight.strength, insight.status) == (
        "INSIGHT", "FREQUENT_PRODUCT", "INFERRED", "LOW", "ACTIVE")
    assert insight.value["product"] == "SmartPhone X1" and len(insight.evidence) == 3  # the three orders are the evidence


def test_a_customer_with_many_accepted_delays_gets_exactly_the_same_request_and_options_as_a_new_one(db, products, engine):
    x1, _ = products
    give_history(db, x1, "+300", 6, delay_days=30)  # always accepted a month's delay
    seen = {}
    for phone in ("+300", "+400"):  # +400 has no history at all
        model, planning, _ = reach_options(db, engine, phone=phone)
        db.expire_all()
        inquiry = next(i for i in all_rows(db, models.Inquiry) if i.planning_request and i.planning_request["customer"]["phone"] == phone)
        seen[phone] = (
            {k: v for k, v in inquiry.planning_request["order"].items()},
            options_of(db, inquiry),
            sorted(inquiry.planning_request),
            audit_events(db, "OPTIONS_PRESENTED")[-1].details["options"],
        )
    assert seen["+300"] == seen["+400"]  # same order block, same keys, same options, same explanation
    request = next(i for i in all_rows(db, models.Inquiry) if i.planning_request and i.planning_request["customer"]["phone"] == "+300").planning_request
    assert request["customer_context"]["is_known_customer"] is True  # the history is passed on, for information only
    assert "priority" not in json.dumps(request).lower() and "tolerat" not in json.dumps(request).lower()


# -- Planning that does not answer ----------------------------------------------------------------------------------


def test_a_request_planning_never_answers_is_reported_once_and_a_late_answer_still_works(db, products, engine):
    model = FakeLLMClient([ask_planning(13), ai("Here is your option. A) 13 x SmartPhone X1 by November 10, 2026. Would you like it?")])
    planning = planning_that_answers(engine, model)
    talk(db, model, "13 X1 phones by November 10", planning=planning)  # 13 is the quantity Planning never answers
    inquiry = the_inquiry(db)

    assert manager.sweep_late_planning_requests(db) == 0  # not late yet
    later = datetime.now(timezone.utc) + timedelta(hours=1)
    assert manager.sweep_late_planning_requests(db, now=later) == 1
    assert manager.sweep_late_planning_requests(db, now=later) == 0  # reported once, not again
    db.expire_all()
    assert messages_of(db, inquiry.conversation_id)[-1].text == planning_module.planning_late_reply()
    assert audit_events(db, "PLANNING_TIMEOUT") and audit_events(db, "STAFF_FLAGGED")
    assert inquiry.stage == "WAITING_FOR_PLANNING"  # still open

    # Planning answers after all: the answer is accepted and explained like any other.
    late_answer = PlanningResult(request_ref=inquiry.planning_request_ref, status="READY",
                                 options=[OfferedOption(kind="REQUESTED", quantity=13, delivery_date=ASKED_FOR_DATE)])
    assert manager.handle_planning_result(db, late_answer).status == "received"
    manager.process_conversation(db, inquiry.conversation_id, model, TODAY, planning)
    db.refresh(inquiry)
    assert inquiry.stage == "OPTIONS_PRESENTED"
