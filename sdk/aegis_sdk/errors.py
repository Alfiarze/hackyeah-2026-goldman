"""Exceptions raised by the Aegis SDK. Every gateway refusal maps to exactly one of these."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aegis_sdk.types import Decision


class AegisError(Exception):
    """Base class. `status` is the HTTP status, `reason_code` the gateway's machine-readable reason."""

    def __init__(self, message: str, *, status: int, reason_code: str):
        super().__init__(message)
        self.status = status
        self.reason_code = reason_code


class Rejected(AegisError):
    """Refused before evaluation: bad agent key, invalid/expired/revoked lease, unknown task (401/403/404)."""


class Blocked(AegisError):
    """The gateway evaluated the call and blocked it. `decision` carries the rule, stage and evidence."""

    def __init__(self, decision: "Decision", *, status: int):
        super().__init__(
            f"{decision.reason_code} ({decision.rule_id}) at stage {decision.stage}",
            status=status, reason_code=decision.reason_code,
        )
        self.decision = decision

    @property
    def rule_id(self) -> str | None:
        return self.decision.rule_id

    @property
    def tool_invoked(self) -> bool:
        return self.decision.tool_invoked


class BudgetExceeded(Blocked):
    """Blocked because a budget scope (task, parent, user, global) had no room (HTTP 429)."""


class Unavailable(Blocked):
    """The upstream model or tool was unreachable (HTTP 502). The gateway failed closed."""
