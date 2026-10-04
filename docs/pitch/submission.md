# HackYeah 2026 — project card texts (copy-paste)

## Project Name
Aegis — AI Control Layer

## Problem
AI agents no longer just answer questions. They read contracts, call tools, send e-mails, query databases, call
MCP servers and other agents, with real permissions and real data. That changes what "being hacked" means: a
compromised agent doesn't give a wrong answer, it leaks a client's contract or takes an irreversible action.

- **Prompt injection** is risk #1 (LLM01) in the OWASP Top 10 for LLM Applications. The instruction can hide
  anywhere the agent reads: a PDF's metadata, a hidden Word run, white 1-pt text, a spreadsheet's hidden sheet,
  speaker notes, image EXIF, a tool result.
- **Excessive agency** (LLM06): agents get broad keys "just in case", so one manipulated step can reach another
  client's files or an outside recipient.
- **Unbounded consumption** (LLM10): loops, recursive agents and parallel runs burn tokens with no ceiling.
- **Supply chain** (LLM03): swapped model weights or LoRA adapters, pickled payloads, typosquatted packages,
  poisoned MCP tool definitions.

Prompt firewalls only look at text. In a bank, the question that matters is different: was this agent ever
authorized to do this, with this data, for this task?

## Solution
Aegis is a gateway that sits between AI agents and everything they can touch: models, tools, files, MCP servers
and other agents. Every task gets a short-lived **mandate** (an HMAC-signed lease): which documents it may read,
which tools it may call, where results may go, how many tokens it may spend and for how long. The agent never
holds tool credentials; only the gateway does, so going around Aegis gets a 401.

Every call passes 10 checks, cheapest first, and the first BLOCK ends it:
rate limit → mandate → known attack signatures (13, external feed) → patterns (Polish PII with checksums: PESEL,
NIP, ID card, passport, IBAN, address; passwords written in sentences; API keys; prompt injection incl. Polish,
base64, leetspeak, zero-width, multi-turn) → data flow (confidential data can't reach outside sinks) → human
approval for risky tools → AI review (local model, can only tighten) → budget escrow (tokens reserved before the
call) → execution (code runs in a network-less sandbox) → output check (DLP before the agent sees it).
Decision in ~0.3 ms (p50); a full tool call in ~9 ms.

It also reads what humans don't see in files: PDF, DOCX, XLSX, PPTX, legacy DOC/XLS/PPT, images (EXIF, GPS, XMP)
and scans (OCR, Polish + English), and blocks active content (JavaScript, macros, DDE, remote templates). Model
and LoRA weights are pinned by sha256; MCP tool definitions are pinned and quarantined on change.

**Benefits:** agents can be given real work without a master key; security edits one YAML policy (hot reload in
under 1 s, broken files rejected, versions with one-click rollback); every decision is explained (rule, stage,
time) and written to an append-only audit; integration is a `base_url` swap (OpenAI-compatible), a Python SDK
or an MCP proxy; runs fully on-prem with the model on the team's GB10, so confidential prompts never leave.

## Idea stage
New Idea

## What's done so far and goal of your project
Built from scratch during HackYeah 2026. Working end to end:
- Gateway (FastAPI + PostgreSQL) with the 10-stage pipeline, ALLOW / REDACT / BLOCK decisions, explained findings
  and an append-only audit (JSONL/CSV export).
- Mandates and leases (HMAC, TTL, revocable), delegation to other agents (subset of the mandate, depth ≤ 3,
  confidentiality inherited), human approvals, rate limits + circuit breaker, atomic budget escrow.
- Document analysis for 10+ formats with hidden-content detection and OCR; sandbox for code; MCP proxy with
  tool hash pinning; model/LoRA hash pinning; supply-chain signatures (pickle, CVE, typosquat).
- One policy file (strict / balanced / permissive profiles), hot reload, versions, rollback.
- Dashboard: guided "Start here" in 3 steps, 10 live attack scenarios with the pipeline replayed step by step,
  "Be the agent" console, content and file checker, approvals, budgets, audit, configuration.
- Python SDK 0.3.0, landing page, 60 s promo film, 10-slide technical deck.
- 250 automated tests (positive and negative for every control), 82 YAML content cases, 10 end-to-end scenarios.
  Proofs: poisoned contract → 0 e-mails reached the mail service; 30 agents racing for one budget → 0 tokens over.

Goal: a control layer a bank could put in front of its agents tomorrow — deterministic rules decide permissions,
AI only adds a second line of defence.

## Team status
Full team

## Current team size
5

## Needed skills
(none — team is full; untick "Software Development")

## Skills comment
We are a complete team and not recruiting.

## Your video presentation
Upload `docs/pitch/aegis-film.mp4` to YouTube as **Unlisted** and paste the link here.

## Website
https://aegis.alfaguys.com

## Code Repository
https://github.com/Alfiarze/hackyeah-2026-goldman

## Instructions on how to open project
**Live:** landing https://aegis.alfaguys.com · dashboard https://dashboardaegis.alfaguys.com (admin key in the
top bar — we hand it to the jury) · API https://gatewayaegis.alfaguys.com (`/health`, `/docs`).

**Locally** (needs Docker):
```
git clone https://github.com/Alfiarze/hackyeah-2026-goldman && cd hackyeah-2026-goldman
make run                      # Postgres + gateway + tool backends + sandbox
open http://localhost:8000/dashboard/     # admin key: dev-admin-key
make test-docker              # full test suite (250 tests)
make demo                     # run every attack scenario against the running stack
```
In the dashboard start with **"Start here"** (3 steps, ~3 minutes), then **Scenarios** → "Poisoned contract".
Model: set `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` in `.env` (any OpenAI-compatible server, e.g. vLLM on
GB10); without it the AI review uses a local heuristic and the console a mock model — every control still works.
Agent integration: point an OpenAI client at `http://localhost:8000/v1`, or `pip install ./sdk`.

## Team name
Aegis

## Presentation
Upload `docs/pitch/aegis.pdf` (10 slides, 2.6 MB).

## Table number
(fill in on site)
