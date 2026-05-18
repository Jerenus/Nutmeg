from __future__ import annotations

import json
from pathlib import Path

from nutmeg.services.jczq_second_leg import solo_from_final


def _write_plan(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "final-plan.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_solo_from_final_prefers_top_level_solo_leg(tmp_path: Path) -> None:
    path = _write_plan(
        tmp_path,
        {
            "solo_leg": {"match_no": "周一001", "pool": "had", "pick": "胜"},
            "favorite_ticket_id": "A",
            "tickets": [
                {
                    "id": "A",
                    "legs": [{"match_no": "周一002", "pool": "ttg", "pick": "2球"}],
                }
            ],
        },
    )

    assert solo_from_final(path) == ("周一001", "had", "胜")


def test_solo_from_final_uses_favorite_ticket_first_leg_after_r28(tmp_path: Path) -> None:
    path = _write_plan(
        tmp_path,
        {
            "favorite_ticket_id": "B",
            "tickets": [
                {
                    "id": "A",
                    "kind": "stable_base",
                    "legs": [{"match_no": "周一001", "pool": "had", "pick": "胜"}],
                },
                {
                    "id": "B",
                    "kind": "main",
                    "legs": [
                        {"match_no": "周一002", "pool": "hhad", "pick": "让负"},
                        {"match_no": "周一003", "pool": "ttg", "pick": "3球"},
                    ],
                },
            ],
        },
    )

    assert solo_from_final(path) == ("周一002", "hhad", "让负")


def test_solo_from_final_falls_back_to_any_single_leg_ticket(tmp_path: Path) -> None:
    path = _write_plan(
        tmp_path,
        {
            "tickets": [
                {
                    "id": "D",
                    "kind": "contrarian",
                    "legs": [
                        {"match_no": "周一001", "pool": "had", "pick": "胜"},
                        {"match_no": "周一002", "pool": "had", "pick": "平"},
                    ],
                },
                {
                    "id": "A",
                    "kind": "stable_base",
                    "legs": [{"match_no": "周一004", "pool": "ttg", "pick": "2球"}],
                },
            ],
        },
    )

    assert solo_from_final(path) == ("周一004", "ttg", "2球")

