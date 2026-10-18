# backend/scripts

Manual verification scripts. None runs in the test suite.

| Script | Needs | Purpose |
| --- | --- | --- |
| `verify_phase1.py` | nothing | Prints the X1 plan, supplier feasibility and the in-memory negotiation flows (agreement, FAILED after 3 rounds, REJECTED, refused messages). |
| `verify_phase2.py` | migrated `DATABASE_URL` | **Resets the database to the X1 baseline**, runs and persists the plan, prints the stored MPS/MRP and opens a session for the Display shortage. |
| `a2a_spike_client.py` | running API + a session id | Sends a C4 REQUEST and a malformed envelope to the A2A endpoints as A2A `SendMessage` calls. |

`verify_phase3.py` and `verify_phase4.py` were removed 2026-10-18 with the legacy supplier routes they answered through.
