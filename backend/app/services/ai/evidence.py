"""Stage F: evidence validation for AI output.

Every source reference produced by a model is checked against the real file
inventory. Invalid references are dropped (or repaired when the intended file
is unambiguous), and claims that end up without valid evidence are marked
unverified. Paths mentioned in prose that do not exist are flagged.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from app.schemas.facts import Claim, EvidenceClass, SourceRef

_PATH_IN_TEXT = re.compile(r"`?([\w@.\-]+(?:/[\w@.\-\[\]()]+)+\.[a-zA-Z]{1,6})`?")


class EvidenceValidator:
    def __init__(self, file_lines: dict[str, int]) -> None:
        self.file_lines = file_lines
        self.by_name: dict[str, list[str]] = {}
        for p in file_lines:
            self.by_name.setdefault(p.rsplit("/", 1)[-1], []).append(p)
        self.stats = {"refs_total": 0, "refs_valid": 0, "refs_repaired": 0, "refs_dropped": 0, "claims_total": 0,
                      "claims_unverified": 0, "phantom_paths": 0}

    def _resolve(self, path: str) -> str | None:
        p = path.strip().strip("`").lstrip("./")
        if p in self.file_lines:
            return p
        cands = [x for x in self.file_lines if x.endswith("/" + p)]
        if len(cands) == 1:
            return cands[0]
        name = p.rsplit("/", 1)[-1]
        if "/" not in p and len(self.by_name.get(name, [])) == 1:
            return self.by_name[name][0]
        return None

    def refs(self, raw: Iterable[Any]) -> list[SourceRef]:
        out: list[SourceRef] = []
        for r in raw or []:
            self.stats["refs_total"] += 1
            if isinstance(r, str):
                m = re.match(r"^(.*?)(?::(\d+)(?:-(\d+))?)?$", r.strip())
                r = {"file": m.group(1), "line_start": m.group(2), "line_end": m.group(3)} if m else {"file": r}
            if not isinstance(r, dict) or not r.get("file"):
                self.stats["refs_dropped"] += 1
                continue
            resolved = self._resolve(str(r["file"]))
            if resolved is None:
                self.stats["refs_dropped"] += 1
                continue
            if resolved != str(r["file"]).strip().lstrip("./"):
                self.stats["refs_repaired"] += 1
            n = self.file_lines[resolved]
            ls, le = _int(r.get("line_start")), _int(r.get("line_end"))
            if ls is not None and (ls < 1 or ls > max(n, 1)):
                ls, le = None, None
            if le is not None and ls is not None and (le < ls or le > n):
                le = min(max(ls, le), n) if n else None
            self.stats["refs_valid"] += 1
            out.append(SourceRef(file=resolved, line_start=ls, line_end=le))
        # dedupe
        seen = set()
        uniq = []
        for s in out:
            k = (s.file, s.line_start, s.line_end)
            if k not in seen:
                seen.add(k)
                uniq.append(s)
        return uniq[:8]

    def phantom_paths(self, text: str) -> list[str]:
        bad = []
        for m in _PATH_IN_TEXT.finditer(text or ""):
            p = m.group(1)
            if p.startswith(("http", "www.")) or "://" in p:
                continue
            if self._resolve(p) is None:
                bad.append(p)
        return bad

    def claim(self, raw: Any, layer: str, default_conf: float = 0.6) -> Claim | None:
        if isinstance(raw, str):
            raw = {"text": raw}
        if not isinstance(raw, dict):
            return None
        text = str(raw.get("text") or raw.get("claim") or "").strip()
        if not text:
            return None
        self.stats["claims_total"] += 1
        sources = self.refs(raw.get("sources") or raw.get("evidence") or [])
        phantoms = self.phantom_paths(text)
        self.stats["phantom_paths"] += len(phantoms)
        verified = bool(sources) and not phantoms
        if not verified:
            self.stats["claims_unverified"] += 1
        conf = _float(raw.get("confidence"), default_conf)
        if not sources:
            conf = min(conf, 0.4)
        if phantoms:
            text += f" _(validation: referenced path(s) not found in repository: {', '.join(phantoms[:3])})_"
            conf = min(conf, 0.3)
        return Claim(text=text, classification=EvidenceClass.AI_INTERPRETED, sources=sources, layer=layer,
                     confidence=round(conf, 2), evidence_type="llm", verified=verified)

    def claims(self, raw: Any, layer: str) -> list[Claim]:
        if not isinstance(raw, list):
            raw = [raw] if raw else []
        out = []
        for r in raw[:40]:
            c = self.claim(r, layer)
            if c is not None:
                out.append(c)
        return out


def _int(v: Any) -> int | None:
    try:
        return int(v) if v is not None and str(v).strip() != "" else None
    except (TypeError, ValueError):
        return None


def _float(v: Any, default: float) -> float:
    try:
        f = float(v)
        return max(0.0, min(1.0, f))
    except (TypeError, ValueError):
        return default
