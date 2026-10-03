"""Python SDK for the Aegis control gateway for AI agents."""

from aegis_sdk.admin import Admin, AsyncAdmin, Check, DocumentCheck
from aegis_sdk.client import LEASE_HEADER, Aegis, AsyncAegis, AsyncTask, Task
from aegis_sdk.errors import AegisError, ApprovalRequired, Blocked, BudgetExceeded, RateLimited, Rejected, Unavailable
from aegis_sdk.types import ChatResult, Decision, Finding, TaskInfo, ToolResult

__all__ = [
    "Aegis", "AsyncAegis", "Task", "AsyncTask", "Admin", "AsyncAdmin", "Check", "DocumentCheck", "LEASE_HEADER",
    "AegisError", "Rejected", "Blocked", "BudgetExceeded", "RateLimited", "ApprovalRequired", "Unavailable",
    "Decision", "Finding", "ChatResult", "ToolResult", "TaskInfo",
]
__version__ = "0.3.0"
