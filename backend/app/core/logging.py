"""Logging setup with a filter that scrubs anything that looks like a credential."""

from __future__ import annotations

import logging
import re

_SCRUB_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9_\-]{8,})"),
    re.compile(r"(sk-ant-[A-Za-z0-9_\-]{8,})"),
    re.compile(r"(AIza[0-9A-Za-z_\-]{20,})"),
    re.compile(r"((?:api[_-]?key|authorization|x-api-key|x-goog-api-key)[\"']?\s*[:=]\s*[\"']?)([^\s\"',}]+)", re.I),
]


class SecretScrubFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        scrubbed = msg
        for pat in _SCRUB_PATTERNS:
            if pat.groups == 2:
                scrubbed = pat.sub(lambda m: m.group(1) + "[REDACTED]", scrubbed)
            else:
                scrubbed = pat.sub("[REDACTED]", scrubbed)
        if scrubbed != msg:
            record.msg = scrubbed
            record.args = ()
        return True


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if any(isinstance(f, SecretScrubFilter) for h in root.handlers for f in h.filters):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(SecretScrubFilter())
    root.addHandler(handler)
    root.setLevel(level.upper())
    # httpx logs full URLs at INFO; Gemini URLs may carry keys in some setups.
    logging.getLogger("httpx").setLevel(logging.WARNING)
