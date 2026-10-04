---
marp: true
theme: default
paginate: true
size: 16:9
title: MANDATE — AI Control Layer
description: Zero-trust execution contracts for AI agents · HackYeah 2026 · Goldman Sachs challenge
style: |
  :root {
    --ink: #0f1720;
    --muted: #5b6673;
    --accent: #1f6feb;
    --block: #c62828;
    --redact: #b26a00;
    --allow: #2e7d32;
    --bg-soft: #f3f6fa;
  }
  section {
    font-family: "Inter", "Helvetica Neue", Arial, sans-serif;
    color: var(--ink);
    font-size: 26px;
    padding: 56px 72px;
  }
  h1 { color: var(--ink); font-size: 52px; letter-spacing: -0.5px; }
  h2 { color: var(--accent); font-size: 36px; margin-bottom: 0.4em; }
  strong { color: var(--ink); }
  code { background: var(--bg-soft); border-radius: 4px; padding: 0 6px; }
  pre { background: var(--bg-soft); color: var(--ink); border: 1px solid #d8dee6; border-radius: 8px; font-size: 18px; line-height: 1.35; }
  pre code { background: transparent; color: inherit; }
  table { font-size: 21px; border-collapse: collapse; }
  th { background: var(--bg-soft); }
  blockquote { border-left: 6px solid var(--accent); color: var(--muted); font-style: normal; }
  .block { color: var(--block); font-weight: 700; }
  .redact { color: var(--redact); font-weight: 700; }
  .allow { color: var(--allow); font-weight: 700; }
  .muted { color: var(--muted); }
  .cols { display: grid; grid-template-columns: 1fr 1fr; gap: 40px; }
  .cols3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 28px; }
  .card { background: var(--bg-soft); border-radius: 10px; padding: 18px 22px; font-size: 22px; }
  .big { font-size: 64px; font-weight: 800; color: var(--accent); line-height: 1; }
  .todo { background: #fff3cd; color: #7a5a00; padding: 0 6px; border-radius: 4px; }
  section.lead { justify-content: center; }
  section.lead h1 { font-size: 72px; }
  section.dark { background: #0f1720; color: #e6edf3; }
  section.dark h1, section.dark h2, section.dark strong { color: #fff; }
  section.dark .card { background: #16212e; color: #e6edf3; }
  section.dark code { background: #22303f; color: #e6edf3; }
  footer { color: var(--muted); font-size: 16px; }
footer: "MANDATE · HackYeah 2026 · Goldman Sachs — AI Control Layer"
---

<!-- _class: lead -->
<!-- _paginate: false -->
<!-- _footer: "" -->

# MANDATE

## Zero-trust execution contracts for AI agents

> Other guardrails ask: *"does this action look dangerous?"*
> MANDATE asks: **"was this agent ever authorised to do this, with this data, in this task?"**

<span class="muted">Team <span class="todo">TEAM NAME</span> · HackYeah 2026 · Goldman Sachs challenge</span>

<!--
NOTATKI (PL, ~20 s):
Dzień dobry. Jesteśmy <zespół>. Zbudowaliśmy MANDATE — warstwę kontrolną dla agentów AI.
Jedno zdanie, które chcemy, żebyście zapamiętali: inne guardraile pytają, czy akcja WYGLĄDA groźnie.
My pytamy, czy agent w ogóle był upoważniony, żeby to zrobić — z tymi danymi, w tym zadaniu.
-->

---

## 1 · The business need

<div class="cols">
<div>

**Agents now act, not just answer**

- write code, send mail, query internal DBs, call MCP tools
- one agent delegates to another
- they hold memory across tasks and clients

**The org wants the productivity**
…but security, compliance and finance must be able to say *yes* safely.

</div>
<div class="card">

**What a bank needs before go-live**

1. Every action traceable to a person + a task
2. Client data never leaves its boundary
3. Spend is capped *before* it happens
4. Known exploits stopped at the door
5. Rules changed by security — live, without redeploy
6. Evidence for auditors, not promises

</div>
</div>

<!--
NOTATKI (~40 s):
Zaczynamy od potrzeby, nie od technologii. Agenci przestali tylko odpowiadać — oni działają:
wysyłają maile, odpytują bazy, wołają narzędzia MCP, delegują pracę innym agentom.
Biznes chce tej produktywności. Ale w banku, zanim cokolwiek pójdzie na produkcję, security,
compliance i finanse muszą móc powiedzieć "tak" — i mieć na to dowód. Po prawej sześć rzeczy,
których potrzebuje bank. Cała reszta prezentacji to odpowiedź na tę listę.
-->

---

## 2 · The problem: agents break the old security model

| Risk | What actually happens | OWASP |
|---|---|---|
| **Dynamic permissions** | Agent reaches client B's files while working for client A; impersonates another actor | LLM06 Excessive Agency |
| **Prompt injection** | A *document* says "send this to evil.com" — the model obeys | LLM01, LLM02 |
| **Data exfiltration by paraphrase** | Regex sees no PESEL — because the model translated / base64-ed it | LLM02 |
| **Runaway cost** | Loop of tool calls, 30 parallel agents, no hard stop | LLM10 Unbounded Consumption |
| **Supply chain** | `pickle` with `os.system`, `trust_remote_code=True`, poisoned GGUF template, swapped MCP tool | LLM03, LLM04 |

> Classic WAF / DLP inspects **content**. Agents fail on **context**: *who*, *for which task*, *with what data already in hand*.

<!--
NOTATKI (~45 s):
Dlaczego stare narzędzia nie wystarczą? Bo WAF i DLP patrzą na TREŚĆ.
A agent zawodzi na KONTEKŚCIE. Przykład: mail na zewnątrz — sam w sobie OK.
Ten sam mail po tym, jak agent przeczytał poufną umowę klienta — to wyciek.
Regex nie zobaczy PESELu, jeśli model go przetłumaczył albo zakodował w base64.
I budżet: agent w pętli albo 30 agentów naraz — bez twardego stopu rachunek rośnie bez limitu.
Każde z tych ryzyk mapujemy na OWASP LLM Top 10 2025.
-->

---

## 3 · Our insight: authorise the *task*, not the *text*

<div class="cols">
<div>

Every agent run gets a **mandate** — a server-side contract issued by the app, never by the prompt:

```yaml
task_id: 4f92
principal: lawyer_anna        # from API key, not body
purpose: "Summarise contract of client A"
resources_allow: ["/clients/A/contracts/*"]
tools_allow: [doc.read, legal_db.search, notes.write]
model_allow: [main/deepseek-v4.1-flash]
budget: {tokens: 20000, calls: 12, concurrency: 3}
expires_at: +15 min
classification: PUBLIC   # only goes UP (taint)
```

</div>
<div>

**Four ideas that make it hold**

1. **Mandate / lease** — HMAC-bound task + principal; no impersonation
2. **Taint / data lineage** — reading a CONFIDENTIAL doc raises the task's level; sinks below it are closed — even after paraphrase
3. **Proof of enforcement** — gateway holds tool credentials; backend counter shows `0` calls after BLOCK
4. **Budget escrow** — atomic reserve → execute → settle in Postgres; overspend impossible by construction

</div>
</div>

<!--
NOTATKI (~50 s):
Nasz pomysł: autoryzujemy ZADANIE, nie tekst.
Każde uruchomienie agenta dostaje mandat — kontrakt po stronie serwera. Tworzy go aplikacja,
nie użytkownik w prompcie. Mówi: kto, po co, do jakich zasobów, jakimi narzędziami, jakim modelem,
za ile i na jak długo.
Cztery mechanizmy: lease z HMAC — nie da się podszyć. Taint — po przeczytaniu poufnego dokumentu
całe zadanie staje się poufne i kanały o niższym clearance są zamknięte, niezależnie od tego,
jak model przeformułuje treść. Proof of enforcement — agent nie ma kluczy do narzędzi, ma je tylko
gateway, więc pokazujemy licznik: zero wywołań. Budget escrow — rezerwujemy budżet atomowo
przed wywołaniem modelu.
-->

---

## 4 · Architecture — one gateway, every channel

```
  App ──► POST /v1/tasks  (mandate + lease)                      app ↔ agent
  Agent ─► /v1/chat/completions  (OpenAI-compatible)             agent ↔ model
  Agent ─► /mcp  (MCP streamable HTTP proxy)                     agent ↔ MCP
  Agent ─► /v1/tasks/{id}/delegate  (narrower child mandate)     agent ↔ agent
                         │
        ┌────────────────▼──────────────── PIPELINE (cheap → expensive, first BLOCK wins) ─┐
        │ 0 policy snapshot  1 mandate/lease  2 allowlist  3 attack signatures            │
        │ 4 PII + secrets    5 taint / IFC    6 semantic (LLM on 2× GB10, only TIGHTENS)     │
        │ 7 budget escrow ── execute ── POST: re-scan model output + tool results         │
        └────────────────┬─────────────────────────────────────────────────────────────────┘
          DeepSeek V4.1 Flash on our two GB10s · tool backends (secret only gateway knows) · Postgres audit
                         ▼
          Dashboard · /metrics p50/p95 · audit export JSONL/CSV
```

**Hybrid by design:** deterministic controls decide fast; the local LLM only *adds* suspicion. **Fail-closed** on timeout. Stateless gateway → scale horizontally, state in Postgres.

<!--
NOTATKI (~45 s):
Architektura. Jeden gateway, przez który przechodzą wszystkie cztery kanały z zadania:
app–agent, agent–model, agent–MCP i agent–agent.
Pipeline idzie od taniego do drogiego: najpierw mandat, allowlista, sygnatury, PII, sekrety, taint —
to wszystko deterministyczne, milisekundy. Dopiero na końcu lokalny model przez Ollamę.
Kluczowa zasada: semantyka może decyzję tylko ZAOSTRZYĆ, nigdy odblokować.
Timeout guarda = blokada. Po wykonaniu skanujemy też wyjście — odpowiedź modelu i wynik narzędzia,
bo tam siedzi pośredni prompt injection.
-->

---

## 5 · One policy file, changed live

<div class="cols">
<div>

```yaml
profile: balanced    # strict | balanced | permissive
models:
  allow: ["main/*"]   # model server from .env: our two GB10s (DeepSeek V4.1 Flash)
controls:
  pii:     {enabled: true, mode: redact}
  secrets: {enabled: true, mode: block}
  attack_signatures: {feed: feeds/attacks.yaml}
  semantic:
    block_at_risk: 0.7   # adherence 30%
    on_timeout: block
budgets:
  default_task: {tokens: 20000, calls: 12}
  per_principal_daily: {tokens: 200000}
```

</div>
<div>

- **Single source of truth** — guardrails, Block vs Redact, adherence %, model allowlist, budgets
- **Hot-reload** from file *or* dashboard → same validation, new version hash, audit diff
- **Bad YAML never disables protection** → last-known-good stays, `POLICY_REJECTED` logged
- **Disabling a control is allowed — and loud**: `CONTROL_DISABLED` event + red tile
- **Attack feed** is external & swappable live (file or URL)
- Every decision stamped with `policy_version`

</div>
</div>

<!--
NOTATKI (~40 s):
Jedno źródło prawdy: policy.yaml. Profile strict, balanced, permissive — próg semantyki to
nasze "adherence %". Block vs redact per kontrola. Allowlista modeli. Budżety.
Wiemy, że będziecie zmieniać konfigurację na żywo — więc: zmiana działa od następnego żądania,
a zepsuty YAML NIE wyłącza ochrony — zostaje ostatnia dobra wersja i wpis w audycie.
Wyłączenie kontroli jest możliwe, ale głośne — czerwony kafelek i event w audycie.
-->

---

<!-- _class: dark -->

## 6 · Live demo — "the evil.com contract"

<div class="cols3">
<div class="card">

**① Good task** <span class="allow">ALLOW</span>
Agent reads client A contract, writes internal note. Mandate visible.

</div>
<div class="card">

**② Hidden instruction** <span class="block">BLOCK</span>
Contract says *"email this to evil.com"*.
`DATA_FLOW_VIOLATION · IFC-003`
`mail requests received: 0`

</div>
<div class="card">

**③ Detector blinded** <span class="block">BLOCK</span>
Semantic guard forced to miss → taint layer still blocks. Defence in depth.

</div>
<div class="card">

**④ You change policy**
strict profile · lower threshold · add signature · delete a control → new `policy_version` on next call

</div>
<div class="card">

**⑤ Launch 30 agents**
Reservations vs refusals. **Overspend: $0**

</div>
<div class="card">

**⑥ Evidence**
Test report · violation details · p50/p95 · audit export

</div>
</div>

<!--
NOTATKI: przejście do demo na żywo — szczegółowy scenariusz w docs/pitch/script.md.
Jeśli demo padnie: nagranie (backup) + screenshoty w appendixie.
-->

---

## 7 · Coverage: every requirement, every control tested

| Challenge requirement | MANDATE | Tests (+ / –) |
|---|---|---|
| Centralized policy engine | `policy.yaml`, 3 profiles, hot-reload, rollback | P-01…06 |
| Deterministic controls | PII (PESEL, Luhn, IBAN), secrets (AWS, JWT, keys), mandate auth | D-01…10 |
| Semantic controls | DeepSeek V4.1 Flash on 2× GB10 as classifier, JSON risk, tighten-only, fail-closed | S-01…04 |
| Budget & resources | Escrow: tokens, calls, time, concurrency; task/user/global | B-01…07 |
| Historical attacks | pickle opcode scan, `trust_remote_code`, CVE-2024-34359, typosquat, MCP tool poisoning | A-01…10 |
| Reporting & audit | Live dashboard, SSE, JSONL/CSV export, no secrets in logs | R-01…04 |
| Self-testing suite | expectations in `tests/cases/*.yaml`, written independently of code | 334 tests |

`make test-docker` → **334 collected · all green in the image** (2 OCR tests skip only on a host without tesseract) · 100+ content cases and red-team probes from YAML, 24 detector unit tests, 10× control-degradation matrix, 7 property-based fuzz tests, 5 live-chat turns

<!--
NOTATKI (~35 s):
Każdy z sześciu wymogów zadania ma moduł i parę testów: pozytywny i negatywny.
Oczekiwane wyniki są spisane w YAML-u niezależnie od implementacji — test nie sprawdza
sam siebie. Liczby pochodzą z ostatniego pełnego przebiegu make test-docker (323 zebrane,
wszystkie zielone w obrazie). Możecie to odpalić jednym poleceniem.
-->

---

## 8 · Proof, not promises

<div class="cols3">
<div class="card">

<div class="big">0</div>

backend calls after BLOCK
<span class="muted">tool counter, not log line</span>

</div>
<div class="card">

<div class="big">$0</div>

overspend with 30 parallel agents
<span class="muted">also with `--workers 4`</span>

</div>
<div class="card">

<div class="big">≈ 1.3 ms</div>

p95 deterministic guard
<span class="muted">p99 3.5 ms · `make bench` → docs/bench-report.md (p50/p95/p99 per stage, throughput) · semantic (DeepSeek V4.1 Flash on 2× GB10): ~1.5–2.5 s per review, runs only on untrusted content</span>

</div>
</div>

**Security team gets:** per-decision `rule_id`, `reason_code`, `stage`, `policy_version`, `latency_ms`, `tool_invoked` — exportable.
**Management gets:** allowed / redacted / blocked live, budget spent vs reserved, cost of protection itself (`guard_budget`).

<!--
NOTATKI (~35 s):
Trzy liczby. Zero — tyle wywołań backendu po blokadzie. To licznik po stronie narzędzia,
nie wpis w logu, który mógłby kłamać. Zero dolarów — overspend przy 30 równoległych agentach,
także na czterech workerach, bo atomowość jest w Postgresie.
I p95 1.3 ms — mierzone (make bench, raport w docs/bench-report.md, pełna metodologia i sprzęt w raporcie).
Security dostaje pełny ślad decyzji, management — kafelki i koszty, łącznie z kosztem samej ochrony.
-->

---

## 9 · Ready to adopt

<div class="cols">
<div>

**Drop-in for developers**
- OpenAI-compatible endpoint → change `base_url`
- MCP proxy → point the agent at `/mcp`
- Python SDK: `pip install ./sdk` → `task.chat()`, `task.call()` — sync + async
- `cp .env.example .env && make run` — Docker Compose, Postgres; model server = our two GB10s (OpenAI-compatible)

**Scales out**
- Stateless gateway, state in Postgres
- Policy change → `NOTIFY` → every instance reloads
- 100% local, open source stack, no paid APIs

</div>
<div>

**Honest limits → roadmap**
- Taint is conservative → some false positives (by design)
- Streaming is buffered before release
- Next: *Research Airlock* (low-clearance lookups in sibling task), Redis for very high RPS, SIEM export, signed policy bundles

</div>
</div>

<!--
NOTATKI (~35 s):
Wdrożenie: deweloper zmienia base_url albo wskazuje agenta na /mcp — i jest pod kontrolą.
Jedna komenda make run. Gateway bezstanowy, więc skaluje się poziomo.
Uczciwie o granicach: taint jest konserwatywny — wolimy fałszywy alarm niż wyciek.
Streaming buforujemy przed wydaniem. Roadmapa: Research Airlock, Redis, eksport do SIEM.
-->

---

<!-- _class: lead -->

# Agents get a mandate. Not a master key.

**MANDATE** — authorise the task, track the data, cap the spend, prove the block.

- Repo: github.com/Alfiarze/hackyeah-2026-goldman
- Demo video: <span class="todo">link</span>
- Team: <span class="todo">names · roles</span>

<span class="muted">Try to break it: change `policy/policy.yaml`, type any prompt in the Playground, run `make test`.</span>

<!--
NOTATKI (~20 s):
Podsumowanie jednym zdaniem: agent dostaje mandat, nie klucz-wytrych.
Zapraszamy: spróbujcie to złamać — zmieńcie politykę, wpiszcie własny prompt w Playground,
odpalcie testy. Dziękujemy, czekamy na pytania.
-->

---

<!-- _class: lead -->
<!-- _paginate: false -->

# Appendix

<span class="muted">Not part of the 10-slide PDF. Backup for Q&A.</span>

---

## A1 · OWASP mapping

| Control | OWASP LLM Top 10 (2025) | OWASP Agentic threats |
|---|---|---|
| Mandate / lease, delegation ⊆ parent | LLM06 Excessive Agency | Privilege compromise, identity spoofing |
| Taint / IFC, output filter | LLM02 Sensitive Info Disclosure | Data exfiltration via tools |
| Injection heuristics + semantic | LLM01 Prompt Injection | Intent breaking, goal manipulation |
| Attack signatures, model registry | LLM03 Supply Chain, LLM04 Poisoning | Tool misuse |
| MCP tool hash / quarantine | LLM03 | Tool poisoning |
| Budget escrow | LLM10 Unbounded Consumption | Resource overload |
| Memory under mandate | LLM08 Vector & Embedding Weakn. | Memory poisoning |
| Audit + policy versions | — | Repudiation / untraceability |

<span class="todo">Verify Agentic threat names against the OWASP doc before submit.</span>

---

## A2 · Q&A cheat sheet

| Likely question | Short answer |
|---|---|
| "What if the LLM guard says ALLOW to an attack?" | It can't widen. Deterministic + taint still decide. Demo ③. |
| "What if the guard is slow / down?" | `on_timeout: block` — fail-closed, audited. |
| "Can the agent call the tool directly?" | No — backend needs a secret only the gateway holds. Bypass test. |
| "Base64 / translation to bypass DLP?" | Taint is on the task, not the text. Paraphrase doesn't lower it. |
| "Two agents racing for budget?" | Single Postgres transaction, conditional `UPDATE`. Tested 30× parallel, 4 workers. |
| "I broke the YAML." | Last-known-good kept, `POLICY_REJECTED` in audit. |
| "Latency cost?" | Deterministic stages first, short-circuit, semantic only on untrusted content + cache. |
| "Why not NeMo Guardrails / Llama Guard?" | They classify content. We add *authorisation + lineage + budget*. Could plug one in as stage 6. |

---

## A3 · Screenshots (backup if live demo fails)

<span class="todo">Dashboard overview</span> · <span class="todo">Task detail with taint timeline</span> · <span class="todo">Policy diff + version</span> · <span class="todo">30 agents budget chart</span>

<!-- Wstaw: ![w:520](img/dashboard.png) itd. po zrobieniu zrzutów -->
