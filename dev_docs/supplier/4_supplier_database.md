# Supplier: Database

**Status:** implemented: migration `backend/alembic/versions/004_purchasing_supplier_engine.py` (schema `supplier_service`).
**Full column list:** `../OVERALL_DATABASE_SCHEMA.md` §5.1. **Fixture:** `../purchasing_agent/seed_data.md` §2–§3.

## 1. Ownership

- Schema `supplier_service`, owned by the Supplier Service, own declarative base (legacy demo resets can't touch it).
- Other modules read it only through `supplier_service/service.py`; nothing writes it except the seed.
- Other schemas point here **logically** (UUID, no database FK): `purchasing_agent.purchasing_contracts`,
  `procurement_requests`, `purchase_requisitions` (`supplier_id`, `item_id`) and
  `negotiation_engine.negotiation_participants.participant_ref` (supplier UUID as text).
- Legacy `purchasing.suppliers` / `purchasing.supplier_items` are separate, untouched and not used by the new code.

## 2. Tables

| Table | Columns | Constraints |
| --- | --- | --- |
| `items` | id · sku · name · unit | sku UNIQUE |
| `suppliers` | id · name · contact_info (JSONB) · rating_data (JSONB, not used in ranking) · is_active (default TRUE) | name UNIQUE |
| `supplier_items` | id · supplier_id (FK) · item_id (FK) · lead_time_days · min_order_qty · available_qty | UNIQUE (supplier_id, item_id); lead_time_days ≥ 0; min_order_qty > 0; available_qty ≥ 0; index on item_id |

No price column anywhere in this schema (price is in `purchasing_agent.purchasing_contracts`, ADR-002).

## 3. Seed data (`supplier_service/seed.py`, PA-v1)

6 items (unit `pcs`): DSP-100 Display Panel, BAT-200 Battery Pack, MBD-300 Main Board, CAM-400 Camera Module,
SPK-500 Speaker, CHP-600 Charging Port.

19 supplier items, 19 suppliers (one item each):

| Item | Suppliers (lead days / MOQ / available) |
| --- | --- |
| DSP-100 | Alpha Displays 10/200/1000 · Beta Optics 6/100/800 · Gamma Screens 4/50/2000 · Dormant Displays 1/10/5000 (**inactive**) |
| BAT-200 | Volt Power 7/100/400 · Cell Works 9/200/500 · Ion Supply 12/300/1500 |
| MBD-300 | Nova Silicon 5/50/600 · Orbit Circuits 6/50/600 · Pixel Boards 8/100/600 · Quartz Electronics 15/100/1000 |
| CAM-400 | Lumen Optics 6/100/300 · Focal Point 5/100/300 · Prism Labs 20/100/2000 |
| SPK-500 | Sonic Audio 4/100/500 · EchoTech 5/100/300 · Wave Acoustics 6/100/300 |
| CHP-600 | PlugCo 5/100/1000 · ConnectRite 5/100/400 |

IDs are fixed: `uuid5(namespace, "item:<sku>")` and `uuid5(namespace, "supplier:<name>")` (`ITEM_IDS`, `SUPPLIER_IDS`).
`contact_info` and `rating_data` are empty in the fixture.

## 4. Not built

- No write path (API or service) for supplier data; `available_qty` is never reduced by commitments (Purchasing holds
  are subtracted at read time instead).
- No link to `core.items` yet (integration).
