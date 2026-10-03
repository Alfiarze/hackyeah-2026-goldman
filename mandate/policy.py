"""Central policy engine: schema, profiles, versioned store, hot-reload."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from mandate.models import Classification

if TYPE_CHECKING:
    import asyncpg

    from mandate.audit import Audit

log = logging.getLogger("mandate.policy")

Mode = Literal["block", "redact"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Toggle(_Strict):
    enabled: bool = True


class ModeControl(_Strict):
    enabled: bool = True
    mode: Mode = "block"


class PiiControl(ModeControl):
    mode: Mode = "redact"
    entities: list[Literal["PESEL", "CREDIT_CARD", "IBAN", "EMAIL", "PHONE"]] = [
        "PESEL",
        "CREDIT_CARD",
        "IBAN",
        "EMAIL",
        "PHONE",
    ]


class SemanticControl(_Strict):
    enabled: bool = True
    backend: Literal["auto", "ollama", "heuristic"] = "auto"
    model: str = "qwen2.5:3b"
    block_at_risk: float = Field(0.7, ge=0.0, le=1.0)
    redact_at_risk: float = Field(0.5, ge=0.0, le=1.0)
    on_error: Literal["block", "allow"] = "block"
    timeout_ms: int = Field(1500, ge=50, le=30000)

    @model_validator(mode="after")
    def _order(self) -> "SemanticControl":
        if self.redact_at_risk > self.block_at_risk:
            raise ValueError("redact_at_risk must be <= block_at_risk")
        return self


class Controls(_Strict):
    mandate: Toggle = Toggle()
    ifc_taint: Toggle = Toggle()
    model_allowlist: Toggle = Toggle()
    pii: PiiControl = PiiControl()
    secrets: ModeControl = ModeControl()
    attack_signatures: ModeControl = ModeControl()
    injection_heuristics: ModeControl = ModeControl(mode="redact")
    semantic: SemanticControl = SemanticControl()


class Limit(_Strict):
    tokens: int = Field(ge=0)
    calls: int = Field(1_000_000, ge=0)
    concurrency: int = Field(1000, ge=1)


class Budgets(_Strict):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    default_max_tokens: int = Field(1024, ge=1)
    per_principal: Limit = Limit(tokens=500_000)
    global_: Limit = Field(Limit(tokens=5_000_000), alias="global")
    guard: Limit = Limit(tokens=200_000, calls=5000)
    usd_per_1k_tokens: float = Field(0.0, ge=0)


class TaskProfile(_Strict):
    description: str = ""
    resources: list[str]
    tools: list[str]
    recipients_allow: list[str] = []
    sinks: dict[str, str] = {}  # may only narrow policy sink clearance
    models: list[str] | None = None
    budget: Limit
    ttl_seconds: int = Field(900, ge=1)

    @field_validator("sinks")
    @classmethod
    def _levels(cls, v: dict[str, str]) -> dict[str, str]:
        for level in v.values():
            Classification.parse(level)
        return v


class Models(_Strict):
    allow: list[str]
    default: str


class Policy(_Strict):
    version: int = 1
    profile: str = "balanced"
    models: Models
    internal_domains: list[str] = []
    sinks: dict[str, str]
    controls: Controls = Controls()
    budgets: Budgets = Budgets()
    task_profiles: dict[str, TaskProfile]
    profiles: dict[str, dict[str, Any]] = {}

    @field_validator("sinks")
    @classmethod
    def _sink_levels(cls, v: dict[str, str]) -> dict[str, str]:
        for level in v.values():
            Classification.parse(level)
        return v

    def sink_clearance(self, sink: str) -> Classification:
        """Unknown sink => PUBLIC (strictest)."""
        return Classification.parse(self.sinks.get(sink, "PUBLIC"))


def _deep_merge(base: dict, overlay: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def parse_policy(text: str) -> Policy:
    """YAML -> validated Policy. Profile gives defaults; explicit `controls` fields win."""
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML error: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("policy must be a YAML mapping")
    profiles = raw.get("profiles") or {}
    profile = raw.get("profile", "balanced")
    if profiles and profile not in profiles:
        raise ValueError(f"unknown profile '{profile}', expected one of {sorted(profiles)}")
    effective = dict(raw)
    effective["controls"] = _deep_merge(profiles.get(profile, {}), raw.get("controls") or {})
    try:
        return Policy.model_validate(effective)
    except ValidationError as exc:
        raise ValueError(_short_errors(exc)) from exc


def _short_errors(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]
    )


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def roundtrip_edit(text: str, mutate) -> str:
    """Apply `mutate(dict)` to YAML text while keeping comments and layout (ruamel round-trip)."""
    import io

    from ruamel.yaml import YAML

    rt = YAML()
    rt.preserve_quotes = True
    rt.indent(mapping=2, sequence=4, offset=2)
    data = rt.load(text) or {}
    mutate(data)
    buf = io.StringIO()
    rt.dump(data, buf)
    return buf.getvalue()


def atomic_write(path: Path, text: str) -> None:
    """tmp in the same dir -> fsync -> os.replace: readers never see a half-written file."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


class PolicyStore:
    def __init__(self, path: Path, pool: "asyncpg.Pool", audit: "Audit"):
        self.path = path
        self.pool = pool
        self.audit = audit
        self.policy: Policy | None = None
        self.text: str = ""
        self.version: str = ""
        self.seq: int = 0
        self._file_hash: str | None = None
        self._lock = asyncio.Lock()

    @property
    def active(self) -> Policy:
        assert self.policy is not None, "policy not loaded"
        return self.policy

    async def load_initial(self) -> None:
        text = self._read_file()
        try:
            await self._activate(text, source="startup", actor="system")
        except ValueError as exc:
            row = await self.pool.fetchrow(
                "SELECT seq, content FROM policy_versions WHERE accepted ORDER BY seq DESC LIMIT 1"
            )
            if row is None:
                raise RuntimeError(f"invalid policy and no last-known-good version: {exc}") from exc
            log.error("policy file invalid at startup, using last-known-good seq=%s", row["seq"])
            self._set(parse_policy(row["content"]), row["content"], row["seq"])
            self._file_hash = content_hash(text) if text is not None else None

    def _read_file(self) -> str | None:
        try:
            return self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def _set(self, policy: Policy, text: str, seq: int) -> None:
        self.policy, self.text, self.seq = policy, text, seq
        self.version = f"v{seq}-{content_hash(text)[:8]}"

    async def _activate(self, text: str | None, source: str, actor: str) -> bool:
        """Validate and swap. Returns True if the active policy changed. Raises ValueError if invalid."""
        if text is None:
            raise ValueError("policy file missing")
        digest = content_hash(text)
        self._file_hash = digest if source in ("file", "startup") else self._file_hash
        if self.policy is not None and digest == content_hash(self.text) and source == "file":
            return False
        try:
            policy = parse_policy(text)
        except ValueError as exc:
            await self.pool.execute(
                "INSERT INTO policy_versions (content_hash, content, source, accepted, error) "
                "VALUES ($1, $2, $3, false, $4)",
                digest, text, source, str(exc),
            )
            await self.audit.system(
                "POLICY_REJECTED", actor=actor, evidence={"source": source, "error": str(exc)[:500]},
                policy_version=self.version,
            )
            raise
        old_text = self.text
        seq = await self.pool.fetchval(
            "INSERT INTO policy_versions (content_hash, content, source, accepted) "
            "VALUES ($1, $2, $3, true) RETURNING seq",
            digest, text, source,
        )
        self._set(policy, text, seq)
        await self.audit.system(
            "POLICY_CHANGED", actor=actor, policy_version=self.version,
            evidence={"source": source, "diff": policy_diff(old_text, text) if old_text else None,
                      "disabled_controls": disabled_controls(policy)},
        )
        return True

    async def reload_from_file(self, actor: str = "file-watcher") -> tuple[bool, str | None]:
        async with self._lock:
            text = self._read_file()
            if text is None:
                return False, "policy file missing (keeping last-known-good)"
            if content_hash(text) == self._file_hash:
                return False, None
            try:
                return await self._activate(text, source="file", actor=actor), None
            except ValueError as exc:
                return False, str(exc)

    async def apply_text(self, text: str, actor: str, source: str = "api") -> str:
        """Validate, persist as a new version, write the file atomically. Raises ValueError."""
        async with self._lock:
            await self._activate(  # validates (and audits a rejection) before touching the file
                text, source=source, actor=actor)
            atomic_write(self.path, text)
            self._file_hash = content_hash(text)
            return self.version

    async def apply_mutation(self, mutate, actor: str) -> str:
        """Load YAML, let `mutate(raw_dict)` edit it, re-serialise and apply."""
        return await self.apply_text(roundtrip_edit(self.text, mutate), actor)

    async def rollback(self, seq: int, actor: str) -> str:
        row = await self.pool.fetchrow(
            "SELECT content FROM policy_versions WHERE seq=$1 AND accepted", seq
        )
        if row is None:
            raise ValueError(f"no accepted policy version seq={seq}")
        # append-only: old content becomes a NEW version
        return await self.apply_text(row["content"], actor=actor, source=f"rollback:{seq}")

    async def watch(self, interval: float) -> None:
        """watchfiles for fast reaction + sha256 polling as a fallback (Docker Desktop mounts)."""
        async def poll() -> None:
            while True:
                await asyncio.sleep(interval)
                await self._safe_reload()

        async def events() -> None:
            try:
                from watchfiles import awatch

                async for _ in awatch(self.path.parent, watch_filter=lambda _c, p: not p.endswith(".tmp")):
                    await self._safe_reload()  # event = "re-read", never "deleted"
            except Exception:  # noqa: BLE001 - polling still covers us
                log.warning("watchfiles unavailable, relying on polling")

        await asyncio.gather(poll(), events())

    async def _safe_reload(self) -> None:
        try:
            await self.reload_from_file()
        except Exception:  # noqa: BLE001
            log.exception("policy reload failed")


def disabled_controls(policy: Policy) -> list[str]:
    return [name for name, cfg in policy.controls if not cfg.enabled]


def policy_diff(old: str, new: str) -> str:
    import difflib

    lines = difflib.unified_diff(old.splitlines(), new.splitlines(), "previous", "new", lineterm="", n=1)
    return "\n".join(list(lines)[:200])
