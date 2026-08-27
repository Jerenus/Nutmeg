import json

from nutmeg.decision.zucai_night import load_af_map, result_code


def test_result_code_home_win():
    assert result_code(4, 1) == "3"


def test_result_code_draw():
    assert result_code(1, 1) == "1"


def test_result_code_away_win():
    assert result_code(1, 2) == "0"


def test_load_af_map(tmp_path):
    (tmp_path / "26111-af-map.json").write_text(json.dumps(
        {"issue": "26111", "fixtures": {"3": 1234501, "4": 1234502}}), "utf-8")
    assert load_af_map(tmp_path, "26111") == {"3": 1234501, "4": 1234502}


def test_load_af_map_missing_file_is_empty(tmp_path):
    assert load_af_map(tmp_path, "26111") == {}
