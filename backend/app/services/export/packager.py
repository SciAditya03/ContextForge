"""Export: build the downloadable context package ZIP."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path


def package_name(project_name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", project_name).strip("-")[:60] or "project"
    return f"contextforge-{slug}"


def build_zip(output_dir: Path, dest: Path, project_name: str) -> Path:
    root = package_name(project_name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in sorted(output_dir.rglob("*")):
            if p.is_file():
                zf.write(p, f"{root}/{p.relative_to(output_dir).as_posix()}")
    tmp.replace(dest)
    return dest
