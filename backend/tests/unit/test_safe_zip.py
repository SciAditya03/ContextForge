import stat
import zipfile
from pathlib import Path

import pytest

from app.services.extraction.safe_zip import (
    ZipLimits,
    ZipSecurityError,
    matches_exclusion,
    normalize_member,
    safe_extract,
)


def _zip(path: Path, entries: dict[str, bytes], symlinks: dict[str, str] | None = None) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
        for name, target in (symlinks or {}).items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, target)
    return path


def test_normalize_member_rejects_unsafe_paths():
    assert normalize_member("a/b/c.py") == "a/b/c.py"
    assert normalize_member("./a//b") == "a/b"
    assert normalize_member("a\\b.py") == "a/b.py"
    for bad in ("../etc/passwd", "a/../../x", "/abs/path", "C:/win.ini", "a/\x00b", ""):
        assert normalize_member(bad) is None


def test_path_traversal_rejected(tmp_path: Path):
    z = _zip(tmp_path / "evil.zip", {"ok.txt": b"hi", "../../outside.txt": b"pwned"})
    with pytest.raises(ZipSecurityError, match="Unsafe path"):
        safe_extract(z, tmp_path / "out", ZipLimits())
    assert not (tmp_path / "outside.txt").exists()


def test_absolute_path_rejected(tmp_path: Path):
    z = _zip(tmp_path / "abs.zip", {"/tmp/abs.txt": b"x"})
    with pytest.raises(ZipSecurityError):
        safe_extract(z, tmp_path / "out", ZipLimits())


def test_symlinks_are_skipped_not_created(tmp_path: Path):
    z = _zip(tmp_path / "link.zip", {"proj/a.py": b"x=1"}, symlinks={"proj/link": "/etc/passwd"})
    res = safe_extract(z, tmp_path / "out", ZipLimits())
    assert ("link", "symlink (not followed)") in res.skipped
    assert not (tmp_path / "out" / "link").exists()


def test_zip_bomb_ratio_detected(tmp_path: Path):
    z = _zip(tmp_path / "bomb.zip", {"big.txt": b"\0" * (20 * 1024 * 1024)})
    with pytest.raises(ZipSecurityError, match="compression ratio"):
        safe_extract(z, tmp_path / "out", ZipLimits(max_ratio=100))


def test_total_size_limit(tmp_path: Path):
    entries = {f"f{i}.txt": bytes(range(256)) * 400 for i in range(10)}  # ~1 MB total, low ratio
    z = _zip(tmp_path / "many.zip", entries)
    with pytest.raises(ZipSecurityError, match="exceeds"):
        safe_extract(z, tmp_path / "out", ZipLimits(max_total_bytes=300_000))


def test_file_count_limit(tmp_path: Path):
    z = _zip(tmp_path / "count.zip", {f"f{i}.txt": b"x" for i in range(30)})
    with pytest.raises(ZipSecurityError, match="file count"):
        safe_extract(z, tmp_path / "out", ZipLimits(max_files=10))


def test_large_single_file_skipped(tmp_path: Path):
    import os

    z = _zip(tmp_path / "large.zip", {"small.txt": b"ok", "large.bin": os.urandom(200_000)})
    res = safe_extract(z, tmp_path / "out", ZipLimits(max_file_bytes=100_000))
    assert "small.txt" in res.extracted
    assert any(p == "large.bin" for p, _ in res.skipped)


def test_not_a_zip(tmp_path: Path):
    p = tmp_path / "x.zip"
    p.write_bytes(b"not a zip at all")
    with pytest.raises(ZipSecurityError, match="not a valid ZIP"):
        safe_extract(p, tmp_path / "out", ZipLimits())


def test_exclusions_and_prefix_strip(tmp_path: Path):
    z = _zip(tmp_path / "p.zip", {"myproj/src/a.py": b"x", "myproj/node_modules/lib/index.js": b"y", "myproj/dist/out.js": b"z", "myproj/app.min.js": b"m"})
    res = safe_extract(z, tmp_path / "out", ZipLimits(), exclusions=["node_modules/", "dist/", "*.min.js"])
    assert res.stripped_prefix == "myproj"
    assert res.extracted == ["src/a.py"]
    assert {p for p, _ in res.excluded} == {"node_modules/lib/index.js", "dist/out.js", "app.min.js"}
    assert (tmp_path / "out" / "src" / "a.py").read_bytes() == b"x"


def test_matches_exclusion_patterns():
    assert matches_exclusion("a/node_modules/x.js", ["node_modules/"]) == "node_modules/"
    assert matches_exclusion("node_modules_backup/x.js", ["node_modules/"]) is None
    assert matches_exclusion("pkg/__pycache__/m.pyc", ["__pycache__/"]) == "__pycache__/"
    assert matches_exclusion("docs/build/x", ["docs/build/"]) == "docs/build/"
    assert matches_exclusion("x.map", ["*.map"]) == "*.map"
    assert matches_exclusion("src/app.py", ["# comment", ""]) is None


def test_extracted_files_not_executable(tmp_path: Path):
    z = _zip(tmp_path / "s.zip", {"run.sh": b"#!/bin/sh\nrm -rf /"})
    safe_extract(z, tmp_path / "out", ZipLimits())
    mode = (tmp_path / "out" / "run.sh").stat().st_mode
    assert not mode & 0o111
