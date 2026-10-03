"""Admin client (`X-Admin-Key`): people's approvals, policy, audit and dry-run checks.

    from aegis_sdk import Admin

    admin = Admin("http://localhost:8000", admin_key="...")
    for a in admin.approvals(status="pending"):
        admin.approve(a["id"])
    print(admin.check("Mój PESEL to 44051401359").redacted)        # Mój PESEL to [REDACTED:PESEL]
    print(admin.check_document(open("umowa.pdf", "rb").read(), "umowa.pdf").decision.action)

The sync and async clients share every method: each one builds a request and `_do` runs it (`Admin` returns the
result, `AsyncAdmin` returns an awaitable). Anything not wrapped yet is one `admin.request("GET", "/admin/...")`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import httpx

from aegis_sdk.errors import AegisError
from aegis_sdk.types import Decision


@dataclass(frozen=True)
class Check:
    """A dry run of text: the decision and, when it is REDACT, the text as the agent would get it."""

    decision: Decision
    redacted: str | None
    raw: dict[str, Any]

    @property
    def action(self) -> str:
        return self.decision.action

    @property
    def blocked(self) -> bool:
        return self.decision.blocked


@dataclass(frozen=True)
class DocumentCheck:
    """A dry run of a whole file: the decision plus where every hidden part and rule was found."""

    decision: Decision
    document: dict[str, Any]   # name, kind, pages, sections [{where, text, rules}], active, privacy, body_rules
    raw: dict[str, Any]

    @property
    def hidden_parts(self) -> list[dict[str, Any]]:
        return self.document.get("sections") or []

    @property
    def active_content(self) -> list[dict[str, Any]]:
        return self.document.get("active") or []


def _admin_check(resp: httpx.Response) -> Any:
    """Admin endpoints answer with plain JSON or an `{"error": ...}` body; text bodies (exports) pass through."""
    if resp.status_code < 400:
        if "json" in resp.headers.get("content-type", ""):
            return resp.json()
        return resp.text
    try:
        err = resp.json().get("error") or {}
    except ValueError:
        err = {}
    reason = err.get("reason_code") or f"HTTP_{resp.status_code}"
    raise AegisError(err.get("message") or reason, status=resp.status_code, reason_code=reason)


def _text(body: dict[str, Any]) -> Check:
    return Check(decision=Decision.from_json(body.get("decision")), redacted=body.get("redacted"), raw=body)


def _document(body: dict[str, Any]) -> DocumentCheck:
    return DocumentCheck(decision=Decision.from_json(body.get("decision")), document=body.get("document") or {}, raw=body)


class _AdminCalls:
    """Every admin call, written once. `_do(method, path, wrap=None, **httpx_kwargs)` is sync or async."""

    _do: Callable[..., Any]

    # -- people's approvals (APPROVAL-001)
    def approvals(self, status: str | None = "pending"):
        return self._do("GET", "/admin/approvals", params={"status": status} if status else None)

    def approve(self, approval_id: str):
        return self._do("POST", f"/admin/approvals/{approval_id}/approve")

    def deny(self, approval_id: str):
        return self._do("POST", f"/admin/approvals/{approval_id}/deny")

    # -- dry runs: nothing is executed, nothing is sent
    def check(self, text: str, *, target: str = "user_input", sink: str | None = None,
              classification: str = "PUBLIC", tool: str | None = None):
        """Run text through the content checks and get the decision (ALLOW / REDACT / BLOCK)."""
        return self._do("POST", "/admin/playground/evaluate", wrap=_text,
                        json={"text": text, "target": target, "sink": sink,
                              "classification": classification, "tool": tool})

    def check_document(self, data: bytes, name: str = "document"):
        """Check a whole file (PDF, Office, legacy Office, image, scan) including its hidden parts."""
        return self._do("POST", "/admin/playground/document", wrap=_document, params={"name": name}, content=data)

    def extract(self, data: bytes, name: str = "document"):
        """What an agent would read from the file: text plus every hidden part. Nothing is evaluated."""
        return self._do("POST", "/admin/playground/extract", params={"name": name}, content=data)

    # -- policy: one YAML, hot-reloaded, versioned
    def policy(self):
        return self._do("GET", "/admin/policy")

    def update_policy(self, yaml_text: str):
        """Apply a new policy. A broken file raises AegisError(422) and the previous version stays active."""
        return self._do("PUT", "/admin/policy", content=yaml_text, headers={"Content-Type": "text/plain"})

    def validate_policy(self, yaml_text: str):
        return self._do("POST", "/admin/policy/validate", content=yaml_text, headers={"Content-Type": "text/plain"})

    def policy_versions(self, limit: int = 50):
        return self._do("GET", "/admin/policy/versions", params={"limit": limit})

    def rollback(self, seq: int):
        return self._do("POST", f"/admin/policy/rollback/{seq}")

    def set_profile(self, profile: str):
        """strict | balanced | permissive"""
        return self._do("PUT", "/admin/policy/profile", json={"profile": profile})

    def controls(self):
        return self._do("GET", "/admin/controls")

    # -- tasks, tools, budgets
    def tasks(self):
        return self._do("GET", "/admin/tasks")

    def revoke_task(self, task_id: str):
        """Kill a task's lease now: its next call is refused."""
        return self._do("POST", f"/admin/tasks/{task_id}/revoke")

    def tools(self):
        return self._do("GET", "/admin/tools")

    def approve_tool(self, name: str):
        return self._do("POST", f"/admin/tools/{name}/approve")

    def quarantine_tool(self, name: str):
        return self._do("POST", f"/admin/tools/{name}/quarantine")

    def budgets(self):
        return self._do("GET", "/admin/budgets")

    # -- evidence
    def audit(self, *, task: str | None = None, rule: str | None = None, action: str | None = None,
              kind: str | None = None, since: str | None = None, limit: int = 200):
        params = {k: v for k, v in {"task": task, "rule": rule, "action": action, "kind": kind,
                                    "since": since, "limit": limit}.items() if v is not None}
        return self._do("GET", "/admin/audit", params=params)

    def export_audit(self, format: str = "jsonl"):
        """The append-only audit log as JSONL or CSV text."""
        return self._do("GET", "/admin/audit/export", params={"format": format})

    def stats(self):
        return self._do("GET", "/admin/stats")

    # -- anything else the gateway grows
    def request(self, method: str, path: str, **kwargs: Any):
        """Raw admin call for endpoints without a helper yet: `admin.request("GET", "/admin/memory")`."""
        return self._do(method, path, **kwargs)


class Admin(_AdminCalls):
    def __init__(self, base_url: str, *, admin_key: str, timeout: float = 60.0,
                 transport: httpx.BaseTransport | None = None):
        self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport,
                                  headers={"X-Admin-Key": admin_key})

    def _do(self, method: str, path: str, wrap: Callable[[Any], Any] | None = None, **kwargs: Any) -> Any:
        body = _admin_check(self._http.request(method, path, **kwargs))
        return wrap(body) if wrap else body

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "Admin":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class AsyncAdmin(_AdminCalls):
    def __init__(self, base_url: str, *, admin_key: str, timeout: float = 60.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport,
                                       headers={"X-Admin-Key": admin_key})

    async def _do(self, method: str, path: str, wrap: Callable[[Any], Any] | None = None, **kwargs: Any) -> Any:
        body = _admin_check(await self._http.request(method, path, **kwargs))
        return wrap(body) if wrap else body

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "AsyncAdmin":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()
