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

MONTHLY_STOP_LOSS_YUAN = 8000
"""月净值 ≤ −8,000 → 空仓到月底。2026-10-01 主循环提案 3,000（约等于 09-20 以来十天的真实
亏损）；2026-10-11 Jun 改为 6,000——当时 10 月净值 −2,940、距旧线 ¥60、26137 三张刚全灭；
2026-10-18 20:15 Jun 再改为 8,000——当时计入待结票后 10 月净值 −6,165、已破 6,000 线 ¥165。
改数只改这里与宪法 §4。"""

STOP_LOSS_HISTORY = (("2026-10-01", 3000), ("2026-10-11", 6000), ("2026-10-18", 8000))
"""止损线历史（生效日, 线），出处＝设计系列第 ⑦ 条与上面 docstring。最后一项必须等于
`MONTHLY_STOP_LOSS_YUAN`（测试守）；改线时两处一起改。"""


def stop_loss_on(day: str) -> int | None:
    """某日（YYYY-MM-DD）生效的止损线；10-01 之前没有月度止损 → None（账房曲线不画线）。"""
    line = None
    for since, value in STOP_LOSS_HISTORY:
        if str(day)[:10] >= since:
            line = value
    return line


def ticket_day(key: str, data_dir: Path) -> str | None:
    """记分牌 tickets 键 → 归属日（YYYY-MM-DD）：`jczq-YYYYMMDD` 按日期；足彩期号按
    `<issue>-issue.json` 的 sale_deadline；找不到 → None（不猜）。归月 / 归日只有这一处口径。"""
    if key.startswith("jczq-") and len(key) == 13 and key[5:].isdigit():
        return f"{key[5:9]}-{key[9:11]}-{key[11:13]}"
    issue_doc = read_json(Path(data_dir) / "zucai" / f"{key}-issue.json")
    deadline = str((issue_doc or {}).get("sale_deadline") or "")
    return deadline[:10] if len(deadline) >= 10 and deadline[4] == deadline[7] == "-" else None


def ticket_month(key: str, data_dir: Path) -> str | None:
    """记分牌 tickets 键 → 所属月份（`ticket_day` 的前 7 位）；找不到 → None。"""
    day = ticket_day(key, data_dir)
    return day[:7] if day else None


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


def with_pending(summary: dict, pending: dict | None, *,
                 stop_loss: int = MONTHLY_STOP_LOSS_YUAN) -> dict:
    """「实质余量」的唯一推导（2026-10-30 Task 10.1）：已结净值减待结实购票注金（按全损计）。
    `tripped` / `room` 只有这一种口径——预审、各页、当日报告、账房月报都从这里出。"""
    pend = pending or {"n": 0, "stake": 0.0}
    effective = round(summary["net"] - float(pend.get("stake") or 0), 2)
    return {**summary, "stop_loss": stop_loss, "tripped": effective <= -stop_loss,
            "pending": pend, "effective_net": effective,
            "room": round(stop_loss + effective, 2)}


def brake_state(data_dir: Path, today: _date, *, stop_loss: int = MONTHLY_STOP_LOSS_YUAN,
                scoreboard_path: Path | None = None, pending: dict | None = None) -> dict:
    """`pending`＝账房 `pending_ledger` 的 {n, stake}：待结实购票按注金全损计（2026-10-28；
    26149/26150 两期预审报「余 ¥766」实 ¥78，都是只读了已结账）。调用方给，本模块不读登记簿；
    要带登记簿的完整状态用 `precheck.month_brake`。"""
    month = today.strftime("%Y-%m")
    summary = month_net(data_dir, month, scoreboard_path=scoreboard_path)
    return with_pending(summary, pending, stop_loss=stop_loss)


def status_line(state: dict) -> str:
    pend = state.get("pending") or {"n": 0}
    base = (f"本月净 {state['net']:+,.0f}（{len(state['entries'])} 条入账"
            + (f"，待结 {pend['n']} 张 ¥{pend['stake']:,.0f} 按全损计 → 实质 "
               f"{state['effective_net']:+,.0f}" if pend.get("n") else "")
            + f"）／止损线 −{state['stop_loss']:,}")
    if state["tripped"]:
        return f"⛔{base} → 已触发，宪法 §4：空仓到月底"
    line = f"{base} → 还有 ¥{state['room']:,.0f} 空间"
    if state.get("unknown"):
        line += f"（{len(state['unknown'])} 条无法归月未计）"
    return line


ZUCAI_SLIP_CAP_YUAN = 800
"""足彩每期单票复式基准。2026-10-12 Jun 定 400→800（那一刻 10 月净 −2,940、26137/26138 六张全灭）；
两票合计 1,600 与日总帽 2,000 不变。机器初稿帽 `zucai_draft.DEFAULT_CAP` 同数；gym 回放仍用 400。
改数只改这里与宪法 §4。"""

DAILY_CAP_YUAN = 2000
"""日总帽（所有渠道，按下单日 `placed_at` 合计；宪法 §4 原数）。2026-10-12 起入预审：超帽记 ⛔
（退出码 1），登记不受限。"""

BRAKE_SLIP_YUAN = ZUCAI_SLIP_CAP_YUAN // 2
BRAKE_ISSUE_YUAN = 800
"""期级刹车（宪法 §4「连续两期全灭 → 次期减半」）：复式 ≤ 单票基准的一半、
同期合计 ≤ 两票合计 1,600 的一半。"""


def day_cap_check(placed_at: str, stake_yuan: int, *, already_yuan: int = 0,
                  cap: int = DAILY_CAP_YUAN) -> str | None:
    """这张票连同同一下单日已登记实购的（所有渠道）超过日总帽 → 一行 ⛔；否则 None。
    已买多少由调用方从登记簿算（本模块不读登记簿）。"""
    if already_yuan + stake_yuan <= cap:
        return None
    return (f"⛔日帽：{str(placed_at)[:10]} 已买 ¥{already_yuan:,} + 这张 ¥{stake_yuan:,} "
            f"> 日总帽 ¥{cap:,}（宪法 §4）→ 超帽（改票后再审；人坚持就登记并另立裁决）")


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
