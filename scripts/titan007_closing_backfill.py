#!/usr/bin/env python
"""Collect titan007 closing odds for every settled JCZQ match, with source timestamps.

Why (2026-09-22): 506 of the 1,228 settled matches in ``jc-results.json`` have no price
at all on disk (no ``bold_odds.json`` for the day, or the code is missing from it), so
they can never enter the experiment corpus. ``jc-results.json`` already carries each
match's titan007 ``match_id``, and titan007's per-match Euro-odds endpoint returns every
bookmaker's **opening** and **closing** line together with the bookmaker's own
``updated_at``. That is objective, pre-kickoff market data with a time attribute, the
B-class kind the corpus may ingest without leakage.

What it writes: ``.nutmeg-data/jczq/daily/<date>/closing_odds.json`` keyed by 竞彩号::

    {"周三008": {"match_id": "2985015", "fetched_at": ..., "source": "titan007_history",
                 "book_count": 31, "updated_at_min": ..., "updated_at_max": ...,
                 "sharp": {"odds": {...}, "fair_probability": {...}, "opening_odds": {...},
                           "bookmaker_count": 5},
                 "all":   {... same shape over every admitted book ...},
                 "per_book": [{"company_id", "company_name", "opening", "current",
                               "updated_at"}, ...]}}

It is idempotent: codes already present (including ones recorded as ``unavailable``)
are skipped, and each day's file is written atomically after that day completes.
Nothing else in the repository reads this file yet; the corpus builder attaches it as a
``closing`` block and uses it as the price source only where no read-time price exists.

Usage::

    uv run python scripts/titan007_closing_backfill.py [--sleep 0.3] [--limit N]
                                                        [--dates 2026-09-01 ...] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nutmeg.data.titan007 import Titan007Client, Titan007Error  # noqa: E402
from nutmeg.services.jczq_titan007_odds import (  # noqa: E402
    _consensus_market,
    all_books,
    sharp_books,
)

FILENAME = "closing_odds.json"


def _market_dict(market) -> dict | None:
    if market is None:
        return None
    data = asdict(market)
    data.pop("independent", None)
    data.pop("line", None)
    return data


def _write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _iso(value) -> str | None:
    return value.isoformat(timespec="seconds") if value is not None else None


def collect(
    *,
    data_dir: Path,
    sleep_s: float,
    limit: int | None,
    dates: list[str] | None,
    dry_run: bool,
    client: Titan007Client | None = None,
) -> dict[str, int]:
    results = json.loads((data_dir / "jc-results.json").read_text(encoding="utf-8"))
    stats = {"days": 0, "fetched": 0, "skipped": 0, "unavailable": 0, "no_match_id": 0}
    own_client = client is None
    client = client or Titan007Client()
    try:
        for date in sorted(results):
            if dates and date not in dates:
                continue
            day = results[date] or {}
            path = data_dir / "daily" / date / FILENAME
            existing = {}
            if path.exists():
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                except ValueError:
                    existing = {}
            changed = False
            for code, got in sorted(day.items()):
                if limit is not None and stats["fetched"] + stats["unavailable"] >= limit:
                    break
                match_id = str((got or {}).get("match_id") or "").strip()
                if not match_id:
                    stats["no_match_id"] += 1
                    continue
                if code in existing:
                    stats["skipped"] += 1
                    continue
                if dry_run:
                    stats["fetched"] += 1
                    continue
                fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
                try:
                    quotes = list(client.fetch_euro_odds(match_id))
                except Titan007Error as exc:
                    existing[code] = {
                        "match_id": match_id,
                        "fetched_at": fetched_at,
                        "source": "titan007_history",
                        "unavailable": str(exc)[:160],
                    }
                    stats["unavailable"] += 1
                    changed = True
                    time.sleep(sleep_s)
                    continue
                stamps = [q.updated_at for q in quotes if q.updated_at is not None]
                existing[code] = {
                    "match_id": match_id,
                    "fetched_at": fetched_at,
                    "source": "titan007_history",
                    "book_count": len(quotes),
                    "updated_at_min": _iso(min(stamps)) if stamps else None,
                    "updated_at_max": _iso(max(stamps)) if stamps else None,
                    "sharp": _market_dict(_consensus_market(quotes, sharp_books())),
                    "all": _market_dict(_consensus_market(quotes, all_books())),
                    "per_book": [
                        {
                            "company_id": q.company_id,
                            "company_name": q.company_name,
                            "opening": q.opening,
                            "current": q.current,
                            "updated_at": _iso(q.updated_at),
                        }
                        for q in quotes
                    ],
                }
                stats["fetched"] += 1
                changed = True
                time.sleep(sleep_s)
            if changed and not dry_run:
                _write_atomic(path, existing)
                stats["days"] += 1
            if limit is not None and stats["fetched"] + stats["unavailable"] >= limit:
                break
    finally:
        if own_client:
            client.close()
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-dir", default=str(ROOT / ".nutmeg-data" / "jczq"))
    ap.add_argument("--sleep", type=float, default=0.3)
    ap.add_argument("--limit", type=int, default=None, help="stop after N network fetches")
    ap.add_argument("--dates", nargs="*", default=None)
    ap.add_argument("--dry-run", action="store_true", help="count work without fetching")
    args = ap.parse_args()
    stats = collect(
        data_dir=Path(args.data_dir),
        sleep_s=args.sleep,
        limit=args.limit,
        dates=args.dates,
        dry_run=args.dry_run,
    )
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
