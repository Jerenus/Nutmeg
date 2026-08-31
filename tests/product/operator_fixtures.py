import json
from pathlib import Path


def write_26112_bundle(root: Path) -> Path:
    root.mkdir(parents=True)
    issue = {
        "issue_id": "26112",
        "sale_deadline": None,
        "sources": [
            {
                "label": "sporttery issue page",
                "url": "https://example.invalid/issue/26112",
                "captured_at": "2026-08-28T14:00:06",
            }
        ],
        "matches": [
            {
                "match_no": 1,
                "competition": "英超",
                "home_team": "水晶宫",
                "away_team": "曼彻斯特城",
                "kickoff_bj": "2026-08-29 03:00",
                "match_date": "2026-08-29",
                "asian_ref": "1.04,受半球/一球,0.80",
            }
        ],
    }
    prep = {
        "issue": "26112",
        "run_date": "2026-08-28",
        "slot": "afternoon",
        "captured_at": "2026-08-28T14:00:07",
        "n_matches": 1,
        "alignment": {"unmatched": [], "ambiguous": []},
        "screens": {
            "coinflip": [],
            "fattest_draws": [],
            "missing_euro_anchor": [],
            "missing_ttg_anchor": [],
            "strong_anchors": [],
        },
        "records": {
            "1": {
                "name": "水晶宫-曼彻斯特城",
                "league": "英超",
                "kickoff_bj": "2026-08-29 03:00",
                "match_date": "2026-08-29",
                "sporttery_match_num": "5011",
                "fair_had": {"home": 0.1956, "draw": 0.2343, "away": 0.5702},
                "sporttery_had_date": "2026-08-27",
                "hhad_line": "+1",
                "ttg_anchor": True,
                "lambda": [1.101, 1.984, -0.07],
                "fit_loss": 0.000707,
                "dc_had": [0.199, 0.2294, 0.5716],
                "top_scores": [["1:1", 0.1069]],
                "ttg_bands": {"total_2": 0.2246},
                "over25": 0.5956,
                "margin": {"0": 0.2294},
                "home_by_2plus": 0.0766,
                "away_by_2plus": 0.3454,
                "hhad_cover": {
                    "line": "+1",
                    "让胜": 0.4284,
                    "让平": 0.2262,
                    "让负": 0.3454,
                },
            }
        },
        "judgment": None,
    }
    rx = {
        "issue": "26112",
        "registered_at": "2026-08-28T13:30:00+08:00",
        "decision": "任九主攻",
        "capital_report": {"票价": "V288=72%帽内"},
        "prescription_P14": {
            "singles": {"3": "3"},
            "doubles": {"4": "31"},
            "fulls": ["1"],
            "expected_broken_legs": 1.65,
            "difficulty_price_cny": 12,
            "correction_log": "fixture",
            "audit_R432": "0 ERROR 0 WARN",
        },
        "ticket_versions": {"R432": "human note; not parsed"},
        "pending_adjudications": [
            {
                "id": "ADJ-1",
                "status": "需你行权",
                "q": "任九档位",
                "options": "R432 / V288",
                "default": "R432",
            }
        ],
        "predictions": [{"id": "P1", "claim": "至少一场平", "falsifier": "全无平局"}],
        "notes": "fixture",
    }
    legs = {
        "issue": "26112",
        "version": "R432",
        "legs": {
            "1": {
                "name": "水晶宫-曼城·310",
                "faces": "310",
                "confidence": 2,
                "directional_flags": [["anchor_shield_out", "1"]],
                "nondirectional_flags": ["two_way_instability"],
                "anchor_integrity": "fail",
                "fair": {"home": 0.196, "draw": 0.289, "away": 0.515},
                "precedents": [["1", "fixture precedent", "live"]],
            }
        },
    }
    for name, value in {
        "26112-issue.json": issue,
        "26112-prep-afternoon.json": prep,
        "26112-rx.json": rx,
        "26112-legs-R432.json": legs,
    }.items():
        (root / name).write_text(json.dumps(value, ensure_ascii=False), "utf-8")
    return root
