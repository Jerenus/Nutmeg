"""北京时间的唯一定义与解析（2026-10-08 第二轮瘦身 B5；此前 11 处各写一份）。

体彩 / 足彩的时间多是无时区的北京时间字串（`2026-09-19 00:30`、`2026-09-24 19:05`），
与带时区的 now 相减会抛 TypeError（2026-09-24 广播作业实发）。一律在这里补成 +08:00。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

BJ = timezone(timedelta(hours=8))


def aware(value) -> datetime:
    """ISO 8601 或旧格式 `YYYY-MM-DD HH:MM[:SS]` → 带时区的 datetime；无时区按北京时间。

    不合法 → ValueError。"""
    dt = datetime.fromisoformat(str(value).strip().replace(" ", "T"))
    return dt if dt.tzinfo else dt.replace(tzinfo=BJ)


def parse_bj(value) -> datetime | None:
    """同 `aware`，空值 / 不合法 → None（不猜）。"""
    if value is None or not str(value).strip():
        return None
    try:
        return aware(value)
    except ValueError:
        return None


def bj_iso(value) -> str:
    """北京时间字串 → `YYYY-MM-DDTHH:MM:SS+08:00`（带时区的先换算到北京时间）。

    义务的 due_at 与 now 在 repository 里按字串字典序比较，空格形式会排错位。"""
    return aware(value).astimezone(BJ).isoformat(timespec="seconds")
