# backend/scripts

Manual verification scripts. None runs in the test suite.

| Script | Needs | Purpose |
| --- | --- | --- |
| `verify_phase1.py` | nothing | Prints the X1 plan, supplier feasibility and the in-memory negotiation flows (agreement, FAILED after 3 rounds, REJECTED, refused messages). |
| `verify_phase2.py` | migrated `DATABASE_URL` | **Resets the database to the X1 baseline**, runs and persists the plan, prints the stored MPS/MRP and opens a session for the Display shortage. |
| `a2a_spike_client.py` | running API + a session id | Sends the C4 envelope to the three A2A endpoints as A2A `SendMessage` calls. Since Phase 3 the Purchasing Agent answers the REQUEST itself, so the script's own OFFER (sequence 2) is refused. |
| `verify_phase4.py` | running API on a freshly seeded `DATABASE_URL` | `approve`, `replan` or `exhaust`: approval → COMMIT, reject → replan (attempt 2), rejecting attempt 2 → human intervention. |
| `verify_phase3.py` | running API on a freshly seeded `DATABASE_URL` | Hands SO-0001 to the Planning Agent and answers the Display negotiation as the supplier (`accept`, `counter`, `reject`, `fail`); prints the session, Planning's results, agent states and the decision log. |
