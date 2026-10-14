"""The read-only tools, tested with real rows in the test database (data access layer included)."""

from datetime import date, datetime, timedelta, timezone

from app.sales_agent import models, tools

FIRST_ORDER_TIME = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 15)


# -- small helpers that build valid rows ----------------------------------------------------------------------------


def add_customer(db, phone="+919876543210", name="Asha") -> models.Customer:
    customer = models.Customer(phone=phone, name=name)
    db.add(customer)
    db.flush()
    return customer


def add_product(db, sku="X1-PHONE", name="SmartPhone X1", active=True) -> models.Product:
    product = models.Product(sku=sku, name=name, active=active)
    db.add(product)
    db.flush()
    return product


def add_confirmed_order(
    db, customer, product, order_number, days_after_first=0, quantity=500, requested_date=date(2026, 11, 10),
    delivery_date=date(2026, 11, 12),
) -> models.Order:
    """A confirmed order with the conversation, inquiry and option it came from."""
    conversation = models.Conversation(customer_id=customer.id, channel="TEST", sender_ref=customer.phone)
    db.add(conversation)
    db.flush()
    inquiry = models.Inquiry(
        conversation_id=conversation.id, customer_id=customer.id, stage="CONFIRMED", product_id=product.id,
        quantity=quantity, requested_date=requested_date,
    )
    db.add(inquiry)
    db.flush()
    option = models.Option(inquiry_id=inquiry.id, kind="LATER_DATE", quantity=quantity, delivery_date=delivery_date)
    db.add(option)
    db.flush()
    order = models.Order(
        order_number=order_number, customer_id=customer.id, inquiry_id=inquiry.id, option_id=option.id,
        product_id=product.id, quantity=quantity, delivery_date=delivery_date,
        confirmed_at=FIRST_ORDER_TIME + timedelta(days=days_after_first),
    )
    db.add(order)
    db.flush()
    return order


def add_memory(db, customer, status="ACTIVE", kind="PREFERENCE", type_="PREFERS_WHATSAPP_UPDATES", **fields):
    source = "STATED" if kind == "PREFERENCE" else "INFERRED"
    memory = models.CustomerMemory(customer_id=customer.id, kind=kind, type=type_, source=source, status=status, **fields)
    db.add(memory)
    db.flush()
    return memory


# -- get_customer_info ----------------------------------------------------------------------------------------------


def test_an_unknown_phone_number_gives_not_found(db):
    add_customer(db, "+919876543210")

    assert tools.get_customer_info(db, "+911111111111") == {"found": False}


def test_a_known_customer_is_found_even_if_the_phone_is_typed_with_spaces(db):
    customer = add_customer(db, "+919876543210", name="Asha")

    info = tools.get_customer_info(db, "+91 98765-43210")

    assert info["found"] is True
    assert info["customer"] == {"id": str(customer.id), "name": "Asha", "phone": "+919876543210"}
    assert info["memory"] == []


def test_only_active_memory_is_returned_and_stated_and_inferred_can_be_told_apart(db):
    customer = add_customer(db)
    add_memory(db, customer, value={"channel": "WHATSAPP"})
    add_memory(db, customer, kind="INSIGHT", type_="FREQUENT_PRODUCT", strength="MEDIUM", value={"sku": "X1-PHONE"})
    add_memory(db, customer, status="SUPERSEDED", type_="WANTS_EARLY_DATE_CHANGE_NOTICE")
    add_memory(db, customer, status="RETIRED", kind="INSIGHT", type_="FREQUENT_PRODUCT", strength="LOW")

    memory = tools.get_customer_info(db, customer.phone)["memory"]

    assert sorted((m["kind"], m["source"], m["type"]) for m in memory) == [
        ("INSIGHT", "INFERRED", "FREQUENT_PRODUCT"),
        ("PREFERENCE", "STATED", "PREFERS_WHATSAPP_UPDATES"),
    ]


def test_memory_of_another_customer_is_not_returned(db):
    asha, ravi = add_customer(db, "+100", "Asha"), add_customer(db, "+200", "Ravi")
    add_memory(db, ravi)

    assert tools.get_customer_info(db, asha.phone)["memory"] == []


def test_the_memory_list_is_limited(db):
    customer = add_customer(db)
    for _ in range(tools.MAX_MEMORY_ITEMS + 2):
        add_memory(db, customer)

    assert len(tools.get_customer_info(db, customer.phone)["memory"]) == tools.MAX_MEMORY_ITEMS


# -- get_product_list -----------------------------------------------------------------------------------------------


def test_the_product_list_has_only_active_products_sorted_by_name(db):
    add_product(db, "T1-TABLET", "Tablet T1")
    add_product(db, "X1-PHONE", "SmartPhone X1")
    add_product(db, "OLD-1", "Old Model", active=False)

    names = [p["name"] for p in tools.get_product_list(db)["products"]]

    assert names == ["SmartPhone X1", "Tablet T1"]


# -- get_order_history ----------------------------------------------------------------------------------------------


def test_the_history_has_the_newest_orders_first_with_the_date_the_customer_asked_for(db):
    customer, product = add_customer(db), add_product(db)
    add_confirmed_order(db, customer, product, "SA-1", days_after_first=0, quantity=100, requested_date=date(2026, 10, 1))
    add_confirmed_order(db, customer, product, "SA-2", days_after_first=5, quantity=250, requested_date=date(2026, 10, 31),
                        delivery_date=date(2026, 11, 7))

    orders = tools.get_order_history(db, customer.id)["orders"]

    assert [o["order_number"] for o in orders] == ["SA-2", "SA-1"]
    assert orders[0] == {
        "order_number": "SA-2", "product": "SmartPhone X1", "quantity": 250, "requested_date": "2026-10-31",
        "delivery_date": "2026-11-07", "status": "CONFIRMED", "confirmed_on": "2026-09-06",
    }


def test_the_history_is_limited_even_if_more_is_asked_for(db):
    customer, product = add_customer(db), add_product(db)
    for number in range(tools.MAX_ORDERS_IN_HISTORY + 3):
        add_confirmed_order(db, customer, product, f"SA-{number}", days_after_first=number)

    assert len(tools.get_order_history(db, customer.id, limit=50)["orders"]) == tools.MAX_ORDERS_IN_HISTORY
    assert len(tools.get_order_history(db, customer.id, limit=2)["orders"]) == 2


def test_the_history_never_includes_another_customers_orders(db):
    asha, ravi, product = add_customer(db, "+100", "Asha"), add_customer(db, "+200", "Ravi"), add_product(db)
    add_confirmed_order(db, ravi, product, "SA-RAVI")

    assert tools.get_order_history(db, asha.id) == {"orders": []}


# -- check_order_details --------------------------------------------------------------------------------------------


def test_valid_details_are_checked_against_the_products_in_the_database(db):
    product = add_product(db)

    answer = tools.check_order_details(db, "smartphone x1", "500", "2026-11-10", TODAY)

    assert answer["valid"] is True
    assert answer["product_id"] == str(product.id)
    assert answer["quantity"] == 500  # a number, not the text "500"
    assert answer["requested_date"] == "2026-11-10"


def test_wrong_details_come_back_with_the_problems(db):
    add_product(db)

    answer = tools.check_order_details(db, "SmartPhone X9", 0, "2026-01-01", TODAY)

    assert answer["valid"] is False
    assert [p["field"] for p in answer["problems"]] == ["product", "quantity", "requested_date"]


def test_a_product_that_is_not_active_cannot_be_ordered(db):
    add_product(db, "OLD-1", "Old Model", active=False)

    answer = tools.check_order_details(db, "Old Model", 5, "2026-11-10", TODAY)

    assert answer["valid"] is False


# -- get_order_status -----------------------------------------------------------------------------------------------


def test_the_status_of_an_order_is_given_in_plain_words(db):
    customer, product = add_customer(db), add_product(db)
    add_confirmed_order(db, customer, product, "SA-7", quantity=500, delivery_date=date(2026, 11, 12))

    status = tools.get_order_status(db, customer.id, "SA-7")

    assert status["found"] is True
    assert status["status_in_words"] == "confirmed"
    assert status["message"] == "Order SA-7 for 500 x SmartPhone X1 is confirmed. Delivery date: 2026-11-12."


def test_without_an_order_number_the_latest_order_is_used(db):
    customer, product = add_customer(db), add_product(db)
    add_confirmed_order(db, customer, product, "SA-1", days_after_first=0)
    add_confirmed_order(db, customer, product, "SA-2", days_after_first=3)

    assert tools.get_order_status(db, customer.id)["order_number"] == "SA-2"


def test_spaces_around_the_order_number_are_ignored(db):
    customer, product = add_customer(db), add_product(db)
    add_confirmed_order(db, customer, product, "SA-7")

    assert tools.get_order_status(db, customer.id, "  SA-7 ")["found"] is True


def test_someone_elses_order_gets_the_same_answer_as_an_order_that_does_not_exist(db):
    asha, ravi, product = add_customer(db, "+100", "Asha"), add_customer(db, "+200", "Ravi"), add_product(db)
    add_confirmed_order(db, ravi, product, "SA-RAVI")

    someone_elses = tools.get_order_status(db, asha.id, "SA-RAVI")
    does_not_exist = tools.get_order_status(db, asha.id, "SA-NOPE")

    assert someone_elses == does_not_exist == {"found": False, "message": "No order was found."}


def test_an_unknown_customer_or_a_customer_without_orders_gets_not_found(db):
    customer = add_customer(db)

    assert tools.get_order_status(db, None, "SA-1")["found"] is False
    assert tools.get_order_status(db, customer.id)["found"] is False
