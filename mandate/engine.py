"""The control layer pipeline. Every channel (model, tool, MCP, delegation) goes through here.

Order: mandate/allowlist -> signatures -> secrets/PII -> data-flow (taint) -> injection -> semantic
-> budget escrow -> EXECUTE -> post checks on the response -> audit.
First BLOCK short-circuits; the semantic model can only tighten a decision.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

import asyncpg
import httpx

from mandate import detectors
from mandate.attacks import FeedStore
from mandate.audit import Audit
from mandate.budget import BudgetExceeded, Escrow, Scope
from mandate.llm import LLMError, complete, estimate_tokens
from mandate.models import Classification, Decision, Finding, GatewayError
from mandate.policy import Limit, Policy, PolicyStore
from mandate.semantic import SemanticGuard
from mandate.settings import Settings
from mandate.tasks import Task, TaskManager


@dataclass(frozen=True)
class ToolSpec:
    content_args: tuple[str, ...] = ()
    resource_arg: str | None = None
    recipient_arg: str | None = None
    reads: bool = False           # result carries resource data (taint source)
    writes: bool = True           # args leave the agent (data-flow sink)
    internal: bool = False        # implemented inside the gateway

    def sink(self, tool: str, args: dict[str, Any], policy: Policy) -> str:
        if tool == "mail.send":
            domain = str(args.get("to", "")).rpartition("@")[2].lower()
            return "mail.send:internal" if domain in [d.lower() for d in policy.internal_domains] else "mail.send:external"
        return tool


TOOLS: dict[str, ToolSpec] = {
    "doc.read": ToolSpec(resource_arg="path", reads=True, writes=False),
    "legal_db.search": ToolSpec(content_args=("query",), reads=True),
    "notes.write": ToolSpec(content_args=("title", "body")),
    "mail.send": ToolSpec(content_args=("subject", "body"), recipient_arg="to"),
    "http.post": ToolSpec(content_args=("url", "body")),
    "code.run": ToolSpec(content_args=("code",)),
    "memory.write": ToolSpec(content_args=("key", "content"), internal=True),
    "memory.read": ToolSpec(content_args=(), reads=True, writes=False, internal=True),
}

LOCAL_TOOL_DEFS = [
    {"name": "memory.write", "description": "Store a note in case-scoped agent memory.",
     "inputSchema": {"type": "object", "properties": {"key": {"type": "string"}, "content": {"type": "string"}},
                     "required": ["key", "content"]}},
    {"name": "memory.read", "description": "Read a note from case-scoped agent memory.",
     "inputSchema": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]}},
]


class _Timer:
    def __init__(self, decision: Decision):
        self.d = decision

    def __call__(self, stage: str):
        timer = self

        class _Ctx:
            def __enter__(self):
                self.t = time.perf_counter()

            def __exit__(self, *exc):
                timer.d.timings[stage] = timer.d.timings.get(stage, 0.0) + (time.perf_counter() - self.t) * 1000
        return _Ctx()


def tool_def_hash(definition: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()


class Gateway:
    def __init__(self, settings: Settings, pool: asyncpg.Pool, policy: PolicyStore, feed: FeedStore,
                 audit: Audit, semantic: SemanticGuard, tool_client: httpx.AsyncClient):
        self.settings = settings
        self.pool = pool
        self.policy = policy
        self.feed = feed
        self.audit = audit
        self.semantic = semantic
        self.tasks = TaskManager(pool, settings.lease_secret)
        self.escrow = Escrow(pool)
        self.tools_http = tool_client

    # ================================================================ models

    def default_model(self, policy: Policy) -> str:
        """The main model server when configured (OpenRouter now, GB10 later), else the policy default."""
        return self.settings.main_model_id if self.settings.main_configured else policy.models.default

    def model_sink(self, policy: Policy, model: str) -> str:
        if model.startswith("main/"):  # where the main server lives decides what data may reach it
            return "llm:onprem" if self.settings.llm_location == "onprem" else "llm:external"
        return policy.model_sink(model)

    # ================================================================ auth

    def agent_id(self, authorization: str | None) -> str:
        key = (authorization or "").removeprefix("Bearer ").strip()
        agent = self.settings.agent_keys.get(key)
        if not agent:
            raise GatewayError(401, "AGENT_UNAUTHENTICATED", "unknown agent key")
        return agent

    # ================================================================ shared checks

    def content_checks(self, decision: Decision, policy: Policy, text: str, *, target: str,
                       tool: str | None = None, pii: bool = True) -> None:
        c = policy.controls
        t = _Timer(decision)
        if c.attack_signatures.enabled:
            with t("signatures"):
                for f in self.feed.scan_text(text, target, c.attack_signatures.mode, tool):
                    decision.add(f)
        if c.secrets.enabled:
            with t("deterministic"):
                if f := detectors.secrets_finding(text, c.secrets.mode):
                    decision.add(f)
        if pii and c.pii.enabled:
            with t("deterministic"):
                if f := detectors.pii_finding(text, c.pii.entities, c.pii.mode):
                    decision.add(f)
        if target in ("user_input", "tool_results", "file_content") and c.injection_heuristics.enabled:
            with t("deterministic"):
                if f := detectors.injection_finding(text, c.injection_heuristics.mode):
                    decision.add(f)

    async def semantic_check(self, decision: Decision, policy: Policy, text: str, task: Task | None) -> None:
        cfg = policy.controls.semantic
        if not cfg.enabled or decision.blocked or not text.strip():
            return
        t0 = time.perf_counter()
        guard_res = None
        if self.semantic.backend_for(cfg) != "heuristic":
            try:  # the guard has its own budget: the cost of protection is accounted for
                guard_res = await self.escrow.reserve(task.id if task else None, [
                    Scope("guard", policy.budgets.guard)], tokens=estimate_tokens(text) + 150)
            except BudgetExceeded as exc:
                decision.add(Finding(action="BLOCK", rule_id="BUD-GUARD", reason_code="GUARD_BUDGET_EXCEEDED",
                                     stage="semantic", detail={"scope": exc.scope_id}))
                return
        result = await self.semantic.classify(text, cfg)
        if guard_res:
            await self.escrow.settle(guard_res, estimate_tokens(text) + 150)
        decision.timings["semantic"] = (time.perf_counter() - t0) * 1000
        if f := SemanticGuard.to_finding(result, cfg):
            decision.add(f)
        else:
            decision.findings.append(Finding(action="ALLOW", rule_id="SEM-000", reason_code="SEMANTIC_OK",
                                             stage="semantic", detail={"risk": result.risk,
                                                                       "backend": result.backend}))

    def taint_check(self, decision: Decision, policy: Policy, task: Task, sink: str) -> None:
        if not policy.controls.ifc_taint.enabled:
            return
        clearance = task.sink_clearance(sink, policy)
        if task.classification > clearance:
            decision.add(Finding(
                action="BLOCK", rule_id="IFC-001", reason_code="DATA_FLOW_VIOLATION", stage="data_flow",
                detail={"task_classification": task.classification.name, "sink": sink,
                        "sink_clearance": clearance.name},
            ))

    def budget_scopes(self, policy: Policy, task: Task, ancestry: list[str],
                      principal_limit: Limit | None = None) -> list[Scope]:
        scopes = [Scope(f"task:{tid}") for tid in ancestry]
        scopes.append(Scope(f"principal:{task.principal}", principal_limit or policy.budgets.per_principal))
        if not task.synthetic:
            scopes.append(Scope("global", policy.budgets.global_))
        return scopes

    async def _finish(self, decision: Decision, t0: float, *, channel: str, target: str, task: Task | None,
                      extra: dict | None = None) -> None:
        decision.latency_ms = (time.perf_counter() - t0) * 1000
        await self.audit.decision(decision, channel=channel, target=target,
                                  principal=task.principal if task else None,
                                  synthetic=bool(task and task.synthetic), extra=extra)

    # ================================================================ agent <-> model

    async def chat(self, agent_id: str, lease: str | None, body: dict[str, Any],
                   principal_limit: Limit | None = None) -> tuple[int, dict[str, Any]]:
        t0 = time.perf_counter()
        task = await self.tasks.verify(lease, agent_id)
        policy = self.policy.active
        d = Decision(policy_version=self.policy.version, task_id=task.id)
        timer = _Timer(d)
        model = body.get("model") or self.default_model(policy)
        messages = [dict(m) for m in body.get("messages", [])]
        if body.get("stream"):
            body = dict(body, stream=False)  # responses are buffered and checked before release
        with timer("mandate"):
            if policy.controls.model_allowlist.enabled and not policy.model_allowed(model):
                d.add(Finding(action="BLOCK", rule_id="MODEL-001", reason_code="MODEL_NOT_ALLOWED",
                              stage="mandate", detail={"model": model}))
            if policy.controls.mandate.enabled and not task.allows_model(model):
                d.add(Finding(action="BLOCK", rule_id="MANDATE-MODEL", reason_code="MODEL_NOT_IN_MANDATE",
                              stage="mandate", detail={"model": model}))
            self.taint_check(d, policy, task, self.model_sink(policy, model))
        untrusted = []
        if not d.blocked:
            for i, m in enumerate(messages):
                role, content = m.get("role"), str(m.get("content", ""))
                target = "tool_results" if role == "tool" else "user_input"
                if role == "assistant":
                    continue
                sub = Decision()
                self.content_checks(sub, policy, content, target=target)
                for f in sub.findings:
                    f.detail["message_index"] = i
                    d.add(f)
                if sub.action == "REDACT":
                    messages[i]["content"] = detectors.redact(content, [s for f in sub.findings for s in f.spans])
                if role in ("user", "tool"):
                    untrusted.append(messages[i]["content"])
                d.timings.update({k: d.timings.get(k, 0) + v for k, v in sub.timings.items()})
        if not d.blocked and untrusted:
            await self.semantic_check(d, policy, "\n\n".join(untrusted), task)
        if d.blocked:
            await self._finish(d, t0, channel="model", target=model, task=task)
            return 403, _blocked(d)

        max_tokens = int(body.get("max_tokens") or policy.budgets.default_max_tokens)
        prompt_tokens = estimate_tokens("\n".join(str(m.get("content", "")) for m in messages))
        reserve = prompt_tokens + max_tokens
        try:
            with timer("budget"):
                ancestry = await self.tasks.ancestry(task)
                res_id = await self.escrow.reserve(task.id, self.budget_scopes(policy, task, ancestry, principal_limit),
                                                   reserve)
        except BudgetExceeded as exc:
            d.add(Finding(action="BLOCK", rule_id="BUD-001", reason_code="BUDGET_EXCEEDED", stage="budget",
                          detail={"scope": exc.scope_id, "dimension": exc.dimension, "requested": reserve}))
            await self._finish(d, t0, channel="model", target=model, task=task)
            return 429, _blocked(d)

        try:
            t_model = time.perf_counter()
            out = await complete(model, messages, max_tokens, providers=self.settings.providers,
                                 extra_body=self.settings.llm_extra_body)
            d.timings["model_call"] = (time.perf_counter() - t_model) * 1000
        except LLMError as exc:
            await self.escrow.mark_uncertain(res_id)
            d.add(Finding(action="BLOCK", rule_id="UPSTREAM", reason_code="MODEL_UNAVAILABLE", stage="execute",
                          detail={"error": str(exc)}))
            await self._finish(d, t0, channel="model", target=model, task=task)
            return 502, _blocked(d)
        used = out.prompt_tokens + out.completion_tokens
        await self.escrow.settle(res_id, used)

        # ---- output filter: the model's answer is checked before it is released
        post = Decision()
        self.content_checks(post, policy, out.content, target="model_output")
        for f in post.findings:
            f.detail["phase"] = "output"
            d.add(f)
        d.timings.update({f"output_{k}": v for k, v in post.timings.items()})
        content = out.content
        if post.action == "BLOCK":
            content = None
        elif post.action == "REDACT":
            content = detectors.redact(out.content, [s for f in post.findings for s in f.spans])
        usage = {"prompt_tokens": out.prompt_tokens, "completion_tokens": out.completion_tokens,
                 "total_tokens": used, "reserved_tokens": reserve,
                 "estimated_cost_usd": round(used / 1000 * policy.budgets.usd_per_1k_tokens, 6)}
        await self._finish(d, t0, channel="model", target=model, task=task, extra={"usage": usage})
        if content is None:
            return 403, _blocked(d)
        return 200, {
            "id": "chatcmpl-" + res_id[:12], "object": "chat.completion", "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": usage, "mandate": d.public(),
        }

    # ================================================================ agent <-> tool / MCP

    async def tool_call(self, agent_id: str, lease: str | None, tool: str, args: dict[str, Any],
                        channel: str = "tool") -> tuple[int, dict[str, Any]]:
        t0 = time.perf_counter()
        task = await self.tasks.verify(lease, agent_id)
        policy = self.policy.active
        d = Decision(policy_version=self.policy.version, task_id=task.id)
        timer = _Timer(d)
        spec = TOOLS.get(tool)
        target = tool
        with timer("mandate"):
            if spec is None:
                d.add(Finding(action="BLOCK", rule_id="TOOL-UNKNOWN", reason_code="UNKNOWN_TOOL", stage="mandate",
                              detail={"tool": tool}))
            elif policy.controls.mandate.enabled:
                if not task.allows_tool(tool):
                    d.add(Finding(action="BLOCK", rule_id="MANDATE-TOOL", reason_code="TOOL_NOT_IN_MANDATE",
                                  stage="mandate", detail={"tool": tool, "allowed": task.mandate["tools"]}))
                if spec.resource_arg:
                    path = str(args.get(spec.resource_arg, ""))
                    target = f"{tool}:{path}"
                    if not task.allows_resource(path):
                        d.add(Finding(action="BLOCK", rule_id="MANDATE-RES", reason_code="RESOURCE_NOT_IN_MANDATE",
                                      stage="mandate", detail={"resource": path}))
                if spec.recipient_arg:
                    to = str(args.get(spec.recipient_arg, ""))
                    target = f"{tool}:{to}"
                    if not task.allows_recipient(to):
                        d.add(Finding(action="BLOCK", rule_id="MANDATE-RCPT", reason_code="RECIPIENT_NOT_ALLOWED",
                                      stage="mandate", detail={"recipient": to,
                                                               "allowed": task.mandate["recipients_allow"]}))
            if spec and not spec.internal:
                status = await self.pool.fetchval("SELECT status FROM tool_registry WHERE name=$1", tool)
                if status == "quarantined":
                    sig = self.feed.tool_poison_signature()
                    d.add(Finding(action="BLOCK", rule_id=sig.id if sig else "ATK-MCP-POISON", stage="signatures",
                                  reason_code="TOOL_QUARANTINED", detail={"tool": tool}))
        sink = spec.sink(tool, args, policy) if spec else tool
        if spec and not d.blocked:
            outbound = "\n".join(str(args.get(a, "")) for a in spec.content_args if args.get(a))
            if outbound:
                # PII rule: content leaving the trust boundary (sink below CONFIDENTIAL) is PII-checked;
                # confidential internal stores (notes, memory, internal mail) may hold PII by design.
                pii_applies = spec.writes and task.sink_clearance(sink, policy) < Classification.CONFIDENTIAL
                sub = Decision()
                self.content_checks(sub, policy, outbound, target="tool_args", tool=tool, pii=pii_applies)
                for f in sub.findings:
                    d.add(f)
                d.timings.update(sub.timings)
                if sub.action == "REDACT":
                    args = dict(args)
                    for a in spec.content_args:
                        if isinstance(args.get(a), str):
                            args[a] = self._redact_all(args[a], policy, tool, pii_applies)
            if spec.writes:
                with timer("data_flow"):
                    self.taint_check(d, policy, task, sink)
        if d.blocked:
            await self._finish(d, t0, channel=channel, target=target, task=task, extra={"sink": sink})
            return 403, _blocked(d)

        try:
            with timer("budget"):
                ancestry = await self.tasks.ancestry(task)
                res_id = await self.escrow.reserve(task.id, self.budget_scopes(policy, task, ancestry), tokens=0)
        except BudgetExceeded as exc:
            d.add(Finding(action="BLOCK", rule_id="BUD-002", reason_code="BUDGET_EXCEEDED", stage="budget",
                          detail={"scope": exc.scope_id, "dimension": exc.dimension}))
            await self._finish(d, t0, channel=channel, target=target, task=task)
            return 429, _blocked(d)

        try:
            t_exec = time.perf_counter()
            result = await self._execute(task, tool, args)
            d.timings["execute"] = (time.perf_counter() - t_exec) * 1000
            d.tool_invoked = True
        except GatewayError as exc:
            await self.escrow.settle(res_id, 0)
            d.add(Finding(action="BLOCK", rule_id=exc.reason_code, reason_code=exc.reason_code, stage="execute",
                          detail={"error": exc.message}))
            await self._finish(d, t0, channel=channel, target=target, task=task)
            return exc.status, _blocked(d)
        except httpx.HTTPError as exc:
            await self.escrow.mark_uncertain(res_id)
            d.add(Finding(action="BLOCK", rule_id="UPSTREAM", reason_code="TOOL_UNAVAILABLE", stage="execute",
                          detail={"error": type(exc).__name__}))
            await self._finish(d, t0, channel=channel, target=target, task=task)
            return 502, _blocked(d)
        await self.escrow.settle(res_id, 0)

        # ---- post: taint from what was read, then inspect what the agent is about to read
        extra: dict[str, Any] = {"sink": sink}
        label = result.pop("_label", None)
        if spec.reads and label is not None and policy.controls.ifc_taint.enabled:
            new_level = await self.tasks.raise_taint(task.id, Classification(label))
            extra["taint"] = {"source": target, "label": Classification(label).name, "task_now": new_level.name}
        content = result.get("content")
        if isinstance(content, str) and content:
            post = Decision()
            self.content_checks(post, policy, content, target="tool_results", pii=False)
            await self.semantic_check(post, policy, content, task)
            for f in post.findings:
                f.detail["phase"] = "result"
                d.add(f)
            d.timings.update({f"result_{k}": v for k, v in post.timings.items()})
            if post.action == "BLOCK":
                result = {"content": None, "withheld": True}
            elif post.action == "REDACT":
                spans = [s for f in post.findings for s in f.spans]
                result = dict(result, content=detectors.redact(content, spans) if spans
                              else "[WITHHELD: content flagged as suspicious by the semantic guard]")
        await self._finish(d, t0, channel=channel, target=target, task=task, extra=extra)
        if d.blocked:
            return 403, _blocked(d) | {"tool_invoked": True}
        return 200, {"result": result, "mandate": d.public()}

    def _redact_all(self, text: str, policy: Policy, tool: str, pii: bool) -> str:
        spans = detectors.find_secrets(text) if policy.controls.secrets.enabled else []
        if pii and policy.controls.pii.enabled:
            spans += detectors.find_pii(text, policy.controls.pii.entities)
        for f in self.feed.scan_text(text, "tool_args", "redact", tool):
            spans += f.spans
        return detectors.redact(text, spans)

    async def _execute(self, task: Task, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool == "memory.write":
            await self.pool.execute(
                "INSERT INTO memory_entries (case_id, key, classification, source_task, content) VALUES ($1,$2,$3,$4,$5)",
                task.mandate.get("case") or "-", str(args.get("key")), int(task.classification), task.id,
                str(args.get("content", "")),
            )
            return {"stored": True, "classification": task.classification.name}
        if tool == "memory.read":
            case = task.mandate.get("case") or "-"
            key = str(args.get("key"))
            row = await self.pool.fetchrow(
                "SELECT * FROM memory_entries WHERE key=$1 AND case_id=$2 ORDER BY id DESC LIMIT 1", key, case)
            if row is None:
                if await self.pool.fetchval("SELECT 1 FROM memory_entries WHERE key=$1 AND case_id<>$2 LIMIT 1",
                                            key, case):
                    raise GatewayError(403, "MEMORY_CROSS_CASE", "memory entry belongs to another case")
                raise GatewayError(404, "MEMORY_NOT_FOUND", "no such memory entry")
            return {"content": row["content"], "_label": row["classification"]}
        resp = await self.tools_http.post(
            f"/tools/{tool}", json={"args": args, "task_id": task.id},
            headers={"X-Backend-Secret": self.settings.tool_backend_secret},
        )
        if resp.status_code >= 400:
            raise GatewayError(resp.status_code, "TOOL_ERROR", resp.text[:200])
        result = resp.json()
        if tool == "doc.read":
            label = await self.pool.fetchval("SELECT label FROM documents WHERE path=$1", args.get("path"))
            # not in the trusted catalog => treat as CONFIDENTIAL (conservative)
            result["_label"] = int(Classification.CONFIDENTIAL) if label is None else label
        elif tool == "legal_db.search":
            result["_label"] = int(Classification.PUBLIC)  # public case law
        return result

    # ================================================================ MCP (JSON-RPC over HTTP)

    async def sync_tool_registry(self) -> list[dict[str, Any]]:
        """Trust-on-first-use; a changed definition is quarantined until an admin re-approves it."""
        resp = await self.tools_http.get("/tools", headers={"X-Backend-Secret": self.settings.tool_backend_secret})
        resp.raise_for_status()
        approved = []
        for definition in resp.json()["tools"]:
            digest = tool_def_hash(definition)
            row = await self.pool.fetchrow("SELECT * FROM tool_registry WHERE name=$1", definition["name"])
            if row is None:
                await self.pool.execute(
                    "INSERT INTO tool_registry (name, definition, definition_hash, status, approved_at) "
                    "VALUES ($1,$2,$3,'approved',now()) ON CONFLICT DO NOTHING",
                    definition["name"], definition, digest)
                approved.append(definition)
            elif row["definition_hash"] == digest and row["status"] == "approved":
                approved.append(definition)
            elif row["definition_hash"] != digest and (row["pending_definition"] or {}) != definition:
                await self.pool.execute(
                    "UPDATE tool_registry SET status='quarantined', pending_definition=$2, updated_at=now() WHERE name=$1",
                    definition["name"], definition)
                sig = self.feed.tool_poison_signature()
                d = Decision(policy_version=self.policy.version, action="BLOCK",
                             reason_code="TOOL_DEFINITION_CHANGED", rule_id=sig.id if sig else "ATK-MCP-POISON",
                             stage="signatures")
                await self.audit.decision(d, channel="mcp", target=definition["name"], principal=None,
                                          extra={"old_hash": row["definition_hash"][:12], "new_hash": digest[:12]})
        return approved

    async def approve_tool(self, name: str, actor: str) -> bool:
        """Approve the definition the MCP server serves NOW (after review), not a stale pending copy."""
        row = await self.pool.fetchrow("SELECT * FROM tool_registry WHERE name=$1", name)
        if row is None:
            return False
        definition = row["pending_definition"] or row["definition"]
        try:
            resp = await self.tools_http.get("/tools", headers={"X-Backend-Secret": self.settings.tool_backend_secret})
            definition = next((t for t in resp.json()["tools"] if t["name"] == name), definition)
        except httpx.HTTPError:
            pass
        await self.pool.execute(
            "UPDATE tool_registry SET definition=$2, definition_hash=$3, pending_definition=NULL, status='approved', "
            "approved_at=now(), updated_at=now() WHERE name=$1", name, definition, tool_def_hash(definition))
        await self.audit.system("TOOL_APPROVED", actor=actor, evidence={"tool": name,
                                                                        "hash": tool_def_hash(definition)[:12]})
        return True

    async def mcp(self, agent_id: str, lease: str | None, message: dict[str, Any]) -> dict[str, Any]:
        rpc_id, method, params = message.get("id"), message.get("method"), message.get("params") or {}

        def ok(result):
            return {"jsonrpc": "2.0", "id": rpc_id, "result": result}

        if method == "initialize":
            return ok({"protocolVersion": "2025-06-18", "serverInfo": {"name": "mandate-gateway", "version": "0.1"},
                       "capabilities": {"tools": {"listChanged": True}}})
        if method in ("notifications/initialized", "ping"):
            return ok({})
        task = await self.tasks.verify(lease, agent_id)
        if method == "tools/list":
            tools = await self.sync_tool_registry() + LOCAL_TOOL_DEFS
            visible = [t for t in tools if task.allows_tool(t["name"]) or not self.policy.active.controls.mandate.enabled]
            return ok({"tools": visible})
        if method == "tools/call":
            if params.get("name") in TOOLS and not TOOLS[params["name"]].internal:
                await self.sync_tool_registry()
            status, body = await self.tool_call(agent_id, lease, params.get("name", ""), params.get("arguments") or {},
                                                channel="mcp")
            text = json.dumps(body.get("result") if status == 200 else body)
            return ok({"content": [{"type": "text", "text": text}], "isError": status != 200,
                       "_meta": {"mandate": body.get("mandate")}})
        return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32601, "message": f"unknown method {method}"}}

    # ================================================================ supply chain

    async def register_model(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        t0 = time.perf_counter()
        policy = self.policy.active
        d = Decision(policy_version=self.policy.version)
        mode = policy.controls.attack_signatures.mode
        if policy.controls.attack_signatures.enabled:
            with _Timer(d)("signatures"):
                findings = []
                if payload.get("source_url"):
                    findings += self.feed.scan_model_source(payload["source_url"], mode)
                findings += self.feed.scan_component(payload.get("packages") or {}, mode)
                template = (payload.get("gguf_metadata") or {}).get("tokenizer.chat_template")
                if template:
                    findings += self.feed.scan_gguf_template(template, mode)
                for name, b64 in (payload.get("files") or {}).items():
                    data = base64.b64decode(b64)
                    if name.endswith((".pkl", ".pickle", ".pt", ".pth", ".bin", ".joblib")) or data[:1] == b"\x80":
                        for f in self.feed.scan_pickle(data, mode):
                            f.detail["file"] = name
                            findings.append(f)
                for f in findings:
                    d.add(f)
        await self._finish(d, t0, channel="model_register", target=str(payload.get("name")), task=None)
        return (403 if d.blocked else 200), {"accepted": not d.blocked, "mandate": d.public()}

    # ================================================================ playground

    async def evaluate(self, text: str, *, target: str = "user_input", sink: str | None = None,
                       classification: str = "PUBLIC", tool: str | None = None) -> dict[str, Any]:
        """Dry run for the jury: decision only, nothing is executed."""
        t0 = time.perf_counter()
        policy = self.policy.active
        d = Decision(policy_version=self.policy.version)
        pii = True
        if sink:
            pii = policy.sink_clearance(sink) < Classification.CONFIDENTIAL or target != "tool_args"
        self.content_checks(d, policy, text, target=target, tool=tool, pii=pii)
        if sink and policy.controls.ifc_taint.enabled:
            level, clearance = Classification.parse(classification), policy.sink_clearance(sink)
            if level > clearance:
                d.add(Finding(action="BLOCK", rule_id="IFC-001", reason_code="DATA_FLOW_VIOLATION", stage="data_flow",
                              detail={"task_classification": level.name, "sink": sink, "sink_clearance": clearance.name}))
        if target in ("user_input", "tool_results", "file_content"):
            await self.semantic_check(d, policy, text, None)
        redacted = detectors.redact(text, [s for f in d.findings for s in f.spans]) if d.action == "REDACT" else None
        await self._finish(d, t0, channel="playground", target=sink or target, task=None)
        return {"decision": d.public(), "redacted": redacted, "executed": False}


def _blocked(d: Decision) -> dict[str, Any]:
    return {"error": {"type": "mandate_blocked", "reason_code": d.reason_code, "rule_id": d.rule_id},
            "mandate": d.public()}


async def gather_limited(coros, limit: int):
    sem = asyncio.Semaphore(limit)

    async def run(c):
        async with sem:
            return await c
    return await asyncio.gather(*(run(c) for c in coros))
