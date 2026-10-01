# C5 (part) — API Error Format

**Status:** CONFIRMED (2026-09-30)
**Implemented in:** `backend/app/core/` (error type + FastAPI exception handlers), used by every router in `backend/app/api/`.

This file defines only the **error format** shared by all HTTP APIs. Per-router request/response
models are written when each router is built (Phase 2 onward) and added as separate C5 files.
A2A protocol errors are handled by the A2A SDK and are not covered here.

---

## 1. Error body

Every non-2xx response from the backend API uses this body:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "quantity must be greater than 0",
    "details": [
      { "field": "lines[0].quantity", "issue": "must be greater than 0" }
    ]
  }
}
```

| Field | Type | Rule |
| --- | --- | --- |
| `code` | string (enum below) | Stable, machine-readable. The frontend branches on this. |
| `message` | string | Short, human-readable, safe to show in the UI. |
| `details` | list, may be empty | Field-level or context items: `{ "field"?: string, "issue": string }`. |

No stack traces, SQL, internal paths, raw LLM output or secrets in any field.

## 2. Codes and HTTP status

| `code` | HTTP | When |
| --- | --- | --- |
| `VALIDATION_ERROR` | 422 | Request body/params fail validation. FastAPI's default `{"detail": [...]}` is replaced by this format. |
| `NOT_FOUND` | 404 | Referenced resource does not exist. |
| `CONFLICT` | 409 | Request conflicts with current state (e.g. duplicate `order_number`). |
| `INVALID_STATE_TRANSITION` | 409 | Action not allowed in the current state (e.g. a supplier response after the session has ended, or for a round that is not the current one). |
| `BUSINESS_RULE_VIOLATION` | 422 | Well-formed request that breaks a deterministic business rule and is refused. |
| `SERVICE_UNAVAILABLE` | 503 | A dependency is unreachable (database, Ollama). |
| `INTERNAL_ERROR` | 500 | Anything unexpected. Logged server-side with context. |

New codes are added in the per-router C5 files through a contract change made before the code.

## 3. Results that are NOT errors

These are normal outcomes, returned with `2xx` and their own response models:

- A negotiation ending without agreement: session `REJECTED` (supplier `REJECT`) or `FAILED` (no agreement within 3 rounds); outcome `FAILED` for Planning.
- A plan that fails deterministic validation (`PlanValidationResult.valid = false`, C1).
- An MRP run that finds shortages.
- An agent deciding `REJECT` or `COUNTER_OFFER`.
- Automatic replanning stopping after 2 attempts and requiring human intervention (**shape PENDING C8**).

Treating these as errors would hide agent decisions from the UI and the decision log.

## 4. Invalid LLM output

Invalid or unparseable LLM output is handled inside the agent (rejected by deterministic validation
and recorded per C7). It never reaches the API as raw text and never changes business state.
If it prevents an API request from completing, the API returns `INTERNAL_ERROR` or
`SERVICE_UNAVAILABLE` with a generic message.
