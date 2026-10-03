# MANDATE — AI Control Layer: plan implementacji

> HackYeah 2026 · Goldman Sachs · start 3.10 11:00 · **zgłoszenie 4.10 11:00** (regulamin mówi 23:00 — planujemy pod wcześniejszy termin, potwierdzić z mentorem)
> Pozycjonowanie: *"Inne guardraile pytają, czy akcja wygląda niebezpiecznie. MANDATE pyta, czy ten agent był kiedykolwiek upoważniony, by zrobić to z tymi danymi, w tym zadaniu."*

---

## 0. Decyzje (zamknięte)

| Temat | Decyzja |
|---|---|
| Forma | Gateway/proxy (FastAPI) między agentem a modelem (Ollama) i narzędziami (MCP/HTTP) |
| Język | Python 3.11+, FastAPI, Pydantic v2, pytest (+ hypothesis), httpx |
| Model lokalny | Ollama, mały model (np. `qwen2.5:3b` / `llama3.2:3b`) do kontroli semantycznej i agenta demo |
| Polityka | Jeden plik `policy/policy.yaml`, hot-reload, wersjonowanie (hash), last-known-good |
| Stan/audyt | **PostgreSQL 17** (zadania, mandaty, budżety, rezerwacje, wersje polityki, audyt w `JSONB`) przez SQLAlchemy 2 async + asyncpg; eksport audytu do JSONL/CSV |
| Uruchomienie | **Docker Compose**: `db` (Postgres) + `gateway` (Dockerfile); Ollama domyślnie na hoście (macOS Metal), opcjonalnie kontener (`--profile ollama`). `make run` = jedna komenda |
| Dashboard | Statyczny HTML + HTMX/Alpine lub lekki React, serwowany przez gateway |
| Zakaz | Brak płatnych API, brak zewnętrznych datasetów/hardware. Wszystko lokalnie |
| Język materiałów | Angielski (kod, README, PDF); wewnętrznie PL |

### Zasady nienegocjowalne (design invariants)
1. **Semantyka nie rozszerza uprawnień.** Model AI może tylko zaostrzyć decyzję (ALLOW→REDACT/BLOCK), nigdy odblokować ani zwiększyć budżetu.
2. **Fail-closed.** Timeout / błąd guarda / błąd polityki ⇒ BLOCK (dla operacji wymagających oceny).
3. **Kontrola przed wykonaniem**, nie obok. Gateway trzyma poświadczenia do narzędzi; agent ich nie widzi.
4. **Zła konfiguracja nie wyłącza ochrony.** Niepoprawny YAML ⇒ zostaje ostatnia poprawna wersja + wpis w audycie.
5. **Każda decyzja ma:** `decision`, `reason_code`, `rule_id`, `policy_version`, `latency_ms`, `tool_invoked: bool`.
6. **Logi bez sekretów:** rule id + klasa danych + resource id, nie surowa treść.

---

## 1. Pokrycie wymagań zadania (checklista obowiązkowa)

| Wymóg zadania | Realizacja | Moduł | Testy |
|---|---|---|---|
| 1. Centralized Policy Engine (guardrails, Block vs Redact / adherence %, allowlista modeli, budżety) | `policy.yaml` + loader + hot-reload; profile surowości `strict/balanced/permissive` | `policy/` | P-01…P-06 |
| 2a. Deterministyczne: PII, sekrety, auth | Regex + walidatory (PESEL, Luhn, IBAN), detektor sekretów (AWS, JWT, klucze API, private key), mandate/lease auth | `controls/pii.py`, `secrets.py`, `mandate.py` | D-01…D-10 |
| 2b. Semantyczne (AI) | Klasyfikator prompt-injection/exfiltracji przez Ollama, wyjście JSON `{risk, label}`, tylko zaostrza | `controls/semantic.py` | S-01…S-04 |
| 3. Budżet i zasoby | Escrow: atomowa rezerwacja tokenów/wywołań/czasu/współbieżności per task i per user | `budget/` | B-01…B-07 |
| 4. Historical Attack Mitigation (malicious code exec, unsafe deserialization, supply chain na repo modeli) | Feed sygnatur `feeds/attacks.yaml` (zewnętrzny, podmienialny live): pickle/`__reduce__`, `trust_remote_code`, `eval/exec/os.system`, CVE-2024-34359 (template injection w GGUF), podejrzane źródła modeli (typosquat, nie-allowlistowane hosty), MCP tool poisoning | `controls/attacks.py` | A-01…A-10 |
| 5. Reporting & Auditing (real-time + eksport) | Dashboard + `/api/audit/export` (JSONL/CSV) + p50/p95 | `audit/`, `dashboard/` | R-01…R-04 |
| 6. Self-testing suite (pozytywne + negatywne dla każdej kontroli) | pytest, ~45 przypadków, oczekiwania spisane niezależnie w `tests/cases/*.yaml` | `tests/` | — |
| Deliverable 1: komunikacja **agent↔agent, app↔agent, agent↔MCP, agent↔model** | agent↔model: OpenAI-compatible proxy; agent↔MCP: **prawdziwy transport MCP** (proxy na `mcp` SDK, streamable HTTP) + REST fallback; agent↔agent: delegacja podzadania z **zawężonym** mandatem (`POST /v1/tasks/{id}/delegate`); app↔agent: `POST /v1/tasks` | `app.py`, `mcp_proxy.py`, `controls/mandate.py` | M-01…M-04 |
| Kontekst: „bez walidacji wejścia **i filtra wyjścia**” | Pipeline w dwóch fazach: **pre** (żądanie/argumenty) i **post** (odpowiedź modelu, wynik narzędzia). Wyniki narzędzi (pośredni prompt injection) też skanowane. Odpowiedzi buforowane przed wydaniem | `pipeline.py` | O-01…O-03 |
| Kontekst: „podszywa się pod innych aktorów” | Principal tylko z uwierzytelnionego klucza API; **lease token** (HMAC) wiąże `task_id`+`principal`; `principal` w body ignorowany | `controls/mandate.py` | D-xx |
| Kontekst: pamięć / współdzielona pamięć | Minimalny `memory.read/write` jako narzędzie pod mandatem: wpisy mają `case`, `classification`; odczyt z innej sprawy = BLOCK; zapis dziedziczy taint | `tools/memory.py` | MEM-01…02 |
| Kontekst: „analizuj ekosystem (np. OWASP)” | Tabela mapowania kontrola → OWASP LLM Top 10 2025 + OWASP Agentic Threats w README i PDF | `README.md` | — |

**Wyróżniki (MANDATE):** task mandate/lease, taint (data lineage), proof of enforcement, budget escrow. Bonus: Policy Lab (diff decyzji), Attack Replay.

---

## 2. Architektura

```
 Agent / App ──HTTP──► GATEWAY (FastAPI)
                         │
   ┌─────────────────────┴───────────────────────────┐
   │ Pipeline (kolejność = od taniego do drogiego)   │
   │  0. Policy snapshot (wersja + hash)             │
   │  1. Mandate/lease: tożsamość, task, TTL, tool,  │
   │     zasób, odbiorca                             │
   │  2. Allowlist: model / narzędzie / host         │
   │  3. Attack signatures (feed): kod, pickle, CVE  │
   │  4. Deterministyczne: PII, sekrety              │
   │  5. Taint/IFC: klasyfikacja zadania vs sink     │
   │  6. Semantyczne (Ollama) — tylko zaostrza       │
   │  7. Budget escrow: reserve → execute → settle   │
   │  ── wykonanie (model / narzędzie) ──            │
   │  POST: sygnatury + PII/sekrety + semantyka      │
   │     na odpowiedzi/wyniku narzędzia; odczyt      │
   │     zasobu podnosi taint                        │
   │  8. Outcome verification (licznik po stronie    │
   │     narzędzia)                                  │
   └─────────────────────┬───────────────────────────┘
                         ▼
        ┌───────────────┬──────────────────┐
        ▼               ▼                  ▼
     Ollama        Tool backends       Audit (JSONL)
                (mock mail, notes,     + PostgreSQL state
                 docs, http-sink)             │
                                              ▼
                                    Dashboard + export
```

Diagram do PDF: ten sam układ w Mermaid/draw.io (wymagany przez zadanie).

Kolejność etapów: pierwszy BLOCK kończy pipeline (short-circuit), więc semantyka (drogi etap) nie odpala się dla żądań już zablokowanych deterministycznie. Wywołanie klasyfikatora semantycznego ma **własny budżet guarda** (`guard_budget`), liczony osobno od budżetu zadania i widoczny na dashboardzie (koszt samej ochrony).

### Punkty wejścia
- `POST /v1/tasks` — app tworzy zadanie z profilu, zwraca lease token (app↔agent).
- `POST /v1/tasks/{id}/delegate` — podzadanie dla innego agenta; mandat dziecka ⊆ mandat rodzica, budżet liczony do puli rodzica (agent↔agent).
- `POST /v1/chat/completions` — OpenAI-compatible proxy do Ollama (agent↔model). `stream=true` ⇒ odpowiedź buforowana, wydana po kontroli (bezpieczny streaming poza zakresem).
- `MCP /mcp` — proxy MCP (streamable HTTP, `mcp` Python SDK): `tools/list` filtrowane wg mandatu + hash definicji (tool poisoning), `tools/call` przez pipeline (agent↔MCP).
- `POST /v1/tools/{tool}/call` — REST fallback dla narzędzi; wrapper SDK `mandate_sdk.govern(tool)`.
- Backendy narzędzi na osobnym porcie, wymagają sekretu znanego tylko gatewayowi (test bypass).

---

## 3. Model danych

### 3.1 Decyzja
```python
class Decision(BaseModel):
    action: Literal["ALLOW", "REDACT", "BLOCK"]
    reason_code: str            # np. DATA_FLOW_VIOLATION, PII_DETECTED, BUDGET_EXCEEDED
    rule_id: str                # np. IFC-003, PII-001
    policy_version: str         # hash/semver
    stage: str                  # które z 8 kroków zdecydowało
    latency_ms: float
    redactions: list[Redaction] = []
    tool_invoked: bool = False
    task_id: str
    evidence: dict              # klasy danych, resource id, bez surowej treści
```
Łączenie decyzji: `BLOCK > REDACT > ALLOW` (najostrzejsza wygrywa).

### 3.2 Mandate (kontrakt zadania, po stronie serwera)
```yaml
task_id: 4f92
principal: lawyer_anna
purpose: "Analyze contract of client A, write internal summary"
resources_allow: ["/clients/A/contracts/*"]
resources_deny:  ["/clients/B/*"]
tools_allow: [doc.read, legal_db.search, notes.write, memory.read, memory.write]
sinks_allow:                       # może tylko ZAWĘZIĆ clearance z polityki (effective = min)
  notes.write:   {max_clearance: CONFIDENTIAL}
  legal_db.search: {max_clearance: INTERNAL}   # wewnętrzna baza orzecznictwa (lokalna)
model_allow: [ollama/qwen2.5:3b]
budget: {tokens: 20000, calls: 12, wall_seconds: 60, concurrency: 3}
expires_at: <TTL>
classification: PUBLIC   # rośnie przez taint, nigdy nie spada
```
Mandat tworzony przez uwierzytelnioną aplikację (`POST /v1/tasks`) z **profilu zadania** w polityce (nie z tekstu użytkownika). Po wygaśnięciu/zakończeniu: `CAPABILITY_EXPIRED`.

### 3.3 Klasyfikacja i taint
`PUBLIC=0 < INTERNAL=1 < CONFIDENTIAL=2 < SECRET=3`.
- Katalog dokumentów (zaufany) nadaje etykietę zasobowi.
- `doc.read` ⇒ `task.classification = max(task.classification, doc.label)`. Model nie może jej obniżyć.
- Sink ma `clearance`. `task.classification > sink.clearance` ⇒ BLOCK `DATA_FLOW_VIOLATION`.
- Konserwatywnie: po odczycie poufnego dokumentu **cały** dalszy output taska jest poufny (parafraza, base64, tłumaczenie bez znaczenia). Znane false positives opisane w README jako świadoma granica.
- Skutek dla scenariusza demo: zapytania do sinków o niższym clearance trzeba wykonać **przed** odczytem poufnego dokumentu albo w osobnym zadaniu (Research Airlock jako przyszły rozwój). Agent demo robi: `legal_db.search` → `doc.read` → model lokalny → `notes.write`. Wszystkie kroki ALLOW.
- Effective clearance sinka = `min(policy.sinks[x], mandate.sinks_allow[x])`. Brak wpisu w polityce ⇒ `PUBLIC` (domyślnie najostrzej).
- REDACT nie obniża taintu: zredagowany tekst z poufnego zadania dalej nie wyjdzie do sinka `PUBLIC`.

### 3.4 Budget escrow
```
reserve (JEDNA transakcja Postgres, wszystkie zakresy: task, rodzic, principal, global):
    dla każdego zakresu, w stałej kolejności po scope_id (brak deadlocków):
        UPDATE budgets
           SET reserved = reserved + :n, active_calls = active_calls + 1
         WHERE scope_id = :scope
           AND spent + reserved + :n <= token_limit
           AND active_calls < concurrency_limit
        RETURNING scope_id;
    0 wierszy w którymkolwiek ⇒ ROLLBACK ⇒ BLOCK BUDGET_EXCEEDED (przed wywołaniem modelu)
    INSERT INTO reservations (id, task_id, amount, status='active')
    COMMIT
execute
settle (transakcja): reserved -= n; spent += actual; active_calls -= 1;
                     reservations.status = 'settled'   (nadwyżka zwolniona)
timeout/niepewność: reservations.status = 'uncertain', rezerwacja zostaje do rozliczenia (nie zerujemy)
```
Warunek w `WHERE` + blokada wiersza przez `UPDATE` = atomowe check-and-reserve bez osobnego locka w aplikacji.
Zakresy: per task, per principal, globalny. Podzadania liczą się do limitu nadrzędnego. Wymiary: tokeny (rezerwacja = `prompt_tokens` + `max_tokens`; brak `max_tokens` w żądaniu ⇒ gateway wstawia limit z polityki, żeby rezerwacja miała górną granicę), liczba wywołań, czas, współbieżność (slot zwalniany w `finally`). Koszt $ = konfigurowalna stawka, oznaczony jako estymacja.
Skalowalność (10% oceny): atomowość budżetu jest w Postgresie, więc jest poprawna przy wielu workerach i wielu instancjach gatewaya (gateway bezstanowy, stan w bazie). MVP uruchamiamy z 1 workerem uvicorn (prostszy snapshot polityki w pamięci). Przy N instancjach: zmiana polityki zapisywana w `policy_versions` + `NOTIFY policy_changed`, każda instancja robi `LISTEN` i przeładowuje snapshot. Test współbieżności uruchamiamy też z `--workers 4`, żeby to udowodnić. Dalej: Redis (Lua) dla bardzo wysokiego RPS — opisane jako przyszły rozwój.

### 3.5 Schemat bazy (PostgreSQL, `db/init/001_schema.sql`)
| Tabela | Kluczowe kolumny |
|---|---|
| `tasks` | `id`, `principal`, `parent_id`, `profile`, `mandate JSONB`, `classification SMALLINT`, `lease_hash`, `expires_at`, `status` |
| `budgets` | `scope_id` (task:/principal:/global/guard), `token_limit`, `spent`, `reserved`, `calls_limit`, `calls_used`, `concurrency_limit`, `active_calls` |
| `reservations` | `id`, `task_id`, `scope_ids TEXT[]`, `amount`, `actual`, `status` (active/settled/uncertain), `created_at` |
| `audit_events` | `id BIGSERIAL`, `ts`, `task_id`, `kind` (DECISION/POLICY_CHANGED/POLICY_REJECTED/CONTROL_DISABLED/…), `action`, `rule_id`, `stage`, `policy_version`, `latency_ms`, `tool_invoked`, `evidence JSONB` — indeksy na `(ts)`, `(task_id)`, `(rule_id)` |
| `policy_versions` | `version` (hash), `content JSONB`, `source` (file/api), `accepted BOOL`, `error`, `created_at` |
| `tool_registry` | `name`, `definition_hash`, `approved_at`, `status` (approved/quarantined) — MCP tool poisoning |
| `memory_entries` | `id`, `case_id`, `classification`, `source_task`, `content` |

Schemat ładowany przez `docker-entrypoint-initdb.d` (tylko przy pustym wolumenie; zmiana schematu ⇒ `make clean && make run`). Bez Alembica — za drogie na 24 h. Testy: osobna baza `goldman_test` czyszczona (`TRUNCATE`) per test.
Audyt do dashboardu: agregacje SQL (blokady per reguła, p50/p95 przez `percentile_cont`). Eksport: `COPY`/stream do JSONL i CSV.

---

## 4. `policy.yaml` (szkic schematu)

```yaml
version: 1
profile: balanced            # strict | balanced | permissive — daje WARTOŚCI DOMYŚLNE;
                             # pole ustawione jawnie w `controls` wygrywa z profilem
models:
  allow: ["ollama/qwen2.5:3b", "ollama/llama3.2:3b"]
classification:
  levels: [PUBLIC, INTERNAL, CONFIDENTIAL, SECRET]
  sinks:
    external_email: PUBLIC
    http.post: PUBLIC
    legal_db.search: INTERNAL
    notes.write: CONFIDENTIAL
    memory.write: CONFIDENTIAL
    ollama_local: SECRET
    # brak wpisu ⇒ PUBLIC
controls:
  mandate:      {enabled: true}
  ifc_taint:    {enabled: true}
  pii:
    enabled: true
    mode: redact             # block | redact
    entities: [PESEL, CREDIT_CARD, IBAN, EMAIL, PHONE]
  secrets:      {enabled: true, mode: block}
  attack_signatures:
    enabled: true
    feed: feeds/attacks.yaml
    mode: block
  injection_heuristics:      # deterministyczna warstwa prompt injection (tania, przed semantyką)
    enabled: true
    mode: block
  semantic:
    enabled: true
    model: ollama/qwen2.5:3b
    block_at_risk: 0.7       # BLOCK gdy risk >= próg; NIŻSZY próg = OSTRZEJ
    redact_at_risk: 0.5      # REDACT/flag dla risk w [0.5, 0.7)
    on_timeout: block        # fail-closed
    timeout_ms: 1500
budgets:
  default_task: {tokens: 20000, calls: 12, wall_seconds: 60, concurrency: 3}
  default_max_tokens: 1024   # wstawiane gdy żądanie nie podaje max_tokens
  per_principal_daily: {tokens: 200000}
  guard_budget: {tokens: 50000, calls: 500}   # koszt samej ochrony (semantyka)
  pricing: {usd_per_1k_tokens: 0.0}   # estymacja
profiles:                    # adherence = 1 - block_at_risk (np. strict = 60%)
  strict:     {semantic: {block_at_risk: 0.4, redact_at_risk: 0.25}, pii: {mode: block}}
  balanced:   {semantic: {block_at_risk: 0.7, redact_at_risk: 0.5},  pii: {mode: redact}}
  permissive: {semantic: {block_at_risk: 0.9, redact_at_risk: 0.75}, pii: {mode: redact}}
```
`enabled: false` dla `mandate`/`ifc_taint` jest dozwolone (jury testuje wyłączanie), ale generuje wpis audytu `CONTROL_DISABLED` i czerwony status na dashboardzie.
Hot-reload: file watcher + `POST /admin/policy/reload` + `PUT /admin/policy` (dashboard). Walidacja Pydantic → atomowa podmiana snapshotu → wpis audytu `POLICY_CHANGED {old, new, diff}`. Błąd ⇒ `POLICY_REJECTED`, zostaje poprzednia wersja. Istniejące zadania: kolejne wywołania używają **nowej** polityki (może tylko ograniczać mandat).

### Feed sygnatur ataków (`feeds/attacks.yaml`)
```yaml
- id: ATK-PICKLE-001
  title: Unsafe deserialization — pickle opcodes importing dangerous globals
  match: {type: pickle_scan, deny_globals: ["os.*", "posix.*", "subprocess.*", "builtins.eval", "builtins.exec", "builtins.__import__"]}
  # skan opcode'ów przez `pickletools.genops` (GLOBAL/STACK_GLOBAL + REDUCE), plik NIE jest deserializowany;
  # regex na tekst nie działa dla binarnych .pkl/.pt/.bin
  severity: high
  refs: [OWASP-LLM03, CWE-502]
- id: ATK-PICKLE-002
  title: Unsafe deserialization calls in code from agent
  match: {type: regex, target: [tool_args, model_output], pattern: "(pickle\\.loads?|torch\\.load\\((?![^)]*weights_only\\s*=\\s*True)|yaml\\.load\\((?![^)]*SafeLoader)|marshal\\.loads)"}
  refs: [CWE-502]
- id: ATK-TRC-001
  title: Remote code via trust_remote_code
  match: {type: regex, target: [tool_args, model_output], pattern: "trust_remote_code\\s*=\\s*True"}
- id: ATK-CVE-2024-34359
  title: llama-cpp-python SSTI via GGUF chat_template (Llama Drama)
  match:
    - {type: component, package: llama-cpp-python, version_lt: "0.2.72"}
    - {type: gguf_template, pattern: "(__class__|__globals__|__subclasses__|__builtins__|os\\.popen)"}
  # sprawdzane w `POST /v1/models/register` (rejestracja modelu/komponentu) — przed uruchomieniem
- id: ATK-EXEC-001
  title: Code exec primitives in arguments of code-executing tools
  match: {type: regex, target: [tool_args], tools: [code.run, shell.exec], pattern: "(os\\.system|subprocess\\.|eval\\(|exec\\(|__import__)"}
  # zawężone do narzędzi wykonujących kod, żeby zwykłe odpowiedzi z przykładami kodu nie dawały FP
- id: ATK-INJ-001
  title: Known prompt-injection phrasings (deterministic heuristic)
  match: {type: regex, flags: i, target: [tool_results, file_content, user_input], pattern: "(ignore (all )?(previous|prior) instructions|disregard .* system prompt|you are now|zignoruj (wszystkie )?poprzednie)"}
- id: ATK-SUPPLY-001
  title: Model from non-allowlisted / typosquatted source
  match: {type: model_source, deny_unless_host: [huggingface.co, ollama.com], typosquat_distance: 2}
- id: ATK-MCP-POISON-001
  title: Tool description changed after approval
  match: {type: tool_hash_mismatch}
```
Feed ładowany tak samo jak polityka (hot-reload); jury może dopisać sygnaturę live. Źródło feedu: plik lokalny **lub** URL (`feed_url`, np. lokalny serwer udający zewnętrzny system threat intel) — spełnia „sygnatury podawane z zewnętrznego systemu”. Zły feed ⇒ zostaje poprzedni (jak polityka).

---

## 5. Struktura repo

```
hackyeah-2026-goldman/
├── PLAN.md
├── README.md                      # 1 komenda uruchomienia, 1 reguła do zmiany
├── pyproject.toml
├── Dockerfile                     # gateway (python:3.12-slim, non-root, healthcheck)
├── docker-compose.yml             # db (Postgres 17) + gateway + opcjonalnie ollama (profile)
├── .env.example                   # porty, credentiale Postgres, OLLAMA_BASE_URL
├── Makefile                       # make run | down | logs | test | test-docker | db-shell | clean | demo | bench
├── db/init/001_schema.sql         # schemat Postgres (docker-entrypoint-initdb.d)
├── policy/policy.yaml
├── feeds/attacks.yaml
├── mandate/
│   ├── app.py                     # FastAPI, routes (tasks, delegate, chat, tools, models/register, admin)
│   ├── mcp_proxy.py               # MCP streamable HTTP proxy (tools/list filtr + hash, tools/call → pipeline)
│   ├── pipeline.py                # pipeline pre/post, short-circuit, łączenie decyzji
│   ├── models.py                  # Decision, Mandate, Redaction (Pydantic)
│   ├── db.py                      # SQLAlchemy async engine (asyncpg), DATABASE_URL
│   ├── policy/ {loader.py, schema.py, watcher.py, feed.py}
│   ├── controls/ {mandate.py, allowlist.py, attacks.py, pickle_scan.py, injection.py,
│   │              pii.py, secrets.py, taint.py, semantic.py}
│   ├── budget/escrow.py
│   ├── tools/ {registry.py, mock_mail.py, notes.py, docs.py, legal_db.py, memory.py}   # backendy z licznikami
│   ├── audit/ {log.py, export.py, metrics.py}
│   └── sdk.py                     # govern(tool) wrapper
├── dashboard/ {index.html, task.html, static/}
├── landing/                       # Astro (statyczna strona projektu)
│   ├── astro.config.mjs  package.json
│   └── src/ {pages/index.astro, components/*.astro, layouts/Base.astro}
├── demo/
│   ├── agent.py                   # agent LLM (Ollama tool-calling)
│   ├── scripted_agent.py          # deterministyczny agent (fallback demo + testy E2E)
│   ├── contracts/*.txt            # syntetyczne umowy (czysta + z injection)
│   ├── fixtures/                  # malicious.pkl (generowany w teście), gguf_template_evil.json
│   └── scenarios/*.py
└── tests/
    ├── cases/*.yaml               # oczekiwane wyniki, niezależne od implementacji
    ├── test_policy.py  test_pii.py  test_secrets.py  test_attacks.py  test_injection.py
    ├── test_taint.py   test_mandate.py  test_delegate.py  test_memory.py
    ├── test_budget.py  test_semantic.py  test_output_filter.py  test_mcp.py
    ├── test_enforcement.py        # proof: tool counter == 0 po BLOCK
    ├── test_hot_reload.py  test_audit.py  test_bypass.py  test_e2e.py
    └── bench/latency.py           # p50/p95 per etap
```

---

## 6. Plan godzinowy (od 3.10 11:00)

Kolejność w górę: **działający szkielet > testy > reszta**. Checkpoint twardy po ~H5. **Testy piszemy razem z każdą kontrolą** (kontrola bez pary pozytywny/negatywny = niezrobiona); H19–22 to tylko uzupełnienie i bypass. Dashboard startuje równolegle od H5 na danych z audytu (UI/demo nie czeka na backend).

| Godz. | Cel | Wynik |
|---|---|---|
| H0–1 | Repo, `pyproject`, Ollama działa, model pobrany, schemat polityki, modele Pydantic, **ustalenie interfejsów** | Kontrakty zamrożone |
| H1–5 | Gateway + pipeline pre/post + mock mail + scripted agent + 1 allow + 1 block + audyt JSONL | **CHECKPOINT:** pełna ścieżka agent→gateway→narzędzie, blokada realna |
| H5–9 | Mandate/lease (HMAC), taint/IFC, PII+sekrety (block/redact), allowlista modeli, injection heuristics | Scena "evil.com" działa deterministycznie |
| H9–13 | Hot-reload + last-good, feed sygnatur (pickle scan, CVE, trust_remote_code), semantyka (Ollama), profile, **proxy MCP** | Jury może zmieniać reguły live |
| H13–16 | Budget escrow + test 30 agentów, limity, delegacja agent↔agent, memory | Overspend = 0 udowodniony |
| H16–19 | Dashboard dopięty (szczegóły zadania, eksport, p50/p95, panel live), proof-of-enforcement | Raportowanie 20% |
| H19–22 | Uzupełnienie testów do ~45, bypass, ad-hoc "jak jury" na świeżym klonie, bench; landing (jeśli jest czas) | Suite zielony |
| H22–23 | README, diagram, PDF (10 slajdów), nagranie demo, **submit najpóźniej 4.10 10:00** | Zgłoszenie |
| H23–24 | Bufor (awarie platformy, poprawki opisu) | — |

Freeze funkcji: H19. Bonusy (Policy Lab, Attack Replay, Lease expiry demo) tylko jeśli checkpoint H5 i H13 zaliczone.
**Kolejność cięcia przy opóźnieniu:** landing → bonusy → memory → delegacja agent↔agent (zostaje jako test API bez UI) → proxy MCP (zostaje REST z hashowaniem definicji narzędzi). Nigdy nie tniemy: testów, hot-reload, PII/sekretów, sygnatur ataków, budżetu, eksportu audytu.

### Podział (4 osoby; dostosować)
| Rola | Odpowiedzialność |
|---|---|
| Backend A | Gateway, pipeline, integracja Ollama/narzędzi, SDK |
| Backend B | Policy engine, hot-reload, mandate, taint, budżet/escrow |
| Security/testy | Kontrole (PII, sekrety, sygnatury, semantyka), feed, test suite, bypass |
| UI/demo | Dashboard, audyt export, diagram, PDF, nagranie, scenariusz demo |

---

## 7. Test suite (min. pozytywny + negatywny na każdą kontrolę)

Oczekiwane wyniki w `tests/cases/*.yaml`: `{id, input, policy_profile, expect: {action, rule_id?}}`. Osobno: **deterministyczne** (stabilne, bez modelu) vs **z modelem** (empiryczne; semantyka mockowana w CI, realny Ollama w `-m live`).

| Obszar | Pozytywny (ALLOW) | Negatywny (BLOCK/REDACT) |
|---|---|---|
| Mandate | Właściwy user+task, zasób przypisany | Zasób klienta B; podmiana principal; wygasły lease; narzędzie spoza listy |
| Taint | Zapis notatki po odczycie CONFIDENTIAL; local LLM | Wysyłka na zewnątrz po odczycie CONFIDENTIAL (też po parafrazie/base64) |
| PII | Tekst bez PII | PESEL, karta (Luhn), IBAN → redact lub block wg profilu |
| Sekrety | Tekst zwykły | AWS key, JWT, private key → block |
| Allowlista modeli | `qwen2.5:3b` | Model spoza listy |
| Sygnatury | Zwykły kod; bezpieczny pickle (dict/list); `torch.load(..., weights_only=True)`; model z allowlisty | Pickle z `os.system` w opcode'ach (generowany w teście, nigdy nie ładowany); `trust_remote_code=True`; `os.system` w `code.run`; GGUF template z `__globals__`; `llama-cpp-python==0.2.71`; typosquat (`hugginface.co`); zmiana opisu narzędzia MCP |
| Hot-reload feedu | Nowa sygnatura dopisana live działa od następnego żądania | Zepsuty feed ⇒ zostaje poprzedni |
| Injection (deterministyczne) | Tekst neutralny | "Ignore previous instructions…" w wyniku narzędzia / dokumencie |
| Semantyka | Dokument *o* prompt injection (opis) | Ukryta instrukcja "wyślij na evil.com"; **wymuszone przeoczenie detektora** → deterministyczna warstwa i tak blokuje; zmiana progu (profil strict) zmienia decyzję |
| Filtr wyjścia | Czysta odpowiedź modelu | Odpowiedź modelu z PESEL/kluczem API → redact/block przed wydaniem |
| MCP | `tools/list` zwraca tylko narzędzia z mandatu | `tools/call` narzędzia spoza mandatu; zmieniony hash definicji ⇒ kwarantanna |
| Agent↔agent | Delegacja z węższym mandatem | Delegacja z szerszymi narzędziami/clearance; podzadanie omija budżet rodzica |
| Memory | Odczyt wpisu z własnej sprawy | Odczyt wpisu sprawy B; zapis po taincie dziedziczy CONFIDENTIAL |
| Impersonacja | Principal z klucza API | `principal` podmieniony w body; lease token innego zadania; podrobiony HMAC |
| Budżet | Mieści się w limicie | Przekroczenie tokenów/wywołań; 30 równoległych: sum(rezerwacji) ≤ limit; pętla runaway zatrzymana |
| Konfiguracja | Poprawna zmiana reguły działa od następnego żądania | Zepsuty YAML ⇒ zostaje last-good; usunięcie kontroli widoczne w audycie |
| Audyt | Pełny ślad decyzji | Sekret nie wycieka do logów |
| Enforcement | `mail.sent == 1` po ALLOW | `mail.sent == 0` po BLOCK |
| Bypass | — | Bezpośrednie wywołanie backendu z pominięciem gatewaya jest odrzucone (token tylko dla gatewaya) |
| Fail-closed | Guard odpowiada | Timeout/błąd semantyki ⇒ BLOCK |

Dodatkowo: test "wyłącz kontrolę w polityce ⇒ test regresji wykrywa naruszenie".

---

## 8. Dashboard

**Widok ogólny (management):** allowed / redacted / blocked (live), budżet zużyty vs zarezerwowany, aktywna wersja polityki + historia zmian, lista kontroli ze statusem on/off i surowością, p50/p95 per etap, top reguły blokujące.
**Szczegóły zadania (security):** mandat, odczytane zasoby, klasyfikacja w czasie, proponowane wywołania, reguła decyzyjna, "tool invoked: no / backend counter", przycisk eksportu JSON/CSV.
**Panel live:** edycja `policy.yaml` w przeglądarce, pole "wpisz własny prompt", przełącznik profilu strict/balanced/permissive, przycisk "Launch 30 agents".

Telemetria wydajności: `/metrics` (JSON) z p50/p95/p99 dla etapów deterministycznych, semantycznych i pełnej operacji; opis sprzętu/modelu/liczby prób w README.

---

## 8a. Landing page (Astro)

Statyczna strona projektu w **Astro** (`landing/`), niezależna od gatewaya. Cel: zgłoszenie przekonuje bez live prezentacji (HackTribe ocenia najpierw offline) i daje jurorom jedno miejsce startowe.

**Sekcje (jedna strona):**
1. Hero: "MANDATE — zero-trust execution contracts for AI agents" + tagline porównawczy + CTA (Demo / GitHub / Docs).
2. Problem: 3 ryzyka z zadania (uprawnienia, prompt injection, pamięć/zasoby).
3. Jak działa: diagram architektury (SVG), 8-stopniowy pipeline.
4. 4 wyróżniki: task mandate, data lineage/taint, proof of enforcement, budget escrow.
5. Demo: animowany przepływ sceny "evil.com" (BLOCK, `mail requests received: 0`) + zrzuty dashboardu.
6. Dowody: wyniki test suite (liczba przypadków, pass), p50/p95, overspend = 0.
7. Quickstart: `make run`, zmiana jednej reguły w `policy.yaml`.
8. Granice i dalszy rozwój (uczciwie: taint konserwatywny, false positives).
9. Zespół + stopka.

**Zasady:** angielski, zero zewnętrznych usług/trackerów, czysty statyczny build (`astro build` → `landing/dist`), mało JS (wyspy tylko dla animacji), dark/light, mobile. Wyniki testów i p50/p95 wstrzykiwane z pliku `landing/src/data/results.json` generowanego przez `make bench` / `make test` (bez ręcznego przepisywania liczb).
**Czas:** ~2–3 h, osoba UI/demo, w oknie H19–22 (po freeze funkcji); szkielet z hero + diagram wcześniej, jeśli UI/demo ma wolne.
**Priorytet:** landing **nie jest** deliverable ani kryterium oceny — pierwszy do cięcia. PDF i dashboard mają pierwszeństwo. Treść landingu = treść PDF (jeden tekst, dwa formaty), żeby nie pisać dwa razy.
**Hosting:** statycznie z repo (GitHub Pages) lub serwowane przez gateway pod `/`; dashboard pod `/dashboard`.

---

## 9. Scenariusz demo (≈5 min, moduły)

1. **0:00–0:40** Dobre zadanie: analiza syntetycznej umowy, zapis notatki; widoczny mandat.
2. **0:40–1:40** Prompt injection w dokumencie → agent próbuje `mail.send(evil.com)` → BLOCK `DATA_FLOW_VIOLATION`, reguła, `mail requests received: 0`.
3. **1:40–2:20** Wymuszone przeoczenie detektora semantycznego → deterministyczna warstwa blokuje.
4. **2:20–3:20** Jury zmienia politykę (profil, próg, usuwa kontrolę, dopisuje sygnaturę) → nowa decyzja z nową wersją.
5. **3:20–4:10** "Launch 30 agents" → rezerwacje vs odmowy, overspend $0.
6. **4:10–5:00** Raport testów, szczegóły jednego naruszenia, p50/p95, eksport audytu.

---

## 10. Ryzyka i mitygacje

| Ryzyko | Mitygacja |
|---|---|
| Ollama wolny na sprzęcie zespołu | Mały model, `timeout_ms`; semantyka tylko na treściach niezaufanych (dokumenty, wyniki narzędzi, input usera), nie na każdym żądaniu; short-circuit po BLOCK; cache wyniku po hashu treści |
| Agent i guard na jednym Ollama ⇒ kolejka, timeouty guarda ⇒ masowe fail-closed | `OLLAMA_NUM_PARALLEL≥2`; mniejszy model dla guarda; test 30 agentów uderza w mock modelu (mierzy gateway, nie Ollamę) |
| Model 3B zawodnie wywołuje narzędzia (tool calling) | Demo i E2E na `scripted_agent.py` (deterministyczny); agent LLM jako dodatkowy pokaz "na żywo" |
| Semantyka niestabilna w testach | Mock klasyfikatora w CI + osobny `-m live` |
| Jury łamie konfigurację | Walidacja + last-good + wpisy `POLICY_REJECTED` |
| Scope creep | Freeze H19; bonusy tylko po checkpointach |
| Rozbieżność wag testów (15% vs 20%) | Planujemy pod 20%; pytanie do mentora |
| Rozbieżność terminu (11:00 vs 23:00) | Planujemy pod 4.10 11:00 |
| False positives z taint | Świadoma granica, opisana w README ("konserwatywnie") |
| Jury nie ma Dockera / Docker nie startuje | README: wymagania (Docker Desktop) na górze; fallback „bez Dockera”: lokalny Postgres + `uvicorn` z `DATABASE_URL`; test uruchomienia na drugim, czystym komputerze przed submitem |
| Ollama w kontenerze na macOS = CPU, bardzo wolno | Domyślnie Ollama na hoście (`host.docker.internal`), kontener tylko przez `--profile ollama` (Linux) |
| Zmiana schematu nie wchodzi (init tylko przy pustym wolumenie) | `make clean && make run`; schemat zamrożony po H5 |

---

## 11. Definition of Done (przed submit)

- [ ] Obca osoba na czystym klonie: `cp .env.example .env && make run` → `/health` = ok, dashboard działa; zmienia 1 regułę w `policy/policy.yaml` (zamontowany wolumen) → widzi efekt bez rebuildu
- [ ] Test współbieżności budżetu przechodzi także z `--workers 4`
- [ ] `make test` zielony; pokrycie pozytywne+negatywne każdej kontroli
- [ ] Scena evil.com + wymuszone przeoczenie detektora działa na świeżym klonie
- [ ] Hot-reload: zła polityka nie wyłącza ochrony
- [ ] Test współbieżności budżetu: overspend = 0
- [ ] Feed sygnatur podmienialny live; pickle (opcode scan) / trust_remote_code / CVE-2024-34359 wykrywane
- [ ] Wszystkie 4 kanały komunikacji przechodzą przez gateway: agent↔model, agent↔MCP, agent↔agent, app↔agent
- [ ] Filtr wyjścia: odpowiedź modelu i wynik narzędzia sprawdzane przed wydaniem
- [ ] Tabela mapowania kontroli na OWASP LLM Top 10 / Agentic w README i PDF
- [ ] Eksport audytu (JSONL/CSV) bez sekretów
- [ ] p50/p95 zmierzone, warunki opisane
- [ ] Diagram architektury, `policy.yaml` z komentarzami i 3 profilami
- [ ] Landing page Astro zbudowany (`astro build`), liczby z `results.json`, linki działają
- [ ] PDF ≤ 10 slajdów, repo/demo link, submit w HackTribe z zapasem

---

## 12. Pierwsze kroki (H0–H1)

1. ✅ `pyproject.toml`, `Dockerfile`, `docker-compose.yml` (db + gateway + opcjonalnie ollama), `Makefile`, szkielet `mandate/app.py` z `/health` (sprawdza Postgresa). `make run` działa.
2. `ollama pull qwen2.5:3b` na hoście; sprawdzić latencję na sprzęcie zespołu.
3. Zamrozić `models.py` (Decision, Mandate), `policy/schema.py` i `db/init/001_schema.sql` — wszyscy kodują pod te kontrakty.
4. Mock mail z licznikiem `/mock/mail/stats` (fundament proof-of-enforcement).
5. Pierwszy test end-to-end: ALLOW zapis notatki, BLOCK wysyłki — zanim powstanie cokolwiek innego.
