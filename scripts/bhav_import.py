"""NSE/BSE EOD bhavcopy import CLI — the free historical option source.

Probe a sample first (always, on first contact with real files):
    uv run python scripts/bhav_import.py --probe /data/bhav/BhavCopy_NSE_FO_..._F_0000.csv.zip

Full import (no ordering needed — spot is in-row):
    uv run python scripts/bhav_import.py --root /data/bhav --glob "**/*.csv*" \\
        --batch 2026-06-bhav --workers 4

EXP-001-EOD readiness report:
    uv run python scripts/bhav_import.py --readiness 2021-01-01:2026-06-01

Where to get the files (free):
    NSE  -> https://www.nseindia.com/all-reports  (Derivatives -> "F&O - UDiFF
            Common Bhavcopy Final"); historical archive at nsearchives.nseindia.com.
    BSE  -> https://www.bseindia.com/  (Derivatives EOD reports) for SENSEX —
            different layout, use a separate mapping and probe it.
"""

import argparse
import asyncio
import json
import sys
import time as time_mod
from datetime import date
from pathlib import Path

from tp_research.bhav.importer import run_import
from tp_research.bhav.parse import BhavMappingConfig, BhavStats, parse_file, synthesize_index_ohlc
from tp_research.bhav.report import ImportReport, readiness_report

from tp_core.config import get_settings
from tp_core.db import Database
from tp_core.db.repos import EventsRepo

MAPPING = Path("docs/data/bhav_mapping.json")


def _p(message: str) -> None:
    print(message)  # noqa: T201 — ops CLI


def probe(sample: Path, config: BhavMappingConfig) -> int:
    stats = BhavStats()
    bars = parse_file(sample, config, stats)
    index_bars = synthesize_index_ohlc(bars, config)
    kinds: dict[str, int] = {}
    for b in bars:
        kinds[b.contract.kind] = kinds.get(b.contract.kind, 0) + 1
    rate = stats.parsed / max(stats.selected, 1)
    _p(
        f"rows={stats.rows} selected(in-universe)={stats.selected} "
        f"parsed={stats.parsed} ({100 * rate:.1f}%)"
    )
    _p(f"kinds={kinds} synthesized_index_spot_days={len(index_bars)}")
    _p(f"rejects={stats.rejected_by_reason}")
    if stats.unmatched_samples:
        _p("unmatched samples (fix docs/data/bhav_mapping.json):")
        for s in stats.unmatched_samples:
            _p(f"  {s!r}")
    if bars:
        b = next((x for x in bars if x.contract.kind == "OPT"), bars[0])
        _p(
            f"first option: {b.contract.synthetic_key} @ {b.ts} "
            f"settle={b.settlement} spot={b.underlying_price} oi={b.oi} lot={b.lot_size}"
        )
    if stats.selected == 0:
        _p("WARNING: 0 in-universe rows — check instrument_type/symbol mapping for this file.")
    return 0 if stats.selected and rate > 0.95 else 1


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--glob", default="**/*.csv*")
    parser.add_argument("--batch", default=f"bhav-{date.today().isoformat()}")  # noqa: DTZ011
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--mapping", type=Path, default=MAPPING)
    parser.add_argument("--readiness", help="start:end ISO dates")
    args = parser.parse_args()

    config = BhavMappingConfig.load(args.mapping)

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
            out = Path(get_settings().datalake_root) / "imports" / "bhav_readiness.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2))
            _p(json.dumps(report["checks"], indent=2))
            _p(f"READY FOR EXP-001-EOD: {report['ready']}")
            _p(f"written: {out}")
            return 0 if report["ready"] else 1

        if not args.root:
            parser.error("--root required (or --probe / --readiness)")
        files = sorted(args.root.glob(args.glob))
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
