"""Append-only audit log (Postgres), live event bus (SSE), reporting queries."""

from __future__ import annotations

import asyncio
import csv
import io
import json
from typing import Any

import asyncpg

from aegis.models import Decision


class Audit:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self._subscribers: set[asyncio.Queue] = set()

    # ------------------------------------------------------------ writing

    async def decision(
        self,
        decision: Decision,
        *,
        channel: str,
        target: str,
        principal: str | None,
        synthetic: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> None:
        evidence = decision.public() | (extra or {})
        row = await self.pool.fetchrow(
            """INSERT INTO audit_events (task_id, principal, kind, channel, target, action, reason_code,
                   rule_id, stage, policy_version, latency_ms, tool_invoked, synthetic, evidence)
               VALUES ($1,$2,'DECISION',$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13) RETURNING id, ts""",
            decision.task_id, principal, channel, target, decision.action, decision.reason_code,
            decision.rule_id, decision.stage, decision.policy_version, decision.latency_ms,
            decision.tool_invoked, synthetic, evidence,
        )
        if not synthetic:
            self._publish({"id": row["id"], "ts": row["ts"].isoformat(), "kind": "DECISION", "channel": channel,
                           "target": target, "task_id": decision.task_id, "principal": principal,
                           "action": decision.action, "rule_id": decision.rule_id,
                           "reason_code": decision.reason_code, "latency_ms": round(decision.latency_ms, 2),
                           "tool_invoked": decision.tool_invoked})

    async def system(self, kind: str, *, actor: str, evidence: dict[str, Any],
                     policy_version: str | None = None, task_id: str | None = None) -> None:
        row = await self.pool.fetchrow(
            "INSERT INTO audit_events (kind, principal, task_id, policy_version, evidence) "
            "VALUES ($1,$2,$3,$4,$5) RETURNING id, ts",
            kind, actor, task_id, policy_version, evidence,
        )
        self._publish({"id": row["id"], "ts": row["ts"].isoformat(), "kind": kind, "principal": actor,
                       "policy_version": policy_version, "task_id": task_id})

    # ------------------------------------------------------------ live bus

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def _publish(self, event: dict[str, Any]) -> None:
        for q in list(self._subscribers):
            if q.full():
                q.get_nowait()
            q.put_nowait(event)

    # ------------------------------------------------------------ reading

    async def query(self, *, task_id=None, rule_id=None, action=None, kind=None, since=None,
                    include_synthetic=False, limit=200) -> list[dict[str, Any]]:
        clauses, args = [], []
        for col, val in (("task_id", task_id), ("rule_id", rule_id), ("action", action), ("kind", kind)):
            if val:
                args.append(val)
                clauses.append(f"{col} = ${len(args)}")
        if since:
            args.append(since)
            clauses.append(f"ts >= ${len(args)}")
        if not include_synthetic:
            clauses.append("NOT synthetic")
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        args.append(min(int(limit), 10_000))
        rows = await self.pool.fetch(
            f"SELECT * FROM audit_events {where} ORDER BY id DESC LIMIT ${len(args)}", *args
        )
        return [_row(r) for r in rows]

    async def export(self, fmt: str, **filters: Any) -> str:
        rows = await self.query(limit=10_000, **filters)
        if fmt == "csv":
            buf = io.StringIO()
            cols = ["id", "ts", "kind", "channel", "target", "task_id", "principal", "action", "reason_code",
                    "rule_id", "stage", "policy_version", "latency_ms", "tool_invoked", "synthetic"]
            writer = csv.DictWriter(buf, fieldnames=cols + ["evidence"])
            writer.writeheader()
            for r in rows:
                writer.writerow({c: r.get(c) for c in cols} | {"evidence": json.dumps(r["evidence"])})
            return buf.getvalue()
        return "\n".join(json.dumps(r, default=str) for r in rows) + ("\n" if rows else "")

    async def stats(self, include_synthetic: bool = False) -> dict[str, Any]:
        syn = "" if include_synthetic else "AND NOT synthetic"
        counts = await self.pool.fetch(
            f"SELECT action, count(*) n FROM audit_events WHERE kind='DECISION' {syn} GROUP BY action"
        )
        by_channel = await self.pool.fetch(
            f"SELECT channel, action, count(*) n FROM audit_events WHERE kind='DECISION' {syn} "
            "GROUP BY channel, action ORDER BY channel"
        )
        top_rules = await self.pool.fetch(
            f"SELECT rule_id, reason_code, action, count(*) n FROM audit_events WHERE kind='DECISION' "
            f"AND action <> 'ALLOW' {syn} GROUP BY rule_id, reason_code, action ORDER BY n DESC LIMIT 10"
        )
        latency = await self.pool.fetchrow(
            f"""SELECT count(*) n,
                   percentile_cont(0.5)  WITHIN GROUP (ORDER BY latency_ms) p50,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) p95,
                   percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_ms) p99
               FROM audit_events WHERE kind='DECISION' {syn}"""
        )
        stages = await self.pool.fetch(
            f"""SELECT key stage, count(*) n,
                   percentile_cont(0.5)  WITHIN GROUP (ORDER BY value::float) p50,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY value::float) p95
               FROM audit_events, jsonb_each_text(evidence->'timings')
               WHERE kind='DECISION' {syn} GROUP BY key ORDER BY key"""
        )
        timeline = await self.pool.fetch(
            f"""SELECT date_trunc('minute', ts) AS bucket, action, count(*) n FROM audit_events
               WHERE kind='DECISION' AND ts > now() - interval '60 minutes' {syn}
               GROUP BY 1, 2 ORDER BY 1"""
        )
        return {
            "totals": {r["action"]: r["n"] for r in counts},
            "by_channel": [dict(r) for r in by_channel],
            "top_rules": [dict(r) for r in top_rules],
            "latency_ms": {k: (round(latency[k], 3) if latency[k] is not None else None)
                           for k in ("p50", "p95", "p99")} | {"n": latency["n"]},
            "stages": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in dict(r).items()}
                       for r in stages],
            "timeline": [{"minute": r["bucket"].isoformat(), "action": r["action"], "n": r["n"]}
                         for r in timeline],
        }


def _row(r: asyncpg.Record) -> dict[str, Any]:
    d = dict(r)
    d["ts"] = d["ts"].isoformat()
    return d
