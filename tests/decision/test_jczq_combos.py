import json

from nutmeg.decision.jczq_combos import enumerate_combos, judgment_legs

DAY = "2026-09-27"


def _day(tmp_path):
    day_dir = tmp_path / "daily" / DAY
    day_dir.mkdir(parents=True)
    reads = [
        {"read_id": "r1", "match_id": "m1", "judgment_tier": "deep_research",
         "note": "[周日001|A-B|deep_research] x",
         "prior": {"home": 0.60, "draw": 0.25, "away": 0.15},
         "belief": {"home": 0.62, "draw": 0.24, "away": 0.14}},
        {"read_id": "r2", "match_id": "m2", "judgment_tier": "deep_research",
         "note": "[周日002|C-D|deep_research] x",
         "prior": {"home": 0.45, "draw": 0.28, "away": 0.27},
         "belief": {"home": 0.45, "draw": 0.28, "away": 0.27}},
        {"read_id": "r3", "match_id": "m3", "judgment_tier": "price_only",
         "note": "[周日003|E-F|price_only] x",
         "prior": {"home": 0.5, "draw": 0.3, "away": 0.2},
         "belief": {"home": 0.5, "draw": 0.3, "away": 0.2}},
    ]
    (day_dir / "reads.json").write_text(json.dumps(reads, ensure_ascii=False), encoding="utf-8")
    board = {"matchInfoList": [{"subMatchList": [
        {"matchNumStr": code, "matchDate": "2026-09-27", "matchTime": "20:00:00",
         "had": {"h": h, "d": d, "a": a},
         "hhad": {"goalLine": "-1", "h": "3.00", "d": "3.50", "a": "2.00"},
         "ttg": {f"s{i}": "5.0" for i in range(8)}}
        for code, h, d, a in (("周日001", "1.50", "3.90", "6.00"),
                              ("周日002", "2.10", "3.20", "3.30"),
                              ("周日003", "1.90", "3.30", "4.00"))]}]}
    (day_dir / "sporttery_markets.json").write_text(json.dumps(board, ensure_ascii=False),
                                                    encoding="utf-8")
    return tmp_path


def test_only_researched_matches_become_judgment_legs(tmp_path):
    legs = judgment_legs(day=DAY, jczq_dir=_day(tmp_path), now="2026-09-27T12:00:00+08:00")
    assert [leg["code"] for leg in legs] == ["周日001", "周日002"]
    options = {(o["market"], o["faces"]) for o in legs[0]["options"]}
    assert ("had", "3") in options and ("had", "31") in options
    assert all(o["market"] != "ttg" for leg in legs for o in leg["options"])


def test_started_matches_are_excluded(tmp_path):
    legs = judgment_legs(day=DAY, jczq_dir=_day(tmp_path), now="2026-09-27T20:30:00+08:00")
    assert legs == []


def test_combos_rank_by_judgment_probability_and_report_return_per_yuan(tmp_path):
    legs = judgment_legs(day=DAY, jczq_dir=_day(tmp_path), now="2026-09-27T12:00:00+08:00")
    combos = enumerate_combos(legs, max_notes=2, top=3)
    best = combos[0]
    assert len(best["legs"]) == 2
    assert best["p"] >= combos[1]["p"] >= combos[2]["p"]
    assert best["notes"] <= 2
    assert round(best["return_per_yuan"], 6) == round(best["odds"] / best["notes"], 6)
