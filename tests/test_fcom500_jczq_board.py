"""trade.500.com 体彩备源 — data-sp 解析 + sporttery value 合成 + 回退（spec 2026-06-11）。

离线 fixture：tests/fixtures/fcom500/jczq-list-20260611.html（真实页面截段，
周四001 墨西哥vs南非 / 周四002 韩国vs捷克 / 周四099 人工停售行）。
"""
from __future__ import annotations

from pathlib import Path

from nutmeg.data.fcom500 import parse_jczq_list

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "fcom500"


def _board_html() -> str:
    return (_FIXTURE_DIR / "jczq-list-20260611.html").read_text(encoding="utf-8")


def _board_by_no() -> dict:
    return {m.match_no: m for m in parse_jczq_list(_board_html())}


# ---------------------------------------------------------------------------
# 解析 — 体彩 sp 价 + tr data 属性
# ---------------------------------------------------------------------------


def test_parse_extracts_had_and_hhad_sp() -> None:
    m1 = _board_by_no()["周四001"]
    assert m1.had_sp == {"home": 1.26, "draw": 4.45, "away": 9.00}
    assert m1.hhad_sp == {"home": 2.00, "draw": 3.25, "away": 3.11}
    assert m1.hhad_line == -1.0


def test_parse_extracts_board_metadata() -> None:
    m1 = _board_by_no()["周四001"]
    assert m1.business_date == "2026-06-11"
    assert m1.match_date == "2026-06-12"
    assert m1.match_time == "03:00"
    assert m1.is_selling is True
    # 停售行（data-isend="1"）解析保留但标记不在售
    m99 = _board_by_no()["周四099"]
    assert m99.is_selling is False


def test_parse_old_fixture_backcompat() -> None:
    # 2026-05-17 旧 fixture：38 场不变，新字段也填上（全部已停售）
    html = (_FIXTURE_DIR / "jczq-list.html").read_text(encoding="utf-8")
    matches = parse_jczq_list(html)
    assert len(matches) == 38
    m1 = {m.match_no: m for m in matches}["周日001"]
    assert m1.is_selling is False
    assert m1.hhad_line == 1.0
    assert m1.business_date == "2026-05-17"


def test_parse_missing_sp_degrades_to_empty_dict() -> None:
    # 去掉所有 data-sp 的行 → had_sp/hhad_sp 为空 dict，不崩
    html = _board_html().replace("data-sp=", "data-xx=")
    matches = parse_jczq_list(html)
    assert matches and all(m.had_sp == {} and m.hhad_sp == {} for m in matches)
