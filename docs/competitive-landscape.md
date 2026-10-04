# Aegis vs. the open-source landscape

Data: GitHub API, 4 Oct 2026. Purpose: one-page positioning for the jury and the deck.
The claim we defend: **mature OSS tools exist for scanning, validating and routing — none of
them decides whether this agent was ever *authorized* to do this action, with this data, for
this task.** Aegis is the authorization, lineage and budget layer that sits in front of all of them.

## The map

| Project | Stars / state | What it actually is | What it covers | The gap Aegis fills |
|---|---|---|---|---|
| BerriAI/litellm | 60.0k, active | LLM gateway / router, 100+ providers | Budgets per virtual key (post-hoc accounting), model allowlists, spend dashboards | No per-task mandate, no data-flow/IFC, no content controls, no proof a blocked call never ran; budgets are ledgers, not escrow |
| promptfoo | 25.7k, active | Prompt eval + red-team scanner | Adversarial probe corpora, eval reports | Finds holes at test time; enforces nothing at runtime. Aegis is the runtime complement |
| NVIDIA/garak | 9.4k, active | LLM vulnerability scanner | Probe categories (injection, data leak, unsafe exec) | Same split: scanner vs. enforcement layer |
| guardrails-ai/guardrails | 7.5k, active | Structured-output validation (schema, re-ask) | Output validity, RAG grounding | Different meaning of "guardrail": quality, not security. No authorization, no PII/policy enforcement |
| katanemo/plano | 7.1k, active | AI-native proxy / data plane | Routing, observability, guardrail hooks | Guardrails as pluggable hooks, not a coherent authorization model; no taint, no escrow |
| NVIDIA-NeMo/Guardrails | 7.2k, active | Conversational rails (Colang) | Dialog topology, topic control, canonical forms | Conversation-centric: no task capability scoping, no budget governance, no audit-grade lineage |
| agentgateway | 5.2k, active | Rust proxy for agents + MCP | L7 routing, authn, traffic management | Transport-level control; no semantic guard, no data-flow, no spend escrow |
| archestra | 4.3k, active | Enterprise AI platform | Gateway + registry + orchestrator | Platform bundle; authorization not task-scoped, no fail-closed content pipeline |
| protectai/llm-guard | 3.2k, slowing (last push Jul 2026) | Python scan library (input/output) | PII, secrets, injection scanners, sandbox | Library, not a control layer: caller decides what to do with findings; no central policy, mandate, budget or proof |
| microsoft/presidio | — | PII detection/redaction service | PII (English-centric NER + regex) | One control, not a layer; Aegis ships Polish-legal validators (PESEL/NIP/dowód) with checksums, not just patterns |
| invariantlabs-ai/invariant-gateway | 82, frozen since Nov 2025 | LLM proxy to observe agents | Agent traffic analysis | Abandoned for the commercial platform — the *idea* (agent security gateway) is validated, the OSS slot is empty |
| preloop | 71, active | "Agent control plane" | MCP firewall, budgets, approvals | Same thesis as ours, early stage — confirms the niche |

## What we deliberately borrowed from the best of them

* From **promptfoo/garak**: the red-team corpus discipline — `make redteam` replays a bundled
  jailbreak/exfiltration corpus through the real pipeline and reports per-technique block rates.
  A scanner's method, enforced at runtime.
* From **litellm**: budget visibility per principal — but as *atomic escrow before execution*
  (reserve → execute → settle), tested with 30 concurrent agents at 0 overspend.
* From **llm-guard**: the detector taxonomy (PII / secrets / injection) — but wired into a
  central versioned policy with hot reload, fail-closed defaults and append-only audit.
* From **presidio**: validator-grade PII — checksummed identifiers (PESEL, NIP, IBAN mod-97,
  Luhn, dowód osobisty check digit) instead of bare regex, so look-alikes pass through.

## Positioning (one sentence)

Scanners (garak, promptfoo) find weaknesses, validators (guardrails-ai) fix outputs, gateways
(litellm, agentgateway) route and meter — **Aegis is the only open-source layer that answers the
authorization question: was this agent ever allowed to do this, with this data, for this task,
within this budget — and can you prove the blocked call never happened.**
