"""单测 titan007 数据层 —— 板面/欧赔解析、降级响应识别。全部离线 fixture。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from nutmeg.data.titan007 import (
    Titan007ParseError,
    parse_board,
    parse_euro_odds,
)

FIXTURES = Path(__file__).parent / "fixtures" / "titan007"


def _board_text() -> str:
    return (FIXTURES / "bf_jc.txt").read_text(encoding="utf-8")


def test_parse_board_extracts_jc_number_and_titan_id():
    rows = parse_board(_board_text())
    assert [r.match_no for r in rows] == ["周一002", "周一003", "周一004"]
    assert [r.match_id for r in rows] == ["3085206", "2993786", "2993793"]


def test_parse_board_decodes_zero_indexed_month():
    """titan007 沿用 JS Date 月份口径（0 起），`2026,8,14` 是 9 月 14 日，不是 8 月。"""
    rows = parse_board(_board_text())
    assert rows[0].kickoff == datetime(2026, 9, 14, 23, 0, 0)
    assert rows[1].kickoff == datetime(2026, 9, 15, 0, 30, 0)


def test_parse_board_keeps_all_team_name_variants():
    rows = parse_board(_board_text())
    assert rows[0].home_names == ("图尔库国际", "英特杜古", "国际图尔")
    assert rows[0].away_names == ("VPS瓦萨", "VPS華沙", "瓦萨")


def test_parse_board_rejects_degraded_response():
    """WAF/错误页必须 raise，绝不返回空 list 冒充『今天没有盘』（2026-06 假空盘死法）。"""
    with pytest.raises(Titan007ParseError):
        parse_board("<html><title>404 - 找不到文件或目录。</title></html>")


def test_parse_board_rejects_empty_match_section():
    with pytest.raises(Titan007ParseError):
        parse_board("13^#003db9^2082^芬超,芬超^,^League.aspx?SclassID=13$")


def _euro_text() -> str:
    return (FIXTURES / "euro_3085206.js").read_text(encoding="utf-8")


def test_parse_euro_odds_returns_every_book():
    quotes = parse_euro_odds(_euro_text())
    assert [q.company_name for q in quotes] == [
        "Lottery Official",
        "Bet 365",
        "Macauslot",
        "HK Jockey Club",
        "Pinnacle",
        "Crown",
    ]


def test_parse_euro_odds_splits_opening_from_current():
    """初赔与即时赔是两组独立字段——这正是 API-Football 结构性缺失的那一半。"""
    pinnacle = next(q for q in parse_euro_odds(_euro_text()) if q.company_id == "177")
    assert pinnacle.opening == {"home": 2.07, "draw": 3.37, "away": 3.54}
    assert pinnacle.current == {"home": 1.71, "draw": 3.81, "away": 5.1}


def test_parse_euro_odds_reads_update_time_with_arithmetic_month():
    pinnacle = next(q for q in parse_euro_odds(_euro_text()) if q.company_id == "177")
    assert pinnacle.updated_at == datetime(2026, 9, 13, 23, 28, 0)


def test_parse_euro_odds_rejects_degraded_response():
    with pytest.raises(Titan007ParseError):
        parse_euro_odds("<html><title>500 - 内部服务器错误。</title></html>")


def test_parse_euro_odds_rejects_too_few_books():
    """半截响应（书目过少）必须 raise，不能当作『这场没盘』。"""
    thin = (
        'var game=Array("177|1|Pinnacle|2.07|3.37|3.54|45|27|26|94|1.71|3.81|5.1'
        '|56|25|18|95|0.9|0.9|0.9|2026,09-1,13,23,28,00|P*|1|0|1.1|0.8|0.6");'
    )
    with pytest.raises(Titan007ParseError):
        parse_euro_odds(thin)
