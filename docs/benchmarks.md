# Benchmarks: Aegis against other guardrails

What the landing page's "How much does a check cost?" section is built from.

## Aegis (measured)

`make bench` (or `python -m aegis.bench`) boots the real gateway in-process with a real Postgres and the real tool
backends, and replays a fixed mixed workload. Full output: [`bench-report.md`](bench-report.md).
Machine: cloud container, 4 vCPU (Intel Xeon @ 2.10 GHz), Python 3.12. Mock model (fixed 50 ms, shown separately as
`model_call`), heuristic AI-review backend, rate limits lifted so the pipeline itself is measured.

| What | p50 | p95 | p99 |
|---|---:|---:|---:|
| Content checks only (signatures, PII, secrets, injection, heuristic AI review) | 0.36 ms | 0.55 ms | 0.67 ms |
| Blocked tool call, full decision (mandate, checks, data flow, audit) | 2.33 ms | 3.55 ms | 3.93 ms |
| Allowed tool call end to end (incl. Postgres budget escrow and the tool) | 7.05 ms | 9.81 ms | 13.4 ms |
| Chat, gateway overhead (end to end minus the 50 ms mock model) | ~9 ms | | |
| Throughput, mixed workload, 16 concurrent | 195 req/s | | |

Per stage (p50): mandate 0.20 ms · signatures 0.09 ms · patterns 0.20 ms · data flow 0.02 ms · AI review
(heuristic) 0.02 ms · budget escrow in Postgres 3.16 ms.

## Others (published figures, not measured by us)

| Product | Kind | Figure | Conditions | Source |
|---|---|---|---|---|
| Protect AI prompt-injection classifier v2 | DeBERTa classifier | 18.4 ms / sample | GPU V100 | [arXiv 2502.15427](https://arxiv.org/abs/2502.15427) |
| Lakera Guard | SaaS API | < 20 ms | 1,000-character input (< 100 ms at 10,000) | [Lakera latency benchmark](https://docs.lakera.ai/docs/latency-benchmark) |
| LLM Guard (Protect AI) | open-source scanners | 30–200 ms | depends on enabled scanners | [protectai.com/llm-guard](https://protectai.com/llm-guard) |
| Azure AI Content Safety Prompt Shields | cloud API | ~100–300 ms | per prompt | [TrueFoundry docs](https://www.truefoundry.com/docs/ai-gateway/azure-prompt-shield) |
| NVIDIA NeMo Guardrails | LLM rails | 491 ms / sample | Vicuna-13B v1.5, GPU V100 | [arXiv 2502.15427](https://arxiv.org/abs/2502.15427) |
| Llama Guard 3 8B | LLM guard | ~500 ms / request | Cloudflare AI Gateway guardrails | [Cloudflare docs](https://developers.cloudflare.com/ai-gateway/guardrails/usage-considerations/) |

## How to read it

- Methods and hardware differ; the other figures are as published by their authors. The comparison shows orders of
  magnitude, not a controlled head-to-head.
- Classifier and LLM guards answer "is this text malicious?" and generalise better to phrasings no rule anticipated.
  Aegis answers that deterministically in under a millisecond, and also decides what a text classifier cannot:
  whether this agent may use this tool, read this file, write to this recipient, spend this budget.
- With a local model plugged in (`LLM_BASE_URL`), the AI-review stage adds that model's latency. It can only tighten
  a decision, never loosen one, so permissions never depend on it.
- Aegis makes no network call to a third party for a decision, so there is no API round trip in its numbers.
