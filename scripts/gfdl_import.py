"""GFDL historical import CLI.

Probe a sample first (always, on first contact with real vendor files):
    uv run python scripts/gfdl_import.py --probe /data/gfdl/sample.csv

Full import (index files are auto-ordered first):
    uv run python scripts/gfdl_import.py --root /data/gfdl --glob "**/*.csv" \\
        --batch 2026-06-gfdl --workers 4

Readiness report for Experiment 001:
    uv run python scripts/gfdl_import.py --readiness 2023-06-01:2026-06-01
"""

import argparse
import asyncio
import json
import sys
import time as time_mod
from datetime import date
from pathlib import Path

from tp_research.gfdl.importer import run_import
from tp_research.gfdl.parse import MappingConfig, ParseStats, parse_file
from tp_research.gfdl.report import ImportReport, readiness_report

from tp_core.config import get_settings
from tp_core.db import Database
from tp_core.db.repos import EventsRepo

MAPPING = Path("docs/data/gfdl_mapping.json")


def _p(message: str) -> None:
    print(message)  # noqa: T201 — ops CLI


def probe(sample: Path, config: MappingConfig) -> int:
    stats = ParseStats()
    bars = parse_file(sample, config, stats)
    kinds: dict[str, int] = {}
    for b in bars:
        kinds[b.contract.kind] = kinds.get(b.contract.kind, 0) + 1
    _p(f"rows={stats.rows} parsed={stats.parsed} ({100 * stats.parsed / max(stats.rows, 1):.1f}%)")
    _p(f"kinds={kinds}")
    _p(f"rejects={stats.rejected_by_reason}")
    if stats.unmatched_samples:
        _p("unmatched ticker samples (fix docs/data/gfdl_mapping.json):")
        for s in stats.unmatched_samples:
            _p(f"  {s!r}")
    if bars:
        b = bars[0]
        _p(f"first bar: {b.contract.synthetic_key} @ {b.ts} close={b.close} oi={b.oi}")
    return 0 if stats.parsed and stats.parsed / max(stats.rows, 1) > 0.95 else 1


def order_index_first(files: list[Path], config: MappingConfig) -> list[Path]:
    """Spot must exist before options enrich; cheap heuristic: any filename
    containing an index ticker fragment sorts first."""
    fragments = [k.split(".")[0].replace(" ", "").upper() for k in config.index_tickers]

    def key(p: Path) -> tuple[int, str]:
        upper = p.name.replace(" ", "").upper()
        return (0 if any(f in upper for f in fragments) else 1, str(p))

    return sorted(files, key=key)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--glob", default="**/*.csv")
    parser.add_argument("--batch", default=f"gfdl-{date.today().isoformat()}")  # noqa: DTZ011
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--mapping", type=Path, default=MAPPING)
    parser.add_argument("--readiness", help="start:end ISO dates")
    args = parser.parse_args()

    config = MappingConfig.load(args.mapping)

    if args.probe:
        return probe(args.probe, config)

    db = Database(get_settings())
    try:
        if args.readiness:
            start_s, end_s = args.readiness.split(":")
            holidays = await EventsRepo(db).holidays()
            report = await readiness_report(
                db, date.fromisoformat(start_s), date.fromisoformat(end_s), holidays
            )
            out = Path(get_settings().datalake_root) / "imports" / "readiness.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2))
            _p(json.dumps(report["checks"], indent=2))
            _p(f"READY FOR EXPERIMENT 001: {report['ready']}")
            _p(f"written: {out}")
            return 0 if report["ready"] else 1

        if not args.root:
            parser.error("--root required (or --probe / --readiness)")
        files = order_index_first(sorted(args.root.glob(args.glob)), config)
        if not files:
            _p(f"no files matched {args.root}/{args.glob}")
            return 1
        _p(f"importing {len(files)} files, batch={args.batch}, workers={args.workers}")
        started = time_mod.monotonic()
        results = await run_import(
            db, files, config, args.batch, workers=args.workers, resume=not args.no_resume
        )
        wall = time_mod.monotonic() - started
        report = ImportReport(batch_id=args.batch, results=results)
        out_dir = report.write(Path(get_settings().datalake_root))
        summary = report.summary()
        summary["benchmark"]["wall_seconds_elapsed"] = round(wall, 1)
        _p(json.dumps(summary, indent=2))
        _p(f"report: {out_dir}/report.json")
        return 0 if summary["files_failed"] == 0 else 1
    finally:
        await db.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
