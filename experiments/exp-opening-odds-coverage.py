#!/usr/bin/env python
"""Diagnose opening-odds coverage without mutating or filling historical data."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DAILY_DIR = ROOT / ".nutmeg-data" / "jczq" / "daily"
_FACES = {"home", "draw", "away"}


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _has_opening(market: object) -> bool:
    if not isinstance(market, dict):
        return False
    winner = market.get("match_winner")
    opening = winner.get("opening_odds") if isinstance(winner, dict) else None
    return isinstance(opening, dict) and _FACES.issubset(opening)


def _missing_reason(source: str) -> str:
    if source == "apifootball":
        return "source_no_opening_odds"
    if source == "titan007":
        return "capture_missing"
    return "provenance_missing"


def coverage_report(daily_dir: Path, *, days: int = 30) -> dict:
    snapshots = sorted(
        path.parent for path in daily_dir.glob("*/bold_odds.json") if path.is_file()
    )[-days:]
    daily: list[dict] = []
    source_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"matches": 0, "covered": 0, "missing": 0}
    )

    for directory in snapshots:
        markets = _load_json(directory / "bold_odds.json")
        provenance_path = directory / "bold_odds_source.json"
        provenance = _load_json(provenance_path)
        covered = 0
        for code, market in sorted(markets.items()):
            source = str(provenance.get(code) or "unknown")
            present = _has_opening(market)
            counts = source_counts[source]
            counts["matches"] += 1
            counts["covered" if present else "missing"] += 1
            covered += int(present)
        total = len(markets)
        daily.append(
            {
                "day": directory.name,
                "matches": total,
                "covered": covered,
                "missing": total - covered,
                "coverage_pct": round(100.0 * covered / total, 1) if total else 0.0,
            }
        )

    by_source = {
        source: {
            **counts,
            "missing_reason": _missing_reason(source),
        }
        for source, counts in sorted(source_counts.items())
    }
    matches = sum(row["matches"] for row in daily)
    covered = sum(row["covered"] for row in daily)
    return {
        "days": len(daily),
        "daily": daily,
        "by_source": by_source,
        "total": {
            "matches": matches,
            "covered": covered,
            "missing": matches - covered,
        },
        "answers": {
            "missing_cause": (
                "缺失样本均无来源溯源记录，无法判定是当时未抓还是源头不提供。"
            ),
            "historical_retrievable": None,
            "historical_retrieval_status": "未测定",
            "historical_retrieval_basis": (
                "现有快照不能证明历史端点现在仍返回初赔，必须实测后才能下结论。"
            ),
            "historical_retrieval_test_required": [
                "对一个过去日期调用 Titan007 历史欧赔端点，检查是否仍返回初赔。",
                "对同一过去日期调用 500.com 历史欧赔端点，检查是否仍返回初赔。",
            ],
            "backfill_performed": False,
            "data_policy": "未插值、未用即时赔率替代开盘赔率、未填默认值。",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daily-dir", type=Path, default=DEFAULT_DAILY_DIR)
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    print(json.dumps(coverage_report(args.daily_dir, days=args.days), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
