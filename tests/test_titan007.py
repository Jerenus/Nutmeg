"""单测 titan007 数据层 —— 板面/欧赔解析、降级响应识别。全部离线 fixture。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from nutmeg.data.titan007 import (
    Titan007ParseError,
    parse_board,
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
