"""Secret detection and redaction.

Used for two purposes:
1. Findings in SECURITY_REVIEW.md (always redacted; raw values never stored).
2. Scrubbing any text before it is sent to an external LLM provider.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from app.schemas.facts import SecretHit


@dataclass(frozen=True)
class SecretRule:
    kind: str
    pattern: re.Pattern[str]
    group: int = 0


RULES: list[SecretRule] = [
    SecretRule("AWS access key id", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    SecretRule("AWS secret access key", re.compile(r"(?i)aws_?secret_?access_?key[\"'\s:=]+([A-Za-z0-9/+=]{40})"), 1),
    SecretRule("GitHub token", re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b")),
    SecretRule("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}\b")),
    SecretRule("OpenAI API key", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{20,}\b")),
    SecretRule("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    SecretRule("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    SecretRule("Slack token", re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}\b")),
    SecretRule("Stripe secret key", re.compile(r"\b(sk|rk)_(live|test)_[A-Za-z0-9]{20,}\b")),
    SecretRule("Twilio key", re.compile(r"\bSK[0-9a-fA-F]{32}\b")),
    SecretRule("SendGrid key", re.compile(r"\bSG\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\b")),
    SecretRule("Private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY(?: BLOCK)?-----")),
    SecretRule("JSON Web Token", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
    SecretRule("Credentials in connection URL", re.compile(r"\b[a-z][a-z0-9+\-.]*://[^\s:/@\"']+:([^\s@/\"'$]{3,})@[^\s\"']+"), 1),
    SecretRule(
        "Hardcoded secret assignment",
        re.compile(
            r"(?i)\b([A-Za-z0-9_]*(?:password|passwd|pwd|secret|api_?key|access_?token|auth_?token|private_?key|client_?secret|jwt_?secret|signing_?key)[A-Za-z0-9_]*)"
            r"\s*[:=]\s*[\"']([^\"'\s]{6,})[\"']"
        ),
        2,
    ),
]

PLACEHOLDER = re.compile(
    r"(?i)^(\$\{.*\}|<.*>|\{\{.*\}\}|changeme|change[-_]?me|your[-_].*|xxx+|\*+|example|dummy|test|testing|placeholder|"
    r"password|secret|todo|none|null|undefined|process\.env.*|os\.environ.*|settings\..*|replace[-_]?me|\.\.\.|sk-\.\.\.|"
    r"sk-your.*|.*_here|fake.*|mock.*|sample.*|redacted|\[redacted.*\])$"
)


def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    return -sum((c / len(s)) * math.log2(c / len(s)) for c in freq.values())


def redact_value(value: str) -> str:
    if len(value) <= 8:
        return "[REDACTED]"
    return f"{value[:3]}…[REDACTED:{len(value)} chars]"


def _is_placeholder(value: str) -> bool:
    v = value.strip()
    if PLACEHOLDER.match(v):
        return True
    return len(set(v)) <= 3


def find_secrets(path: str, text: str, is_template: bool = False) -> list[SecretHit]:
    hits: list[SecretHit] = []
    seen: set[tuple[int, str]] = set()
    for lineno, line in enumerate(text.splitlines(), 1):
        if len(line) > 4000:
            line = line[:4000]
        for rule in RULES:
            for m in rule.pattern.finditer(line):
                value = m.group(rule.group) if rule.group else m.group(0)
                if rule.kind in {"Hardcoded secret assignment", "Credentials in connection URL"}:
                    if _is_placeholder(value) or is_template:
                        continue
                    if rule.kind == "Hardcoded secret assignment" and shannon_entropy(value) < 2.5:
                        continue
                key = (lineno, rule.kind)
                if key in seen:
                    continue
                seen.add(key)
                weak = len(value) < 8 or shannon_entropy(value) < 2.5
                hits.append(SecretHit(file=path, line=lineno, kind=rule.kind, redacted=redact_value(value), weak=weak))
    return hits


def redact_text(text: str) -> tuple[str, int]:
    """Replace every detected secret value in ``text`` with a placeholder. Returns (text, count)."""
    count = 0

    def _sub_rule(rule: SecretRule, s: str) -> str:
        nonlocal count

        def repl(m: re.Match[str]) -> str:
            nonlocal count
            whole = m.group(0)
            if rule.group:
                val = m.group(rule.group)
                if rule.kind == "Hardcoded secret assignment" and (_is_placeholder(val) or shannon_entropy(val) < 2.5):
                    return whole
                if rule.kind == "Credentials in connection URL" and _is_placeholder(val):
                    return whole
                count += 1
                start, end = m.start(rule.group) - m.start(0), m.end(rule.group) - m.start(0)
                return whole[:start] + "[REDACTED_SECRET]" + whole[end:]
            count += 1
            return "[REDACTED_SECRET]"

        return rule.pattern.sub(repl, s)

    # private key bodies first: drop everything between BEGIN/END markers
    out, n = re.subn(r"-----BEGIN [A-Z ]*PRIVATE KEY[A-Z ]*-----.*?-----END [A-Z ]*PRIVATE KEY[A-Z ]*-----", "[REDACTED_PRIVATE_KEY]", text, flags=re.S)
    count += n
    for rule in RULES:
        out = _sub_rule(rule, out)
    return out, count
