# backend/app/data

| File | Purpose |
| --- | --- |
| `x1_fixture.py` | SmartPhone X1 fixture (X1-v2) as domain objects, from the former `docs/smartphone_x1_fixture.md` (removed 2026-10-16; still in git history). Builders: `x1_order`, `x1_bom`, `x1_inventory`, `x1_suppliers`; overrides reproduce scenarios S2, S3, S4, S6, S7. |
| `seed_data.py` | `reset_and_seed(db)` empties the 24 C2 tables and loads the X1 baseline (finished product, single-level BOM, 6 component positions in one warehouse, 14 suppliers, 3 agents, baseline order SO-0001 with status NEW). Run `python -m app.data.seed_data` from `backend/`. SKUs, warehouse, demo customer and agent names are placeholders the fixture does not define. |

`scenarios.py` is an empty placeholder (Scenario Manager, Phase 4).
