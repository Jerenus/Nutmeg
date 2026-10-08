import json
from pathlib import Path

from nutmeg.decision.match_results import board_outcomes, day_rows, outcome_90, outcomes


def _jc(data: Path, doc) -> None:
    (data / "jczq").mkdir(parents=True, exist_ok=True)
    (data / "jczq" / "jc-results.json").write_text(
        doc if isinstance(doc, str) else json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def test_outcome_90_uses_sporttery_face_codes():
    assert outcome_90(2, 1) == "3" and outcome_90(1, 1) == "1" and outcome_90(0, 3) == "0"
    assert outcome_90(0, 0) == "1"


def test_board_outcomes_derives_every_finished_match_in_code_order(tmp_path: Path):
    _jc(tmp_path, {"2026-10-06": {
        "周二002": {"match_id": "9", "ft_home": 0, "ft_away": 1, "ht_home": 0, "ht_away": 0},
        "周二001": {"match_id": "8", "ft_home": 2, "ft_away": 2},
        "周二003": {"match_id": "7", "ft_home": None, "ft_away": None},
    }})
    got = board_outcomes(tmp_path, "2026-10-06")
    assert got == {"周二001": {"outcome_90": "1", "goals_h": 2, "goals_a": 2},
                   "周二002": {"outcome_90": "0", "goals_h": 0, "goals_a": 1}}
    assert list(got) == ["周二001", "周二002"]
    assert set(day_rows(tmp_path, "2026-10-06")) == {"周二001", "周二002", "周二003"}


def test_unsealed_missing_or_corrupt_source_is_empty_not_an_error(tmp_path: Path):
    assert board_outcomes(tmp_path, "2026-10-06") == {}           # 文件不存在
    _jc(tmp_path, "{not json")
    assert board_outcomes(tmp_path, "2026-10-06") == {}           # 损坏
    _jc(tmp_path, {"2026-10-05": {"周一001": {"ft_home": 1, "ft_away": 0}}})
    assert board_outcomes(tmp_path, "2026-10-06") == {}           # 当日未封存
    assert outcomes({"周一001": {"ft_home": "3", "ft_away": "1"}}) == {
        "周一001": {"outcome_90": "3", "goals_h": 3, "goals_a": 1}}
