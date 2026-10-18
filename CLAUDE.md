# Decentralized MRPII system with Multi-Agent negotiation

## 1. Project Goal
Build a decentralized MRPII system with autonomous domain agents that coordinate and negotiate. Shared infrastructure is allowed; centralized business decision-making is not. LLMs support reasoning but are never the source of business truth.

## 2. Current Development Direction
- Develop each agent independently, with clear interfaces and tests, then integrate the agents.
- Only the **Sales Agent** is considered properly implemented today. Other agent code is legacy/provisional and must not be assumed compatible with the new architecture. Inspect it for reusable ideas, but do not preserve or depend on it without approval.
- Target logical agents discussed: Sales, Production Planning, Inventory, Purchasing, Warehouse, and HR. There is no separate Production agent (decided 2026-10-18); the roster is the six agents in `dev_docs/adr/ADR-001.md` §2.
- Supplier is currently a **data/procurement service plus a supplier-facing interface**, not an autonomous MRPII agent.
- Keep the frontend/API, agent logic, deterministic domain services, persistence, and communication adapters separated.

## 3. Decentralized Communication (Future Integration)
- **A2A (agent-to-agent):** targeted requests, responses, proposals, counteroffers, acceptances, rejections, and negotiations between relevant agents.
- **Publish–Subscribe (Pub/Sub):** announce business events/outcomes to agents that subscribed to those event types.
- Events say that something happened; agents decide what to do. Pub/Sub must not broadcast everything to every agent.
- Agents may communicate in an N:N network, but connections/subscriptions must follow responsibilities and need. Do not require Planning to relay every interaction or make it the universal coordinator.
- Keep private negotiation details between relevant participants; publish only the outcomes/details that subscribers need.
- Define message/event schemas and correlation/causation identifiers. Design handlers for retries, duplicate delivery, timeouts and recoverable failure. Do not choose a broker or A2A framework unless an approved decision settles it.
- Shared communication or negotiation infrastructure may manage delivery, sessions, protocol state and timeouts. It must not choose business outcomes or override an agent's constraints.

## 4. Domain Ownership and Boundaries
- Each agent owns its decisions, domain records, constraints and state. Shared database infrastructure is acceptable, but logical ownership and write permissions must remain clear.
- An agent must not directly edit another agent's internal tables or state. Use agreed interfaces/messages and identifiers.
- Planning owns production planning and material requirements; it does not choose suppliers for Purchasing or directly modify Inventory.
- Inventory owns stock availability, allocation and reservation constraints; it does not make supplier-selection decisions.
- Purchasing owns procurement decisions, supplier evaluation, quantity/delivery terms, its requisitions, supplier legs, contract references and audit records.
- Sales owns customer conversations and order interactions. It should request feasibility through agreed interfaces rather than bypassing domain agents.
- Planning owns its production planning records.
- HR owns workforce records.

## 5. Additional Decisions Reference 
`ADR-001.md` is the detailed reference for the architecture discussion, rationale, examples, Sales-specific notes, and pending decisions. Keep this file focused on operating rules; update the ADR when a decision is confirmed.
- **Negotiation priority queues:** proposed per-agent queues should consider urgency, production impact, customer-commitment risk, and waiting time. Prevent starvation and conflicting resource commitments. The exact scoring rules are not finalized.
- **Shared LLM runtime:** the current direction is one shared Ollama Qwen 3.5B runtime for the logical agents, rather than a separate model copy per agent. Measure load and latency before introducing a custom AI-inference queue.
- **Open decisions stay open:** do not assume a specific message broker, final event catalogue, A2A contract, priority algorithm, or recovery/consistency strategy until approved.

### For more details : `dev_docs/adr/ADR-001.md`

## 6. Purchasing Agent — Current Build Scope
Build Purchasing from scratch as an independently runnable and testable agent. Use test inputs/mocks for unfinished agents; do not claim real multi-agent integration until it exists.

### For more details: `dev_docs/agent_architectures/purchasing_agent_architecture`

## 7. Source of Truth and Project Docs
Before non-trivial work, inspect relevant files, especially:
- Follow `dev_docs/agents/issue-tracker.md`, `dev_docs/agents/triage-labels.md`, and `dev_docs/agents/domain.md` when present.
- `dev_docs/` system specification, scenarios, database/schema relations, and agent architecture docs if present.
- `dev_docs/adr/`, and root `GLOSSARY.md`.
- `.scratch/<feature>/` specs and issue-tracker notes where applicable.

Prefer the latest approved decision/spec and current repository evidence. A diagram or proposed spec is not proof of implementation. If code, docs, or specs conflict, report the conflict and ask or propose a resolution; do not silently invent one. Do not use web search for project-specific truth unless explicitly requested.

## 8. Implementation Workflow
- Continue from the current state and make small, reviewable changes. Explain significant decisions simply; avoid sweeping rewrites and unrelated files.
- Implement the approved spec, run relevant tests, report changed files/results and any unresolved issues, then stop for developer review.
- Do not commit, push, merge, or rewrite Git history unless explicitly asked for that exact operation.
- Update relevant docs after implementation. Do not build future architecture just because it appears in a diagram.