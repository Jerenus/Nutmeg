import json
from pathlib import Path

import pytest

from nutmeg.decision.rsi_population import matches_for_population

DATA_DIR = Path(".nutmeg-data")


def test_both_uses_explicit_channel_map_for_recorded_26131_board():
    day = "2026-09-20"
    issue = "26131"
    jczq = matches_for_population("jczq", day=day, issue=issue, data_dir=DATA_DIR)
    zucai = matches_for_population("zucai", day=day, issue=issue, data_dir=DATA_DIR)
    both = matches_for_population("both", day=day, issue=issue, data_dir=DATA_DIR)

    assert len(jczq) == 30
    assert len(zucai) == 14
    assert len(both) == 30
    assert sum(row["source"] == "both" for row in both) == 14
    assert not any(row.get("unmapped") for row in both)


def test_both_respects_existing_explicit_26130_channel_map():
    day = "2026-09-19"
    issue = "26130"
    jczq = matches_for_population("jczq", day=day, issue=issue, data_dir=DATA_DIR)
    both = matches_for_population("both", day=day, issue=issue, data_dir=DATA_DIR)

    assert len(both) == len(jczq)
    assert sum(row["source"] == "both" for row in both) == 14
    assert not any(row.get("unmapped") for row in both)


def test_both_marks_shared_match_once(tmp_path):
    day = "2026-09-20"
    day_dir = tmp_path / "jczq" / "daily" / day
    zucai_dir = tmp_path / "zucai"
    day_dir.mkdir(parents=True)
    zucai_dir.mkdir()
    day_dir.joinpath("jczq-legs-base.json").write_text(
        json.dumps(
            {
                "legs": {
                    "周日001": {"match_id": "shared", "code": "ignored"},
                    "周日002": {"match_id": "jczq-only"},
                }
            }
        ),
        encoding="utf-8",
    )
    zucai_dir.joinpath("26131-store-ids.json").write_text(
        json.dumps(
            {
                "1": {"match_id": "shared", "match_no": 1},
                "2": {"match_id": "zucai-only", "match_no": 2},
            }
        ),
        encoding="utf-8",
    )
    zucai_dir.joinpath("26131-channel-map.json").write_text(
        json.dumps({"shared": 1}), encoding="utf-8"
    )

    result = matches_for_population(
        "both", day=day, issue="26131", data_dir=tmp_path
    )

    assert all(
        set(row) == {
            "match_id",
            "code",
            "match_no",
            "canonical_id",
            "source",
            "unmapped",
        }
        for row in result
    )
    assert result == [
        {
            "match_id": "shared",
            "code": "周日001",
            "match_no": 1,
            "canonical_id": None,
            "source": "both",
            "unmapped": False,
        },
        {
            "match_id": "jczq-only",
            "code": "周日002",
            "match_no": None,
            "canonical_id": None,
            "source": "jczq",
            "unmapped": False,
        },
        {
            "match_id": "zucai-only",
            "code": None,
            "match_no": 2,
            "canonical_id": None,
            "source": "zucai",
            "unmapped": True,
        },
    ]


def test_both_without_an_issue_degrades_to_jczq():
    assert matches_for_population(
        "both", day="2026-09-20", issue=None, data_dir=DATA_DIR
    ) == matches_for_population(
        "jczq", day="2026-09-20", issue=None, data_dir=DATA_DIR
    )


def test_historical_replay_root_has_no_prospective_match_population(tmp_path):
    day = "2026-09-19"
    day_dir = tmp_path / "jczq" / "daily" / day
    day_dir.mkdir(parents=True)
    day_dir.joinpath("jczq-legs-base.json").write_text(
        json.dumps({"legs": {"周六001": {"match_id": "replay-match"}}}),
        encoding="utf-8",
    )
    tmp_path.joinpath(f"replay-input-manifest-{day}.json").write_text(
        "{}", encoding="utf-8"
    )

    assert matches_for_population(
        "jczq", day=day, issue=None, data_dir=tmp_path
    ) == []
    assert matches_for_population(
        "both", day=day, issue=None, data_dir=tmp_path
    ) == []


def test_unknown_population_is_rejected():
    with pytest.raises(ValueError, match="population"):
        matches_for_population(
            "unknown", day="2026-09-20", issue=None, data_dir=DATA_DIR
        )
