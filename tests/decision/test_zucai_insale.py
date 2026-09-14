# tests/decision/test_zucai_insale.py
import json
from datetime import date

import pytest

from nutmeg.decision.zucai_insale import parse_board, write_snapshots

_HEAD = (
    '<li class="chked" data-expect="26103" ><i class="ico-chk"></i>当前第26103期</li>'
    '<span class="zcfilter-endtime">官方售彩截止时间：08-11 22:00</span>'
)


def _row(cid, home, away, kickoff, pjgl, league="欧冠", cls="bet-tb-tr"):
    return (
        f'<tr class="{cls}" data-cid="{cid}" data-vs="{home}vs{away}" '
        f'data-asian="0.80,平手,0.98" data-pjgl="{pjgl}">'
        f'<td class="td td-no">{cid}</td>'
        f'<td class="td td-evt"><a href="#">{league}</a></td>'
        f'<td class="td td-endtime">{kickoff}</td>'
        f'<td class="td td-team"><span class="team-l"><a href="#" class="team-l">{home}</a></span>'
        f'<span class="team-r"><a href="#" class="team-r">{away}</a></span></td></tr>'
    )


def _page(n=14):
    # 交替行用不同 class(500.com 真实形状),解析必须两种都吃到
    rows = "".join(_row(i, f"主{i}", f"客{i}", "08-12 00:00", "50.00,25.00,25.00",
                        cls="bet-tb-tr" if i % 2 else "bet-tb-tr bet-tb-tr-alt")
                   for i in range(1, n + 1))
    return _HEAD + rows


def test_parses_all_fourteen_rows_including_alternating_class():
    """交替行的 class 带后缀,只匹配 class="bet-tb-tr" 会只拿到 7 行(实抓踩过)。"""
    board = parse_board(_page(), today=date(2026, 8, 11))
    assert board["issue"] == "26103"
    assert board["deadline"] == "2026-08-11 22:00"
    assert len(board["matches"]) == 14
    assert [m["match_no"] for m in board["matches"]] == list(range(1, 15))


def test_pjgl_is_already_devigged_fair():
    """data-pjgl 是多家均值平均概率,三路和恒为 100 —— 归一后即市场 fair。"""
    board = parse_board(_page(), today=date(2026, 8, 11))
    fair = board["matches"][0]["fair_had"]
    assert abs(sum(fair.values()) - 1.0) < 1e-9
    assert abs(fair["home"] - 0.50) < 1e-9


def test_kickoff_year_inferred_and_date_split_out():
    board = parse_board(_page(), today=date(2026, 8, 11))
    m = board["matches"][0]
    assert m["kickoff_bj"] == "2026-08-12 00:00" and m["match_date"] == "2026-08-12"


def test_incomplete_board_is_a_failure_not_a_partial_result():
    """不足 14 场必须是解析失败;半份板面比没有板面更危险。"""
    assert parse_board(_page(13), today=date(2026, 8, 11)) is None
    assert parse_board("<html>维护</html>", today=date(2026, 8, 11)) is None


def test_snapshots_match_the_schema_build_prep_reads(tmp_path):
    board = parse_board(_page(), today=date(2026, 8, 11))
    got = write_snapshots(board, tmp_path, slot="afternoon")
    issue_doc = json.loads((tmp_path / "26103-issue.json").read_text("utf-8"))
    odds_doc = json.loads((tmp_path / "26103-odds.json").read_text("utf-8"))
    assert got["n_matches"] == 14 and got["n_priced"] == 14
    assert {"match_no", "home_team", "away_team", "kickoff_bj", "match_date"} <= \
        set(issue_doc["matches"][0])
    # 概率 → 隐含赔率;50% → 2.0
    assert abs(odds_doc["matches"][0]["home"] - 2.0) < 1e-6


def test_revision_slot_writes_a_separate_odds_file(tmp_path):
    board = parse_board(_page(), today=date(2026, 8, 11))
    write_snapshots(board, tmp_path, slot="revision")
    assert (tmp_path / "26103-odds-revision.json").exists()
    assert not (tmp_path / "26103-odds.json").exists()


def test_asian_handicap_is_reference_only(tmp_path):
    """亚盘落盘但只作参考:体彩 hhad 是三路,用亚盘口径读受让腿会高估约 28pp。"""
    board = parse_board(_page(), today=date(2026, 8, 11))
    write_snapshots(board, tmp_path)
    issue_doc = json.loads((tmp_path / "26103-issue.json").read_text("utf-8"))
    odds_doc = json.loads((tmp_path / "26103-odds.json").read_text("utf-8"))
    assert issue_doc["matches"][0]["asian_ref"] == "0.80,平手,0.98"
    assert "asian" not in json.dumps(odds_doc)      # 不进赔率/算术侧


def test_morning_slot_writes_the_baseline_odds_file_build_prep_reads(tmp_path):
    """26123 出生事故:morning 曾写到 -odds-revision.json,而 build_prep 只在
    slot=='revision' 时读那份 → 11:00 早刷新落盘后备料立刻 FileNotFoundError。"""
    board = parse_board(_page(), today=date(2026, 8, 11))
    write_snapshots(board, tmp_path, slot="morning")
    assert (tmp_path / "26103-odds.json").exists()
    assert not (tmp_path / "26103-odds-revision.json").exists()


def test_explicit_issue_fetches_selected_page_and_preserves_source(tmp_path):
    from nutmeg.decision.zucai_insale import fetch_and_write

    urls = []
    page = '<li data-expect="26102">当前第26102期</li>' + _page()
    def fetcher(url):
        urls.append(url)
        return page
    got = fetch_and_write(tmp_path, issue="26103", fetcher=fetcher)
    assert urls == ["https://trade.500.com/sfc/?expect=26103"]
    assert got["issue"] == "26103"
    doc = json.loads(got["issue_path"].read_text())
    assert doc["sources"][0]["url"] == urls[0]


def test_explicit_issue_mismatch_fails_before_writing(tmp_path):
    from nutmeg.decision.zucai_insale import fetch_and_write

    with pytest.raises(ValueError, match="26104"):
        fetch_and_write(tmp_path, issue="26104", fetcher=lambda _: _page())
    assert list(tmp_path.iterdir()) == []
