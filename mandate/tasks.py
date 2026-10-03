"""Task mandates: creation from trusted profiles, HMAC leases, delegation, taint."""

from __future__ import annotations

import fnmatch
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from mandate.models import Classification, GatewayError
from mandate.policy import Limit, Policy


@dataclass
class Task:
    id: str
    principal: str
    agent_id: str
    parent_id: str | None
    profile: str
    mandate: dict[str, Any]
    classification: Classification
    status: str
    synthetic: bool
    expires_at: datetime

    @classmethod
    def from_row(cls, r: asyncpg.Record) -> "Task":
        return cls(r["id"], r["principal"], r["agent_id"], r["parent_id"], r["profile"], r["mandate"],
                   Classification(r["classification"]), r["status"], r["synthetic"], r["expires_at"])

    def view(self) -> dict[str, Any]:
        return {"task_id": self.id, "principal": self.principal, "agent_id": self.agent_id,
                "parent_id": self.parent_id, "profile": self.profile, "mandate": self.mandate,
                "classification": self.classification.name, "status": self.status,
                "synthetic": self.synthetic, "expires_at": self.expires_at.isoformat()}

    # ---------------------------------------------------------- capability checks

    def allows_tool(self, tool: str) -> bool:
        return tool in self.mandate["tools"]

    def allows_resource(self, path: str) -> bool:
        if ".." in path:
            return False
        return any(fnmatch.fnmatchcase(path, p) for p in self.mandate["resources"])

    def allows_recipient(self, address: str) -> bool:
        address = address.strip().lower()
        return any(fnmatch.fnmatchcase(address, p.lower()) for p in self.mandate["recipients_allow"])

    def allows_model(self, model: str) -> bool:
        models = self.mandate.get("models")
        return models is None or model in models

    def sink_clearance(self, sink: str, policy: Policy) -> Classification:
        """effective = min(policy clearance, mandate narrowing)."""
        level = policy.sink_clearance(sink)
        narrowed = self.mandate.get("sinks", {}).get(sink)
        if narrowed is not None:
            level = min(level, Classification.parse(narrowed))
        return level


def _fill(pattern: str, params: dict[str, str]) -> str:
    for key, value in params.items():
        pattern = pattern.replace("{" + key + "}", value)
    return pattern


class TaskManager:
    def __init__(self, pool: asyncpg.Pool, lease_secret: str):
        self.pool = pool
        self._secret = lease_secret.encode()

    def _sign(self, task_id: str, agent_id: str, principal: str, expires_at: datetime) -> str:
        msg = f"{task_id}|{agent_id}|{principal}|{int(expires_at.timestamp())}".encode()
        return hmac.new(self._secret, msg, hashlib.sha256).hexdigest()[:32]

    def lease_for(self, task: Task) -> str:
        return f"{task.id}.{self._sign(task.id, task.agent_id, task.principal, task.expires_at)}"

    async def create(self, policy: Policy, *, principal: str, agent_id: str, profile: str,
                     params: dict[str, str] | None = None, purpose: str = "", synthetic: bool = False) -> Task:
        tp = policy.task_profiles.get(profile)
        if tp is None:
            raise GatewayError(400, "UNKNOWN_TASK_PROFILE", f"unknown task profile '{profile}'")
        params = {k: str(v) for k, v in (params or {}).items()}
        for value in params.values():
            if not value.replace("-", "").replace("_", "").isalnum():
                raise GatewayError(400, "INVALID_PARAM", "task params must be alphanumeric")
        mandate = {
            "case": params.get("client"),
            "resources": [_fill(p, params) for p in tp.resources],
            "tools": list(tp.tools),
            "recipients_allow": [_fill(p, params) for p in tp.recipients_allow],
            "sinks": dict(tp.sinks),
            "models": tp.models,
            "budget": tp.budget.model_dump(),
        }
        return await self._insert(principal, agent_id, profile, purpose, mandate, None,
                                  Classification.PUBLIC, tp.ttl_seconds, synthetic)

    async def _insert(self, principal, agent_id, profile, purpose, mandate, parent_id, classification,
                      ttl_seconds, synthetic) -> Task:
        task_id = "t_" + secrets.token_hex(6)
        expires = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        budget = Limit(**mandate["budget"])
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """INSERT INTO tasks (id, principal, agent_id, parent_id, profile, purpose, mandate,
                       classification, synthetic, expires_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING *""",
                task_id, principal, agent_id, parent_id, profile, purpose, mandate,
                int(classification), synthetic, expires,
            )
            await conn.execute(
                "INSERT INTO budgets (scope_id, token_limit, calls_limit, concurrency_limit) VALUES ($1,$2,$3,$4)",
                f"task:{task_id}", budget.tokens, budget.calls, budget.concurrency,
            )
        return Task.from_row(row)

    async def get(self, task_id: str) -> Task | None:
        row = await self.pool.fetchrow("SELECT * FROM tasks WHERE id=$1", task_id)
        return Task.from_row(row) if row else None

    async def verify(self, lease: str | None, agent_id: str) -> Task:
        """Lease must be genuine, bound to THIS agent, active and not expired."""
        if not lease or "." not in lease:
            raise GatewayError(401, "LEASE_REQUIRED", "missing X-Mandate-Lease")
        task_id, _, sig = lease.partition(".")
        task = await self.get(task_id)
        if task is None:
            raise GatewayError(403, "LEASE_INVALID", "unknown task")
        expected = self._sign(task.id, task.agent_id, task.principal, task.expires_at)
        if not hmac.compare_digest(sig, expected):
            raise GatewayError(403, "LEASE_INVALID", "lease signature mismatch")
        if task.agent_id != agent_id:
            raise GatewayError(403, "LEASE_AGENT_MISMATCH", "lease belongs to another agent")
        if task.status != "active":
            raise GatewayError(403, f"CAPABILITY_{task.status.upper()}", f"task is {task.status}")
        if task.expires_at <= datetime.now(timezone.utc):
            raise GatewayError(403, "CAPABILITY_EXPIRED", "mandate expired")
        return task

    async def set_status(self, task_id: str, status: str) -> bool:
        res = await self.pool.execute(
            "UPDATE tasks SET status=$2 WHERE (id=$1 OR parent_id=$1) AND status='active'", task_id, status
        )
        return res != "UPDATE 0"

    async def raise_taint(self, task_id: str, level: Classification) -> Classification:
        """Classification only goes up. Propagates to the parent (results flow back to it)."""
        new = await self.pool.fetchval(
            "UPDATE tasks SET classification = GREATEST(classification, $2) WHERE id=$1 RETURNING classification",
            task_id, int(level),
        )
        parent = await self.pool.fetchval("SELECT parent_id FROM tasks WHERE id=$1", task_id)
        if parent:
            await self.raise_taint(parent, level)
        return Classification(new)

    async def delegate(self, parent: Task, *, agent_id: str, tools: list[str] | None,
                       resources: list[str] | None, budget_tokens: int | None, purpose: str) -> Task:
        """Child mandate must be a subset of the parent's; child starts with the parent's taint."""
        pm = parent.mandate
        tools = tools if tools is not None else pm["tools"]
        resources = resources if resources is not None else pm["resources"]
        extra_tools = sorted(set(tools) - set(pm["tools"]))
        if extra_tools:
            raise GatewayError(403, "DELEGATION_ESCALATION", f"tools not in parent mandate: {extra_tools}")
        bad_res = [r for r in resources if not any(fnmatch.fnmatchcase(r, p) or r == p for p in pm["resources"])]
        if bad_res:
            raise GatewayError(403, "DELEGATION_ESCALATION", f"resources not in parent mandate: {bad_res}")
        parent_budget = Limit(**pm["budget"])
        tokens = budget_tokens if budget_tokens is not None else parent_budget.tokens
        if tokens > parent_budget.tokens:
            raise GatewayError(403, "DELEGATION_ESCALATION", "child budget larger than parent budget")
        mandate = dict(pm, tools=tools, resources=resources,
                       budget=dict(pm["budget"], tokens=tokens))
        ttl = max(1, int((parent.expires_at - datetime.now(timezone.utc)).total_seconds()))
        return await self._insert(parent.principal, agent_id, parent.profile, purpose, mandate, parent.id,
                                  parent.classification, ttl, parent.synthetic)

    async def ancestry(self, task: Task) -> list[str]:
        """Task id and all ancestors (budget is charged to every level)."""
        ids, current = [task.id], task.parent_id
        while current:
            ids.append(current)
            current = await self.pool.fetchval("SELECT parent_id FROM tasks WHERE id=$1", current)
        return ids
