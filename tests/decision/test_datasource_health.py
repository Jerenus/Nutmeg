"""单测数据底座健康度 —— 每项检查都要能在坏的时候变红，否则是安慰剂。"""

from __future__ import annotations

from nutmeg.decision.datasource_health import HealthCheck, render_health, verdict_of


def _c(name: str, ok: bool, detail: str = "", value: str = "") -> HealthCheck:
    return HealthCheck(name=name, ok=ok, detail=detail, value=value)


def test_verdict_is_the_worst_of_its_checks():
    assert verdict_of([_c("a", True), _c("b", True)]) == "healthy"
    assert verdict_of([_c("a", True), _c("b", False)]) == "degraded"
    assert verdict_of([]) == "unknown"


def test_report_marks_each_check_and_names_the_failures():
    report = render_health(
        "2026-09-14",
        [_c("板面可达", True, value="11 场"), _c("欧赔覆盖", False, "缺 3 场", "8/11")],
    )
    assert "degraded" in report
    assert "板面可达" in report and "欧赔覆盖" in report
    assert "缺 3 场" in report


def test_coverage_check_fails_below_the_floor():
    from nutmeg.decision.datasource_health import coverage_check

    assert coverage_check(board=10, covered=10).ok is True
    assert coverage_check(board=10, covered=9).ok is False
    assert coverage_check(board=0, covered=0).ok is False   # 空板面 = 无法确认健康


def test_freshness_check_fails_when_the_snapshot_is_stale():
    from nutmeg.decision.datasource_health import freshness_check

    assert freshness_check(age_minutes=30, limit_minutes=180).ok is True
    assert freshness_check(age_minutes=400, limit_minutes=180).ok is False
    assert freshness_check(age_minutes=None, limit_minutes=180).ok is False


def test_clv_fill_check_fails_when_the_axis_is_starving():
    """CLV 轴饿肚子是可持续性问题：Brier 喂饱而 CLV 空着，因子生死判不准。"""
    from nutmeg.decision.datasource_health import clv_fill_check

    assert clv_fill_check(read_time=100, closing=95).ok is True
    assert clv_fill_check(read_time=2264, closing=122).ok is False   # 换源前的实况
    assert clv_fill_check(read_time=0, closing=0).ok is False


def test_clv_fill_judges_the_window_not_the_lifetime_backlog():
    """全历史比值被换源前的存量主导，据此判定会让这项永远红 —— 永远红=被忽略。

    判定只看近窗口；全历史只作为上下文印出来。
    """
    from nutmeg.decision.datasource_health import clv_fill_check

    check = clv_fill_check(read_time=11, closing=11, lifetime=(2308, 155))
    assert check.ok is True
    assert "2308" in check.detail and "7%" in check.detail


def test_zucai_intl_check_reports_alignment_coverage():
    """足彩链的健康标准与竞彩不同：对不上是常态，不是故障。

    足彩板含竞彩不卖的场（亚运女足、部分葡超/瑞典超），那些场 titan007 板面上根本
    没有。所以这里不要求 100%，只要求「能对上的都对上了」——即已落盘的国际欧赔
    份数等于对齐算法在当期板面上能命中的份数。空则红：一场都对不上意味着对齐坏了。
    """
    from nutmeg.decision.datasource_health import zucai_intl_check

    assert zucai_intl_check(total=14, priced=10).ok is True
    assert zucai_intl_check(total=14, priced=0).ok is False
    assert zucai_intl_check(total=0, priced=0).ok is False
