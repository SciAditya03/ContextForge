"""Hardened ZIP extraction for untrusted archives.

Protections:
- path traversal (absolute paths, ``..`` segments, drive letters, backslashes)
- symlinks (skipped, never created)
- ZIP bombs (declared + actual size accounting, per-entry compression ratio)
- file count, single-file size and total size limits
- extraction timeout
- encrypted entries (rejected)
- exclusion patterns applied before anything touches disk
Nothing extracted is ever executed.
"""

from __future__ import annotations

import fnmatch
import shutil
import stat
import time
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

CHUNK = 1024 * 64


class ZipSecurityError(Exception):
    """Raised when an archive violates a security constraint."""


@dataclass
class ZipLimits:
    max_archive_bytes: int = 200 * 1024 * 1024
    max_total_bytes: int = 1024 * 1024 * 1024
    max_files: int = 50_000
    max_file_bytes: int = 50 * 1024 * 1024
    max_ratio: int = 200
    timeout_s: float = 120.0


@dataclass
class ExtractionResult:
    root: Path
    extracted: list[str] = field(default_factory=list)
    excluded: list[tuple[str, str]] = field(default_factory=list)  # (path, reason)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    total_bytes: int = 0
    stripped_prefix: str | None = None


def normalize_member(name: str) -> str | None:
    """Return a safe relative POSIX path, or None if the name is unsafe."""
    name = name.replace("\\", "/")
    if not name or name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        return None
    parts = []
    for part in PurePosixPath(name).parts:
        if part in ("", "."):
            continue
        if part == ".." or "\x00" in part:
            return None
        parts.append(part)
    if not parts:
        return None
    return "/".join(parts)


def matches_exclusion(rel_path: str, patterns: Iterable[str]) -> str | None:
    """Return the matching pattern if ``rel_path`` is excluded.

    Patterns ending in ``/`` match a directory name anywhere in the path.
    Other patterns are fnmatch'd against the basename and the full path.
    """
    parts = rel_path.split("/")
    base = parts[-1]
    for pat in patterns:
        pat = pat.strip()
        if not pat or pat.startswith("#"):
            continue
        if pat.endswith("/"):
            d = pat.rstrip("/")
            if "/" in d:
                if rel_path.startswith(d + "/") or f"/{d}/" in f"/{rel_path}":
                    return pat
            elif any(fnmatch.fnmatch(p, d) for p in parts[:-1]):
                return pat
        elif fnmatch.fnmatch(base, pat) or fnmatch.fnmatch(rel_path, pat):
            return pat
    return None


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def _common_prefix(names: list[str]) -> str | None:
    """Detect a single top-level folder wrapping the whole archive."""
    tops = {n.split("/", 1)[0] for n in names}
    if len(tops) == 1:
        top = next(iter(tops))
        if all("/" in n for n in names):
            return top
    return None


def safe_extract(
    archive: Path,
    dest: Path,
    limits: ZipLimits,
    exclusions: Iterable[str] = (),
) -> ExtractionResult:
    exclusions = list(exclusions)
    if archive.stat().st_size > limits.max_archive_bytes:
        raise ZipSecurityError(
            f"Archive exceeds maximum size of {limits.max_archive_bytes // (1024 * 1024)} MB"
        )
    if not zipfile.is_zipfile(archive):
        raise ZipSecurityError("File is not a valid ZIP archive")

    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()
    started = time.monotonic()
    result = ExtractionResult(root=dest)

    try:
        zf = zipfile.ZipFile(archive)
    except zipfile.BadZipFile as exc:
        raise ZipSecurityError(f"Corrupt ZIP archive: {exc}") from exc

    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > limits.max_files * 4:
            raise ZipSecurityError(f"Archive contains too many entries ({len(infos)})")

        declared_total = sum(i.file_size for i in infos)
        if declared_total > limits.max_total_bytes * 4:
            raise ZipSecurityError("Archive declared uncompressed size is unreasonably large")

        safe_names: list[tuple[zipfile.ZipInfo, str]] = []
        for info in infos:
            rel = normalize_member(info.filename)
            if rel is None:
                raise ZipSecurityError(f"Unsafe path in archive: {info.filename!r}")
            safe_names.append((info, rel))

        prefix = _common_prefix([r for _, r in safe_names])
        result.stripped_prefix = prefix

        count = 0
        for info, rel in safe_names:
            if time.monotonic() - started > limits.timeout_s:
                raise ZipSecurityError("Extraction timed out")
            if prefix:
                rel = rel[len(prefix) + 1 :]
            if not rel:
                continue
            if _is_symlink(info):
                result.skipped.append((rel, "symlink (not followed)"))
                continue
            if info.flag_bits & 0x1:
                result.skipped.append((rel, "encrypted entry"))
                continue
            pat = matches_exclusion(rel, exclusions)
            if pat:
                result.excluded.append((rel, f"excluded by pattern '{pat}'"))
                continue
            if info.file_size > limits.max_file_bytes:
                result.skipped.append((rel, f"file larger than {limits.max_file_bytes // (1024 * 1024)} MB"))
                continue
            if info.compress_size > 0 and info.file_size / max(info.compress_size, 1) > limits.max_ratio and info.file_size > 1024 * 1024:
                raise ZipSecurityError(f"Suspicious compression ratio for {rel!r} (possible ZIP bomb)")
            count += 1
            if count > limits.max_files:
                raise ZipSecurityError(f"Archive exceeds maximum file count of {limits.max_files}")

            target = (dest / rel).resolve()
            if not str(target).startswith(str(dest_resolved) + "/"):
                raise ZipSecurityError(f"Path escapes extraction directory: {rel!r}")
            target.parent.mkdir(parents=True, exist_ok=True)

            written = 0
            with zf.open(info) as src, open(target, "wb") as out:
                while True:
                    chunk = src.read(CHUNK)
                    if not chunk:
                        break
                    written += len(chunk)
                    result.total_bytes += len(chunk)
                    if written > limits.max_file_bytes:
                        out.close()
                        target.unlink(missing_ok=True)
                        raise ZipSecurityError(f"Entry {rel!r} exceeds declared size limits")
                    if result.total_bytes > limits.max_total_bytes:
                        raise ZipSecurityError(
                            f"Extracted content exceeds {limits.max_total_bytes // (1024 * 1024)} MB"
                        )
                    out.write(chunk)
            target.chmod(0o600)
            result.extracted.append(rel)
    return result


def cleanup(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
