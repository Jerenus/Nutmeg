# tests/decision/test_ops_status.py
"""今日状态页 —— 每条结局都必须与它的时间证据并排。"""
from datetime import date, datetime

from nutmeg.decision.ops_status import (
    CronStatus,
    PendingItem,
    agent_status,
    describe_calendar,
    format_status,
)

TODAY = date(2026, 9, 17)


def _agent(**kw):
    base = dict(
        label="com.nutmeg.decision.am", schedule="08:00",
        loaded=True, last_exit="0",
    )
    base.update(kw)
    return agent_status(**base)


def test_outcome_prefers_the_newest_dated_log():
    """出生事故 2026-09-17：我 tail 了 err 日志看见 WAF 失败就报告「今天失败」，
    而那条错误是两天前的（文件 mtime 为证）。结局必须跟着时间证据走。"""
    agent = _agent(
        out_text="NUTMEG_OK stage=am run_date=2026-09-17",
        out_at=datetime(2026, 9, 17, 8, 0),
        err_text="NUTMEG_FAILED am degraded: WAF",
        err_at=datetime(2026, 9, 15, 8, 0),
    )
    assert agent.outcome == "成功"
    assert agent.last_at == datetime(2026, 9, 17, 8, 0)


def test_newer_failure_wins_over_older_success():
    agent = _agent(
        out_text="NUTMEG_OK stage=am",
        out_at=datetime(2026, 9, 15, 8, 0),
        err_text="NUTMEG_FAILED am degraded: WAF",
        err_at=datetime(2026, 9, 17, 8, 0),
    )
    assert agent.outcome == "失败"


def test_log_without_a_timestamp_is_never_assumed_to_be_today():
    agent = _agent(out_text="NUTMEG_OK stage=am", out_at=None)
    assert agent.outcome == "无时间证据"
    assert agent.stale_days(TODAY) is None


def test_unmarked_log_falls_back_to_the_exit_code():
    """备料链只打摘要行、不发 NUTMEG_OK —— 如实标「无标记」而不是假装成功。"""
    agent = _agent(
        out_text="  备料 → .nutmeg-data/zucai/26128-prep-afternoon.json",
        out_at=datetime(2026, 9, 17, 14, 0),
    )
    assert agent.outcome == "无标记"


def test_nonzero_exit_without_a_marker_is_a_failure():
    agent = _agent(
        last_exit="1", out_text="traceback…", out_at=datetime(2026, 9, 17, 14, 0)
    )
    assert agent.outcome == "失败"


def test_stale_agent_is_flagged_in_the_page():
    agent = _agent(
        label="com.nutmeg.zucai.prep",
        out_text="NUTMEG_OK", out_at=datetime(2026, 9, 1, 14, 0),
    )
    assert agent.stale_days(TODAY) == 16
    text = format_status([agent], [], [], today=TODAY)
    assert "久未更新（16 天）" in text


def test_unloaded_agent_is_flagged():
    text = format_status(
        [_agent(loaded=False, out_text="NUTMEG_OK", out_at=datetime(2026, 9, 17))],
        [], [], today=TODAY,
    )
    assert "未加载" in text


def test_failing_agent_prints_its_tail():
    text = format_status(
        [_agent(err_text="NUTMEG_FAILED am degraded: Sporttery WAF",
                err_at=datetime(2026, 9, 17, 8, 0))],
        [], [], today=TODAY,
    )
    assert "最近一次失败" in text
    assert "Sporttery WAF" in text


# —— 排期渲染 ————————————————————————————————

def test_long_even_schedule_is_compressed():
    """f2 观察仪一天 96 个时刻；逐条打印会把状态页冲垮（首版实测如此）。"""
    entries = [{"Hour": h, "Minute": m} for h in range(8, 24) for m in (0, 15, 30, 45)]
    assert describe_calendar(entries) == "每 15 分 08:00-23:45"


def test_short_schedule_lists_every_time():
    assert describe_calendar(
        [{"Hour": 8, "Minute": 0}, {"Hour": 19, "Minute": 30}]
    ) == "08:00、19:30"


def test_uneven_schedule_is_not_faked_into_an_interval():
    entries = [{"Hour": 8}, {"Hour": 9}, {"Hour": 11}, {"Hour": 18}]
    assert describe_calendar(entries) == "4 个时刻 08:00-18:00"


def test_missing_schedule_says_so():
    assert describe_calendar(None) == "未声明"


# —— OpenClaw 与待办 ————————————————————————

def test_failing_cron_job_is_alarming_and_shows_its_error():
    """26128 当天实测：早间复盘对齐连败 5 次而没人发现。"""
    job = CronStatus(
        name="Nutmeg-早间复盘对齐", enabled=True, schedule="20 8 * * *",
        last_status="error", consecutive_errors=5,
        last_error="FallbackSummaryError: All models failed (429)",
    )
    assert job.alarming
    text = format_status([], [job], [], today=TODAY)
    assert "⚠️" in text
    assert "All models failed" in text


def test_disabled_failing_job_is_not_alarming():
    job = CronStatus(
        name="Nutmeg-暂定判读讨论", enabled=False, schedule="30 17 * * *",
        last_status="error", consecutive_errors=2, last_error="x",
    )
    assert not job.alarming


def test_pending_items_are_listed():
    text = format_status(
        [], [], [PendingItem("待官方开奖", "26127", "票已登记，official 无该期")],
        today=TODAY,
    )
    assert "26127" in text
    assert "待官方开奖" in text


def test_empty_page_still_states_each_section():
    text = format_status([], [], [], today=TODAY)
    assert "launchd" in text and "OpenClaw" in text and "待办" in text
