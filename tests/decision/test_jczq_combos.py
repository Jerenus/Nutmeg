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


def _leg(code: str, p_single: float) -> dict:
    # 一条腿：单选 p_single / 双选 p_single+0.2；赔率随意
    return {"code": code, "name": code, "kickoff": "", "belief": {}, "prior": {},
            "options": [{"market": "had", "faces": "3", "p": p_single, "odds": [1.5],
                         "modal_odds": 1.5},
                        {"market": "had", "faces": "31", "p": min(p_single + 0.2, 0.99),
                         "odds": [1.5, 4.0], "modal_odds": 1.5}]}


def test_max_pool_prunes_to_strongest_legs_and_keeps_top_order():
    # 2026-10-25：周末 23 场板 5,900 万候选把 research verdict 卡死/被杀；裁腿后结果仍按 P 降序
    legs = [_leg(f"L{i:02d}", 0.30 + i * 0.02) for i in range(20)]  # L19 最强
    full = enumerate_combos(legs, max_legs=2, max_notes=4, top=5)
    pruned = enumerate_combos(legs, max_legs=2, max_notes=4, top=5, max_pool=6)
    assert [c["p"] for c in pruned] == [c["p"] for c in full]
    assert all(c["p"] >= n["p"] for c, n in zip(pruned, pruned[1:], strict=False))
    used = {leg["code"] for c in pruned for leg in c["legs"]}
    assert used <= {f"L{i:02d}" for i in range(14, 20)}


def test_top_is_bounded_without_keeping_every_candidate():
    legs = [_leg(f"L{i:02d}", 0.40 + i * 0.01) for i in range(8)]
    combos = enumerate_combos(legs, max_legs=3, max_notes=4, top=3)
    assert len(combos) == 3
    assert combos[0]["p"] >= combos[1]["p"] >= combos[2]["p"]
