"""The Sales Agent tables: do the rules of our design really live in the database?

"Refused" means the test adds a wrong row and expects the database to say no (an IntegrityError).
"""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.data.seed_data import reset
from app.sales_agent import models

NOW = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)


# -- small helpers that build valid rows, so each test shows only what is special about it --------------------------


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


def make_inquiry(conversation, **fields):
    return models.Inquiry(conversation_id=conversation.id, **fields)


def make_message(conversation, **fields):
    return models.Message(conversation_id=conversation.id, direction="IN", text="Hi", **fields)


def make_order(customer, inquiry, option, product, order_number, **fields):
    values = {"quantity": 500, "delivery_date": date(2026, 11, 10), "confirmed_at": NOW, **fields}
    return models.Order(
        order_number=order_number, customer_id=customer.id, inquiry_id=inquiry.id, option_id=option.id,
        product_id=product.id, **values,
    )


def make_memory(customer, **fields):
    values = {"kind": "PREFERENCE", "type": "PREFERS_WHATSAPP_UPDATES", "source": "STATED", **fields}
    return models.CustomerMemory(customer_id=customer.id, **values)


def refuses(db, *rows):
    """The database must refuse these rows. Only they are undone (a savepoint), so earlier rows of the test stay."""
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add_all(rows)
            db.flush()


def accepts(db, *rows):
    db.add_all(rows)
    db.flush()


# -- the tests ------------------------------------------------------------------------------------------------------


def test_the_nine_tables_exist_and_the_demo_reset_cannot_delete_sales_data(engine, db):
    assert set(inspect(engine).get_table_names(schema="sales_agent")) == {
        "customers", "products", "conversations", "messages", "inquiries", "options", "orders", "customer_memory",
        "audit_log",
    }
    make_customer(db)
    db.commit()

    reset(db)  # the project's "empty every table" function, behind POST /simulation/reset
    db.commit()

    assert db.scalar(select(models.Customer.phone)) == "+100"


def test_a_closed_inquiry_must_say_why_and_a_conversation_has_only_one_active_inquiry(db):
    conversation = make_conversation(db)

    # A closed inquiry always has a reason, and an open one never has one.
    refuses(db, make_inquiry(conversation, stage="CLOSED"))
    refuses(db, make_inquiry(conversation, stage="GATHERING", closed_reason="DECLINED"))
    refuses(db, make_inquiry(conversation, stage="CLOSED", closed_reason="BORED"))
    refuses(db, make_inquiry(conversation, stage="SOMEWHERE"))
    accepts(db, make_inquiry(conversation, stage="CLOSED", closed_reason="DECLINED"))

    # Only one unfinished inquiry at a time, but other conversations are independent.
    active = make_inquiry(conversation, stage="GATHERING")
    accepts(db, active)
    refuses(db, make_inquiry(conversation, stage="NEEDS_STAFF"))
    accepts(db, make_inquiry(make_conversation(db), stage="GATHERING"))

    # Once the active one is finished, a new one may start.
    active.stage, active.closed_reason = "CLOSED", "REPLACED"
    db.flush()
    accepts(db, make_inquiry(conversation, stage="GATHERING"))


def test_duplicates_are_refused_for_phone_message_id_planning_reference_and_orders(db):
    # One phone number, one customer.
    make_customer(db, "+100")
    refuses(db, models.Customer(phone="+100"))

    # The same channel message delivered twice is refused. The same id in another conversation is fine, and our own
    # messages (no id) are not limited.
    conversation, other = make_conversation(db), make_conversation(db)
    accepts(db, make_message(conversation, provider_message_id="wamid-1"))
    refuses(db, make_message(conversation, provider_message_id="wamid-1"))
    accepts(db, make_message(other, provider_message_id="wamid-1"))
    accepts(db, make_message(conversation), make_message(conversation))

    # A planning request reference is used by one inquiry only, and an inquiry needs a quantity above zero.
    accepts(db, make_inquiry(conversation, planning_request_ref="REQ-1"))
    refuses(db, make_inquiry(other, planning_request_ref="REQ-1"))
    refuses(db, make_inquiry(other, quantity=0))

    # An inquiry becomes at most one order, a chosen option at most one order, and order numbers are unique.
    customer, product = make_customer(db, "+200"), models.Product(sku="X1-PHONE", name="SmartPhone X1")
    db.add(product)
    first = make_inquiry(make_conversation(db, customer), stage="CONFIRMED")
    second = make_inquiry(make_conversation(db, customer), stage="CONFIRMED")
    accepts(db, first, second)
    options = [models.Option(inquiry_id=i.id, kind="REQUESTED", quantity=500, delivery_date=date(2026, 11, 10))
               for i in (first, first, second)]
    accepts(db, *options)
    first_option, first_option_again, second_option = options

    accepts(db, make_order(customer, first, first_option, product, "SA-1"))
    refuses(db, make_order(customer, first, first_option_again, product, "SA-2"))  # the inquiry twice
    refuses(db, make_order(customer, second, first_option, product, "SA-3"))  # the option twice
    refuses(db, make_order(customer, second, second_option, product, "SA-1"))  # the number twice
    refuses(db, make_order(customer, second, second_option, product, "SA-4", quantity=0))
    accepts(db, make_order(customer, second, second_option, product, "SA-4"))  # a correct order still works


def test_memory_rules_protect_customers_from_unfair_labels(db):
    customer = make_customer(db)
    inquiry = make_inquiry(make_conversation(db, customer))
    accepts(db, inquiry)

    # What the customer said (a preference) and what our rules found (an insight) are both saved, with their evidence.
    said = make_memory(customer, evidence=[{"type": "MESSAGE", "id": "m-12"}])
    found = make_memory(customer, kind="INSIGHT", type="FREQUENT_PRODUCT", source="INFERRED", strength="MEDIUM")
    accepts(db, said, found)
    assert said.evidence == [{"type": "MESSAGE", "id": "m-12"}]

    # There is no type for "tolerates delays", "flexible customer" or "low priority". The database refuses them.
    for unwanted in ("TOLERATES_DELAYS", "FLEXIBLE_CUSTOMER", "LOW_PRIORITY"):
        refuses(db, make_memory(customer, type=unwanted))
        refuses(db, make_memory(customer, kind="INSIGHT", type=unwanted, source="INFERRED"))

    refuses(db, make_memory(customer, kind="PREFERENCE", type="FREQUENT_PRODUCT"))  # a type must fit its kind
    refuses(db, make_memory(customer, source="INFERRED"))  # a preference is always stated by the customer
    refuses(db, make_memory(customer, kind="INSIGHT", type="FREQUENT_PRODUCT", source="STATED"))  # an insight never is
    refuses(db, make_memory(customer, strength="HIGH"))  # only inferred memories have a strength

    # A preference for one order must name it, and a general one must not.
    refuses(db, make_memory(customer, scope="THIS_ORDER"))
    refuses(db, make_memory(customer, scope="GENERAL", inquiry_id=inquiry.id))
    accepts(db, make_memory(customer, scope="THIS_ORDER", inquiry_id=inquiry.id))
