"""worldcup 子包 — 门控与赛制规则测试。"""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from nutmeg.services.worldcup import is_wc_active
from nutmeg.services.worldcup.tournament import (
    Tournament,
    allocate_best_thirds,
    load_tournament,
    rank_group,
    rank_thirds,
    validate_tournament,
)


def test_wc_active_inside_window() -> None:
    assert is_wc_active("2026-06-11") is True
    assert is_wc_active("2026-07-19") is True


def test_wc_inactive_outside_window() -> None:
    assert is_wc_active("2026-06-10") is False
    assert is_wc_active("2026-07-20") is False
    assert is_wc_active("2027-06-15") is False


def test_wc_active_bad_date_is_false() -> None:
    assert is_wc_active("not-a-date") is False


def _mini_tournament_dict() -> dict:
    """4 队 1 组 + 1 场 r32 的最小合法赛制,供规则单测复用。"""
    return {
        "tournament": "FIFA World Cup 2026",
        "window": {"start": "2026-06-11", "end": "2026-07-19"},
        "teams": [
            {"id": "Mexico", "zh": "墨西哥", "group": "A", "host": True},
            {"id": "Poland", "zh": "波兰", "group": "A", "host": False},
            {"id": "Senegal", "zh": "塞内加尔", "group": "A", "host": False},
            {"id": "Jordan", "zh": "约旦", "group": "A", "host": False},
        ],
        "matches": [
            {"match_id": "M01", "stage": "group", "group": "A",
             "date_utc": "2026-06-11", "home": "Mexico", "away": "Poland",
             "venue_country": "Mexico"},
            {"match_id": "M73", "stage": "r32", "date_utc": "2026-06-28",
             "home_slot": "1A", "away_slot": "2A", "venue_country": "USA"},
        ],
    }


def test_load_tournament_from_dict() -> None:
    t = Tournament.from_dict(_mini_tournament_dict())
    assert t.teams["Mexico"].zh == "墨西哥"
    assert t.groups["A"] == ["Mexico", "Poland", "Senegal", "Jordan"]
    assert t.matches[1].home_slot == "1A"


def test_validate_catches_unknown_team_and_slot() -> None:
    raw = _mini_tournament_dict()
    raw["matches"][0]["home"] = "Atlantis"
    raw["matches"][1]["away_slot"] = "1Z"
    errors = validate_tournament(Tournament.from_dict(raw))
    assert any("Atlantis" in e for e in errors)
    assert any("1Z" in e for e in errors)


# match_goals: {(home, away): (gh, ga)}


def test_rank_group_points_then_gd_then_gf() -> None:
    goals = {
        ("A1", "A2"): (2, 0), ("A1", "A3"): (1, 1), ("A1", "A4"): (0, 1),
        ("A2", "A3"): (3, 0), ("A2", "A4"): (2, 2), ("A3", "A4"): (0, 0),
    }
    order = rank_group(["A1", "A2", "A3", "A4"], goals, random.Random(1))
    # A4: 5分(1胜2平)/ A2: 4分 gd+1 gf5 / A1: 4分 gd+1 gf3(同 gd,gf 分高下)/ A3: 2分
    assert order == ["A4", "A2", "A1", "A3"]


def test_rank_group_h2h_breaks_full_tie() -> None:
    # B1/B2 同 6 分同 gd+2 同 gf4 全平;B2 赢了 B1 的 h2h → B2 在前。
    # 故意让 h2h 胜者(B2)在输入序里靠后:稳定排序会错排 B1 在前,只有 h2h 子表能纠正。
    goals = {
        ("B1", "B2"): (1, 2), ("B1", "B3"): (2, 0), ("B1", "B4"): (1, 0),
        ("B2", "B3"): (0, 1), ("B2", "B4"): (2, 0),
        ("B3", "B4"): (1, 1),
    }
    order = rank_group(["B1", "B2", "B3", "B4"], goals, random.Random(1))
    assert order.index("B2") < order.index("B1")


def test_rank_thirds_orders_by_points_gd_gf() -> None:
    thirds = [("A", "tA", 4, 1, 5), ("B", "tB", 6, 0, 2), ("C", "tC", 4, 2, 3)]
    ranked = rank_thirds(thirds, random.Random(1))
    assert [g for g, *_ in ranked] == ["B", "C", "A"]


def test_allocate_best_thirds_respects_allowed_groups() -> None:
    ranked = [("B", "tB", 6, 0, 2), ("C", "tC", 4, 2, 3), ("A", "tA", 4, 1, 5)]
    slots = {"S1": "AB", "S2": "BC", "S3": "ABC"}
    alloc = allocate_best_thirds(ranked, slots)
    assert set(alloc.values()) == {"tA", "tB", "tC"}
    assert alloc["S1"] in {"tA", "tB"}
    assert alloc["S2"] in {"tB", "tC"}


def test_load_tournament_real_file_validates() -> None:
    """真实静态文件落库后必须零校验错误(Task 3 落库前先 skip)。"""
    path = Path("nutmeg/data/wc2026_tournament.json")
    if not path.exists():
        pytest.skip("wc2026_tournament.json 尚未落库(Task 3)")
    t = load_tournament()
    assert validate_tournament(t) == []
    assert len(t.teams) == 48
    assert len(t.groups) == 12
    assert len(t.matches) == 104
