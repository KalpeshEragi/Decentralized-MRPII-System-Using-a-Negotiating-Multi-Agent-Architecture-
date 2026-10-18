"""Inventory Agent (inventory_agent/2, quantity_accounting.md §5): the developer's 5000 -> 3000 example through the real
negotiation layer and events, an exact ledger, and no double booking when three requests compete for little stock."""

from datetime import timedelta
from decimal import Decimal as D

from sqlalchemy import func, select

from app.events import channel
from app.inventory_agent import manager as inventory, reads
from app.inventory_agent.models import Reservation, StockBalance, StockLedger
from app.negotiation.envelope import ResourceType, Terms
from app.negotiation.models import Session
from app.simulation.clock import today

X, Y = "item-x", "item-y"


def stock(db, item, quantity, order) -> Terms:
    return Terms(resource_type=ResourceType.STOCK, resource_ref=item, quantity=D(quantity),
                 needed_by=today(db) + timedelta(days=5), order_id=order)


def numbers(session_factory, item):
    with session_factory() as db:
        row = db.get(StockBalance, item)
        return (row.on_hand, row.held, row.reserved, inventory.atp_on(db, row, today(db) + timedelta(days=5)))


def test_the_5000_to_3000_example_with_an_exact_ledger(session_factory, pump, fake_planning):
    planning, request = fake_planning
    with session_factory() as db:
        inventory.setup(db, [{"item_id": X, "on_hand": 5000, "safety_stock": 0}])
        for n in (1, 2, 3):
            request(db, "INVENTORY", stock(db, X, 500, f"O-{n}"), f"C-{n}")
        db.commit()
    pump([planning])
    assert numbers(session_factory, X) == (5000, 0, 1500, 3500)  # three orders held, then committed

    with session_factory() as db:  # O-2 grows 500 -> 1000: only the extra 500 is negotiated (QA-3)
        request(db, "INVENTORY", stock(db, X, 500, "O-2"), "C-2b")
        db.commit()
    pump([planning])
    assert numbers(session_factory, X) == (5000, 0, 2000, 3000)  # the developer's example

    with session_factory() as db:
        o2_extra, o3 = (db.scalars(select(Reservation).where(Reservation.for_ref == ref)
                                   .order_by(Reservation.created_at.desc())).first() for ref in ("O-2", "O-3"))
        channel.publish(db, event_type="PlanRevised", publisher="PLANNING", entity_type="plan", entity_id="O-2",
                        entity_version=2, correlation_id="C-2",
                        payload={"releases": [
                            {"owner": "INVENTORY", "reservation_id": str(o2_extra.id), "quantity": "400"},
                            {"owner": "INVENTORY", "reservation_id": str(o3.id), "quantity": "500"}]})
        channel.publish(db, event_type="MaterialIssuedToProduction", publisher="WAREHOUSE",
                        entity_type="production_order", entity_id="O-1", entity_version=1, correlation_id="C-1",
                        payload={"production_order_id": "O-1", "kits": "500",
                                 "components": [{"item_id": X, "issued": "500", "missing": "0"}]})
        db.commit()
    pump([planning])
    # O-2 reduced 1000 -> 600 (release 400), O-3 cancelled (release 500), O-1 issued 500 (stock and reservation down)
    assert numbers(session_factory, X) == (4500, 0, 600, 3900)

    with session_factory() as db:  # QA-1: every balance equals the sum of its ledger rows
        sums = dict(db.execute(select(StockLedger.bucket, func.sum(StockLedger.delta))
                               .where(StockLedger.resource_ref == X).group_by(StockLedger.bucket)).all())
        assert (sums["ON_HAND"], sums["RESERVED"], sums.get("HELD", 0)) == (4500, 600, 0)


def test_three_requests_for_scarce_stock_never_double_book(session_factory, pump, fake_planning):
    planning, request = fake_planning
    with session_factory() as db:  # quantity_accounting.md §5.2: 1200 on hand, 200 safety stock -> 1000 available
        inventory.setup(db, [{"item_id": Y, "on_hand": 1200, "safety_stock": 200}])
        sessions = [request(db, "INVENTORY", stock(db, Y, 500, f"P-{n}"), f"S-{n}") for n in (1, 2, 3)]
        db.commit()
    pump([planning])  # all three get an offer (offers are non-binding); holds are checked one at a time

    on_hand, held, reserved, available = numbers(session_factory, Y)
    assert (held + reserved, available) == (1000, 0)  # never more than the 1000 available
    with session_factory() as db:
        rows = [db.get(Session, s) for s in sessions]
        assert sorted((r.status, r.last_reason_code or "") for r in rows) == [
            ("COMMITTED", ""), ("COMMITTED", ""), ("REJECTED", "STALE")]
        assert sum(1 for ref in ("P-1", "P-2", "P-3") for row in reads.reservations_for(db, ref)
                   if row["kind"] == "RESERVATION") == 2
