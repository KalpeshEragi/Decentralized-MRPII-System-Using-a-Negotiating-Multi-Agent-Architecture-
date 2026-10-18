# backend/app/warehouse_agent

The Warehouse Agent (`dev_docs/warehouse_agent/`): owner of receiving capacity, storage space (two zones, WH-2) and
physical moves; never of item quantities (IN-1). Deterministic (WH-5); template wording until the AI steps are switched
on (IMP-2).

| File | Purpose |
| --- | --- |
| `models.py` | `warehouse` schema: zones, daily capacities (receiving, shipping), receiving and shipping days, holds, space commitments, space movements (WD-1 movement profile), space ledger, event versions, audit log. |
| `manager.py` | `free_space` / `free_receiving`, `fits` (every day of the stay), `answer` (offer / later arrival / most that fits / reject) for STORAGE_SPACE and RECEIVING_SLOT, holds / commits (`ReceivingSlotCommitted` for deliveries) / aborts, `store_finished_goods` (`FinishedGoodsStored`), `issue_kits` (WF-1, `MaterialIssuedToProduction`), `ship` (`ShipmentDispatched`), hold expiry, `PlanRevised` (release exactly the listed space commitments not yet in use), `setup`, `register`. |
| `reads.py` | Read module (IB-2): `free_space`, `free_receiving`, `commitments_for`. |
| `api.py` | `POST /warehouse/setup` (simulator, `X-Door-Key`), `GET /warehouse/zones/{zone}/space`, `/receiving`, `/commitments/{ref}`. |

`ProcurementCommitted` makes Warehouse expect each delivery in the materials zone (a planned arrival); the receiving
slot itself is negotiated later (WH-1, PI-5). Daily routine (`run_day` on `SimulatedDayStarted`, WB-3): expire holds →
receive the deliveries due (`MaterialReceived`) → issue complete kits for
the production orders starting today (Planning's read module, kit from the shared BOM) → ship what is due and stored
for its order. Goods from production go to the finished-goods space committed for their customer demand; a
sub-assembly for another production order goes to the materials zone. Simulated deliveries and capacity changes come
with the Purchasing stub (step 6).

**Tests:** exercised end to end by `backend/tests/platform/test_s1_order_flow.py`.
