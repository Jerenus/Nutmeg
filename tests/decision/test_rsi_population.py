import json
from pathlib import Path

import pytest

from nutmeg.decision.rsi_population import matches_for_population

DATA_DIR = Path(".nutmeg-data")


@pytest.mark.parametrize(
    ("day", "issue"),
    [("2026-09-19", "26130"), ("2026-09-20", "26131")],
)
def test_both_is_the_real_match_id_union_for_recorded_boards(day, issue):
    jczq = matches_for_population("jczq", day=day, issue=issue, data_dir=DATA_DIR)
    zucai = matches_for_population("zucai", day=day, issue=issue, data_dir=DATA_DIR)
    both = matches_for_population("both", day=day, issue=issue, data_dir=DATA_DIR)

    jczq_ids = {row["match_id"] for row in jczq}
    zucai_ids = {row["match_id"] for row in zucai}
    both_ids = {row["match_id"] for row in both}

    assert both_ids == jczq_ids | zucai_ids
    assert len(both) == len(both_ids)
    assert len(both) != len(jczq)


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

    result = matches_for_population(
        "both", day=day, issue="26131", data_dir=tmp_path
    )

    assert result == [
        {"match_id": "shared", "code": "周日001", "source": "both"},
        {"match_id": "jczq-only", "code": "周日002", "source": "jczq"},
        {"match_id": "zucai-only", "match_no": 2, "source": "zucai"},
    ]


def test_both_without_an_issue_degrades_to_jczq():
    assert matches_for_population(
        "both", day="2026-09-20", issue=None, data_dir=DATA_DIR
    ) == matches_for_population(
        "jczq", day="2026-09-20", issue=None, data_dir=DATA_DIR
    )


def test_unknown_population_is_rejected():
    with pytest.raises(ValueError, match="population"):
        matches_for_population(
            "unknown", day="2026-09-20", issue=None, data_dir=DATA_DIR
        )
