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


from nutmeg.data.fcom500 import Fcom500JczqMatch, sporttery_value_from_jczq_board  # noqa: E402
from nutmeg.services.jczq_bold_combos import bold_matches_from_sporttery  # noqa: E402


def _synth_value() -> dict:
    return sporttery_value_from_jczq_board(parse_jczq_list(_board_html()))


# ---------------------------------------------------------------------------
# 合成 — sporttery getMatchCalculatorV1 同形 value dict
# ---------------------------------------------------------------------------


def test_synth_value_shape() -> None:
    value = _synth_value()
    assert value["nutmegSource"] == "fcom500-fallback"
    (day,) = value["matchInfoList"]
    assert day["businessDate"] == "2026-06-11"
    subs = {s["matchNumStr"]: s for s in day["subMatchList"]}
    s1 = subs["周四001"]
    assert s1["matchStatus"] == "Selling"
    assert s1["homeTeamAbbName"] == "墨西哥"
    assert s1["awayTeamAbbName"] == "南非"
    assert s1["matchDate"] == "2026-06-12"
    assert s1["matchTime"] == "03:00"
    assert s1["had"] == {"h": 1.26, "d": 4.45, "a": 9.00}
    assert s1["hhad"] == {"h": 2.00, "d": 3.25, "a": 3.11, "goalLineValue": "-1"}


def test_synth_excludes_not_selling() -> None:
    (day,) = _synth_value()["matchInfoList"]
    nums = [s["matchNumStr"] for s in day["subMatchList"]]
    assert nums == ["周四001", "周四002"]  # 周四099 停售被排除


def test_synth_groups_by_business_date() -> None:
    def mk(no: str, bdate: str) -> Fcom500JczqMatch:
        return Fcom500JczqMatch(
            match_no=no, fid="1", home_team="甲", away_team="乙",
            league="", league_short="测试", kickoff="",
            had_sp={"home": 2.0, "draw": 3.0, "away": 4.0},
            hhad_sp={}, hhad_line=0.0, business_date=bdate,
            match_date=bdate, match_time="20:00", is_selling=True,
        )

    value = sporttery_value_from_jczq_board(
        [mk("周四001", "2026-06-11"), mk("周五003", "2026-06-12")]
    )
    days = value["matchInfoList"]
    assert [d["businessDate"] for d in days] == ["2026-06-11", "2026-06-12"]
    assert all(len(d["subMatchList"]) == 1 for d in days)


def test_synth_skips_match_with_no_pools_and_empty_input() -> None:
    no_pools = Fcom500JczqMatch(
        match_no="周四050", fid="1", home_team="甲", away_team="乙",
        league="", league_short="", kickoff="",
        business_date="2026-06-11", match_date="2026-06-11",
        match_time="20:00", is_selling=True,
    )
    assert sporttery_value_from_jczq_board([no_pools])["matchInfoList"] == []
    assert sporttery_value_from_jczq_board([])["matchInfoList"] == []


def test_synth_roundtrip_into_bold_matches() -> None:
    # 合成 value 直接喂引擎入口 → BoldMatch，had/hhad 数值一致、ttg/crs 缺省为空
    matches = bold_matches_from_sporttery(
        _synth_value(), run_date="2026-06-11", bold_odds={}
    )
    by_no = {m.match_no: m for m in matches}
    assert set(by_no) == {"周四001", "周四002"}
    m1 = by_no["周四001"]
    assert m1.home == "墨西哥" and m1.away == "南非"
    assert m1.tc_odds == {"home": 1.26, "draw": 4.45, "away": 9.00}
    assert m1.hhad_odds == {"home": 2.00, "draw": 3.25, "away": 3.11}
    assert m1.hhad_line == -1.0
    assert m1.ttg_odds == {} and m1.crs_odds == {}
