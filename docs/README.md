# docs

Working documents shared by the two developers. Finalized specifications live in `dev_docs/`.

| Folder | Contents |
| --- | --- |
| `contracts/` | Shared contracts (C1–C9): shapes and rules both developers build against. |
| `decisions/` | Coordination items awaiting or recording a joint decision (e.g. Phase 0 items P0-xx). |

## Folder README template

Every meaningful folder has a concise `README.md` describing the **actual** code in it (roadmap Section 6).
Use this outline; drop sections that do not apply. Never describe code that does not exist yet.

```markdown
# <path/to/folder>

One or two sentences: what this folder is responsible for and why it exists.

## Files
| File | Purpose (main class/function, why it exists, how it relates to other files) |

## Relationships
Which folders it uses, which folders use it, and any boundary rule (e.g. "agents call services, never tables").

## Data / control flow
Short description of the main flow, if not obvious.

## Dependencies
Important libraries or contracts (e.g. C1, C4).

**Tests:** where the tests for this folder live.
```
