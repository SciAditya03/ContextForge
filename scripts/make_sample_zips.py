"""Package each sample repository in samples/ as a ZIP (written to samples/dist/, git-ignored)."""

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"


def main() -> int:
    out = SAMPLES / "dist"
    out.mkdir(exist_ok=True)
    for d in sorted(p for p in SAMPLES.iterdir() if p.is_dir() and p.name != "dist"):
        dest = out / f"{d.name}.zip"
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(d.rglob("*")):
                if f.is_file():
                    zf.write(f, f"{d.name}/{f.relative_to(d).as_posix()}")
        print(f"wrote {dest.relative_to(ROOT)} ({dest.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
