"""期页与竞彩板共用的表单小件：页面报错换人话、倍数、北京今天、过关方式文字。"""
from __future__ import annotations

import re

# precheck.build_slip 的报错是写给命令行的；页面上换成人话（precheck 不改）
_PAGE_WORDS = {"足彩票须给 --faces": "还没选场", "竞彩票须给 --legs-file": "还没选腿"}
_SHORT = re.compile(r"任九至少选 (\d+) 场，实得 (\d+) 场")


def _page_error(message: str) -> str:
    if message in _PAGE_WORDS:
        return _PAGE_WORDS[message]
    if short := _SHORT.fullmatch(message):
        need, got = int(short[1]), int(short[2])
        return f"任九还差 {need - got} 场（已选 {got} 场）"
    return message


def error_text(error: Exception) -> str:
    message = error.args[0] if isinstance(error, KeyError) and error.args else error
    return _page_error(str(message))


def today_bj() -> str:
    from datetime import datetime

    from nutmeg.decision.bj_time import BJ

    return datetime.now(BJ).date().isoformat()


def parse_multiplier(raw) -> int:
    try:
        value = int(1 if raw in (None, "") else raw)
    except (TypeError, ValueError):
        value = 0
    if not 1 <= value <= 99:
        raise ValueError("倍数须为 1–99 的整数")
    return value


def parlay_label(sizes: tuple[int, ...], n_legs: int) -> str:
    if sizes == (1,) and n_legs == 1:
        return "单关"
    return "+".join(f"{m}串1" for m in sizes)
