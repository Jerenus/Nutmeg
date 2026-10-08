import json
from pathlib import Path

from nutmeg.decision.day_results import bridge_results


def test_bridge_results_writes_results_90_for_yesterday(tmp_path: Path):
    data = tmp_path / "data"
    (data / "jczq").mkdir(parents=True)
    (data / "jczq" / "jc-results.json").write_text(json.dumps({
        "2026-09-22": {"周二001": {"match_id": "1", "ft_home": 2, "ft_away": 0},
                       "周二002": {"match_id": "2", "ft_home": None, "ft_away": None}},
    }), encoding="utf-8")
    report = bridge_results(data_dir=data, date="2026-09-23")
    results_path = data / "daily" / "2026-09-23" / "results-90.json"
    doc = json.loads(results_path.read_text(encoding="utf-8"))
    assert doc == {"周二001": {"outcome_90": "3", "goals_h": 2, "goals_a": 0}}
    assert report == {"source_day": "2026-09-22", "written": 1, "missing": ["周二002"],
                      "unsealed": False}


def test_bridge_results_without_source_day_writes_nothing(tmp_path: Path):
    data = tmp_path / "data"
    (data / "jczq").mkdir(parents=True)
    (data / "jczq" / "jc-results.json").write_text("{}", encoding="utf-8")
    report = bridge_results(data_dir=data, date="2026-09-23")
    assert report == {"source_day": "2026-09-22", "written": 0, "missing": [],
                      "unsealed": False}
    assert not (data / "daily" / "2026-09-23" / "results-90.json").exists()
