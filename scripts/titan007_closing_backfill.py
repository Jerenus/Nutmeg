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


def _fetch_entry(client: Titan007Client, match_id: str, sleep_s: float) -> tuple[dict, bool]:
    """One titan007 Euro-odds fetch → stored entry; second value = success."""
    fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        quotes = list(client.fetch_euro_odds(match_id))
    except Titan007Error as exc:
        time.sleep(sleep_s)
        return {
            "match_id": match_id,
            "fetched_at": fetched_at,
            "source": "titan007_history",
            "unavailable": str(exc)[:160],
        }, False
    stamps = [q.updated_at for q in quotes if q.updated_at is not None]
    entry = {
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
    time.sleep(sleep_s)
    return entry, True


def collect_zucai(
    *,
    zucai_dir: Path,
    sleep_s: float,
    limit: int | None,
    issues: list[str] | None,
    dry_run: bool,
    client: Titan007Client | None = None,
) -> dict[str, int]:
    """足彩期次：`<issue>-odds-intl.json` 里带 titan007 id 的场次 → `<issue>-closing-odds.json`。

    这是标签最全的样本（legs-base 126 行）此前唯一缺的东西：书商数、初赔、终赔。
    """
    stats = {"issues": 0, "fetched": 0, "skipped": 0, "unavailable": 0, "no_match_id": 0}
    own_client = client is None
    client = client or Titan007Client()
    try:
        for path in sorted(zucai_dir.glob("*-odds-intl.json")):
            issue = path.name[:5]
            if issues and issue not in issues:
                continue
            doc = json.loads(path.read_text(encoding="utf-8"))
            target = zucai_dir / f"{issue}-closing-odds.json"
            existing = {}
            if target.exists():
                try:
                    existing = json.loads(target.read_text(encoding="utf-8"))
                except ValueError:
                    existing = {}
            changed = False
            for m in doc.get("matches") or []:
                if limit is not None and stats["fetched"] + stats["unavailable"] >= limit:
                    break
                no = str(m.get("match_no") or "")
                match_id = str(m.get("titan007_match_id") or "").strip()
                if not no or not match_id:
                    stats["no_match_id"] += 1
                    continue
                if no in existing:
                    stats["skipped"] += 1
                    continue
                if dry_run:
                    stats["fetched"] += 1
                    continue
                entry, ok = _fetch_entry(client, match_id, sleep_s)
                existing[no] = entry
                stats["fetched" if ok else "unavailable"] += 1
                changed = True
            if changed and not dry_run:
                _write_atomic(target, existing)
                stats["issues"] += 1
            if limit is not None and stats["fetched"] + stats["unavailable"] >= limit:
                break
    finally:
        if own_client:
            client.close()
    return stats


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
                entry, ok = _fetch_entry(client, match_id, sleep_s)
                existing[code] = entry
                stats["fetched" if ok else "unavailable"] += 1
                changed = True
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
    ap.add_argument(
        "--zucai", action="store_true",
        help="collect for 足彩 issues from <issue>-odds-intl.json instead of the JCZQ board",
    )
    ap.add_argument("--zucai-dir", default=str(ROOT / ".nutmeg-data" / "zucai"))
    args = ap.parse_args()
    if args.zucai:
        stats = collect_zucai(
            zucai_dir=Path(args.zucai_dir), sleep_s=args.sleep, limit=args.limit,
            issues=args.dates, dry_run=args.dry_run,
        )
        print(json.dumps(stats, ensure_ascii=False))
        return 0
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
