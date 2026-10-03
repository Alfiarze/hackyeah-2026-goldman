from enum import IntEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

Action = Literal["ALLOW", "REDACT", "BLOCK"]
_SEVERITY = {"ALLOW": 0, "REDACT": 1, "BLOCK": 2}


class Classification(IntEnum):
    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    SECRET = 3

    @classmethod
    def parse(cls, value: "str | int | Classification") -> "Classification":
        if isinstance(value, str):
            return cls[value.upper()]
        return cls(value)


class Finding(BaseModel):
    """Result of one control on one piece of content."""

    action: Action
    rule_id: str
    reason_code: str
    stage: str
    detail: dict[str, Any] = Field(default_factory=dict)
    spans: list[tuple[int, int, str]] = Field(default_factory=list)  # (start, end, label) to redact


class Decision(BaseModel):
    action: Action = "ALLOW"
    reason_code: str = "OK"
    rule_id: str | None = None
    stage: str | None = None
    policy_version: str = ""
    latency_ms: float = 0.0
    tool_invoked: bool = False
    task_id: str | None = None
    findings: list[Finding] = Field(default_factory=list)
    timings: dict[str, float] = Field(default_factory=dict)

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)
        if _SEVERITY[finding.action] > _SEVERITY[self.action]:
            self.action = finding.action
            self.reason_code = finding.reason_code
            self.rule_id = finding.rule_id
            self.stage = finding.stage

    @property
    def blocked(self) -> bool:
        return self.action == "BLOCK"

    def public(self) -> dict[str, Any]:
        """Evidence safe to return/log: no raw content, only ids and classes."""
        return {
            "action": self.action,
            "reason_code": self.reason_code,
            "rule_id": self.rule_id,
            "stage": self.stage,
            "policy_version": self.policy_version,
            "latency_ms": round(self.latency_ms, 3),
            "tool_invoked": self.tool_invoked,
            "task_id": self.task_id,
            "findings": [
                {
                    "action": f.action,
                    "rule_id": f.rule_id,
                    "reason_code": f.reason_code,
                    "stage": f.stage,
                    "detail": f.detail,
                }
                for f in self.findings
            ],
            "timings": {k: round(v, 3) for k, v in self.timings.items()},
        }


class GatewayError(Exception):
    """Request rejected before evaluation (auth, unknown task, ...)."""

    def __init__(self, status: int, reason_code: str, message: str = ""):
        super().__init__(message or reason_code)
        self.status = status
        self.reason_code = reason_code
        self.message = message or reason_code
