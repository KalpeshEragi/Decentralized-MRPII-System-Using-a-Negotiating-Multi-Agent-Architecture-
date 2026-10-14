"""The read-only tools, tested with real rows in the test database (the data access layer is included)."""

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
    """A confirmed order, with the conversation, inquiry and option it came from."""
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


def add_memory(db, customer, status="ACTIVE", kind="PREFERENCE", type_="PREFERS_WHATSAPP_UPDATES"):
    source = "STATED" if kind == "PREFERENCE" else "INFERRED"
    db.add(models.CustomerMemory(customer_id=customer.id, kind=kind, type=type_, source=source, status=status))
    db.flush()


# -- the tests ------------------------------------------------------------------------------------------------------


def test_customer_lookup_ignores_phone_formatting_and_returns_only_active_memory(db):
    asha, ravi = add_customer(db, "+919876543210", "Asha"), add_customer(db, "+100", "Ravi")
    add_memory(db, asha)
    add_memory(db, asha, kind="INSIGHT", type_="FREQUENT_PRODUCT")
    add_memory(db, asha, status="SUPERSEDED", type_="WANTS_EARLY_DATE_CHANGE_NOTICE")
    add_memory(db, asha, status="RETIRED", kind="INSIGHT", type_="FREQUENT_PRODUCT")
    add_memory(db, ravi)

    assert tools.get_customer_info(db, "+911111111111") == {"found": False}

    info = tools.get_customer_info(db, "+91 98765-43210")  # typed with spaces and a dash
    assert info["customer"] == {"id": str(asha.id), "name": "Asha", "phone": "+919876543210"}
    # Only the two active notes, not Ravi's, and what the customer said is told apart from what our rules inferred.
    assert sorted((m["kind"], m["source"], m["type"]) for m in info["memory"]) == [
        ("INSIGHT", "INFERRED", "FREQUENT_PRODUCT"),
        ("PREFERENCE", "STATED", "PREFERS_WHATSAPP_UPDATES"),
    ]


def test_order_history_and_status_are_newest_first_limited_and_strictly_the_customers_own(db):
    asha, ravi, product = add_customer(db, "+100", "Asha"), add_customer(db, "+200", "Ravi"), add_product(db)
    count = tools.MAX_ORDERS_IN_HISTORY + 3
    for number in range(count):
        add_confirmed_order(db, asha, product, f"SA-{number}", days_after_first=number)
    newest = add_confirmed_order(db, asha, product, "SA-NEWEST", days_after_first=count, quantity=250,
                                 requested_date=date(2026, 10, 31), delivery_date=date(2026, 11, 7))
    add_confirmed_order(db, ravi, product, "SA-RAVI", days_after_first=count + 5)  # newer than all of Asha's

    # History: newest first, limited even if more is asked for, with the date the customer originally asked for.
    orders = tools.get_order_history(db, asha.id, limit=50)["orders"]
    assert len(orders) == tools.MAX_ORDERS_IN_HISTORY
    assert [o["order_number"] for o in orders][:2] == ["SA-NEWEST", f"SA-{count - 1}"]
    assert orders[0] == {
        "order_number": "SA-NEWEST", "product": "SmartPhone X1", "quantity": 250, "requested_date": "2026-10-31",
        "delivery_date": "2026-11-07", "status": "CONFIRMED", "confirmed_on": newest.confirmed_at.date().isoformat(),
    }

    # Status: by order number, or the latest order when no number is given, in plain words.
    status = tools.get_order_status(db, asha.id, "  SA-NEWEST ")
    assert status["message"] == "Order SA-NEWEST for 250 x SmartPhone X1 is confirmed. Delivery date: 2026-11-07."
    assert tools.get_order_status(db, asha.id)["order_number"] == "SA-NEWEST"

    # Privacy: Ravi's orders never show up for Asha, and asking for one gets exactly the answer for a missing order.
    assert "SA-RAVI" not in [o["order_number"] for o in orders]
    not_found = {"found": False, "message": "No order was found."}
    assert tools.get_order_status(db, asha.id, "SA-RAVI") == tools.get_order_status(db, asha.id, "SA-NOPE") == not_found
    assert tools.get_order_status(db, None, "SA-0") == not_found  # an unknown customer
    assert tools.get_order_history(db, add_customer(db, "+300", "New").id) == {"orders": []}


def test_only_active_products_can_be_ordered(db):
    add_product(db, "T1-TABLET", "Tablet T1")
    product = add_product(db, "X1-PHONE", "SmartPhone X1")
    add_product(db, "OLD-1", "Old Model", active=False)

    assert [p["name"] for p in tools.get_product_list(db)["products"]] == ["SmartPhone X1", "Tablet T1"]

    answer = tools.check_order_details(db, "smartphone x1", "500", "2026-11-10", TODAY)
    assert answer["valid"] is True and answer["product_id"] == str(product.id)
    assert answer["quantity"] == 500  # a number, not the text "500"
    assert tools.check_order_details(db, "Old Model", 5, "2026-11-10", TODAY)["valid"] is False
