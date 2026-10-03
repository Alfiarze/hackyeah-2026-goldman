"""Deterministic (non-AI) content controls: PII, secrets, prompt-injection heuristics."""

from __future__ import annotations

import re
from collections.abc import Iterable

from aegis.models import Finding

# ---------------------------------------------------------------- validators


def _pesel_ok(s: str) -> bool:
    weights = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
    digits = [int(c) for c in s]
    return (10 - sum(w * d for w, d in zip(weights, digits)) % 10) % 10 == digits[10]


def _luhn_ok(s: str) -> bool:
    digits = [int(c) for c in re.sub(r"\D", "", s)]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d *= 2
            d -= 9 if d > 9 else 0
        total += d
    return total % 10 == 0


def _iban_ok(s: str) -> bool:
    s = re.sub(r"\s", "", s).upper()
    if not 15 <= len(s) <= 34:
        return False
    rearranged = s[4:] + s[:4]
    return int("".join(str(int(c, 36)) for c in rearranged)) % 97 == 1


PII_PATTERNS: dict[str, tuple[re.Pattern[str], object]] = {
    "PESEL": (re.compile(r"(?<!\d)\d{11}(?!\d)"), _pesel_ok),
    "CREDIT_CARD": (re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)"), _luhn_ok),
    "IBAN": (re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?\b"), _iban_ok),
    "EMAIL": (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), None),
    "PHONE": (re.compile(r"(?<![\d+])(?:\+48[ -]?)?\d{3}[ -]\d{3}[ -]\d{3}(?!\d)"), None),
}

SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "AWS_ACCESS_KEY": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "PRIVATE_KEY": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    "GITHUB_TOKEN": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "SLACK_TOKEN": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "API_KEY": re.compile(r"\b(?:sk|pk|rk)-(?:live|test|proj)?[-_]?[A-Za-z0-9]{20,}\b"),
    "PASSWORD_ASSIGNMENT": re.compile(
        r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|haslo|hasło)\s*[:=]\s*['\"]?[^\s'\"]{6,}"
    ),
}

INJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "IGNORE_INSTRUCTIONS": re.compile(
        r"(?i)\b(?:ignore|disregard|forget|override)\b[^.\n]{0,40}\b(?:previous|prior|above|earlier|all)\b[^.\n]{0,20}\b(?:instructions?|prompts?|rules|directives)"
    ),
    "IGNORE_INSTRUCTIONS_PL": re.compile(
        r"(?i)\b(?:zignoruj|pomiń|zapomnij)\b[^.\n]{0,40}\b(?:poprzednie|wcześniejsze|wszystkie)\b[^.\n]{0,20}\b(?:instrukcje|polecenia|zasady)"
    ),
    "ROLE_OVERRIDE": re.compile(r"(?i)\byou are now\b|\bnew system prompt\b|\bact as (?:an? )?(?:unrestricted|jailbroken)"),
    "SYSTEM_PROMPT_EXFIL": re.compile(r"(?i)\b(?:reveal|print|show|repeat)\b[^.\n]{0,30}\b(?:system prompt|hidden instructions)"),
    "HIDDEN_AI_NOTE": re.compile(r"(?i)\b(?:note|message|instruction)s? (?:for|to) the (?:ai|assistant|agent|llm)\b"),
    "CONCEALMENT": re.compile(r"(?i)\bdo not (?:mention|tell|inform|reveal)\b[^.\n]{0,30}\b(?:user|anyone|this)"),
}


# ---------------------------------------------------------------- detectors


def find_pii(text: str, entities: Iterable[str]) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    for name in entities:
        pattern, validator = PII_PATTERNS[name]
        for m in pattern.finditer(text):
            if validator is None or validator(m.group(0)):
                spans.append((m.start(), m.end(), name))
    return _dedupe(spans)


def find_secrets(text: str) -> list[tuple[int, int, str]]:
    return _dedupe(
        (m.start(), m.end(), name) for name, p in SECRET_PATTERNS.items() for m in p.finditer(text)
    )


_HIDDEN_BLOCK = re.compile(r"<!--.*?-->|\[//\]: # \(.*?\)|<span[^>]*display:\s*none[^>]*>.*?</span>", re.S | re.I)


def find_injection(text: str) -> list[tuple[int, int, str]]:
    hidden = [(m.start(), m.end()) for m in _HIDDEN_BLOCK.finditer(text)]
    spans = []
    for name, p in INJECTION_PATTERNS.items():
        for m in p.finditer(text):
            block = next(((s, e) for s, e in hidden if s <= m.start() < e), None)
            if block:  # instruction hidden in markup: remove the whole hidden block
                spans.append((block[0], block[1], name))
                continue
            # otherwise widen to the containing sentence/line
            nl, dot = text.rfind("\n", 0, m.start()), text.rfind(". ", 0, m.start())
            start = max(nl + 1 if nl != -1 else 0, dot + 2 if dot != -1 else 0)
            ends = [e for e in (text.find("\n", m.end()), text.find(". ", m.end())) if e != -1]
            end = min(ends) + 1 if ends else len(text)
            spans.append((start, end, name))
    return _dedupe(spans)


def _dedupe(spans: Iterable[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    out: list[tuple[int, int, str]] = []
    for s in sorted(spans):
        if out and s[0] < out[-1][1]:
            prev = out[-1]
            out[-1] = (prev[0], max(prev[1], s[1]), prev[2])
        else:
            out.append(s)
    return out


def redact(text: str, spans: list[tuple[int, int, str]]) -> str:
    for start, end, label in sorted(_dedupe(spans), reverse=True):
        text = f"{text[:start]}[REDACTED:{label}]{text[end:]}"
    return text


# ---------------------------------------------------------------- findings


def pii_finding(text: str, entities: Iterable[str], mode: str) -> Finding | None:
    spans = find_pii(text, entities)
    if not spans:
        return None
    return Finding(
        action="BLOCK" if mode == "block" else "REDACT",
        rule_id="PII-001",
        reason_code="PII_DETECTED",
        stage="deterministic",
        detail={"entities": sorted({s[2] for s in spans}), "count": len(spans)},
        spans=spans,
    )


def secrets_finding(text: str, mode: str) -> Finding | None:
    spans = find_secrets(text)
    if not spans:
        return None
    return Finding(
        action="BLOCK" if mode == "block" else "REDACT",
        rule_id="SEC-001",
        reason_code="SECRET_DETECTED",
        stage="deterministic",
        detail={"types": sorted({s[2] for s in spans}), "count": len(spans)},
        spans=spans,
    )


def injection_finding(text: str, mode: str) -> Finding | None:
    spans = find_injection(text)
    if not spans:
        return None
    return Finding(
        action="BLOCK" if mode == "block" else "REDACT",
        rule_id="INJ-001",
        reason_code="PROMPT_INJECTION_HEURISTIC",
        stage="deterministic",
        detail={"patterns": sorted({s[2] for s in spans})},
        spans=spans,
    )
