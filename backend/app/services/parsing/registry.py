"""Parser dispatch with a content-addressed on-disk cache."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from app.schemas.facts import FileCategory, FileRecord
from app.services.parsing.base import PARSER_VERSION, ParseResult
from app.services.parsing.heuristic_parser import SPECS, parse_heuristic, parse_prisma, parse_sql
from app.services.parsing.python_parser import parse_python
from app.services.parsing.ts_parser import parse_typescript
from app.services.security.secrets import redact_text

log = logging.getLogger(__name__)

PARSEABLE_CATEGORIES = {FileCategory.SOURCE, FileCategory.TEST, FileCategory.MIGRATION, FileCategory.SCHEMA, FileCategory.CONFIG, FileCategory.BUILD}


def parser_for(rec: FileRecord) -> str | None:
    if rec.status != "included" or rec.category not in PARSEABLE_CATEGORIES:
        return None
    lang = rec.language
    if lang == "Python":
        return "python"
    if lang in {"JavaScript", "TypeScript"}:
        return "ts"
    if lang == "Prisma":
        return "prisma"
    if lang == "SQL":
        return "sql"
    if lang in SPECS:
        return "heuristic"
    return None


def parse_file(root: Path, rec: FileRecord, cache_dir: Path | None, max_bytes: int) -> ParseResult | None:
    kind = parser_for(rec)
    if kind is None:
        return None
    if rec.size > max_bytes:
        return None
    cache_file = None
    if cache_dir is not None and rec.sha256:
        # key on content *and* path: relative imports / file-based routes depend on location
        key = hashlib.sha256(f"{PARSER_VERSION}:{kind}:{rec.path}:{rec.sha256}".encode()).hexdigest()
        cache_file = cache_dir / f"{key}.json"
        if cache_file.exists():
            try:
                return ParseResult.from_json(cache_file.read_text(encoding="utf-8"))
            except Exception:
                cache_file.unlink(missing_ok=True)
    text = (root / rec.path).read_text(encoding="utf-8", errors="replace")
    if kind == "python":
        res = parse_python(rec.path, text)
    elif kind == "ts":
        res = parse_typescript(rec.path, text)
    elif kind == "prisma":
        res = parse_prisma(rec.path, text)
    elif kind == "sql":
        res = parse_sql(rec.path, text)
    else:
        res = parse_heuristic(rec.path, text, rec.language or "")
    _sanitize(res)
    if cache_file is not None:
        try:
            cache_file.write_text(res.to_json(), encoding="utf-8")
        except OSError as exc:
            log.debug("parse cache write failed: %s", exc)
    return res


def _sanitize(res: ParseResult) -> None:
    """Strip secret values from every extracted string before it is stored, rendered or sent anywhere."""
    for s in res.module.symbols:
        if s.signature:
            s.signature = redact_text(s.signature)[0]
        if s.docstring:
            s.docstring = redact_text(s.docstring)[0]
    if res.module.docstring:
        res.module.docstring = redact_text(res.module.docstring)[0]
    res.module.string_literals_sql = [(redact_text(t)[0], ln) for t, ln in res.module.string_literals_sql]
    for c in res.client_calls:
        c.url = redact_text(c.url)[0]
    for h in res.module.http_calls:
        h["url"] = redact_text(str(h.get("url", "")))[0]
    for o in res.db_operations:
        if o.snippet:
            o.snippet = redact_text(o.snippet)[0]
    for m in res.db_models:
        for f in m.fields:
            if f.default:
                f.default = redact_text(f.default)[0]


def safe_parse(root: Path, rec: FileRecord, cache_dir: Path | None, max_bytes: int) -> tuple[ParseResult | None, str | None]:
    try:
        return parse_file(root, rec, cache_dir, max_bytes), None
    except RecursionError:
        return None, "file too deeply nested to parse"
    except Exception as exc:
        log.warning("parser failed for %s: %s", rec.path, exc)
        return None, f"{type(exc).__name__}: {exc}"
