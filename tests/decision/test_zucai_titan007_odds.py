"""单测足彩国际欧赔对齐 —— 足彩场号 ↔ titan007 场次。

竞彩那条链有竞彩号可查表；足彩没有这个键：500.com 在售页不带 titan007 id，titan007
也没有胜负彩板面。所以只能用**开球时刻为主键、队名做消歧**，且要求唯一——对不上就
丢场，退回 500.com 单源，绝不猜。
"""

from __future__ import annotations

from datetime import datetime

from nutmeg.data.titan007 import Titan007BoardRow, Titan007BookQuote
from nutmeg.services.zucai_titan007_odds import align_zucai_to_titan007


def _row(no: str, mid: str, kickoff: str, home: tuple, away: tuple) -> Titan007BoardRow:
    return Titan007BoardRow(
        match_id=mid, match_no=no, kickoff=datetime.fromisoformat(kickoff),
        home_names=home, away_names=away,
    )


def _match(no: int, home: str, away: str, kickoff_bj: str) -> dict:
    return {"match_no": no, "home_team": home, "away_team": away,
            "kickoff_bj": kickoff_bj}


def test_aligns_on_exact_kickoff_when_the_slot_is_unique():
    rows = [_row("周一007", "300", "2026-09-15T02:15", ("吉达国民",), ("棉农",))]
    out = align_zucai_to_titan007([_match(2, "吉国民", "棉农", "2026-09-15 02:15")], rows)
    assert out == {2: rows[0]}


def test_abbreviation_mismatch_is_survivable_because_kickoff_is_the_key():
    """``吉国民`` 与 ``吉达国民`` 无子串关系——纯队名匹配会丢这场。"""
    rows = [_row("周一007", "300", "2026-09-15T02:15", ("吉达国民",), ("棉农",))]
    assert align_zucai_to_titan007(
        [_match(2, "吉国民", "棉农", "2026-09-15 02:15")], rows
    ) == {2: rows[0]}


def test_same_kickoff_is_disambiguated_by_either_side_name():
    rows = [
        _row("周一008", "801", "2026-09-15T02:45", ("国际米兰",), ("乌迪内斯",)),
        _row("周一009", "901", "2026-09-15T02:45", ("圣旺红星",), ("梅斯",)),
    ]
    # ``国米`` 对不上 ``国际米兰``，但 ``乌迪内`` 是 ``乌迪内斯`` 的子串 → 客队定案
    out = align_zucai_to_titan007([_match(6, "国米", "乌迪内", "2026-09-15 02:45")], rows)
    assert out[6].match_no == "周一008"


def test_ambiguous_slot_is_dropped_rather_than_guessed():
    rows = [
        _row("周一A", "1", "2026-09-15T01:00", ("甲队",), ("乙队",)),
        _row("周一B", "2", "2026-09-15T01:00", ("甲队",), ("丙队",)),
    ]
    # 主队名两边都命中、客队名都不命中 → 仍是两解 → 丢
    assert align_zucai_to_titan007([_match(1, "甲队", "丁队", "2026-09-15 01:00")], rows) == {}


def test_a_match_absent_from_the_board_is_simply_missing():
    """足彩板含竞彩不卖的场（亚运女足/部分葡超）——缺席是常态，不是故障。"""
    rows = [_row("周一006", "600", "2026-09-15T01:00", ("博德闪耀",), ("桑德菲杰",))]
    assert align_zucai_to_titan007(
        [_match(1, "中国女", "中港女", "2026-09-14 18:00")], rows
    ) == {}


def test_unparseable_kickoff_is_dropped_not_defaulted():
    rows = [_row("周一006", "600", "2026-09-15T01:00", ("博德闪耀",), ("桑纳菲",))]
    assert align_zucai_to_titan007([_match(1, "博德", "桑纳菲", "")], rows) == {}


def test_collect_builds_market_odds_for_the_aligned_matches():
    from nutmeg.services.zucai_titan007_odds import collect_zucai_euro_titan007

    rows = [_row("周一006", "600", "2026-09-15T01:00", ("博德闪耀",), ("桑纳菲",))]

    def _quote(cid: str, opening, current) -> Titan007BookQuote:
        keys = ("home", "draw", "away")
        return Titan007BookQuote(
            company_id=cid, company_name=cid,
            opening=dict(zip(keys, opening, strict=True)),
            current=dict(zip(keys, current, strict=True)),
            updated_at=None,
        )

    quotes = [
        _quote("177", [2.0, 3.4, 3.6], [1.7, 3.8, 5.0]),
        _quote("545", [1.8, 3.6, 4.4], [1.8, 3.6, 4.4]),
        _quote("281", [1.9, 3.5, 4.0], [1.75, 3.7, 4.6]),
    ]
    issue_doc = {"matches": [_match(14, "博德", "桑纳菲", "2026-09-15 01:00")]}
    out = collect_zucai_euro_titan007(
        issue_doc, board_fetcher=lambda: rows, odds_fetcher=lambda mid: quotes
    )
    assert set(out) == {14}
    entry = out[14]
    assert entry["jczq_match_no"] == "周一006"
    assert entry["titan007_match_id"] == "600"
    assert entry["books"] == 3
    assert entry["opening_odds"]            # 初赔可得——500.com 那条链没有
    assert entry["micro"]["drift_pp"]       # drift 不再恒为 0


def _quotes() -> list[Titan007BookQuote]:
    keys = ("home", "draw", "away")
    return [
        Titan007BookQuote(company_id=cid, company_name=cid,
                          opening=dict(zip(keys, o, strict=True)),
                          current=dict(zip(keys, c, strict=True)), updated_at=None)
        for cid, o, c in (("177", [2.0, 3.4, 3.6], [1.7, 3.8, 5.0]),
                          ("545", [1.8, 3.6, 4.4], [1.8, 3.6, 4.4]),
                          ("281", [1.9, 3.5, 4.0], [1.75, 3.7, 4.6]))
    ]


def test_collect_reaches_matches_off_the_jczq_board_through_the_schedule_page():
    # 2026-09-24：26132 的 8 场周五比赛不在竞彩在售板上 → 国际盘整场缺席。
    from nutmeg.services.zucai_titan007_odds import collect_zucai_euro_titan007

    board = [_row("周四006", "2981425", "2026-09-25T02:45", ("荷兰",), ("德国",))]
    schedule = {
        "2026-09-24": [_row("", "2981425", "2026-09-25T02:45", ("荷兰",), ("德国",))],
        "2026-09-25": [
            _row("", "2981429", "2026-09-26T02:45", ("意大利",), ("比利时",)),
            _row("", "2981479", "2026-09-26T02:45", ("波兰",), ("波黑",)),
        ],
    }
    seen: list[str] = []

    def schedule_fetcher(day: str):
        seen.append(day)
        return schedule.get(day, [])

    issue_doc = {"matches": [
        _match(3, "荷兰", "德国", "2026-09-25 02:45"),
        _match(10, "意大利", "比利时", "2026-09-26 02:45"),
    ]}
    out = collect_zucai_euro_titan007(
        issue_doc, board_fetcher=lambda: board, odds_fetcher=lambda mid: _quotes(),
        schedule_fetcher=schedule_fetcher,
    )

    assert set(out) == {3, 10}
    assert (out[3]["jczq_match_no"], out[3]["align_source"]) == ("周四006", "jc_board")
    assert out[10]["jczq_match_no"] is None
    assert (out[10]["titan007_match_id"], out[10]["align_source"]) == ("2981429", "schedule")
    # 开球日 + 前一天（凌晨场挂在前一天的页上）
    assert sorted(set(seen)) == ["2026-09-24", "2026-09-25", "2026-09-26"]


def test_schedule_rows_skip_youth_teams_and_accept_a_one_sided_translation_gap():
    # 整天赛程里同刻有青年队；译名常只差一边（赫塔费/赫塔菲、托林斯/杜连斯）。
    from nutmeg.services.zucai_titan007_odds import align_zucai_to_titan007

    rows = [
        _row("", "1", "2026-09-26T02:45", ("意大利U21",), ("比利时U21",)),
        _row("", "2", "2026-09-18T01:00", ("皇家贝蒂斯",), ("赫塔菲",)),
        _row("", "3", "2026-09-18T03:00", ("利勒斯特罗姆",), ("杜连斯",)),
        _row("", "4", "2026-09-18T03:00", ("比尔森胜利",), ("圣吉罗斯",)),
    ]
    matches = [
        _match(10, "意大利", "比利时", "2026-09-26 02:45"),
        _match(12, "贝蒂斯", "赫塔费", "2026-09-18 01:00"),
        _match(8, "利勒斯", "托林斯", "2026-09-18 03:00"),
        _match(9, "比尔森", "圣吉尔联合", "2026-09-18 03:00"),
    ]
    aligned = align_zucai_to_titan007(matches, rows)
    assert 10 not in aligned                      # 青年队不顶包成年队
    assert {no: row.match_id for no, row in aligned.items() if no != 10} == {
        12: "2", 8: "3", 9: "4"}


def test_schedule_two_char_abbreviation_needs_the_other_side_too():
    from nutmeg.services.zucai_titan007_odds import align_zucai_to_titan007

    rows = [
        _row("", "1", "2026-09-19T01:00", ("萨普斯堡",), ("KFUM奥斯陆",)),
        _row("", "2", "2026-09-19T01:00", ("吉达国民",), ("利雅得胜利",)),
    ]
    matches = [
        _match(14, "萨堡", "奥斯KF", "2026-09-19 01:00"),     # 两字按序 + 另一边不中 → 丢
        _match(11, "吉国民", "利胜利", "2026-09-19 01:00"),   # 三字按序 → 认
    ]
    aligned = align_zucai_to_titan007(matches, rows)
    assert 14 not in aligned
    assert aligned[11].match_id == "2"


def test_schedule_prefers_the_row_where_both_sides_match_when_one_side_is_shared():
    from nutmeg.services.zucai_titan007_odds import align_zucai_to_titan007

    rows = [
        _row("", "1", "2026-09-17T20:15", ("上海申花",), ("淡滨尼流浪者",)),
        _row("", "2", "2026-09-17T20:15", ("上海海港",), ("淡宾尼士流浪",)),
    ]
    aligned = align_zucai_to_titan007(
        [_match(1, "上海申花", "淡宾尼士流浪", "2026-09-17 20:15")], rows
    )
    assert 1 not in aligned                        # 各中一边、无一两边全中 → 丢，不猜
    rows.append(_row("", "3", "2026-09-17T20:15", ("上海申花",), ("淡宾尼士流浪",)))
    assert align_zucai_to_titan007(
        [_match(1, "上海申花", "淡宾尼士流浪", "2026-09-17 20:15")], rows
    )[1].match_id == "3"


def test_collect_survives_a_failed_jczq_board_when_the_schedule_works():
    from nutmeg.services.zucai_titan007_odds import collect_zucai_euro_titan007

    def broken_board():
        raise RuntimeError("bf_jc down")

    out = collect_zucai_euro_titan007(
        {"matches": [_match(10, "意大利", "比利时", "2026-09-26 02:45")]},
        board_fetcher=broken_board,
        odds_fetcher=lambda mid: _quotes(),
        schedule_fetcher=lambda day: [
            _row("", "2981429", "2026-09-26T02:45", ("意大利",), ("比利时",))
        ],
    )
    assert set(out) == {10}
