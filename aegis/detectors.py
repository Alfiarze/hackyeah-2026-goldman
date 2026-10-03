"""Deterministic (non-AI) content controls: PII, secrets, prompt-injection heuristics."""

from __future__ import annotations

import base64
import binascii
import re
import unicodedata
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


def _nip_ok(s: str) -> bool:
    digits = [int(c) for c in re.sub(r"\D", "", s)]
    if len(digits) != 10:
        return False
    check = sum(w * d for w, d in zip((6, 5, 7, 2, 3, 4, 5, 6, 7), digits)) % 11
    return check != 10 and check == digits[9]


def _weighted_mod10_ok(s: str, weights: tuple[int, ...]) -> bool:
    """Polish ID card / passport: letters A=10..Z=35, weighted sum (check digit included) divisible by 10."""
    s = re.sub(r"\s", "", s).upper()
    if len(s) != len(weights):
        return False
    return sum(w * int(c, 36) for w, c in zip(weights, s)) % 10 == 0


def _id_card_ok(s: str) -> bool:  # ABC123456, check digit is the 4th character
    return _weighted_mod10_ok(s, (7, 3, 1, 9, 7, 3, 1, 7, 3))


def _passport_ok(s: str) -> bool:  # AB1234567, check digit is the 3rd character
    return _weighted_mod10_ok(s, (7, 3, 9, 1, 7, 3, 1, 7, 3))


_UP = "A-ZĄĆĘŁŃÓŚŹŻ"
_STREET = (r"\b(?:[Uu]l\.|[Uu]lic[ayę]|[Aa]l\.|[Aa]lej[aię]|[Oo]s\.|[Oo]siedl[eu]|[Pp]l\.|[Pp]lac[u]?)\s*"
           rf"[{_UP}0-9][\w.\- ]{{1,40}}?\s\d{{1,4}}[A-Za-z]?(?:\s?/\s?\d{{1,4}}[A-Za-z]?)?(?!\d)")
_POSTAL = rf"(?<![\d-])\d{{2}}-\d{{3}}(?![\d-])\s+[{_UP}][a-ząćęłńóśźż]+(?:[ -][{_UP}][a-ząćęłńóśźż]+)?"
_STREET_EN = r"\b\d{1,5}\s+[A-Z][a-z]+(?:\s[A-Z][a-z]+)?\s(?:Street|St\.|Avenue|Ave\.|Road|Rd\.|Boulevard|Blvd\.|Lane)\b"

PII_PATTERNS: dict[str, tuple[re.Pattern[str], object]] = {
    "PESEL": (re.compile(r"(?<!\d)\d{11}(?!\d)"), _pesel_ok),
    "CREDIT_CARD": (re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)"), _luhn_ok),
    "IBAN": (re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?\b"), _iban_ok),
    "EMAIL": (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), None),
    "PHONE": (re.compile(r"(?<![\d+])(?:\+48[ -]?)?\d{3}[ -]\d{3}[ -]\d{3}(?!\d)"), None),
    # tax id: 10 digits (plain, 123-456-78-90 or 123-45-67-890), optional PL prefix, mod-11 checksum
    "NIP": (re.compile(r"(?<![\w-])(?:PL)?(?:\d{3}-\d{3}-\d{2}-\d{2}|\d{3}-\d{2}-\d{2}-\d{3}|\d{10})(?![\w-])"), _nip_ok),
    "ID_CARD": (re.compile(r"(?i)(?<![\w])[A-Z]{3}\s?\d{6}(?![\w])"), _id_card_ok),
    "PASSPORT": (re.compile(r"(?i)(?<![\w])[A-Z]{2}\s?\d{7}(?![\w])"), _passport_ok),
    "ADDRESS": (re.compile(f"{_STREET}|{_POSTAL}|{_STREET_EN}"), None),
}

SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "AWS_ACCESS_KEY": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "PRIVATE_KEY": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    "GITHUB_TOKEN": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "SLACK_TOKEN": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "API_KEY": re.compile(r"\b(?:sk|pk|rk)[-_](?:live|test|proj)?[-_]?[A-Za-z0-9]{20,}\b"),
    "GOOGLE_API_KEY": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "CONNECTION_STRING": re.compile(r"\b[a-z][a-z0-9+.-]{1,20}://[^\s:/@]+:[^\s@/]+@[^\s/]+"),
    "PASSWORD_ASSIGNMENT": re.compile(
        r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|haslo|hasło)\s*[:=]\s*['\"]?[^\s'\"]{6,}"
    ),
}

# A password given in plain words: "moje hasło to Zima2024", "my password is Tr0ub4dor&3",
# "hasło do banku: Kot!2024", "PIN 4821". Only the value is reported; it must look like a credential.
_PASSWORD_PHRASE = re.compile(
    r"(?i)\b(?:has(?:ł|l)(?:o|a|em|u)?|password|passwd|pwd|passcode|passphrase|parol\w*)\b"
    r"(?:\s+(?:to|jest|is|was|brzmi|na|my|moje|mój|nowe|new|do\s+\S+|for\s+(?:my\s+)?\S+|of\s+\S+)\b)*"
    r"\s*[:=]?\s*[\"'“„`]?(?P<value>[^\s\"'”`,;]{6,64})"
)
_PIN_PHRASE = re.compile(r"(?i)\bPIN\b(?:\s+(?:to|jest|is|code|kod|do\s+\S+))*\s*[:=]?\s*(?P<value>\d{4,8})\b")


def _looks_like_password(v: str) -> bool:
    v = v.rstrip(".!?)")
    if len(v) < 6 or "://" in v:
        return False
    has_alpha = any(c.isalpha() for c in v)
    has_digit = any(c.isdigit() for c in v)
    has_symbol = any(not c.isalnum() for c in v)
    inner_upper = any(c.isupper() for c in v[1:])
    return has_digit or (has_alpha and has_symbol) or (inner_upper and any(c.islower() for c in v))


def find_password_phrases(text: str) -> list[tuple[int, int, str]]:
    spans = [(m.start("value"), m.end("value"), "PASSWORD") for m in _PASSWORD_PHRASE.finditer(text)
             if _looks_like_password(m.group("value"))]
    spans += [(m.start("value"), m.end("value"), "PIN") for m in _PIN_PHRASE.finditer(text)]
    return spans


INJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "IGNORE_INSTRUCTIONS": re.compile(
        r"(?i)\b(?:ignore|disregard|forget|override)\b[^.\n]{0,40}\b(?:previous|prior|above|earlier|all|your)\b[^.\n]{0,20}\b(?:instructions?|prompts?|rules|directives)"
    ),
    "IGNORE_INSTRUCTIONS_PL": re.compile(
        r"(?i)\b(?:zignoruj|pomiń|zapomnij)\b[^.\n]{0,40}\b(?:poprzednie|wcześniejsze|wszystkie)\b[^.\n]{0,20}\b(?:instrukcje|polecenia|zasady)"
    ),
    "ROLE_OVERRIDE": re.compile(r"(?i)\byou are now\b|\bnew system prompt\b|\bact as (?:an? )?(?:unrestricted|jailbroken)"),
    "SYSTEM_PROMPT_EXFIL": re.compile(r"(?i)\b(?:reveal|print|show|repeat|output)\b[^.\n]{0,30}\b(?:system prompt|hidden instructions|initial instructions)"),
    "SYSTEM_PROMPT_EXFIL_PL": re.compile(
        r"(?i)\b(?:pokaż|wypisz|ujawnij|powtórz|podaj|wyświetl)\b[^.\n]{0,30}\b(?:prompt\w* systemow\w*|instrukcj\w* systemow\w*|ukryt\w* instrukcj\w*)"
    ),
    "JAILBREAK": re.compile(
        r"(?i)\b(?:do anything now|(?:developer|god|jailbreak|unrestricted|unfiltered) mode|jailbroken)\b"
        r"|\byou (?:have|are|'re|now have)\b[^.\n]{0,30}\b(?:no|without any|without)\b (?:restrictions|limits|rules|filters|guidelines)"
        r"|\b(?:nie masz|jesteś bez|nie obowiązują cię)\b[^.\n]{0,20}\b(?:ograniczeń|zasad|filtrów|cenzury|reguł|żadne zasady)"
        r"|\btryb (?:dewelopera|deweloperski|bez ograniczeń|boga)\b"
    ),
    "JAILBREAK_DAN": re.compile(r"\bDAN\b(?=[^.\n]{0,60}\b(?i:anything|restrictions|rules|jailbreak|mode|prompt)\b)|\b(?i:you are|jesteś)\s+DAN\b"),
    "ROLEPLAY_BYPASS": re.compile(
        r"(?i)\b(?:act|pretend|roleplay|role-play)\b[^.\n]{0,20}\b(?:as|to be|you are)\b[^.\n]{0,30}\b(?:grand(?:ma|mother)|deceased|evil|unfiltered|unrestricted|uncensored)"
        r"|\b(?:udawaj|wciel się|odgrywaj|zachowuj się jak)\b[^.\n]{0,40}\b(?:babci\w*|zmarł\w*|bez ograniczeń|bez cenzury|zł\w+ AI)"
    ),
    "MARKDOWN_EXFIL": re.compile(r"!\[[^\]]*\]\(\s*https?://[^)\s]*[?&][^)\s]*\)"),
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
    spans = [(m.start(), m.end(), name) for name, p in SECRET_PATTERNS.items() for m in p.finditer(text)]
    return _dedupe(spans + find_password_phrases(text))


_HIDDEN_BLOCK = re.compile(r"<!--.*?-->|\[//\]: # \(.*?\)|<span[^>]*display:\s*none[^>]*>.*?</span>", re.S | re.I)


_ZERO_WIDTH = re.compile("[\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "|": "l"})
_SPACED = re.compile(r"\b(?:\w[ .\-_*]){3,}\w\b")
_B64 = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{16,}={0,2}(?![A-Za-z0-9+/=])")


def _deobfuscate(text: str) -> list[str]:
    """Variants an attacker uses to slip past the plain patterns: zero-width characters, homoglyphs (NFKC),
    leetspeak, s p a c e d letters and base64-wrapped instructions."""
    clean = unicodedata.normalize("NFKC", _ZERO_WIDTH.sub("", text))
    joined = _SPACED.sub(lambda m: re.sub(r"[ .\-_*]", "", m.group(0)), clean)
    variants = [clean, joined, joined.translate(_LEET)]
    for m in _B64.finditer(text):
        try:
            decoded = base64.b64decode(m.group(0), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if decoded.isprintable() or "\n" in decoded:
            variants.append(decoded)
    return [v for v in dict.fromkeys(variants) if v != text]


def find_injection(text: str) -> list[tuple[int, int, str]]:
    spans = _find_injection_plain(text)
    if spans:
        return spans
    for variant in _deobfuscate(text):  # obfuscated instruction: offsets do not map back, flag the whole text
        names = sorted({s[2] for s in _find_injection_plain(variant)})
        if names:
            return [(0, len(text), f"OBFUSCATED_{names[0]}")]
    return []


def _find_injection_plain(text: str) -> list[tuple[int, int, str]]:
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
