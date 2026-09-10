from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.product.operator_review_history import OperatorReviewHistoryReader

AS_OF = datetime(2026, 9, 3, 3, tzinfo=UTC)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


def test_factor_verdicts_are_relevant_temporal_and_hide_legacy_payload_shape(
    tmp_path: Path,
) -> None:
    decision_dir = tmp_path / "jczq" / "decision"
    decision_dir.mkdir(parents=True)
    verdicts = [
        {
            "factor_id": "lineup_news_gap",
            "as_of": "2026-09-02",
            "n_reads": 19,
            "brier_delta_vs_prior": -0.0716,
            "clv_hit_rate": 0.21,
            "direction_hit_rate": 0.105,
            "recommendation": "keep",
            "next_review_at": "",
        },
        {
            "factor_id": "unrelated_factor",
            "as_of": "2026-09-02",
            "n_reads": 4,
            "brier_delta_vs_prior": 0.1,
            "clv_hit_rate": 0.0,
            "direction_hit_rate": 0.0,
            "recommendation": "retire",
            "next_review_at": "",
        },
        {
            "factor_id": "lineup_news_gap",
            "as_of": "2026-09-04",
            "n_reads": 20,
            "brier_delta_vs_prior": -0.08,
            "clv_hit_rate": 0.25,
            "direction_hit_rate": 0.15,
            "recommendation": "keep",
            "next_review_at": "",
        },
    ]
    (decision_dir / "verdicts.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in verdicts),
        encoding="utf-8",
    )

    history = OperatorReviewHistoryReader(tmp_path).factor_verdicts(
        factor_ids=("lineup_news_gap",),
        as_of=AS_OF,
    )

    assert len(history) == 1
    row = history[0]
    assert row.factor_label == "lineup_news_gap"
    assert row.as_of == "2026-09-02"
    assert row.sample_count == 19
    assert row.recommendation == "keep"
    assert row.brier_delta_vs_prior == "-0.0716"
    assert row.clv_hit_rate == "0.21"
    assert row.direction_hit_rate == "0.105"
    assert not hasattr(row, "factor_id")
    assert not hasattr(row, "raw_payload")


def test_zucai_night_calibrations_are_issue_scoped_temporal_and_summarized(
    tmp_path: Path,
) -> None:
    zucai_dir = tmp_path / "zucai"
    base = {
        "issue": "26116",
        "source": "API-Football 90-minute result",
        "fetched_at": "2026-09-02T01:25:31+00:00",
        "results": {
            "1": {
                "code": "3",
                "ft": "2-0",
                "home": "Home",
                "away": "Away",
                "status": "Match Finished",
            }
        },
        "skipped": ["场2未返回"],
    }
    _write_json(zucai_dir / "26116-night-2026-09-01-af.json", base)
    _write_json(
        zucai_dir / "26117-night-2026-09-01-af.json",
        {**base, "issue": "26117"},
    )
    _write_json(
        zucai_dir / "26116-night-2026-09-04-af.json",
        {**base, "fetched_at": "2026-09-04T01:25:31+00:00"},
    )

    history = OperatorReviewHistoryReader(tmp_path).night_calibrations(
        issue="26116",
        as_of=AS_OF,
    )

    assert len(history) == 1
    row = history[0]
    assert row.captured_at == datetime(2026, 9, 2, 1, 25, 31, tzinfo=UTC)
    assert row.source_label == "API-Football 90-minute result"
    assert row.result_count == 1
    assert row.skipped_count == 1
    assert not hasattr(row, "results")
    assert not hasattr(row, "path")


def test_zucai_night_calibration_accepts_legacy_null_skipped_as_zero(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "zucai" / "26116-night-2026-09-02-af.json",
        {
            "issue": "26116",
            "source": "two-source 90-minute result",
            "fetched_at": "2026-09-03T02:40:00+00:00",
            "results": {
                "14": {
                    "code": "1",
                    "ft": "1-1",
                    "ht": "0-0",
                    "home": "Home",
                    "away": "Away",
                    "status": "Match Finished",
                    "note": "90-minute settlement scope",
                }
            },
            "skipped": None,
            "pending": ["12", "13"],
            "ticket_status": {"R1": "still alive"},
        },
    )

    history = OperatorReviewHistoryReader(tmp_path).night_calibrations(
        issue="26116",
        as_of=AS_OF,
    )

    assert len(history) == 1
    assert history[0].skipped_count == 2


def test_legacy_review_history_reader_stays_outside_formal_product_runtime() -> None:
    runtime_sources = (
        Path("nutmeg/product/operator_queries.py"),
        Path("nutmeg/product/wiring.py"),
    )

    for path in runtime_sources:
        source = path.read_text(encoding="utf-8")
        assert "operator_review_history" not in source
        assert "OperatorReviewHistoryReader" not in source
