# 3 · Reporting

The security dashboard is served by the gateway at `/dashboard/`
(live: <https://dashboardaegis.alfaguys.com>, locally: <http://localhost:8000/dashboard/>, admin key `hackyeah`).

## Screenshots

| | |
|---|---|
| **Start here → Live test** — a chat with the guard layer underneath; every message checked live ![](screenshots/10-live-chat.png) | **Live** — every decision as it happens, what reached the tools, spend ![](screenshots/02-live-monitor.png) |
| **Run a scenario** — scripted attacks replayed stage by stage ![](screenshots/03-scenario-poisoned-contract.png) | **Audit log** — append-only, filter, export JSONL/CSV ![](screenshots/04-audit-log.png) |
| **Controls** — switch controls, redact vs block, strictness ![](screenshots/05-controls.png) | **Policy file** — edit, validate, versions, rollback ![](screenshots/06-policy-versions.png) |
| **Budget** — escrow explained, 30-agent race ![](screenshots/07-budget-race.png) | **Test an input / file** — verdict and where in the file ![](screenshots/08-document-check.png) |
| **Tasks** — mandates, classification read so far, calls used ![](screenshots/09-tasks.png) | **Guided tour** — three steps from zero to a blocked attack ![](screenshots/01-start-here.png) |

## Metrics

Every decision is stored with its rule id, stage, per-stage timings, channel, task, principal and policy version
(never raw content). Exposed by the admin API and shown in the dashboard:

| Metric | Where | Endpoint |
|---|---|---|
| Decisions by outcome (ALLOW / REDACT / BLOCK), total and over time (per minute) | Live, Start | `GET /admin/stats` → `totals`, `timeline` |
| Decisions by channel (chat, tool, MCP, model registry, playground) | Live | `stats.by_channel` |
| Top firing rules (e.g. `MANDATE-RCPT`, `PII-001`, `IFC-001`) | Live | `stats.top_rules` |
| Decision latency p50 / p95 / p99 | Live | `GET /admin/metrics` → `latency_ms` |
| Latency per pipeline stage (mandate, signatures, patterns, data flow, AI review, budget, execute, output) | Live | `metrics.stages` |
| Tokens spent / reserved, estimated cost (USD), uncertain reservations | Budget, Live | `stats.budget` |
| Budget per scope (task, user, global, guard) and open reservations | Budget | `GET /admin/budgets`, `/admin/reservations` |
| Active tasks, their mandates and classification | Tasks | `GET /admin/tasks` |
| Calls that actually reached each tool backend (proof a blocked call never arrived) | Live | `stats.backend` |
| Pending / decided human approvals | Approvals | `GET /admin/approvals` |
| Rate-limit and circuit-breaker trips | Audit, Live | `RATE-001`, `CIRCUIT-001` in audit |
| Policy version, profile, disabled controls, feed version and signature count | sidebar, Live | `stats.policy`, `stats.feed` |
| Model server, location (on-prem / cloud), AI-review backend | sidebar | `stats.llm`, `stats.semantic`, `GET /health` |
| MCP tool status (approved / quarantined, pinned hash) | Tools | `GET /admin/tools` |
| Full audit trail, filterable by task, rule, action, kind, time | Audit | `GET /admin/audit`, `GET /admin/audit/export?format=jsonl|csv` |
| Live event stream | Live | `GET /admin/events` (SSE) |

The audit table is append-only: the database refuses `UPDATE` and `DELETE` on it.
