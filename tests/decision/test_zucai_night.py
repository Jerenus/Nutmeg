import json

from nutmeg.decision.zucai_night import fetch_af_day, load_af_map, result_code


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


def _af_payload():
    return {"response": [
        {"fixture": {"id": 1234503, "status": {"short": "AET"}},
         "teams": {"home": {"name": "Celje"}, "away": {"name": "Slovan Bratislava"}},
         "score": {"fulltime": {"home": 1, "away": 1}}},
        {"fixture": {"id": 1234501, "status": {"short": "FT"}},
         "teams": {"home": {"name": "AEK Athens FC"}, "away": {"name": "Levski Sofia"}},
         "score": {"fulltime": {"home": 4, "away": 0}}},
    ]}


def test_fetch_af_day_uses_fulltime_and_status(monkeypatch):
    monkeypatch.setenv("NUTMEG_API_FOOTBALL_BASE_URL", "https://af.example")
    monkeypatch.setenv("NUTMEG_API_FOOTBALL_KEY", "k")
    seen = {}

    def fake_fetcher(url, headers):
        seen["url"], seen["headers"] = url, headers
        return _af_payload()

    fixtures = fetch_af_day("2026-08-26", fetcher=fake_fetcher)
    assert seen["url"] == "https://af.example/fixtures?date=2026-08-26"
    assert seen["headers"] == {"x-apisports-key": "k"}
    assert fixtures[1234503] == {"status": "AET", "ft_home": 1, "ft_away": 1,
                                 "home": "Celje", "away": "Slovan Bratislava"}
    assert fixtures[1234501]["ft_home"] == 4
