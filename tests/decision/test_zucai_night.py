import json

from nutmeg.decision.zucai_night import (
    fetch_af_day,
    load_af_map,
    night_results,
    result_code,
)


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


_MATCHES = [
    {"match_no": 3, "home_team": "雅典", "away_team": "索斯基"},
    {"match_no": 5, "home_team": "采列", "away_team": "布拉迪"},
    {"match_no": 7, "home_team": "萨茨堡", "away_team": "米亚尔"},
    {"match_no": 8, "home_team": "比尔森", "away_team": "红星"},
]
_FIXTURES = {
    1234501: {"status": "FT", "ft_home": 4, "ft_away": 0,
              "home": "AEK Athens FC", "away": "Levski Sofia"},
    1234503: {"status": "AET", "ft_home": 1, "ft_away": 1,
              "home": "Celje", "away": "Slovan Bratislava"},
    1234507: {"status": "NS", "ft_home": None, "ft_away": None,
              "home": "Salzburg", "away": "Brann"},
}


def test_night_results_codes_and_skips():
    af_map = {"3": 1234501, "5": 1234503, "7": 1234507}
    results, skipped = night_results(_MATCHES, af_map, _FIXTURES)
    assert results["3"]["code"] == "3" and results["3"]["ft"] == "4-0"
    assert results["5"]["code"] == "1"          # AET 取 90' 1-1 = 平
    assert "7" not in results                    # 未完赛
    assert any("场7" in s and "NS" in s for s in skipped)
    assert any("场8" in s and "无映射" in s for s in skipped)
