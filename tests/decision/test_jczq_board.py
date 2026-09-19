import json

from nutmeg.decision.jczq_board import build_board_legs, devig


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
