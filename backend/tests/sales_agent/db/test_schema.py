"""The Sales Agent tables: do they exist, and does the database refuse wrong data?

Each "refused" test adds a wrong row and expects the database to say no (an IntegrityError).
"""

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.data.seed_data import reset
from app.sales_agent import models
from app.sales_agent.seed import TEST_PRODUCTS, seed_products

NOW = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)


# -- small helpers that build valid rows, so each test only shows what is special about it ---------------------------


def make_customer(db, phone="+100"):
    customer = models.Customer(phone=phone)
    db.add(customer)
    db.flush()
    return customer


def make_conversation(db, customer=None):
    conversation = models.Conversation(customer_id=customer.id if customer else None, channel="TEST", sender_ref="+100")
    db.add(conversation)
    db.flush()
    return conversation


def make_message(conversation, **fields):
    return models.Message(conversation_id=conversation.id, direction="IN", text="Hi", **fields)


def make_inquiry(conversation, **fields):
    return models.Inquiry(conversation_id=conversation.id, **fields)


def make_product(db, sku="X1-PHONE"):
    product = models.Product(sku=sku, name="SmartPhone X1")
    db.add(product)
    db.flush()
    return product


def make_option(db, inquiry, **fields):
    option = models.Option(
        inquiry_id=inquiry.id, kind="REQUESTED", quantity=500, delivery_date=date(2026, 11, 10), **fields
    )
    db.add(option)
    db.flush()
    return option


def make_order(customer, inquiry, option, product, **fields):
    values = {"order_number": "SA-0001", "quantity": 500, "delivery_date": date(2026, 11, 10), "confirmed_at": NOW}
    values.update(fields)
    return models.Order(
        customer_id=customer.id, inquiry_id=inquiry.id, option_id=option.id, product_id=product.id, **values
    )


def make_memory(customer, **fields):
    values = {"kind": "PREFERENCE", "type": "PREFERS_WHATSAPP_UPDATES", "source": "STATED"}
    values.update(fields)
    return models.CustomerMemory(customer_id=customer.id, **values)


def assert_database_refuses(db, *rows):
    """Adding these rows must fail. Only the wrong rows are undone (a savepoint), so the rows the test created
    earlier are still there and the test can go on."""
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add_all(rows)
            db.flush()


def assert_database_accepts(db, *rows):
    db.add_all(rows)
    db.flush()


# -- the tables exist -----------------------------------------------------------------------------------------------


def test_the_nine_tables_exist_in_their_own_schema(engine):
    tables = set(inspect(engine).get_table_names(schema="sales_agent"))

    assert tables == {
        "customers", "products", "conversations", "messages", "inquiries", "options", "orders", "customer_memory",
        "audit_log",
    }


def test_the_demo_reset_does_not_delete_sales_agent_data(db):
    make_customer(db)
    db.commit()

    reset(db)  # the project's "empty every table" function, used by POST /simulation/reset
    db.commit()

    assert db.scalar(select(models.Customer.phone)) == "+100"


# -- customers and products -----------------------------------------------------------------------------------------


def test_a_phone_number_belongs_to_one_customer(db):
    make_customer(db, "+100")

    assert_database_refuses(db, models.Customer(phone="+100"))


def test_a_customer_needs_a_phone_number(db):
    assert_database_refuses(db, models.Customer(name="No phone"))


def test_a_product_code_is_unique(db):
    make_product(db, "X1-PHONE")

    assert_database_refuses(db, models.Product(sku="X1-PHONE", name="Another"))


def test_seeding_products_twice_adds_them_only_once(db):
    assert seed_products(db) == len(TEST_PRODUCTS)
    assert seed_products(db) == 0
    assert len(list(db.scalars(select(models.Product)))) == len(TEST_PRODUCTS)


# -- conversations and messages -------------------------------------------------------------------------------------


def test_a_conversation_can_exist_without_a_customer_yet(db):
    conversation = make_conversation(db, customer=None)

    assert conversation.customer_id is None


@pytest.mark.parametrize("fields", [{"channel": "SMS"}, {"status": "DONE"}])
def test_a_conversation_with_an_unknown_channel_or_status_is_refused(db, fields):
    values = {"channel": "TEST", "sender_ref": "+100", **fields}

    assert_database_refuses(db, models.Conversation(**values))


def test_the_same_provider_message_id_cannot_be_saved_twice_in_a_conversation(db):
    conversation = make_conversation(db)
    assert_database_accepts(db, make_message(conversation, provider_message_id="wamid-1"))

    assert_database_refuses(db, make_message(conversation, provider_message_id="wamid-1"))


def test_the_same_provider_message_id_is_fine_in_another_conversation(db):
    first, second = make_conversation(db), make_conversation(db)
    assert_database_accepts(db, make_message(first, provider_message_id="wamid-1"))

    assert_database_accepts(db, make_message(second, provider_message_id="wamid-1"))


def test_messages_without_a_provider_message_id_are_not_limited(db):
    conversation = make_conversation(db)

    assert_database_accepts(db, make_message(conversation), make_message(conversation))


def test_a_message_direction_must_be_in_or_out(db):
    conversation = make_conversation(db)

    assert_database_refuses(db, models.Message(conversation_id=conversation.id, direction="SIDEWAYS", text="Hi"))


def test_only_our_own_messages_have_a_delivery_status(db):
    conversation = make_conversation(db)

    assert_database_refuses(db, make_message(conversation, delivery_status="SENT"))  # an IN message
    assert_database_accepts(db, models.Message(conversation_id=conversation.id, direction="OUT", text="Hi", delivery_status="SENT"))


# -- inquiries ------------------------------------------------------------------------------------------------------


def test_a_new_inquiry_starts_in_the_gathering_stage_with_nothing_filled_in(db):
    inquiry = make_inquiry(make_conversation(db))
    assert_database_accepts(db, inquiry)

    assert inquiry.stage == "GATHERING"
    assert inquiry.product_id is None and inquiry.quantity is None and inquiry.requested_date is None


def test_an_unknown_stage_is_refused(db):
    assert_database_refuses(db, make_inquiry(make_conversation(db), stage="SOMEWHERE"))


def test_a_closed_inquiry_must_say_why_and_an_open_one_must_not(db):
    conversation = make_conversation(db)

    assert_database_refuses(db, make_inquiry(conversation, stage="CLOSED"))
    assert_database_refuses(db, make_inquiry(conversation, stage="GATHERING", closed_reason="DECLINED"))
    assert_database_refuses(db, make_inquiry(conversation, stage="CLOSED", closed_reason="BORED"))
    assert_database_accepts(db, make_inquiry(conversation, stage="CLOSED", closed_reason="DECLINED"))


def test_a_conversation_has_only_one_active_inquiry(db):
    conversation = make_conversation(db)
    assert_database_accepts(db, make_inquiry(conversation, stage="GATHERING"))

    assert_database_refuses(db, make_inquiry(conversation, stage="NEEDS_STAFF"))


def test_a_new_inquiry_is_allowed_once_the_old_one_is_finished(db):
    conversation = make_conversation(db)
    assert_database_accepts(
        db,
        make_inquiry(conversation, stage="CLOSED", closed_reason="REPLACED"),
        make_inquiry(conversation, stage="CLOSED", closed_reason="DECLINED"),
        make_inquiry(conversation, stage="CONFIRMED"),
    )

    assert_database_accepts(db, make_inquiry(conversation, stage="GATHERING"))


def test_different_conversations_can_each_have_an_active_inquiry(db):
    assert_database_accepts(db, make_inquiry(make_conversation(db)), make_inquiry(make_conversation(db)))


def test_the_inquiry_quantity_must_be_above_zero(db):
    conversation = make_conversation(db)

    assert_database_refuses(db, make_inquiry(conversation, quantity=0))
    assert_database_refuses(db, make_inquiry(conversation, quantity=-5))
    assert_database_accepts(db, make_inquiry(conversation, quantity=500))


def test_a_planning_request_reference_is_used_once(db):
    first, second = make_conversation(db), make_conversation(db)
    assert_database_accepts(db, make_inquiry(first, planning_request_ref="REQ-1"))

    assert_database_refuses(db, make_inquiry(second, planning_request_ref="REQ-1"))


def test_the_conversation_can_point_at_its_current_inquiry(db):
    conversation = make_conversation(db)
    inquiry = make_inquiry(conversation)
    assert_database_accepts(db, inquiry)

    conversation.current_inquiry_id = inquiry.id
    db.flush()

    assert db.get(models.Conversation, conversation.id).current_inquiry_id == inquiry.id


# -- options and orders ---------------------------------------------------------------------------------------------


def test_an_option_needs_a_known_kind_and_a_quantity_above_zero(db):
    inquiry = make_inquiry(make_conversation(db))
    assert_database_accepts(db, inquiry)
    option = dict(inquiry_id=inquiry.id, delivery_date=date(2026, 11, 10))

    assert_database_refuses(db, models.Option(kind="MAGIC", quantity=5, **option))
    assert_database_refuses(db, models.Option(kind="REQUESTED", quantity=0, **option))
    assert_database_accepts(db, models.Option(kind="LATER_DATE", quantity=5, **option))


def test_a_confirmed_order_is_saved_with_assumed_payment(db):
    customer = make_customer(db)
    inquiry = make_inquiry(make_conversation(db, customer), stage="CONFIRMED")
    product = make_product(db)
    assert_database_accepts(db, inquiry)
    option = make_option(db, inquiry)
    order = make_order(customer, inquiry, option, product)

    assert_database_accepts(db, order)

    assert (order.status, order.payment_status) == ("CONFIRMED", "ASSUMED_PAID")


def test_an_inquiry_becomes_at_most_one_order(db):
    customer, product = make_customer(db), make_product(db)
    inquiry = make_inquiry(make_conversation(db, customer), stage="CONFIRMED")
    assert_database_accepts(db, inquiry)
    first_option, second_option = make_option(db, inquiry), make_option(db, inquiry)
    assert_database_accepts(db, make_order(customer, inquiry, first_option, product, order_number="SA-1"))

    assert_database_refuses(db, make_order(customer, inquiry, second_option, product, order_number="SA-2"))


def test_an_option_becomes_at_most_one_order(db):
    customer, product = make_customer(db), make_product(db)
    first = make_inquiry(make_conversation(db, customer), stage="CONFIRMED")
    second = make_inquiry(make_conversation(db, customer), stage="CONFIRMED")
    assert_database_accepts(db, first, second)
    option = make_option(db, first)
    assert_database_accepts(db, make_order(customer, first, option, product, order_number="SA-1"))

    assert_database_refuses(db, make_order(customer, second, option, product, order_number="SA-2"))


def test_an_order_number_is_unique_and_the_quantity_is_above_zero(db):
    customer, product = make_customer(db), make_product(db)
    first = make_inquiry(make_conversation(db, customer), stage="CONFIRMED")
    second = make_inquiry(make_conversation(db, customer), stage="CONFIRMED")
    assert_database_accepts(db, first, second)
    first_option, second_option = make_option(db, first), make_option(db, second)
    assert_database_accepts(db, make_order(customer, first, first_option, product, order_number="SA-1"))

    assert_database_refuses(db, make_order(customer, second, second_option, product, order_number="SA-1"))
    assert_database_refuses(db, make_order(customer, second, second_option, product, order_number="SA-2", quantity=0))


# -- customer memory ------------------------------------------------------------------------------------------------


def test_a_stated_preference_from_the_allowed_list_is_saved(db):
    customer = make_customer(db)
    memory = make_memory(customer, evidence=[{"type": "MESSAGE", "id": "m-12"}])
    assert_database_accepts(db, memory)

    assert (memory.scope, memory.status, memory.strength) == ("GENERAL", "ACTIVE", None)
    assert memory.evidence == [{"type": "MESSAGE", "id": "m-12"}]


def test_an_inferred_insight_is_saved_with_its_strength(db):
    customer = make_customer(db)

    assert_database_accepts(
        db, make_memory(customer, kind="INSIGHT", type="FREQUENT_PRODUCT", source="INFERRED", strength="MEDIUM")
    )


@pytest.mark.parametrize("unwanted_type", ["TOLERATES_DELAYS", "FLEXIBLE_CUSTOMER", "LOW_PRIORITY"])
def test_types_outside_the_allowed_list_are_refused(db, unwanted_type):
    customer = make_customer(db)

    assert_database_refuses(db, make_memory(customer, type=unwanted_type))
    assert_database_refuses(db, make_memory(customer, kind="INSIGHT", type=unwanted_type, source="INFERRED"))


def test_a_type_must_belong_to_its_kind(db):
    customer = make_customer(db)

    # FREQUENT_PRODUCT is an insight, not a preference.
    assert_database_refuses(db, make_memory(customer, kind="PREFERENCE", type="FREQUENT_PRODUCT"))


def test_a_preference_is_stated_and_an_insight_is_inferred(db):
    customer = make_customer(db)

    assert_database_refuses(db, make_memory(customer, kind="PREFERENCE", source="INFERRED"))
    assert_database_refuses(db, make_memory(customer, kind="INSIGHT", type="FREQUENT_PRODUCT", source="STATED"))


def test_only_inferred_memories_have_a_strength(db):
    customer = make_customer(db)

    assert_database_refuses(db, make_memory(customer, strength="HIGH"))


def test_a_preference_for_one_order_must_name_the_inquiry_and_a_general_one_must_not(db):
    customer = make_customer(db)
    inquiry = make_inquiry(make_conversation(db, customer))
    assert_database_accepts(db, inquiry)

    assert_database_refuses(db, make_memory(customer, scope="THIS_ORDER"))
    assert_database_refuses(db, make_memory(customer, scope="GENERAL", inquiry_id=inquiry.id))
    assert_database_accepts(db, make_memory(customer, scope="THIS_ORDER", inquiry_id=inquiry.id))


# -- audit log ------------------------------------------------------------------------------------------------------


def test_an_audit_entry_has_a_known_actor_and_keeps_its_details(db):
    entry = models.AuditLog(actor="SALES_AI", event_type="AI_TURN", details={"next_step": "ask_more"})
    assert_database_accepts(db, entry)
    assert db.get(models.AuditLog, entry.id).details == {"next_step": "ask_more"}

    assert_database_refuses(db, models.AuditLog(actor="STRANGER", event_type="AI_TURN"))


def test_new_ids_are_random_unique_codes(db):
    customer = make_customer(db)

    assert isinstance(customer.id, uuid.UUID)
