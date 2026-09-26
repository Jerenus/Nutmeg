import json
from datetime import datetime

from nutmeg.decision.jczq_board import BJ, build_board_legs, devig


def test_devig_normalises_1x2_odds():
    p = devig({"home": 2.0, "draw": 3.5, "away": 4.0})
    assert abs(sum(p.values()) - 1.0) < 1e-9
    assert p["home"] > p["draw"] > p["away"]


def test_build_board_legs_joins_kernel_matches_with_bold_odds(tmp_path):
    day = tmp_path / "daily" / "2026-09-19"
    day.mkdir(parents=True)
    (day / "bold_odds.json").write_text(
        json.dumps(
            {
                "周五001": {
                    "match_winner": {
                        "odds": {"home": 2.0, "draw": 3.5, "away": 4.0},
                        "line": None,
                    }
                },
                "周五002": {
                    "match_winner": {
                        "odds": {"home": 1.5, "draw": 4.0, "away": 6.0},
                        "line": -1,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    matches = [
        {
            "match_id": "m-1",
            "home_team": "A",
            "away_team": "B",
            "competition": "英超",
            "scheduled_at": "2026-09-19T19:00:00+00:00",
            "board_code": "周五001",
        },
        {
            "match_id": "m-2",
            "home_team": "C",
            "away_team": "D",
            "competition": "德甲",
            "scheduled_at": "2026-09-19T20:30:00+00:00",
            "board_code": "周五002",
        },
    ]

    doc = build_board_legs(day="2026-09-19", matches=matches, jczq_dir=tmp_path)

    assert set(doc["legs"]) == {"周五001", "周五002"}
    leg = doc["legs"]["周五001"]
    assert leg["match_id"] == "m-1"
    assert leg["judgment_tier"] == "price_only"
    assert leg["kickoff_bj"] == "2026-09-20T03:00:00+08:00"
    assert abs(sum(leg["fair"].values()) - 1) < 1e-9
    assert doc["legs"]["周五002"]["hhad_line"] == -1
    assert (day / "jczq-legs-base.json").exists()


def test_rebuilding_the_board_keeps_judgments_and_started_matches(tmp_path):
    """17:15 刷新曾把 007–016 的深研冲回 price_only、把已开球的 001–006 整场删掉
    （F9 名单随之少 6 场，2026-09-26）。重建只许加新场、刷未开球场的价格。"""
    day = tmp_path / "daily" / "2026-09-19"
    day.mkdir(parents=True)
    (day / "bold_odds.json").write_text(json.dumps({
        "周五001": {"match_winner": {"odds": {"home": 2.0, "draw": 3.5, "away": 4.0}}},
        "周五002": {"match_winner": {"odds": {"home": 1.5, "draw": 4.0, "away": 6.0}}},
        "周五003": {"match_winner": {"odds": {"home": 3.0, "draw": 3.0, "away": 2.5}}},
    }), encoding="utf-8")
    started = {"match_id": "m-0", "name": "X-Y", "kickoff_bj": "2026-09-19T12:00:00+08:00",
               "fair": {"home": 0.5, "draw": 0.3, "away": 0.2}, "judgment_tier": "deep_research",
               "faces": "31", "stance": {"face": "3"}}
    researched = {"match_id": "m-1", "name": "A-B", "kickoff_bj": "2026-09-20T03:00:00+08:00",
                  "fair": {"home": 0.4, "draw": 0.3, "away": 0.3}, "judgment_tier": "deep_research",
                  "faces": "31", "stance": {"face": "3"}, "face_status": {"home": {}}}
    (day / "jczq-legs-base.json").write_text(json.dumps(
        {"day": "2026-09-19", "legs": {"周五000": started, "周五001": researched}}),
        encoding="utf-8")
    matches = [
        {"match_id": "m-1", "home_team": "A", "away_team": "B", "competition": "英超",
         "scheduled_at": "2026-09-19T19:00:00+00:00", "board_code": "周五001"},
        {"match_id": "m-2", "home_team": "C", "away_team": "D", "competition": "德甲",
         "scheduled_at": "2026-09-19T20:30:00+00:00", "board_code": "周五002"},
    ]

    doc = build_board_legs(day="2026-09-19", matches=matches, jczq_dir=tmp_path,
                           now=datetime(2026, 9, 19, 17, 15, tzinfo=BJ))

    assert set(doc["legs"]) == {"周五000", "周五001", "周五002"}
    assert doc["legs"]["周五000"] == started
    kept = doc["legs"]["周五001"]
    assert (kept["judgment_tier"], kept["faces"], kept["stance"]) == ("deep_research", "31",
                                                                       {"face": "3"})
    assert kept["fair"]["home"] == devig({"home": 2.0, "draw": 3.5, "away": 4.0})["home"]
    assert doc["legs"]["周五002"]["judgment_tier"] == "price_only"


def test_rebuild_does_not_reprice_a_match_that_already_kicked_off(tmp_path):
    day = tmp_path / "daily" / "2026-09-19"
    day.mkdir(parents=True)
    (day / "bold_odds.json").write_text(json.dumps(
        {"周五001": {"match_winner": {"odds": {"home": 2.0, "draw": 3.5, "away": 4.0}}}}),
        encoding="utf-8")
    leg = {"match_id": "m-1", "name": "A-B", "kickoff_bj": "2026-09-19T12:00:00+08:00",
           "fair": {"home": 0.4, "draw": 0.3, "away": 0.3}, "judgment_tier": "price_only",
           "faces": "310"}
    (day / "jczq-legs-base.json").write_text(json.dumps({"legs": {"周五001": leg}}),
                                             encoding="utf-8")
    matches = [{"match_id": "m-1", "home_team": "A", "away_team": "B", "competition": "英超",
                "scheduled_at": "2026-09-19T04:00:00+00:00", "board_code": "周五001"}]

    doc = build_board_legs(day="2026-09-19", matches=matches, jczq_dir=tmp_path,
                           now=datetime(2026, 9, 19, 17, 15, tzinfo=BJ))

    assert doc["legs"]["周五001"] == leg
