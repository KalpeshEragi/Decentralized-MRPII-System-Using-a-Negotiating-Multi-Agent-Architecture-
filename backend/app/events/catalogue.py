"""The event catalogue (EM-1, `architecture/rules_events_replenishment.md` §3): every event of the system, once.

Per event: its publisher, its subscribers (required = must have a handler; optional = listed for the design but not
built yet), the payload model, a description, a version and a status:

    ACTIVE      published and delivered normally
    DEPRECATED  still delivered; publishing it logs a warning (step 1 of removing an event)
    RETIRED     publishing and subscribing are refused (stored old events stay readable)

Payload models list every field the publisher sends (taken from the publishing code and from the events of earlier
runs). Unknown fields are a mismatch: refused in tests and development, logged in the demo (EM-3). Adding an event is
one entry here plus the publisher's call and the subscribers' handlers. The channel only stores and delivers.
"""

from dataclasses import dataclass, field, replace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

SALES, PLANNING, INVENTORY, PURCHASING, WAREHOUSE, HR = "SALES", "PLANNING", "INVENTORY", "PURCHASING", "WAREHOUSE", "HR"
SIMULATOR_CLOCK = "SIMULATOR_CLOCK"
ACTIVE, DEPRECATED, RETIRED = "ACTIVE", "DEPRECATED", "RETIRED"

Number = str | int | float  # quantities travel as decimal strings; a few publishers send ints


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


# -- Sales ---------------------------------------------------------------------------------------------------------------

class OrderConfirmed(Payload):
    order_number: str
    inquiry_id: str
    option_id: str
    customer_id: str
    product_id: str
    quantity: Number
    delivery_date: str
    confirmed_at: str
    confirming_message_id: str
    payment: str


class OrderChangeRequested(Payload):
    order_number: str
    quantity: Number


class OrderCancelled(Payload):
    order_number: str


# -- Planning ------------------------------------------------------------------------------------------------------------

class _PlanEvent(Payload):
    demand_id: str
    order_number: str | None = None  # empty before the customer confirmed
    request_ref: str


class PlanCommitted(_PlanEvent):
    delivery_day: str
    quantity: Number
    production_orders: list[dict[str, Any]]


class PlanCommitFailed(_PlanEvent):
    reason: str


class PlanRevised(_PlanEvent):
    reason: str
    releases: list[dict[str, Any]] = []
    detail: str | None = None
    quantity: Number | None = None
    production_orders: list[dict[str, Any]] | None = None
    cancelled_production_orders: list[str] | None = None
    continuing_production_orders: list[str] | None = None
    production_order_id: str | None = None
    from_day: str | None = None
    to_day: str | None = None


class PlanAtRisk(_PlanEvent):
    reason: str
    production_order_id: str | None = None
    delivery_day: str | None = None
    day: str | None = None                      # worker absence
    skill: str | None = None
    missing_hours: Number | None = None
    item_id: str | None = None                  # supplier delay
    arrival_day: str | None = None
    needed_by: str | None = None
    days_late: int | None = None
    estimated_delivery_day: str | None = None


class ProductionOrderReleased(Payload):
    production_order_id: str
    demand_id: str
    item_id: str
    quantity: Number
    start_day: str
    end_day: str
    steps: list[dict[str, Any]]


class _ProductionProgress(Payload):
    production_order_id: str
    item_id: str
    quantity: Number
    for_kind: str
    for_ref: str
    order_ref: str


class ProductionStarted(_ProductionProgress):
    pass


class ProductionCompleted(_ProductionProgress):
    completion_day: str


class ProductionBatchCompleted(_ProductionProgress):
    completion_day: str
    completed: Number          # finished so far, including this batch
    total: Number              # the production order's quantity
    hour: int                  # time of day the batch was finished (SIM-1)


# -- Inventory -----------------------------------------------------------------------------------------------------------

class ReservationCommitted(Payload):
    reservation_id: str
    item_id: str
    quantity: Number
    for_kind: str
    for_ref: str


class ReservationReleased(Payload):
    reservation_id: str
    item_id: str
    quantity: Number
    for_ref: str


class SafetyStockBreached(Payload):
    item_id: str
    safety_stock: Number
    released: Number


# -- Purchasing ----------------------------------------------------------------------------------------------------------

class ProcurementCommitted(Payload):
    procurement_request_id: str
    item_id: str | None
    for_kind: str | None
    for_ref: str | None
    legs: list[dict[str, Any]]


class SupplierDeliveryDelayed(Payload):
    procurement_request_id: str
    leg_id: str
    quantity: Number
    old_date: str
    new_date: str
    item_id: str | None
    for_kind: str | None
    for_ref: str | None


# -- Warehouse -----------------------------------------------------------------------------------------------------------

class ReceivingSlotCommitted(Payload):
    commitment_id: str
    for_ref: str
    arrival_day: str
    item_id: str
    quantity: Number
    space_units: Number


class MaterialReceived(Payload):
    procurement_request_id: str
    leg_id: str
    item_id: str
    quantity: Number
    day: str
    for_ref: str | None


class MaterialIssuedToProduction(Payload):
    production_order_id: str
    kits: Number
    components: list[dict[str, Any]]


class FinishedGoodsStored(Payload):
    production_order_id: str
    item_id: str
    quantity: Number
    zone: str
    for_kind: str
    for_ref: str
    order_ref: str


class StorageCapacityChanged(Payload):
    resource: str
    units: Number


class ShipmentDispatched(Payload):
    order_ref: str
    item_id: str
    quantity: Number
    date: str


# -- HR ------------------------------------------------------------------------------------------------------------------

class WorkforceCommitted(Payload):
    commitment_id: str
    production_order_id: str
    skill: str
    hours_by_day: dict[str, Any]


class WorkforceCapacityChanged(Payload):
    worker: str
    pools: dict[str, Any]
    at_risk: list[dict[str, Any]]


# -- simulator -----------------------------------------------------------------------------------------------------------

class SimulatedDayStarted(Payload):
    date: str


# -- the catalogue ---------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class EventDefinition:
    name: str
    publisher: str
    subscribers: dict[str, bool]          # subscriber -> required (True: must have a handler)
    payload: type[Payload] | None         # None: not built yet (no publisher); publishing it is refused
    description: str
    version: int = 1
    status: Literal["ACTIVE", "DEPRECATED", "RETIRED"] = ACTIVE
    decided_in: str = ""                  # the decision or doc that introduced it
    notes: tuple[str, ...] = field(default_factory=tuple)
    explanation: str = ""                 # what it means in the factory, when it happens, why it matters
    caused_by: tuple[str, ...] = ()       # events or outside causes that lead to it
    leads_to: tuple[str, ...] = ()        # events that follow from it (directly or on a later day)


def _req(*agents: str) -> dict[str, bool]:
    return {a: True for a in agents}


def _opt(*agents: str) -> dict[str, bool]:
    return {a: False for a in agents}


DEFINITIONS: tuple[EventDefinition, ...] = (
    EventDefinition("OrderConfirmed", SALES, _req(PLANNING), OrderConfirmed,
                    "The customer confirmed an option: Sales has an order.", decided_in="pubsub §8"),
    EventDefinition("OrderChangeRequested", SALES, _req(PLANNING), OrderChangeRequested,
                    "The customer asks for another quantity on a confirmed order.", decided_in="pubsub §8, S7"),
    EventDefinition("OrderCancelled", SALES, _req(PLANNING), OrderCancelled,
                    "The customer cancelled a confirmed order.", decided_in="pubsub §8, S6"),
    EventDefinition("PlanCommitted", PLANNING, {**_req(), **_opt(SALES, INVENTORY, PURCHASING, WAREHOUSE, HR)},
                    PlanCommitted, "Planning committed the plan of an order (all owners committed).",
                    decided_in="pubsub §8"),
    EventDefinition("PlanCommitFailed", PLANNING, _opt(SALES, INVENTORY, PURCHASING, WAREHOUSE, HR), PlanCommitFailed,
                    "Planning could not commit an order's plan.", decided_in="pubsub §8"),
    EventDefinition("PlanRevised", PLANNING, {**_req(SALES, INVENTORY, WAREHOUSE, HR), **_opt(PURCHASING)},
                    PlanRevised, "Planning changed a committed plan and lists what each owner must release.",
                    decided_in="pubsub §8, RD-5"),
    EventDefinition("PlanAtRisk", PLANNING, _opt(SALES), PlanAtRisk,
                    "A committed order may miss its date (worker absence, supplier delay); an estimate, not a promise.",
                    decided_in="RD-4"),
    EventDefinition("ProductionOrderReleased", PLANNING, {**_req(HR), **_opt(WAREHOUSE, INVENTORY)}, ProductionOrderReleased,
                    "A firm production order is released to the shop floor.", decided_in="RD-7"),
    EventDefinition("ProductionStarted", PLANNING, _opt(SALES, INVENTORY, WAREHOUSE), ProductionStarted,
                    "Production of an order started.", decided_in="RD-3"),
    EventDefinition("ProductionCompleted", PLANNING, {**_req(WAREHOUSE, HR), **_opt(SALES)}, ProductionCompleted,
                    "Production of an order finished.", decided_in="RD-3"),
    EventDefinition("ProductionBatchCompleted", PLANNING, {**_req(WAREHOUSE), **_opt(SALES)}, ProductionBatchCompleted,
                    "A batch of a running production order is finished (not the last one).", decided_in="SIM-3"),
    EventDefinition("ReservationCommitted", INVENTORY, _opt(PLANNING), ReservationCommitted,
                    "Inventory reserved stock for an order.", decided_in="IN-2"),
    EventDefinition("ReservationReleased", INVENTORY, _opt(PLANNING), ReservationReleased,
                    "Inventory released (part of) a reservation.", decided_in="IN-2"),
    EventDefinition("StockAvailabilityChanged", INVENTORY, _opt(PLANNING), None,
                    "Inventory's available stock of an item changed.", decided_in="pubsub §8",
                    notes=("not built: no publisher yet",)),
    EventDefinition("SafetyStockBreached", INVENTORY, _opt(PLANNING), SafetyStockBreached,
                    "Inventory lent safety stock to an urgent order; Planning should refill it (RD-6, refill not "
                    "built yet).", decided_in="RD-6"),
    EventDefinition("ProcurementCommitted", PURCHASING, {**_req(INVENTORY, WAREHOUSE), **_opt(PLANNING)},
                    ProcurementCommitted, "Purchasing committed a purchase with its suppliers.", decided_in="PI-4"),
    EventDefinition("SupplierDeliveryDelayed", PURCHASING, _req(PLANNING, INVENTORY, WAREHOUSE),
                    SupplierDeliveryDelayed, "A supplier announced that a committed delivery comes later.",
                    decided_in="S2"),
    EventDefinition("SupplierQuantityReduced", PURCHASING, _opt(PLANNING, INVENTORY, WAREHOUSE), None,
                    "A supplier delivers less than committed.", decided_in="pubsub §8",
                    notes=("not built: no publisher yet",)),
    EventDefinition("ReceivingSlotCommitted", WAREHOUSE, _opt(PURCHASING, PLANNING), ReceivingSlotCommitted,
                    "Warehouse committed a receiving slot for a delivery.", decided_in="WH-1"),
    EventDefinition("MaterialReceived", WAREHOUSE, {**_req(INVENTORY), **_opt(PURCHASING, PLANNING)}, MaterialReceived,
                    "A delivery arrived at the receiving dock.", decided_in="WH-3"),
    EventDefinition("MaterialIssuedToProduction", WAREHOUSE, {**_req(INVENTORY), **_opt(PLANNING)},
                    MaterialIssuedToProduction, "Complete kits were issued to a production order.",
                    decided_in="WH-3"),
    EventDefinition("FinishedGoodsStored", WAREHOUSE, {**_req(INVENTORY), **_opt(PLANNING, SALES)},
                    FinishedGoodsStored, "Finished goods were put into storage.", decided_in="WH-3"),
    EventDefinition("StorageCapacityChanged", WAREHOUSE, _opt(PLANNING, PURCHASING), StorageCapacityChanged,
                    "A receiving, shipping or zone capacity changed.", decided_in="WH-6"),
    EventDefinition("ShipmentDispatched", WAREHOUSE, {**_req(INVENTORY, PLANNING), **_opt(SALES)}, ShipmentDispatched,
                    "An order's goods left the factory.", decided_in="PB-3"),
    EventDefinition("WorkforceCommitted", HR, _opt(PLANNING), WorkforceCommitted,
                    "HR committed worker-hours to a production order.", decided_in="HR-2"),
    EventDefinition("WorkforceCapacityChanged", HR, _req(PLANNING), WorkforceCapacityChanged,
                    "A worker is absent; HR covered what it could and lists what is still at risk.",
                    decided_in="HR-5, S5"),
    EventDefinition("SimulatedDayStarted", SIMULATOR_CLOCK, {**_req(PLANNING, INVENTORY, WAREHOUSE, HR, PURCHASING),
                                                             **_opt(SALES)},
                    SimulatedDayStarted, "The simulated clock moved to a new day.", decided_in="DM-1"),
)

# -- the story of each event: what it means, what causes it, what follows (shown on the Events page and given to the
#    event manager assistant). Cause and follow-up names that are events are checked by the catalogue test.

STORY: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "OrderConfirmed": (
        "A customer said yes to one of the options Sales showed. From now on it is an order with a number; Planning "
        "must turn the held option into firm commitments with every owner.",
        ("Customer accepts an option (Sales)",), ("PlanCommitted", "PlanCommitFailed")),
    "OrderChangeRequested": (
        "A customer wants a different quantity on a confirmed order. Planning treats it as a change on top of what is "
        "already committed: more is planned and secured, less is released.",
        ("Customer changes the quantity (Sales, trigger CHANGE_ORDER)",), ("PlanRevised",)),
    "OrderCancelled": (
        "A customer cancelled a confirmed order. Planning frees what is not started yet; work already released "
        "finishes and goes to free stock.",
        ("Customer cancels (Sales, trigger CANCEL_ORDER)",), ("PlanRevised",)),
    "PlanCommitted": (
        "Every owner committed its part of an order (stock, worker-hours, space, supply): the plan is firm and its "
        "production orders will be released on their days.",
        ("OrderConfirmed",), ("ProductionOrderReleased",)),
    "PlanCommitFailed": (
        "Planning could not make an order's plan firm (an owner refused at commit or the option was unknown). What "
        "was held is released; the customer is told.",
        ("OrderConfirmed",), ("PlanRevised",)),
    "PlanRevised": (
        "Planning changed a committed plan and lists exactly what each owner must release (reservations, hours, "
        "space). Reasons: cancellation, quantity change, worker-absence repair, order completed, failed commit.",
        ("OrderCancelled", "OrderChangeRequested", "WorkforceCapacityChanged", "ShipmentDispatched",
         "PlanCommitFailed"),
        ("ReservationReleased",)),
    "PlanAtRisk": (
        "A committed order may miss its delivery date. Planning gives an estimate, not a promise; it does not move a "
        "customer's date on its own.",
        ("SupplierDeliveryDelayed", "WorkforceCapacityChanged"), ()),
    "ProductionOrderReleased": (
        "A firm production order starts its last day of preparation: HR assigns named workers, the Warehouse will "
        "issue its kits next morning.",
        ("SimulatedDayStarted", "PlanCommitted"), ("MaterialIssuedToProduction", "ProductionStarted")),
    "ProductionStarted": (
        "The shop floor started producing an order.", ("Shop-floor report",),
        ("ProductionBatchCompleted", "ProductionCompleted")),
    "ProductionBatchCompleted": (
        "A batch of a running production order is finished (e.g. 25 of 60 main boards at 10:00). The Warehouse puts "
        "it away at once, so the components can feed the next operation as soon as they exist; the last batch is "
        "announced as ProductionCompleted instead.",
        ("Shop-floor report",), ("FinishedGoodsStored",)),
    "ProductionCompleted": (
        "The shop floor finished an order: the Warehouse puts the goods away, HR frees remaining hours.",
        ("Shop-floor report",), ("FinishedGoodsStored",)),
    "ReservationCommitted": (
        "Inventory turned a hold into a firm reservation for an order: that stock can no longer be promised to "
        "anyone else.", ("Planning's COMMIT of a stock negotiation",), ()),
    "ReservationReleased": (
        "Inventory gave back (part of) a reservation because Planning no longer needs it.", ("PlanRevised",), ()),
    "StockAvailabilityChanged": (
        "Meant to announce that an item's available stock changed. Not built: no agent publishes it yet.", (), ()),
    "SafetyStockBreached": (
        "Inventory lent part of its safety stock to an urgent order. The stock is below its safety level until it is "
        "refilled (refill not built yet: rules_events_replenishment.md section 4).",
        ("Inventory lends safety stock in a negotiation",), ()),
    "ProcurementCommitted": (
        "Purchasing committed a purchase with its suppliers (one or more deliveries with dates). Inventory expects "
        "the receipt, the Warehouse expects the delivery.",
        ("Planning's COMMIT of a supply negotiation",), ("MaterialReceived",)),
    "SupplierDeliveryDelayed": (
        "A supplier will deliver later than agreed. Everyone that counted on that delivery moves its expectation; "
        "Planning checks whether an order is now at risk.",
        ("Supplier / trigger SUPPLIER_DELAY",), ("PlanAtRisk",)),
    "SupplierQuantityReduced": (
        "Meant to announce that a supplier delivers less than agreed. Not built: no agent publishes it yet.", (), ()),
    "ReceivingSlotCommitted": (
        "The Warehouse booked a day at the receiving dock for a delivery, so the dock is never overbooked.",
        ("Purchasing's COMMIT of a receiving slot",), ("MaterialReceived",)),
    "MaterialReceived": (
        "A delivery arrived at the dock: Inventory's stock goes up; bought for an order, it is reserved for it.",
        ("SimulatedDayStarted",), ()),
    "MaterialIssuedToProduction": (
        "The Warehouse gave complete kits of components to a production order; Inventory's stock and reservations "
        "go down.", ("SimulatedDayStarted", "ProductionOrderReleased"), ("ProductionStarted",)),
    "FinishedGoodsStored": (
        "Produced goods were put into storage and reserved for what they were made for (one batch at a time).",
        ("ProductionBatchCompleted", "ProductionCompleted"), ("ShipmentDispatched",)),
    "StorageCapacityChanged": (
        "A receiving, shipping or storage capacity changed. New plans and deliveries are made around it; what was "
        "already committed stays.", ("Trigger WAREHOUSE_CAPACITY",), ()),
    "ShipmentDispatched": (
        "An order's goods left the factory: Inventory's stock goes down, Planning counts the order as delivered.",
        ("SimulatedDayStarted",), ("PlanRevised",)),
    "WorkforceCommitted": (
        "HR committed worker-hours of a skill to a production order.",
        ("Planning's COMMIT of a workforce negotiation",), ()),
    "WorkforceCapacityChanged": (
        "A worker is absent. HR first covers it itself (move a worker, overtime); what it cannot cover is listed as "
        "at risk for Planning to repair.", ("Trigger WORKER_ABSENT",), ("PlanRevised", "PlanAtRisk")),
    "SimulatedDayStarted": (
        "The simulated clock moved to a new day. Every agent runs its morning routine: expire holds, release "
        "production orders, receive deliveries, issue kits, ship.",
        ("Next day / Play",), ("ProductionOrderReleased", "MaterialReceived", "MaterialIssuedToProduction",
                               "ShipmentDispatched")),
}

DEFINITIONS = tuple(replace(d, explanation=STORY[d.name][0], caused_by=STORY[d.name][1], leads_to=STORY[d.name][2])
                    for d in DEFINITIONS)
BY_NAME: dict[str, EventDefinition] = {d.name: d for d in DEFINITIONS}
