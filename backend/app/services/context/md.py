"""Small Markdown rendering helpers."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.schemas.facts import Claim, DirectoryNode, EvidenceClass, SourceRef

BADGE = {
    EvidenceClass.DETECTED: "`DETECTED`",
    EvidenceClass.INFERRED: "`INFERRED`",
    EvidenceClass.AI_INTERPRETED: "`AI_INTERPRETED`",
    EvidenceClass.UNKNOWN: "`UNKNOWN`",
}


def esc(v: object) -> str:
    s = "" if v is None else str(v)
    return s.replace("|", "\\|").replace("\n", " ").replace("\r", " ").strip()


def table(headers: Sequence[str], rows: Iterable[Sequence[object]], empty: str = "_None found._") -> str:
    rows = list(rows)
    if not rows:
        return empty
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for r in rows:
        out.append("| " + " | ".join(esc(c) for c in r) + " |")
    return "\n".join(out)


def ref(r: SourceRef | None) -> str:
    return r.label() if r else ""


def loc(file: str | None, start: int | None = None, end: int | None = None) -> str:
    if not file:
        return ""
    if start is None:
        return f"`{file}`"
    if end and end != start:
        return f"`{file}:{start}-{end}`"
    return f"`{file}:{start}`"


def claim_line(c: Claim) -> str:
    srcs = ", ".join(s.label() for s in c.sources[:5])
    flag = "" if c.verified else " ⚠ _unverified_"
    src = f" — sources: {srcs}" if srcs else " — _no source reference_"
    return f"- {BADGE[c.classification]} {c.text}{src} _(confidence {c.confidence:.2f})_{flag}"


def claims_block(claims: list[Claim], empty: str) -> str:
    if not claims:
        return empty
    return "\n".join(claim_line(c) for c in claims)


def bullet(items: Iterable[str], empty: str = "_None._") -> str:
    items = [i for i in items if i]
    return "\n".join(f"- {i}" for i in items) if items else empty


def tree_text(node: DirectoryNode, files_by_dir: dict[str, list[str]], max_depth: int = 4, max_entries: int = 400) -> str:
    lines: list[str] = [f"{node.name}/"]
    count = 0

    def walk(n: DirectoryNode, prefix: str, depth: int) -> None:
        nonlocal count
        children = sorted(n.children, key=lambda c: c.name)
        files = sorted(files_by_dir.get(n.path, []))
        entries: list[tuple[str, DirectoryNode | None]] = [(c.name + "/", c) for c in children] + [(f, None) for f in files]
        for i, (name, child) in enumerate(entries):
            if count >= max_entries:
                lines.append(prefix + "└── … (truncated)")
                return
            last = i == len(entries) - 1
            conn = "└── " if last else "├── "
            if child is not None and depth >= max_depth:
                lines.append(f"{prefix}{conn}{name} ({_count_files(child)} files)")
                count += 1
                continue
            lines.append(prefix + conn + name)
            count += 1
            if child is not None:
                walk(child, prefix + ("    " if last else "│   "), depth + 1)

    walk(node, "", 1)
    return "```text\n" + "\n".join(lines) + "\n```"


def _count_files(n: DirectoryNode) -> int:
    return n.files + sum(_count_files(c) for c in n.children)
