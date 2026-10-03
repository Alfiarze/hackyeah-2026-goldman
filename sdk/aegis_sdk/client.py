"""Aegis gateway client, sync and async.

    from aegis_sdk import Aegis

    aegis = Aegis("http://localhost:8000", app_key="...", agent_key="...")
    with aegis.create_task(principal="lawyer_anna", agent_id="demo-agent",
                           profile="contract_review", params={"client": "A"}) as task:
        doc = task.call("doc.read", path="/clients/A/contracts/acquisition.txt")
        answer = task.chat(f"List the three biggest risks:\\n{doc.content}")
        task.call("notes.write", title="Risk memo", body=answer.content)
    # leaving the block completes the task: its lease stops working

Every refusal raises: `Rejected` (auth / lease), `Blocked` (policy said no, with the rule and evidence),
`BudgetExceeded` (429) or `Unavailable` (502, failed closed). The agent never holds tool credentials:
tools run behind the gateway.
"""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Any

import httpx

from aegis_sdk.errors import AegisError, ApprovalRequired, Blocked, BudgetExceeded, RateLimited, Rejected, Unavailable
from aegis_sdk.types import ChatResult, Decision, TaskInfo, ToolResult

LEASE_HEADER = "X-Mandate-Lease"

# ------------------------------------------------------------------ shared request/response logic


def _agent_headers(agent_key: str | None, lease: str) -> dict[str, str]:
    if not agent_key:
        raise ValueError("an agent_key is required for agent calls")
    return {"Authorization": f"Bearer {agent_key}", LEASE_HEADER: lease}


def _messages(prompt: str | list[dict[str, Any]], system: str | None) -> list[dict[str, Any]]:
    msgs = [{"role": "user", "content": prompt}] if isinstance(prompt, str) else list(prompt)
    if system:
        msgs.insert(0, {"role": "system", "content": system})
    return msgs


def _check(resp: httpx.Response) -> dict[str, Any]:
    """Map a gateway response to data or to the right exception."""
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if resp.status_code < 400:
        return body
    err = body.get("error") or {}
    if "mandate" in body:  # evaluated and blocked: carries a full decision
        decision = Decision.from_json(body["mandate"])
        if resp.status_code == 429:
            if decision.rule_id in ("RATE-001", "CIRCUIT-001"):
                raise RateLimited(decision, status=429)
            raise BudgetExceeded(decision, status=429)
        if decision.rule_id == "APPROVAL-001":
            raise ApprovalRequired(decision, status=resp.status_code)
        if resp.status_code == 502:
            raise Unavailable(decision, status=502)
        raise Blocked(decision, status=resp.status_code)
    reason = err.get("reason_code") or f"HTTP_{resp.status_code}"
    message = err.get("message") or reason
    if resp.status_code in (401, 403, 404):
        raise Rejected(message, status=resp.status_code, reason_code=reason)
    raise AegisError(message, status=resp.status_code, reason_code=reason)


def _chat_result(body: dict[str, Any]) -> ChatResult:
    choice = (body.get("choices") or [{}])[0]
    return ChatResult(content=(choice.get("message") or {}).get("content") or "", model=body.get("model", ""),
                      usage=body.get("usage") or {}, decision=Decision.from_json(body.get("mandate")), raw=body)


def _tool_result(body: dict[str, Any]) -> ToolResult:
    return ToolResult(result=body.get("result"), decision=Decision.from_json(body.get("mandate")), raw=body)


def _mcp_result(body: dict[str, Any]) -> dict[str, Any]:
    if "error" in body:
        raise AegisError(body["error"].get("message", "MCP error"), status=400, reason_code="MCP_ERROR")
    return body.get("result") or {}


def _model_body(name: str, source_url: str | None, files: dict[str, bytes] | None,
                packages: dict[str, str] | None, gguf_metadata: dict[str, Any] | None) -> dict[str, Any]:
    body: dict[str, Any] = {"name": name, "packages": packages or {},
                            "files": {k: base64.b64encode(v).decode() for k, v in (files or {}).items()}}
    if source_url:
        body["source_url"] = source_url
    if gguf_metadata:
        body["gguf_metadata"] = gguf_metadata
    return body


def _model_result(body: dict[str, Any]) -> dict[str, Any]:
    return {"accepted": body.get("accepted", False), "sha256": body.get("sha256") or {},
            "decision": Decision.from_json(body.get("mandate"))}


def _rpc(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}


def _task_body(principal: str, agent_id: str, profile: str, params: dict[str, str] | None,
               purpose: str) -> dict[str, Any]:
    return {"principal": principal, "agent_id": agent_id, "profile": profile,
            "params": params or {}, "purpose": purpose}


def _delegate_body(agent_id: str, tools, resources, budget_tokens, purpose) -> dict[str, Any]:
    return {"agent_id": agent_id, "tools": tools, "resources": resources,
            "budget_tokens": budget_tokens, "purpose": purpose}


# ------------------------------------------------------------------ sync


class Aegis:
    """Synchronous client. `app_key` creates tasks (trusted app); `agent_key` makes agent calls."""

    def __init__(self, base_url: str, *, agent_key: str | None = None, app_key: str | None = None,
                 timeout: float = 120.0, transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.agent_key = agent_key
        self.app_key = app_key
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout, transport=transport)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "Aegis":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def health(self) -> dict[str, Any]:
        return _check(self._http.get("/health"))

    def create_task(self, *, principal: str, agent_id: str, profile: str, params: dict[str, str] | None = None,
                    purpose: str = "", agent_key: str | None = None) -> "Task":
        """Called by the trusted app: creates the mandate and returns the agent's lease."""
        if not self.app_key:
            raise ValueError("create_task needs app_key (the trusted app creates mandates, not the agent)")
        body = _check(self._http.post("/v1/tasks", headers={"X-App-Key": self.app_key},
                                      json=_task_body(principal, agent_id, profile, params, purpose)))
        return Task(self, body["task_id"], body["lease"], agent_key or self.agent_key, body)

    def task(self, task_id: str, lease: str, *, agent_key: str | None = None) -> "Task":
        """Attach to a task whose lease the app handed to this agent."""
        return Task(self, task_id, lease, agent_key or self.agent_key, None)

    def register_model(self, name: str, *, source_url: str | None = None, files: dict[str, bytes] | None = None,
                       packages: dict[str, str] | None = None,
                       gguf_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Supply-chain check before a model or LoRA adapter is used (app key). Weights are compared with the
        sha256 pinned in the policy; a refused artifact raises `Blocked` (e.g. MODEL-HASH-001, ATK-SUPPLY-001)."""
        if not self.app_key:
            raise ValueError("register_model needs app_key")
        return _model_result(_check(self._http.post(
            "/v1/models/register", headers={"X-App-Key": self.app_key},
            json=_model_body(name, source_url, files, packages, gguf_metadata))))

    def request(self, method: str, path: str, *, task: "Task | None" = None, **kwargs: Any) -> dict[str, Any]:
        """Raw call for an endpoint without a helper yet; errors still map to the SDK exceptions."""
        headers = dict(kwargs.pop("headers", None) or {}) | (task._h if task else {})
        return _check(self._http.request(method, path, headers=headers, **kwargs))


class Task:
    """One task under one mandate. All calls carry the task's lease."""

    def __init__(self, client: Aegis, task_id: str, lease: str, agent_key: str | None, created: dict | None):
        self._c = client
        self.task_id = task_id
        self.lease = lease
        self.agent_key = agent_key
        self.created = created

    def __enter__(self) -> "Task":
        return self

    def __exit__(self, *exc) -> None:
        try:
            self.complete()
        except AegisError:
            pass  # already completed, revoked or expired

    @property
    def _h(self) -> dict[str, str]:
        return _agent_headers(self.agent_key, self.lease)

    def info(self) -> TaskInfo:
        return TaskInfo.from_json(_check(self._c._http.get(f"/v1/tasks/{self.task_id}", headers=self._h)))

    def chat(self, prompt: str | list[dict[str, Any]], *, model: str | None = None,
             max_tokens: int | None = None, system: str | None = None) -> ChatResult:
        body: dict[str, Any] = {"messages": _messages(prompt, system)}
        if model:
            body["model"] = model
        if max_tokens:
            body["max_tokens"] = max_tokens
        return _chat_result(_check(self._c._http.post("/v1/chat/completions", headers=self._h, json=body)))

    def call(self, tool: str, **args: Any) -> ToolResult:
        return _tool_result(_check(self._c._http.post(f"/v1/tools/{tool}/call", headers=self._h,
                                                      json={"args": args})))

    def call_approved(self, tool: str, *, timeout: float = 300.0, interval: float = 2.0, **args: Any) -> ToolResult:
        """Like `call`, for tools that need a person's approval: retries the identical call until it is approved
        (then it runs once) or `timeout` passes, when the last `ApprovalRequired` is raised."""
        deadline = time.monotonic() + timeout
        while True:
            try:
                return self.call(tool, **args)
            except ApprovalRequired:
                if time.monotonic() + interval > deadline:
                    raise
                time.sleep(interval)

    def tool(self, name: str):
        """A callable bound to one tool: `send = task.tool("mail.send"); send(to=..., subject=..., body=...)`."""
        return lambda **args: self.call(name, **args)

    def run_code(self, code: str) -> ToolResult:
        """Run code in the gateway's sandbox (no network, read-only, hard limits)."""
        return self.call("code.run", code=code)

    def delegate(self, *, agent_id: str, agent_key: str, tools: list[str] | None = None,
                 resources: list[str] | None = None, budget_tokens: int | None = None,
                 purpose: str = "") -> "Task":
        """Hand part of the work to another agent. Its mandate must be a subset of this one."""
        body = _check(self._c._http.post(f"/v1/tasks/{self.task_id}/delegate", headers=self._h,
                                         json=_delegate_body(agent_id, tools, resources, budget_tokens, purpose)))
        return Task(self._c, body["task_id"], body["lease"], agent_key, body)

    def complete(self) -> None:
        _check(self._c._http.post(f"/v1/tasks/{self.task_id}/complete", headers=self._h))

    def mcp_tools(self) -> list[dict[str, Any]]:
        """Tools visible to this task through the MCP proxy (filtered by mandate, pinned by hash)."""
        return _mcp_result(_check(self._c._http.post("/mcp", headers=self._h, json=_rpc("tools/list"))))["tools"]

    def mcp_call(self, name: str, **arguments: Any) -> dict[str, Any]:
        return _mcp_result(_check(self._c._http.post("/mcp", headers=self._h, json=_rpc(
            "tools/call", {"name": name, "arguments": arguments}))))

    def openai_client(self):
        """A drop-in `openai.OpenAI` client whose calls go through Aegis under this task's mandate."""
        from openai import OpenAI  # optional dependency: pip install "aegis-sdk[openai]"

        return OpenAI(base_url=f"{self._c.base_url}/v1", api_key=self.agent_key,
                      default_headers={LEASE_HEADER: self.lease})


# ------------------------------------------------------------------ async


class AsyncAegis:
    """Asynchronous client with the same surface as `Aegis`."""

    def __init__(self, base_url: str, *, agent_key: str | None = None, app_key: str | None = None,
                 timeout: float = 120.0, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.agent_key = agent_key
        self.app_key = app_key
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "AsyncAegis":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def health(self) -> dict[str, Any]:
        return _check(await self._http.get("/health"))

    async def create_task(self, *, principal: str, agent_id: str, profile: str,
                          params: dict[str, str] | None = None, purpose: str = "",
                          agent_key: str | None = None) -> "AsyncTask":
        if not self.app_key:
            raise ValueError("create_task needs app_key (the trusted app creates mandates, not the agent)")
        body = _check(await self._http.post("/v1/tasks", headers={"X-App-Key": self.app_key},
                                            json=_task_body(principal, agent_id, profile, params, purpose)))
        return AsyncTask(self, body["task_id"], body["lease"], agent_key or self.agent_key, body)

    def task(self, task_id: str, lease: str, *, agent_key: str | None = None) -> "AsyncTask":
        return AsyncTask(self, task_id, lease, agent_key or self.agent_key, None)

    async def register_model(self, name: str, *, source_url: str | None = None,
                             files: dict[str, bytes] | None = None, packages: dict[str, str] | None = None,
                             gguf_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.app_key:
            raise ValueError("register_model needs app_key")
        return _model_result(_check(await self._http.post(
            "/v1/models/register", headers={"X-App-Key": self.app_key},
            json=_model_body(name, source_url, files, packages, gguf_metadata))))

    async def request(self, method: str, path: str, *, task: "AsyncTask | None" = None,
                      **kwargs: Any) -> dict[str, Any]:
        headers = dict(kwargs.pop("headers", None) or {}) | (task._h if task else {})
        return _check(await self._http.request(method, path, headers=headers, **kwargs))


class AsyncTask:
    def __init__(self, client: AsyncAegis, task_id: str, lease: str, agent_key: str | None, created: dict | None):
        self._c = client
        self.task_id = task_id
        self.lease = lease
        self.agent_key = agent_key
        self.created = created

    async def __aenter__(self) -> "AsyncTask":
        return self

    async def __aexit__(self, *exc) -> None:
        try:
            await self.complete()
        except AegisError:
            pass

    @property
    def _h(self) -> dict[str, str]:
        return _agent_headers(self.agent_key, self.lease)

    async def info(self) -> TaskInfo:
        return TaskInfo.from_json(_check(await self._c._http.get(f"/v1/tasks/{self.task_id}", headers=self._h)))

    async def chat(self, prompt: str | list[dict[str, Any]], *, model: str | None = None,
                   max_tokens: int | None = None, system: str | None = None) -> ChatResult:
        body: dict[str, Any] = {"messages": _messages(prompt, system)}
        if model:
            body["model"] = model
        if max_tokens:
            body["max_tokens"] = max_tokens
        return _chat_result(_check(await self._c._http.post("/v1/chat/completions", headers=self._h, json=body)))

    async def call(self, tool: str, **args: Any) -> ToolResult:
        return _tool_result(_check(await self._c._http.post(f"/v1/tools/{tool}/call", headers=self._h,
                                                            json={"args": args})))

    async def call_approved(self, tool: str, *, timeout: float = 300.0, interval: float = 2.0,
                            **args: Any) -> ToolResult:
        deadline = time.monotonic() + timeout
        while True:
            try:
                return await self.call(tool, **args)
            except ApprovalRequired:
                if time.monotonic() + interval > deadline:
                    raise
                await asyncio.sleep(interval)

    def tool(self, name: str):
        async def bound(**args: Any) -> ToolResult:
            return await self.call(name, **args)
        return bound

    async def run_code(self, code: str) -> ToolResult:
        return await self.call("code.run", code=code)

    async def delegate(self, *, agent_id: str, agent_key: str, tools: list[str] | None = None,
                       resources: list[str] | None = None, budget_tokens: int | None = None,
                       purpose: str = "") -> "AsyncTask":
        body = _check(await self._c._http.post(
            f"/v1/tasks/{self.task_id}/delegate", headers=self._h,
            json=_delegate_body(agent_id, tools, resources, budget_tokens, purpose)))
        return AsyncTask(self._c, body["task_id"], body["lease"], agent_key, body)

    async def complete(self) -> None:
        _check(await self._c._http.post(f"/v1/tasks/{self.task_id}/complete", headers=self._h))

    async def mcp_tools(self) -> list[dict[str, Any]]:
        return _mcp_result(_check(await self._c._http.post("/mcp", headers=self._h,
                                                           json=_rpc("tools/list"))))["tools"]

    async def mcp_call(self, name: str, **arguments: Any) -> dict[str, Any]:
        return _mcp_result(_check(await self._c._http.post("/mcp", headers=self._h, json=_rpc(
            "tools/call", {"name": name, "arguments": arguments}))))

    def openai_client(self):
        """A drop-in `openai.AsyncOpenAI` client under this task's mandate."""
        from openai import AsyncOpenAI

        return AsyncOpenAI(base_url=f"{self._c.base_url}/v1", api_key=self.agent_key,
                           default_headers={LEASE_HEADER: self.lease})
