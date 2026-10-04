# Aegis performance report

* generated: `2026-10-04T04:46:19` by `make bench`
* machine: Linux-6.18.44-fc-v64-x86_64-with-glibc2.39 · x86_64 · 4 logical cores · Python 3.12.3
* run: 150 measured requests per workload (+12 warm-up, excluded), 168 mixed requests per concurrency level

Methodology: the real gateway pipeline in-process (real Postgres, real tool backends over ASGI, mandate, budget escrow, taint, detectors). Model = `mock/echo` (its fixed 50 ms generation delay is the `model_call` stage), semantic guard = the local heuristic backend. Rate limits and the circuit breaker are lifted in the benchmark policy so the pipeline itself is measured; everything else is production code.

## End-to-end decision latency (sequential, ms)

| workload | decision | p50 | p95 | p99 |
|---|---|---:|---:|---:|
| chat: clean prompt | ALLOW | 59.1 | 62.0 | 64.3 |
| chat: PII redacted | REDACT | 59.5 | 64.2 | 93.7 |
| chat: prompt injection | REDACT | 60.3 | 65.8 | 83.3 |
| tool: doc.read (taint raise) | ALLOW | 10.6 | 16.2 | 21.0 |
| tool: notes.write ALLOW | ALLOW | 7.05 | 9.81 | 13.4 |
| tool: mail BLOCK (data flow) | BLOCK | 2.33 | 3.55 | 3.93 |
| guard only: playground | REDACT | 0.36 | 0.55 | 0.67 |

## Per-stage latency (across all measured decisions, ms)

| stage | samples | p50 | p95 | p99 |
|---|---:|---:|---:|---:|
| mandate | 900 | 0.20 | 0.61 | 0.83 |
| signatures | 900 | 0.09 | 0.16 | 0.54 |
| deterministic | 900 | 0.20 | 0.55 | 0.98 |
| data_flow | 300 | 0.02 | 0.03 | 0.05 |
| semantic | 600 | 0.02 | 0.03 | 0.06 |
| budget | 900 | 3.16 | 5.36 | 8.83 |
| execute | 300 | 1.83 | 2.83 | 3.08 |
| model_call | 450 | 50.4 | 50.5 | 51.1 |
| output_deterministic | 450 | 0.06 | 0.10 | 0.23 |
| output_signatures | 450 | 0.10 | 0.15 | 0.19 |
| result_deterministic | 150 | 0.85 | 1.37 | 1.58 |
| result_semantic | 150 | 0.03 | 0.04 | 0.08 |
| result_signatures | 150 | 0.10 | 0.14 | 0.23 |

**Deterministic guard (playground dry run):** p50 0.36 ms · p95 0.55 ms · p99 0.67 ms — this is the cost of protection itself, excluding any model call.

## Throughput (mixed workload, requests/s)

| concurrency | requests | wall time | req/s |
|---:|---:|---:|---:|
| 1 | 168 | 5.2 s | 32.4 |
| 4 | 168 | 1.7 s | 101.6 |
| 16 | 168 | 0.9 s | 195.3 |

Reproduce: `make bench` (writes `docs/bench-report.md`). Figures describe the machine listed above; on hardware with a model server the `model_call` stage is the model's latency.
