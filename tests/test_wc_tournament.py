"""worldcup 子包 — 门控与赛制规则测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from nutmeg.services.worldcup import is_wc_active
from nutmeg.services.worldcup.tournament import (
    Tournament,
    load_tournament,
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
