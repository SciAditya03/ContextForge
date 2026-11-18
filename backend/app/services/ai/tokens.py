"""Token estimation, budgeting and context-window management helpers.

Estimates are provider-neutral (characters / 3.5, which is conservative for
source code). Actual usage reported by providers is recorded separately.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

CHARS_PER_TOKEN = 3.5


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN) if text else 0


@dataclass
class DepthProfile:
    name: str
    max_ai_files: int
    per_file_chars: int
    batch_tokens: int
    effort: str
    include_tests: bool
    module_batch: int = 12


DEPTHS: dict[str, DepthProfile] = {
    "quick": DepthProfile("quick", max_ai_files=40, per_file_chars=6_000, batch_tokens=9_000, effort="low", include_tests=False),
    "standard": DepthProfile("standard", max_ai_files=160, per_file_chars=14_000, batch_tokens=16_000, effort="medium", include_tests=False),
    "deep": DepthProfile("deep", max_ai_files=700, per_file_chars=28_000, batch_tokens=28_000, effort="high", include_tests=True),
}


@dataclass
class TokenBudget:
    total: int
    used: int = 0
    reservations: dict[str, int] = field(default_factory=dict)

    @property
    def remaining(self) -> int:
        return max(0, self.total - self.used)

    def can_afford(self, tokens: int, keep_for_later: int = 0) -> bool:
        return self.used + tokens + keep_for_later <= self.total

    def spend(self, tokens: int) -> None:
        self.used += max(0, tokens)


def truncate_lines(text: str, max_chars: int) -> tuple[str, int, int]:
    """Return (numbered text, included_line_count, total_lines).

    Lines are prefixed with their 1-based number so the model can cite exact ranges.
    Truncation keeps whole lines from the top and records what was dropped.
    """
    lines = text.splitlines()
    out: list[str] = []
    size = 0
    width = len(str(len(lines)))
    for i, line in enumerate(lines, 1):
        if len(line) > 400:
            line = line[:400] + " …[line truncated]"
        entry = f"{str(i).rjust(width)}| {line}"
        if size + len(entry) + 1 > max_chars and out:
            out.append(f"[… lines {i}-{len(lines)} omitted: per-file character budget of {max_chars} reached …]")
            return "\n".join(out), i - 1, len(lines)
        out.append(entry)
        size += len(entry) + 1
    return "\n".join(out), len(lines), len(lines)
