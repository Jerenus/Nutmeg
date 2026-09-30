"""月度止损（设计系列第 7 条，2026-10-01）：期级刹车之上的账户级刹车。

宪法 §4 只有「连续两期全灭 → 次期减半或空仓」；26131–26134 十天真实净值约 −¥3,400，
两次行权都是负样本。本模块只做算术：从记分牌 `tickets` 汇总本月净值，与止损线比较，
给 `betslip preview/register` 与 `plan frontier` 打印状态。⛔不阻断登记（登记是事实），
出票阶段由主循环按宪法执行空仓。
"""

from __future__ import annotations

import json
from datetime import date as _date
from pathlib import Path

MONTHLY_STOP_LOSS_YUAN = 3000
"""月净值 ≤ −3,000 → 空仓到月底。数字是主循环 2026-10-01 的提案（约等于 09-20 以来十天的
真实亏损），Jun 未改数前按此执行；改数只改这里与宪法 §4。"""


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def ticket_month(key: str, data_dir: Path) -> str | None:
    """记分牌 tickets 键 → 所属月份：`jczq-YYYYMMDD` 按日期；足彩期号按 `<issue>-issue.json`
    的 sale_deadline；找不到 → None（不猜）。"""
    if key.startswith("jczq-") and len(key) == 13 and key[5:].isdigit():
        return f"{key[5:9]}-{key[9:11]}"
    issue_doc = _read_json(Path(data_dir) / "zucai" / f"{key}-issue.json")
    deadline = str((issue_doc or {}).get("sale_deadline") or "")
    return deadline[:7] if len(deadline) >= 7 and deadline[4] == "-" else None


def month_net(data_dir: Path, month: str, *, scoreboard_path: Path | None = None) -> dict:
    """{month, net, stake, entries:[(key, net)], unknown:[key]}，只算 net 是数字的条目。"""
    sb = _read_json(scoreboard_path or Path(data_dir) / "scoreboard.json", {}) or {}
    entries, unknown = [], []
    net = stake = 0.0
    for key, doc in (sb.get("tickets") or {}).items():
        if not isinstance(doc, dict) or not isinstance(doc.get("net"), int | float):
            continue
        when = ticket_month(key, data_dir)
        if when is None:
            unknown.append(key)
            continue
        if when != month:
            continue
        entries.append((key, float(doc["net"])))
        net += float(doc["net"])
        stake += float(doc.get("stake") or 0)
    return {"month": month, "net": round(net, 2), "stake": round(stake, 2),
            "entries": entries, "unknown": unknown}


def brake_state(data_dir: Path, today: _date, *, stop_loss: int = MONTHLY_STOP_LOSS_YUAN,
                scoreboard_path: Path | None = None) -> dict:
    month = today.strftime("%Y-%m")
    summary = month_net(data_dir, month, scoreboard_path=scoreboard_path)
    tripped = summary["net"] <= -stop_loss
    return {**summary, "stop_loss": stop_loss, "tripped": tripped,
            "room": round(stop_loss + summary["net"], 2)}


def status_line(state: dict) -> str:
    base = (f"本月净 {state['net']:+,.0f}（{len(state['entries'])} 条入账）"
            f"／止损线 −{state['stop_loss']:,}")
    if state["tripped"]:
        return f"⛔{base} → 已触发，宪法 §4：空仓到月底"
    line = f"{base} → 还有 ¥{state['room']:,.0f} 空间"
    if state.get("unknown"):
        line += f"（{len(state['unknown'])} 条无法归月未计）"
    return line
