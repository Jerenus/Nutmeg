"""月度止损（设计系列第 7 条，2026-10-01）：期级刹车之上的账户级刹车。

宪法 §4 只有「连续两期全灭 → 次期减半或空仓」；26131–26134 十天真实净值约 −¥3,400，
两次行权都是负样本。本模块只做算术：从记分牌 `tickets` 汇总本月净值，与止损线比较，
给 `betslip preview/register` 打印状态。⛔不阻断登记（登记是事实）；2026-10-06 起止损触发
与期级刹车超帽在**预审**记否决（退出码 1），登记照收、审票结论随票入账。
"""

from __future__ import annotations

from datetime import date as _date
from pathlib import Path

from nutmeg.decision.files import read_json

MONTHLY_STOP_LOSS_YUAN = 3000
"""月净值 ≤ −3,000 → 空仓到月底。数字是主循环 2026-10-01 的提案（约等于 09-20 以来十天的
真实亏损），Jun 未改数前按此执行；改数只改这里与宪法 §4。"""


def ticket_month(key: str, data_dir: Path) -> str | None:
    """记分牌 tickets 键 → 所属月份：`jczq-YYYYMMDD` 按日期；足彩期号按 `<issue>-issue.json`
    的 sale_deadline；找不到 → None（不猜）。"""
    if key.startswith("jczq-") and len(key) == 13 and key[5:].isdigit():
        return f"{key[5:9]}-{key[9:11]}"
    issue_doc = read_json(Path(data_dir) / "zucai" / f"{key}-issue.json")
    deadline = str((issue_doc or {}).get("sale_deadline") or "")
    return deadline[:7] if len(deadline) >= 7 and deadline[4] == "-" else None


def month_net(data_dir: Path, month: str, *, scoreboard_path: Path | None = None) -> dict:
    """{month, net, stake, entries:[(key, net)], unknown:[key]}，只算 net 是数字的条目。"""
    sb = read_json(scoreboard_path or Path(data_dir) / "scoreboard.json", {}) or {}
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


BRAKE_SLIP_YUAN = 200
BRAKE_ISSUE_YUAN = 800
"""期级刹车（宪法 §4「连续两期全灭 → 次期减半」）：复式 ≤¥200、同期合计 ≤¥800（帽减半）。"""


def _wiped(doc: dict) -> bool | None:
    """记分牌一期：全灭 True / 有派奖 False / 缺数 None（不猜）。"""
    payout, stake, net = doc.get("payout"), doc.get("stake"), doc.get("net")
    if isinstance(payout, int | float):
        return payout == 0
    if isinstance(stake, int | float) and isinstance(net, int | float) and stake > 0:
        return net == -stake
    return None


def issue_brake(data_dir: Path, issue: str, *, scoreboard_path: Path | None = None) -> dict | None:
    """这一期要不要按刹车档（2026-10-06：从「只在初稿里给个刹车档」改成预审否决）。

    两个来源：① 记分牌里本期之前**有下注**的最近两期都全灭；② 记分牌 `adjudications` 里
    针对本期的事前承诺（`caps.issue == 本期`，可带 slip_yuan / issue_yuan 覆盖默认减半）。
    → {"reason", "slip_yuan", "issue_yuan"} 或 None。"""
    sb = read_json(scoreboard_path or Path(data_dir) / "scoreboard.json", {}) or {}
    for key, adj in (sb.get("adjudications") or {}).items():
        caps = adj.get("caps") if isinstance(adj, dict) else None
        if isinstance(caps, dict) and str(caps.get("issue")) == str(issue):
            return {"reason": f"事前承诺 {key}",
                    "slip_yuan": int(caps.get("slip_yuan") or BRAKE_SLIP_YUAN),
                    "issue_yuan": int(caps.get("issue_yuan") or BRAKE_ISSUE_YUAN)}
    tickets = sb.get("tickets") or {}
    prior = sorted((k for k, d in tickets.items()
                    if k.isdigit() and k < str(issue) and isinstance(d, dict)
                    and ((d.get("stake") or 0) > 0 or (d.get("net") or 0) < 0)), reverse=True)[:2]
    if len(prior) == 2 and all(_wiped(tickets[k]) is True for k in prior):
        return {"reason": f"连续两期全灭（{prior[1]}、{prior[0]}）",
                "slip_yuan": BRAKE_SLIP_YUAN, "issue_yuan": BRAKE_ISSUE_YUAN}
    return None


def brake_check(data_dir: Path, issue: str, stake_yuan: int, *,
                already_yuan: int = 0) -> str | None:
    """本期刹车生效且这张票（或连同本期已买的）超帽 → 一行 ⛔；否则 None。"""
    brake = issue_brake(data_dir, issue) if issue else None
    if not brake:
        return None
    over_slip = stake_yuan > brake["slip_yuan"]
    over_issue = already_yuan + stake_yuan > brake["issue_yuan"]
    if not (over_slip or over_issue):
        return None
    return (f"⛔刹车：{brake['reason']} → 本期复式 ≤¥{brake['slip_yuan']}、合计 "
            f"≤¥{brake['issue_yuan']}；这张 ¥{stake_yuan:,}，连同本期已买 ¥{already_yuan:,} "
            "→ 超帽（改票后再审；人坚持就登记并另立裁决）")
