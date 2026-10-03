"""Historical attack mitigation: signature feed (hot-reloadable, local file or external URL)."""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import pickletools
import re
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal, Union
from urllib.parse import urlparse

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from mandate.models import Finding
from mandate.policy import atomic_write, content_hash, roundtrip_edit

if TYPE_CHECKING:
    from mandate.audit import Audit

log = logging.getLogger("mandate.attacks")

Target = Literal["user_input", "tool_args", "tool_results", "model_output", "file_content"]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegexMatch(_M):
    type: Literal["regex"]
    pattern: str
    flags: str = ""
    targets: list[Target] = ["user_input", "tool_args", "tool_results", "model_output", "file_content"]
    tools: list[str] | None = None  # restrict to these tools (for tool_args)

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, v: str) -> str:
        re.compile(v)
        return v

    def compiled(self) -> re.Pattern[str]:
        flags = re.I if "i" in self.flags else 0
        return re.compile(self.pattern, flags | re.S)


class PickleMatch(_M):
    type: Literal["pickle_scan"]
    deny_globals: list[str]


class ComponentMatch(_M):
    type: Literal["component"]
    package: str
    version_lt: str


class GgufTemplateMatch(_M):
    type: Literal["gguf_template"]
    pattern: str


class ModelSourceMatch(_M):
    type: Literal["model_source"]
    allow_hosts: list[str]
    typosquat_distance: int = 2


class ToolHashMatch(_M):
    type: Literal["tool_hash_mismatch"]


MatchSpec = Annotated[
    Union[RegexMatch, PickleMatch, ComponentMatch, GgufTemplateMatch, ModelSourceMatch, ToolHashMatch],
    Field(discriminator="type"),
]


class Signature(_M):
    id: str
    title: str
    severity: Literal["low", "medium", "high", "critical"] = "high"
    enabled: bool = True
    refs: list[str] = []
    match: list[MatchSpec]

    @field_validator("match", mode="before")
    @classmethod
    def _listify(cls, v: Any) -> Any:
        return [v] if isinstance(v, dict) else v


class Feed(_M):
    version: int = 1
    signatures: list[Signature]

    @field_validator("signatures")
    @classmethod
    def _unique(cls, v: list[Signature]) -> list[Signature]:
        ids = [s.id for s in v]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate signature ids")
        return v


_feed_adapter = TypeAdapter(Feed)


def parse_feed(text: str) -> Feed:
    try:
        raw = yaml.safe_load(text)
        return _feed_adapter.validate_python(raw)
    except (yaml.YAMLError, ValidationError, re.error) as exc:
        raise ValueError(str(exc)[:800]) from exc


# ---------------------------------------------------------------- matchers


def pickle_globals(data: bytes) -> list[str]:
    """List module.name globals a pickle would import. Never unpickles."""
    found: list[str] = []
    strings: list[str] = []
    try:
        for opcode, arg, _pos in pickletools.genops(data):
            if opcode.name in ("SHORT_BINUNICODE", "BINUNICODE", "UNICODE", "BINUNICODE8", "SHORT_BINSTRING", "BINSTRING", "STRING"):
                strings.append(str(arg))
            elif opcode.name == "GLOBAL":
                module, _, name = str(arg).partition(" ")
                found.append(f"{module}.{name}")
            elif opcode.name == "STACK_GLOBAL" and len(strings) >= 2:
                found.append(f"{strings[-2]}.{strings[-1]}")
    except Exception:  # noqa: BLE001 - malformed pickle: report what we saw
        found.append("<malformed-pickle>")
    return found


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:4])


def _levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _finding(sig: Signature, detail: dict[str, Any], mode: str, spans=None) -> Finding:
    return Finding(
        action="BLOCK" if mode == "block" else "REDACT",
        rule_id=sig.id,
        reason_code="KNOWN_ATTACK_SIGNATURE",
        stage="signatures",
        detail={"title": sig.title, "severity": sig.severity, "refs": sig.refs, **detail},
        spans=spans or [],
    )


class FeedStore:
    def __init__(self, path: Path, audit: "Audit", url: str | None = None):
        self.path = path
        self.url = url
        self.audit = audit
        self.feed: Feed = Feed(signatures=[])
        self.text = ""
        self.version = ""
        self._file_hash: str | None = None
        self._lock = asyncio.Lock()

    @property
    def signatures(self) -> list[Signature]:
        return [s for s in self.feed.signatures if s.enabled]

    async def load_initial(self) -> None:
        await self.reload(actor="startup")
        if not self.version:
            raise RuntimeError("attack feed invalid at startup")

    async def _fetch(self) -> str | None:
        if self.url:
            try:
                async with httpx.AsyncClient(timeout=3) as client:
                    resp = await client.get(self.url)
                    resp.raise_for_status()
                    return resp.text
            except httpx.HTTPError as exc:
                log.warning("feed url unreachable (%s), using local file", exc)
        try:
            return self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    async def reload(self, actor: str = "file-watcher") -> str | None:
        async with self._lock:
            text = await self._fetch()
            if text is None:
                return "feed missing (keeping previous)"
            digest = content_hash(text)
            if digest == self._file_hash:
                return None
            self._file_hash = digest
            return await self._activate(text, actor, source=self.url or "file")

    async def _activate(self, text: str, actor: str, source: str) -> str | None:
        try:
            feed = parse_feed(text)
        except ValueError as exc:
            await self.audit.system("FEED_REJECTED", actor=actor, evidence={"source": source, "error": str(exc)[:500]})
            return str(exc)
        self.feed, self.text, self.version = feed, text, content_hash(text)[:8]
        await self.audit.system(
            "FEED_CHANGED", actor=actor,
            evidence={"source": source, "version": self.version, "signatures": [s.id for s in feed.signatures]},
        )
        return None

    async def apply_text(self, text: str, actor: str) -> str:
        async with self._lock:
            error = await self._activate(text, actor, source="api")
            if error:
                raise ValueError(error)
            atomic_write(self.path, text)
            self._file_hash = content_hash(text)
            return self.version

    async def mutate(self, fn, actor: str) -> str:
        def guarded(raw):
            raw.setdefault("signatures", [])
            fn(raw)
        return await self.apply_text(roundtrip_edit(self.text or "version: 1\nsignatures: []\n", guarded), actor)

    async def watch(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval if not self.url else max(interval, 5))
            try:
                await self.reload()
            except Exception:  # noqa: BLE001
                log.exception("feed reload failed")

    # ------------------------------------------------------------ scanning

    def scan_text(self, text: str, target: Target, mode: str, tool: str | None = None) -> list[Finding]:
        out = []
        for sig in self.signatures:
            for m in sig.match:
                if isinstance(m, RegexMatch) and target in m.targets:
                    if m.tools is not None and tool not in m.tools:
                        continue
                    hits = list(m.compiled().finditer(text))
                    if hits:
                        spans = [(h.start(), h.end(), sig.id) for h in hits]
                        out.append(_finding(sig, {"target": target, "matches": len(hits)}, mode, spans))
                        break
        return out

    def scan_pickle(self, data: bytes, mode: str) -> list[Finding]:
        imported = pickle_globals(data)
        out = []
        for sig in self.signatures:
            for m in sig.match:
                if isinstance(m, PickleMatch):
                    bad = sorted({g for g in imported if any(fnmatch.fnmatch(g, p) for p in m.deny_globals)})
                    if bad or "<malformed-pickle>" in imported:
                        out.append(_finding(sig, {"globals": bad or ["<malformed-pickle>"]}, mode))
        return out

    def scan_component(self, packages: dict[str, str], mode: str) -> list[Finding]:
        out = []
        for sig in self.signatures:
            for m in sig.match:
                if isinstance(m, ComponentMatch):
                    installed = packages.get(m.package)
                    if installed and _version_tuple(installed) < _version_tuple(m.version_lt):
                        out.append(_finding(sig, {"package": m.package, "version": installed,
                                                  "fixed_in": m.version_lt}, mode))
        return out

    def scan_gguf_template(self, template: str, mode: str) -> list[Finding]:
        out = []
        for sig in self.signatures:
            for m in sig.match:
                if isinstance(m, GgufTemplateMatch) and re.search(m.pattern, template):
                    out.append(_finding(sig, {"field": "tokenizer.chat_template"}, mode))
        return out

    def scan_model_source(self, url: str, mode: str) -> list[Finding]:
        host = (urlparse(url).hostname or url).lower()
        out = []
        for sig in self.signatures:
            for m in sig.match:
                if isinstance(m, ModelSourceMatch):
                    allowed = [h.lower() for h in m.allow_hosts]
                    if host in allowed or any(host.endswith("." + h) for h in allowed):
                        continue
                    near = [h for h in allowed if _levenshtein(host, h) <= m.typosquat_distance]
                    kind = "typosquat" if near else "non_allowlisted_host"
                    out.append(_finding(sig, {"host": host, "kind": kind, "looks_like": near}, mode))
        return out

    def tool_poison_signature(self) -> Signature | None:
        for sig in self.signatures:
            if any(isinstance(m, ToolHashMatch) for m in sig.match):
                return sig
        return None
