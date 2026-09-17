"""今日状态页 —— 定时链路的单一视图。

**出生事故 2026-09-17（我自己踩的）。** 我要判断当天的链路是否健康，于是
`tail` 了 `decision.am.err.log`，看见一条 `NUTMEG_FAILED am degraded:
Sporttery returned no matchInfoList (degraded/WAF response)`，就当场向用户报告
「今天 08:00 跑成功、17:15 又跑出 WAF 降级」。**两句都错**：那条错误是 **9/15** 的
（该文件 mtime 就是 9/15 08:00），17:15 只是当日数据文件的 mtime。

错的根因不是我马虎，是**结构**：`NUTMEG_OK` / `NUTMEG_FAILED` 这两行**不带时间戳**，
out 与 err 是两个文件各自追加，launchd 与 OpenClaw 又各管一半链路——
「今天到底跑了什么、成没成」没有任何一个地方能一眼看全。

所以本模块的第一纪律：**任何一条结论都必须与它的时间证据一起打印**。
日志尾行永远和该文件的 mtime 并排显示；拿不到 mtime 就显示「无时间证据」，
而不是让读的人（包括我）默认它是今天的。

⛔只读。不启停任何任务、不改任何配置、不推送。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

OK_MARK = "NUTMEG_OK"
FAILED_MARK = "NUTMEG_FAILED"
STALE_AFTER_DAYS = 2
"""日更任务超过这么久没有新日志就标记为「久未更新」。"""


@dataclass(frozen=True)
class AgentStatus:
    label: str
    schedule: str
    loaded: bool
    last_exit: str
    out_tail: str
    out_at: datetime | None
    err_tail: str
    err_at: datetime | None

    @property
    def outcome(self) -> str:
        """最近一次可辨认的结局。**只认带时间证据的那一条。**

        备料链（`zucai-prep`）不发 `NUTMEG_OK` 标记，只打摘要行——此时退回
        launchd 记录的退出码，并如实标成「无标记」而不是假装成功。
        """
        candidates = [
            (self.out_at, self.out_tail),
            (self.err_at, self.err_tail),
        ]
        dated = [(at, text) for at, text in candidates if at is not None and text]
        if not dated:
            return "无时间证据"
        _at, text = max(dated, key=lambda pair: pair[0])
        if FAILED_MARK in text:
            return "失败"
        if OK_MARK in text:
            return "成功"
        if self.last_exit == "0":
            return "无标记"
        if self.last_exit not in ("", "0"):
            return "失败"
        return "未知"

    @property
    def last_at(self) -> datetime | None:
        stamps = [at for at in (self.out_at, self.err_at) if at is not None]
        return max(stamps) if stamps else None

    def stale_days(self, today: date) -> int | None:
        if self.last_at is None:
            return None
        return (today - self.last_at.date()).days


@dataclass(frozen=True)
class CronStatus:
    name: str
    enabled: bool
    schedule: str
    last_status: str
    consecutive_errors: int
    last_error: str

    @property
    def alarming(self) -> bool:
        return self.enabled and (
            self.consecutive_errors > 0 or self.last_status == "error"
        )


@dataclass(frozen=True)
class PendingItem:
    kind: str
    subject: str
    detail: str


def _tail_marker(text: str) -> str:
    """取日志里最后一条 NUTMEG_OK / NUTMEG_FAILED 行；没有就取最后一行非空。"""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith(OK_MARK) or line.startswith(FAILED_MARK):
            return line
    return lines[-1] if lines else ""


def agent_status(
    label: str,
    schedule: str,
    *,
    loaded: bool,
    last_exit: str,
    out_text: str = "",
    out_at: datetime | None = None,
    err_text: str = "",
    err_at: datetime | None = None,
) -> AgentStatus:
    return AgentStatus(
        label=label,
        schedule=schedule,
        loaded=loaded,
        last_exit=last_exit,
        out_tail=_tail_marker(out_text),
        out_at=out_at,
        err_tail=_tail_marker(err_text),
        err_at=err_at,
    )


def _minutes(entry: dict) -> int | None:
    hour, minute = entry.get("Hour"), entry.get("Minute", 0)
    if hour is None:
        return None
    return int(hour) * 60 + int(minute)


def describe_calendar(interval: object) -> str:
    """StartCalendarInterval → 人读的时刻。

    等间隔的长数组压成「每 N 分钟 起-止」——f2 观察仪一天 96 个时刻，
    逐条打印会把状态页冲垮（首版实测就是这样）。
    """
    if isinstance(interval, str):
        return interval
    if isinstance(interval, list):
        if len(interval) <= 3:
            return "、".join(describe_calendar(item) for item in interval)
        stamps = sorted(
            m for m in (_minutes(i) for i in interval if isinstance(i, dict))
            if m is not None
        )
        gaps = {b - a for a, b in zip(stamps, stamps[1:], strict=False)}
        span = f"{stamps[0] // 60:02d}:{stamps[0] % 60:02d}-" \
               f"{stamps[-1] // 60:02d}:{stamps[-1] % 60:02d}" if stamps else ""
        if len(gaps) == 1:
            return f"每 {gaps.pop()} 分 {span}"
        return f"{len(interval)} 个时刻 {span}"
    if not isinstance(interval, dict):
        return "未声明"
    hour = interval.get("Hour")
    minute = interval.get("Minute", 0)
    if hour is None:
        return f"每小时 {int(minute):02d} 分"
    return f"{int(hour):02d}:{int(minute):02d}"


def format_status(
    agents: list[AgentStatus],
    jobs: list[CronStatus],
    pending: list[PendingItem],
    *,
    today: date,
) -> str:
    lines = [f"# Nutmeg 今日状态（{today.isoformat()}）", "", "## launchd 定时任务"]
    if not agents:
        lines.append("  （没有已安装的 com.nutmeg.* agent）")
    for agent in agents:
        stale = agent.stale_days(today)
        when = (
            agent.last_at.strftime("%m-%d %H:%M")
            if agent.last_at
            else "无时间证据"
        )
        marks = []
        if not agent.loaded:
            marks.append("未加载")
        if agent.outcome == "失败":
            marks.append("⚠️最近一次失败")
        if stale is not None and stale > STALE_AFTER_DAYS:
            marks.append(f"⚠️久未更新（{stale} 天）")
        lines.append(
            f"  {agent.label:34}{agent.schedule:14}"
            f"{agent.outcome:6}@{when:12}exit={agent.last_exit or '-':4}"
            + ("  " + "／".join(marks) if marks else "")
        )
        if agent.outcome == "失败":
            tail = agent.err_tail or agent.out_tail
            lines.append(f"      {tail[:150]}")
    lines += ["", "## OpenClaw 定时任务"]
    if not jobs:
        lines.append("  （没有 Nutmeg 相关 cron job）")
    for job in jobs:
        state = "启用" if job.enabled else "停用"
        mark = "  ⚠️" if job.alarming else ""
        lines.append(
            f"  {job.name:28}{state:6}{job.schedule:16}"
            f"{job.last_status or '-':8}连败={job.consecutive_errors}{mark}"
        )
        if job.alarming and job.last_error:
            lines.append(f"      {job.last_error[:150]}")
    lines += ["", "## 待办（不会自己消失的）"]
    if not pending:
        lines.append("  （无）")
    for item in pending:
        lines.append(f"  [{item.kind}] {item.subject} — {item.detail}")
    lines += [
        "",
        "> 每条结局都与它的**时间证据**并排打印。NUTMEG_OK/NUTMEG_FAILED 行本身不带",
        "> 时间戳，只看日志尾行会把几天前的失败读成今天的（2026-09-17 我就这么读错过）。",
    ]
    return "\n".join(lines)
