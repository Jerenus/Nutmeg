"""传统足彩在售期探测 —— 备料定时任务的门控。

只回答两个**事实**问题:当前在售哪一期、销售何时截止。**不含任何判读**——
本模块存在的唯一理由是让 14:00 的备料任务知道"今天要不要干活",以及在无期的
日子仍然能发出心跳(2026-07-21 那次 launchd 静默死亡三周未被发现,根因就是
"不说话的任务"和"死掉的任务"从外面看完全一样)。

源:500.com 胜负彩在售页。页面把当前期号与官方截止时间都渲染在服务端,
形如::

    <li class="chked" data-expect="26103" >...当前第26103期</li>
    <span class="zcfilter-endtime">官方售彩截止时间：08-11 22:00</span>

截止时间只给 MM-DD,年份按"离 today 最近"推断(跨年时 12-31 / 01-02 都能落对)。

上一期已截止、下一期还没开售时(国际比赛日常见),页面仍选中已截止的那期,
截止时间旁写「官方售彩已截止」而不是「售彩截止时间：」::

    <li class="chked" data-expect="26135" >...当前第26135期</li>
    <span ...>&nbsp;&nbsp;10-05 22:00&nbsp;&nbsp;官方售彩已截止</span>

这是合法的「今日无期」(``closed=True``),不是探测失败——2026-10-06 它被当成
探测失败,早备料 exit 1 并推送,而当天只是 26136 未开售。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

INSALE_URL = "https://trade.500.com/sfc/"

_CURRENT_ISSUE_RE = re.compile(r"当前第\s*(\d{5})\s*期")
_CHKED_ISSUE_RE = re.compile(r'class="chked"[^>]*data-expect="(\d{5})"')
_DEADLINE_RE = re.compile(r"售彩截止时间[：:]\s*(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})")
_CLOSED_RE = re.compile(
    r"(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})(?:\s|&nbsp;)*官方售彩已截止")


@dataclass(frozen=True)
class InsaleIssue:
    """当前在售期。deadline 为北京时间的 naive datetime(与体彩口径一致)。"""

    issue: str
    deadline: datetime
    source_url: str = INSALE_URL
    closed: bool = False        # 已截止、下一期未开售:页面上没有在售期

    def is_sale_day(self, today: date) -> bool:
        """今天是不是这一期的销售截止日 = 今天该不该备料。已截止的期永远不是。"""
        return not self.closed and self.deadline.date() == today


def _resolve_year(month: int, day: int, today: date) -> int:
    """MM-DD 补年份:在 today 前后各取一年,选离 today 最近的那个。

    截止日总在 today 当天或未来几天,但 2 月 29 日与跨年边界都可能让"直接用
    today.year"落错,故三候选取最近。
    """
    best = None
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            cand = date(year, month, day)
        except ValueError:      # 2 月 29 日遇平年
            continue
        gap = abs((cand - today).days)
        if best is None or gap < best[0]:
            best = (gap, cand)
    if best is None:
        raise ValueError(f"无法解析截止日期 {month:02d}-{day:02d}")
    return best[1].year


def parse_insale(html: str, *, today: date, source_url: str = INSALE_URL) -> InsaleIssue | None:
    """从在售页 HTML 解析当前期号与截止时间。任一缺失返回 None(视为探测失败)。

    页面写「官方售彩已截止」时返回 ``closed=True`` 的已截止期(合法无期)。
    """
    # The current-sale label remains on explicitly selected future-issue pages.
    m_issue = _CHKED_ISSUE_RE.search(html) or _CURRENT_ISSUE_RE.search(html)
    m_dead = _DEADLINE_RE.search(html)
    m_closed = None if m_dead else _CLOSED_RE.search(html)
    if not m_issue or not (m_dead or m_closed):
        return None
    month, day, hour, minute = (int(x) for x in (m_dead or m_closed).groups())
    year = _resolve_year(month, day, today)
    return InsaleIssue(
        issue=m_issue.group(1),
        deadline=datetime(year, month, day, hour, minute),
        source_url=source_url,
        closed=m_closed is not None,
    )


def _default_fetcher(url: str) -> str:
    from nutmeg.data.http import get_text

    # 500.com 是 GB 系编码,charset 声明不总可靠 —— 显式解码,坏字节不致命。
    return get_text(url, encodings=("gb18030",), errors="ignore")


def detect_insale(*, today: date | None = None, fetcher=None,
                  source_url: str = INSALE_URL) -> InsaleIssue | None:
    """抓在售页并解析。网络或解析失败一律返回 None,由调用方决定如何告警。"""
    today = today or date.today()
    fetcher = fetcher or _default_fetcher
    try:
        html = fetcher(source_url)
    except Exception:           # noqa: BLE001 — 探测失败不该让定时任务崩,但必须可见
        return None
    return parse_insale(html, today=today, source_url=source_url)


def gate(*, today: date | None = None, fetcher=None) -> tuple[InsaleIssue | None, str]:
    """门控主入口。返回 (在售期或 None, 人读的一行状态)。

    四种状态各自有明确文案,**没有一种是沉默**:
      - 今天是截止日        → 该备料
      - 今天不是截止日      → 心跳:下一期何时截止
      - 上一期已截止、下一期未开售 → 心跳:今日无期(合法,不是探测失败)
      - 探测失败            → 心跳:探测失败(不可当作"今日无期")
    """
    today = today or date.today()
    insale = detect_insale(today=today, fetcher=fetcher)
    if insale is None:
        return None, "⚠️ 在售期探测失败(网络或页面结构变化)——不可当作『今日无期』,请人工确认"
    if insale.closed:
        return insale, (f"今日无期。{insale.issue} 已截止"
                        f"({insale.deadline:%Y-%m-%d %H:%M}),下一期未开售")
    if insale.is_sale_day(today):
        return insale, (f"今日有期 {insale.issue},截止 "
                        f"{insale.deadline:%Y-%m-%d %H:%M}")
    return insale, (f"今日无期。下一期 {insale.issue} 截止 "
                    f"{insale.deadline:%Y-%m-%d %H:%M}"
                    f"({(insale.deadline.date() - today).days} 天后)")


