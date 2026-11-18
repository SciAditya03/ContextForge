"""Command-line entry point: analyse a directory or ZIP without the web UI.

    python -m app.cli analyze ./my-project --out ./context --provider none
    python -m app.cli analyze project.zip --provider anthropic --depth standard
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path

from app.core.config import DEFAULT_EXCLUSIONS, get_settings
from app.core.logging import setup_logging
from app.services.extraction.safe_zip import matches_exclusion
from app.services.pipeline.runner import AnalysisJob, PipelineRunner


def zip_directory(src: Path, dest: Path, exclusions: list[str]) -> None:
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(src.rglob("*")):
            if p.is_symlink() or not p.is_file():
                continue
            rel = p.relative_to(src).as_posix()
            if matches_exclusion(rel, exclusions):
                continue
            zf.write(p, f"{src.name}/{rel}")


async def _analyze(args: argparse.Namespace) -> int:
    settings = get_settings()
    setup_logging("WARNING")
    src = Path(args.path).resolve()
    work = Path(tempfile.mkdtemp(prefix="contextforge-"))
    archive = work / "upload.zip"
    if src.is_dir():
        zip_directory(src, archive, DEFAULT_EXCLUSIONS)
    elif src.suffix.lower() == ".zip":
        shutil.copy(src, archive)
    else:
        print("path must be a directory or a .zip file", file=sys.stderr)
        return 2
    cfg = None
    if args.provider != "none":
        from app.db.database import Database
        from app.services.settings_service import SettingsService

        svc = SettingsService(Database(settings.db_path), settings)
        cfg = svc.provider_config({"provider": args.provider, "model": args.model}, depth=args.depth)

    async def emit(e: dict) -> None:  # type: ignore[type-arg]
        if e.get("type") == "stage" and e.get("status") in ("done", "failed", "skipped", "warning"):
            print(f"[{e['status']:>7}] {e['stage']:<15} {e.get('detail', '')}")

    job = AnalysisJob(project_id=uuid.uuid4().hex, name=args.name or src.stem, description=args.description, archive=archive, workdir=work,
                      depth=args.depth, exclusions=list(DEFAULT_EXCLUSIONS), token_budget=args.token_budget, max_file_kb=1024, max_concurrency=4,
                      send_source=not args.structure_only, use_cache=True, keep_archive=False, provider_config=cfg)
    stats = await PipelineRunner(settings, emit).run(job)
    out = Path(args.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(work / "output", out)
    for z in work.glob("*.zip"):
        shutil.copy(z, out.parent / z.name)
    shutil.rmtree(work, ignore_errors=True)
    print(json.dumps({k: stats[k] for k in ("files", "routes", "db_models", "findings", "documents", "output_valid")}, indent=2))
    print(f"Context written to {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="contextforge")
    sub = parser.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze", help="analyse a directory or ZIP archive")
    a.add_argument("path")
    a.add_argument("--out", default="./contextforge-output")
    a.add_argument("--name")
    a.add_argument("--description")
    a.add_argument("--provider", default="none", choices=["none", "anthropic", "openai", "gemini", "openai_compatible"])
    a.add_argument("--model")
    a.add_argument("--depth", default="standard", choices=["quick", "standard", "deep"])
    a.add_argument("--token-budget", type=int, default=400_000)
    a.add_argument("--structure-only", action="store_true", help="never send source code to the AI provider")
    args = parser.parse_args(argv)
    return asyncio.run(_analyze(args))


if __name__ == "__main__":
    raise SystemExit(main())
