# 5 · Implementation

The code stays where the build expects it (moving it would break the Docker images and imports); this page maps it.

## Code

| Path | What |
|---|---|
| [`aegis/app.py`](../aegis/app.py) | FastAPI app: task API, `/v1/chat/completions`, `/v1/tools/{tool}/call`, `/mcp`, `/v1/models/register`, `/health` |
| [`aegis/engine.py`](../aegis/engine.py) | the pipeline: rate limit → mandate → signatures → patterns → data flow → approval → AI review → budget → execute → output |
| [`aegis/tasks.py`](../aegis/tasks.py) | tasks, HMAC leases, mandates, delegation (subset, depth limit) |
| [`aegis/policy.py`](../aegis/policy.py) | strict policy schema (pydantic, unknown keys rejected), hot reload, versions, rollback |
| [`aegis/detectors.py`](../aegis/detectors.py) | PII with checksums, secrets, passwords in sentences, injection patterns, de-obfuscation |
| [`aegis/documents.py`](../aegis/documents.py) | PDF / OOXML / OLE2 / image analysis, hidden parts, active content, OCR |
| [`aegis/attacks.py`](../aegis/attacks.py) | signature feed: regex, pickle scan, components (CVEs), model sources, tool hashes |
| [`aegis/semantic.py`](../aegis/semantic.py) | AI review (OpenAI-compatible model or heuristic), single-flight, fail-closed |
| [`aegis/budget.py`](../aegis/budget.py) | atomic escrow in Postgres (reserve → settle), rate counters |
| [`aegis/sandbox.py`](../aegis/sandbox.py) | sandbox runner: locked-down `docker run` per `code.run` |
| [`aegis/audit.py`](../aegis/audit.py), [`aegis/admin.py`](../aegis/admin.py) | append-only audit, stats/metrics, admin API used by the dashboard |
| [`aegis/backends.py`](../aegis/backends.py) | mock tool backends + MCP server with call counters (the proof a blocked call never arrived) |
| [`aegis/scenarios.py`](../aegis/scenarios.py), [`aegis/bench.py`](../aegis/bench.py) | end-to-end attack scenarios, performance benchmark |
| [`policy/policy.yaml`](../policy/policy.yaml), [`feeds/attacks.yaml`](../feeds/attacks.yaml) | the policy and the attack feed |
| [`db/init/`](../db/init/) | schema (applied idempotently at start), seed document catalog |
| [`dashboard/`](../dashboard/) | React + Vite security console (served at `/dashboard/`) |
| [`landing/`](../landing/) | Astro landing page + API docs page (`/docs/`) |
| [`sdk/`](../sdk/) | Python SDK (sync + async, typed exceptions, admin client) |
| [`.claude/skills/aegis-gateway/`](../.claude/skills/aegis-gateway/) | Claude Code skill + stdlib probe to test the API from any agent |
| [`tests/`](../tests/) | 334 tests, YAML content and red-team cases |

Stack: Python 3.12, FastAPI, asyncpg / PostgreSQL 17, pypdf, olefile, Pillow, tesseract; React 18 + Vite; Astro;
Docker Compose. No paid APIs: the model is any OpenAI-compatible server (vLLM on two GB10s in production).

## Deploying into an existing agentic ecosystem

Aegis is a network hop, not a library the agent must adopt. Three ways in, none requires rewriting the agent:

**1. OpenAI-compatible (one line).** Point the agent's OpenAI client at Aegis; the agent key is the API key, the
lease is a header. Works for anything built on the OpenAI SDK, LangChain, LlamaIndex, AutoGen, CrewAI, etc.

```python
client = OpenAI(base_url="https://gatewayaegis.alfaguys.com/v1", api_key=AGENT_KEY,
                default_headers={"X-Mandate-Lease": lease})
```

**2. MCP proxy.** Register Aegis as the agent's MCP server (`POST /mcp`, JSON-RPC). `tools/list` returns only tools on
the mandate; `tools/call` goes through the pipeline; real MCP servers sit behind the gateway with its secret.

**3. Python SDK / REST.** `pip install ./sdk` — `task.call(...)`, `task.chat(...)`, typed `Blocked`,
`ApprovalRequired`, `RateLimited`; or plain HTTP ([API docs](https://aegis.alfaguys.com/docs/)).

**The one integration step on the app side:** when the app starts an agent job, it creates a task
(`POST /v1/tasks` with the app key and a task profile) and hands the returned lease to the agent. Existing tools are
moved behind the gateway by giving them the gateway's backend secret, so a direct call from an agent fails.

## Deployment

| Where | How |
|---|---|
| Laptop / single server | `make run` (Docker Compose: Postgres, gateway, tool backends, sandbox runner) → `http://localhost:8000/dashboard/` |
| Cloud / PaaS | Coolify with [`docker-compose.coolify.yml`](../docker-compose.coolify.yml): generated secrets, no published host ports, domains per service ([README](../README.md#deploying-on-coolify)) |
| On-prem with the model | the same stack next to vLLM on two NVIDIA GB10s (DGX Spark, tensor parallel 2, 200 Gb/s link); set `LLM_BASE_URL`, `LLM_MODEL`, `LLM_LOCATION=onprem` |

Configuration is environment variables (`.env.example`) plus `policy/policy.yaml`. Default demo admin key:
`hackyeah` (set `ADMIN_API_KEY` to change it — do so before exposing the dashboard beyond a trusted network).

## Scalability and operations

- **Stateless gateway**: all state (tasks, leases, budgets, approvals, audit) is in PostgreSQL, so gateway replicas
  can be added behind a load balancer. Budget escrow uses atomic row updates, so replicas can't overspend together.
- **Throughput**: 195 req/s on one 4-vCPU container with the full pipeline; per-decision cost is dominated by the
  Postgres escrow (~3 ms), the checks themselves are sub-millisecond.
- **Fixed, countable cost**: no per-call third-party API; every token is reserved and logged per task, user, global.
- **Fail-closed** everywhere (model, tools, sandbox, AI review errors); policy errors keep the last good version.
- **Policy as code**: one YAML in git, hot-reloaded, versioned in the DB with rollback; signature feed can be a URL.

## Further considerations

- Production hardening: rotate all keys (`.env.example` values are demo defaults), put the dashboard behind SSO,
  run the sandbox runner on a separate host, enable `require_pinned` for model artifacts.
- What the AI review adds: generalisation to phrasings no rule anticipated; it is optional and can only tighten.
- Known limits: OCR quality depends on the scan; the heuristic AI-review fallback is weaker than a real model;
  classification of documents comes from the catalog (`db/init/002_seed.sql`), not inferred from content.
- More: [`README.md`](../README.md), [`FAQ.md`](../FAQ.md), [`docs/benchmarks.md`](../docs/benchmarks.md),
  [`docs/competitive-landscape.md`](../docs/competitive-landscape.md), deck [`docs/pitch/aegis.pdf`](../docs/pitch/aegis.pdf).
