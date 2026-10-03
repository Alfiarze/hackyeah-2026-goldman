"""Typed views of what the gateway returns. Raw JSON stays available on `.raw`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Finding:
    action: str
    rule_id: str
    reason_code: str
    stage: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Decision:
    """The `mandate` object attached to every gateway response."""

    action: str                 # ALLOW | REDACT | BLOCK
    reason_code: str
    rule_id: str | None
    stage: str | None
    policy_version: str
    latency_ms: float
    tool_invoked: bool
    task_id: str | None
    findings: tuple[Finding, ...]
    timings: dict[str, float]

    @property
    def allowed(self) -> bool:
        return self.action == "ALLOW"

    @property
    def redacted(self) -> bool:
        return self.action == "REDACT"

    @property
    def blocked(self) -> bool:
        return self.action == "BLOCK"

    @classmethod
    def from_json(cls, d: dict[str, Any] | None) -> "Decision":
        d = d or {}
        return cls(
            action=d.get("action", "ALLOW"),
            reason_code=d.get("reason_code", "OK"),
            rule_id=d.get("rule_id"),
            stage=d.get("stage"),
            policy_version=d.get("policy_version", ""),
            latency_ms=float(d.get("latency_ms") or 0.0),
            tool_invoked=bool(d.get("tool_invoked")),
            task_id=d.get("task_id"),
            findings=tuple(Finding(f.get("action", ""), f.get("rule_id", ""), f.get("reason_code", ""),
                                   f.get("stage", ""), f.get("detail") or {}) for f in d.get("findings") or []),
            timings=dict(d.get("timings") or {}),
        )


@dataclass(frozen=True)
class ChatResult:
    content: str
    model: str
    usage: dict[str, Any]
    decision: Decision
    raw: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    result: Any
    decision: Decision
    raw: dict[str, Any]

    @property
    def content(self) -> Any:
        """Shortcut for tools that return text (doc.read, legal_db.search, code.run)."""
        return self.result.get("content") if isinstance(self.result, dict) else None

    @property
    def sandbox(self) -> dict[str, Any] | None:
        """Evidence from the sandbox runner when the call was code.run."""
        return self.result.get("sandbox") if isinstance(self.result, dict) else None


@dataclass(frozen=True)
class TaskInfo:
    task_id: str
    principal: str
    agent_id: str
    profile: str
    classification: str
    status: str
    mandate: dict[str, Any]
    expires_at: str
    parent_id: str | None = None

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "TaskInfo":
        return cls(d["task_id"], d["principal"], d["agent_id"], d["profile"], d["classification"],
                   d["status"], d["mandate"], d["expires_at"], d.get("parent_id"))
