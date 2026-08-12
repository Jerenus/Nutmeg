# tests/decision/test_zucai_gate.py
from datetime import date, datetime

from nutmeg.decision.zucai_gate import InsaleIssue, gate, parse_insale

# 500.com 在售页把当前期号与官方截止时间都渲染在服务端(2026-08-10 实抓形状)。
_PAGE = (
    '<div class="zcfilter-qih"><ul class="qih-list qih-list2">'
    '<li class="chked" data-expect="26103" ><i class="ico-chk"></i>当前第26103期</li>'
    '</ul></div><span class="zcfilter-endtime">官方售彩截止时间：08-11 22:00</span>'
)


def test_parse_extracts_issue_and_deadline():
    got = parse_insale(_PAGE, today=date(2026, 8, 10))
    assert got == InsaleIssue(issue="26103", deadline=datetime(2026, 8, 11, 22, 0),
                              source_url=got.source_url)


def test_parse_returns_none_when_page_shape_changes():
    """页面改版必须是"探测失败",不能悄悄变成"今日无期"——后者会让备料静默停摆。"""
    assert parse_insale("<html>维护中</html>", today=date(2026, 8, 10)) is None
    assert parse_insale('当前第26103期', today=date(2026, 8, 10)) is None   # 缺截止时间


def test_deadline_year_inferred_across_new_year():
    """MM-DD 补年份:12-31 与 01-02 在跨年那几天都要落对,不能一律用 today.year。"""
    page = _PAGE.replace("08-11 22:00", "01-02 20:00")
    assert parse_insale(page, today=date(2026, 12, 31)).deadline.year == 2027
    page = _PAGE.replace("08-11 22:00", "12-31 20:00")
    assert parse_insale(page, today=date(2027, 1, 1)).deadline.year == 2026


def test_is_sale_day_is_deadline_day_not_draw_day():
    """备料的触发日是**销售截止日**,不是开奖日(26102 截止 8/09、开奖 8/10)。"""
    insale = InsaleIssue("26102", datetime(2026, 8, 9, 20, 0))
    assert insale.is_sale_day(date(2026, 8, 9))
    assert not insale.is_sale_day(date(2026, 8, 10))


def test_gate_speaks_in_all_three_states():
    """三种状态都必须有文案。不说话的任务和死掉的任务从外面看完全一样(7/21 教训)。"""
    sale_day, msg = gate(today=date(2026, 8, 11), fetcher=lambda _u: _PAGE)
    assert sale_day.issue == "26103" and "今日有期" in msg

    _, msg = gate(today=date(2026, 8, 10), fetcher=lambda _u: _PAGE)
    assert "今日无期" in msg and "26103" in msg

    def boom(_url):
        raise RuntimeError("网络挂了")

    insale, msg = gate(today=date(2026, 8, 10), fetcher=boom)
    assert insale is None
    assert "探测失败" in msg and "不可当作" in msg   # 失败 ≠ 无期


def test_hours_left():
    insale = InsaleIssue("26103", datetime(2026, 8, 11, 22, 0))
    assert insale.hours_left(datetime(2026, 8, 11, 14, 0)) == 8.0
