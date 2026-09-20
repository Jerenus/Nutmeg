import importlib.util
import json
from pathlib import Path

_PATH = Path(__file__).parents[2] / "experiments" / "exp-opening-odds-coverage.py"
_SPEC = importlib.util.spec_from_file_location("opening_odds_coverage", _PATH)
assert _SPEC and _SPEC.loader
opening_odds_coverage = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(opening_odds_coverage)


def _write_day(root: Path, day: str, rows: dict, sources: dict | None = None) -> None:
    target = root / day
    target.mkdir(parents=True)
    (target / "bold_odds.json").write_text(json.dumps(rows), encoding="utf-8")
    if sources is not None:
        (target / "bold_odds_source.json").write_text(
            json.dumps(sources), encoding="utf-8"
        )


def _market(opening: bool) -> dict:
    return {
        "match_winner": {
            "opening_odds": {"home": 2.0, "draw": 3.0, "away": 4.0}
            if opening
            else {}
        }
    }


def test_diagnoses_missing_opening_odds_by_source_without_filling_values(tmp_path: Path):
    _write_day(tmp_path, "2026-09-13", {"周日001": _market(False)})
    _write_day(
        tmp_path,
        "2026-09-14",
        {"周一001": _market(True), "周一002": _market(False)},
        {"周一001": "titan007", "周一002": "titan007"},
    )

    report = opening_odds_coverage.coverage_report(tmp_path, days=30)

    assert report["total"] == {"matches": 3, "covered": 1, "missing": 2}
    assert report["by_source"] == {
        "unknown": {
            "matches": 1,
            "covered": 0,
            "missing": 1,
            "missing_reason": "provenance_missing",
        },
        "titan007": {
            "matches": 2,
            "covered": 1,
            "missing": 1,
            "missing_reason": "capture_missing",
        },
    }
    assert report["answers"]["missing_cause"] == (
        "缺失样本均无来源溯源记录，无法判定是当时未抓还是源头不提供。"
    )
    assert report["answers"]["historical_retrievable"] is None
    assert report["answers"]["historical_retrieval_status"] == "未测定"
    assert report["answers"]["historical_retrieval_test_required"] == [
        "对一个过去日期调用 Titan007 历史欧赔端点，检查是否仍返回初赔。",
        "对同一过去日期调用 500.com 历史欧赔端点，检查是否仍返回初赔。",
    ]
    assert report["answers"]["backfill_performed"] is False


def test_uses_only_latest_requested_daily_snapshots(tmp_path: Path):
    _write_day(tmp_path, "2026-09-12", {"旧001": _market(False)})
    _write_day(tmp_path, "2026-09-13", {"新001": _market(True)})

    report = opening_odds_coverage.coverage_report(tmp_path, days=1)

    assert [row["day"] for row in report["daily"]] == ["2026-09-13"]
    assert report["total"] == {"matches": 1, "covered": 1, "missing": 0}
