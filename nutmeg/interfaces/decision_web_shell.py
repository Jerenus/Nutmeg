"""外壳：统一导航 + 空仓登记 + 今天页数据（2026-10-28 产品形态第 6 阶段 Task 6.1）。
只读组装，不产生判断。

导航不做成 Jinja 继承链：`decision/_nav.html` 一段 include，数据来自 Jinja 全局 `shell()`——
`/day` `/issue` `/jczq` 各加一行 include，路由一条不用改。

月度刹车只用 `precheck.month_brake` + `bankroll.status_line`：与期页、竞彩页止损块同一份数，
不再从 `account.month_report` 读第二遍。导航只放一枚紧凑标记，`title` 是 `status_line` 全文。

空仓登记（Jun 10-28 定）写当日 `daily/<日>/passes.jsonl`，不进 `betslips.jsonl`；
见 `day_decisions.append_pass`。
"""
from __future__ import annotations

import re
from datetime import date as _date
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI
from fastapi.responses import JSONResponse

_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_TIERS = ("A", "B", "b", "C", "D")
_LICENSE_TIERS = ("A", "B", "b")
_BRAKE_KEYS = ("net", "effective_net", "stop_loss", "room", "tripped", "pending")
DEFAULT_PASS_REASON = "同意机器默认空仓"
_CHANNEL_OF = {"register_zucai": "zucai", "register_jczq": "jczq"}


def app_now(app: FastAPI) -> datetime:
    """`app.state.now`（可调用或 datetime；测试 / 沙盒回放换钟）；没有就北京时间当前时刻。"""
    from nutmeg.decision.bj_time import BJ

    now = getattr(app.state, "now", None)
    if callable(now):
        now = now()
    return now if isinstance(now, datetime) else datetime.now(BJ)


def _bj_date(now: datetime) -> str:
    from nutmeg.decision.bj_time import BJ

    return (now.astimezone(BJ) if now.tzinfo else now).date().isoformat()


def _yuan(x: float) -> str:
    return f"{'−' if x < 0 else '+'}{abs(x):,.0f}"


def _chip(state: dict) -> str:
    """导航上的紧凑刹车标记：越线写实质与线，未越线只写余量。只是排版，数全来自 month_brake。"""
    if state["tripped"]:
        return f"⛔ 实质 {_yuan(state['effective_net'])} / 线 −{state['stop_loss']:,}"
    return f"余 ¥{state['room']:,.0f}"


def _err(errors: list[str], what: str, exc: Exception) -> None:
    errors.append(f"{what}：{exc!r}"[:200])


def shell_state(data_dir: Path | str, now: datetime) -> dict:
    """{today, issues:[{issue, deadline, close}], brake:{line, chip, net, effective_net, stop_loss,
    room, tripped, pending}|None, issue_brake:{期: issue_brake|None}, drafts:纠正草稿数|None,
    inbox:待签数|None, errors}。每块各自 try。"""
    from nutmeg.decision.bankroll import issue_brake, status_line
    from nutmeg.decision.bj_time import parse_bj
    from nutmeg.decision.lineup_watch import active_issues, issue_doc
    from nutmeg.decision.precheck import month_brake

    data_dir = Path(data_dir)
    today = _bj_date(now)
    errors: list[str] = []
    issues: list[dict] = []
    try:
        for issue in active_issues(data_dir, now):
            doc = issue_doc(data_dir, issue) or {}
            deadline = doc.get("sale_deadline") or doc.get("sale_stop")
            close = parse_bj(deadline)
            issues.append({"issue": issue, "deadline": deadline,
                           "close": close.strftime("%H:%M") if close else None})
    except Exception as exc:  # noqa: BLE001 —— 在售期读不出要看得见，不能读成「今天没期」
        _err(errors, "在售期读取失败", exc)
    brake = None
    try:
        state = month_brake(data_dir, today)
        brake = {k: state.get(k) for k in _BRAKE_KEYS} | {"line": status_line(state),
                                                          "chip": _chip(state)}
    except Exception as exc:  # noqa: BLE001
        _err(errors, "月度刹车读取失败", exc)
    issue_brakes: dict[str, Any] = {}
    for item in issues:
        try:
            issue_brakes[item["issue"]] = issue_brake(data_dir, item["issue"])
        except Exception as exc:  # noqa: BLE001
            _err(errors, f"期 {item['issue']} 刹车档读取失败", exc)
    return {"today": today, "issues": issues, "brake": brake, "issue_brake": issue_brakes,
            "drafts": _drafts(data_dir), "inbox": _pending(data_dir), "errors": errors}


def _drafts(data_dir: Path) -> int | None:
    """导航「纠正」角标：纠正账草稿数（只读 corrections.jsonl）；读不出 → None，不出角标。"""
    from nutmeg.decision.corrections import draft_count

    try:
        return draft_count(data_dir)
    except Exception:  # noqa: BLE001 —— 角标是提示，读不出就不显示，不进 errors
        return None


def _pending(data_dir: Path) -> int | None:
    """导航「待签」角标：收件箱待签数（proposals.jsonl + 闭环开着的 RSI 项，只读）；
    读不出 → None。"""
    from nutmeg.decision.proposals import pending_count

    try:
        return pending_count(data_dir)
    except Exception:  # noqa: BLE001 —— 角标是提示，读不出就不显示，不进 errors
        return None


def _shape(shape, keys: tuple[str, ...]) -> dict | None:
    return {k: shape.get(k) for k in keys} if isinstance(shape, dict) else None


def glance(data_dir: Path, issue: str, deadline: str | None) -> dict:
    """在售期一眼：档计数 / 许可行（A/B/b）/ 主形 / 替代 / 机器默认，全部来自旁车，页面不计数。"""
    from nutmeg.decision.packet_doc import load_packet
    from nutmeg.interfaces.decision_web_issue import _names

    out: dict[str, Any] = {"issue": issue, "deadline": deadline, "default": None,
                           "tiers": dict.fromkeys(_TIERS, 0), "license_rows": [],
                           "main_shape": None, "alternatives": [], "errors": []}
    try:
        packet = load_packet(data_dir, issue)
        out["errors"] += packet["errors"]
        names = _names(data_dir, issue, {})
        for row in packet["rows"]:
            tier = row.get("tier")
            if tier in out["tiers"]:
                out["tiers"][tier] += 1
            if tier in _LICENSE_TIERS:
                out["license_rows"].append({"no": row["no"], "name": names.get(row["no"], ""),
                                            "tier": tier, "k": row.get("k"), "n": row.get("n")})
        out["default"] = packet["default"]
        out["main_shape"] = _shape(packet["main_shape"], ("label", "price", "p", "note"))
        out["alternatives"] = [s for s in (_shape(a, ("label", "role", "price", "p", "note"))
                                           for a in packet["alternatives"]) if s]
    except Exception as exc:  # noqa: BLE001 —— 一期旁车坏了不该拖垮今天页
        _err(out["errors"], f"期 {issue} 旁车读取失败", exc)
    return out


def _linked(row: dict) -> dict:
    """登记类截止补去处链接；还开着的再补空仓登记的目标（done / expired 不再给按钮）。"""
    from nutmeg.decision.day_decisions import decision_href

    target = str(row.get("id") or "").rsplit(":", 1)[-1]
    href = decision_href(row)
    channel = _CHANNEL_OF.get(row.get("kind"))
    pass_target = ({"channel": channel, "target": target}
                   if channel and row.get("status") == "open" else None)
    return {**row, "href": href, "pass_target": pass_target}


def today_extras(data_dir: Path | str, date: str, now: datetime, *,
                 decisions: list[dict] | None = None) -> dict:
    """并进 `/api/day/{date}`：{shell, passes, glance:[…], decisions, errors}。
    今天的待人决定按当前文件现算（`broadcast_decisions`：登记截止 + pass 即时生效）、登记类排前；
    其它日期照报告时写下的 `decisions`。每块各自 try。"""
    from nutmeg.decision.day_decisions import REGISTER_KINDS, broadcast_decisions, read_passes

    data_dir = Path(data_dir)
    errors: list[str] = []
    shell = shell_state(data_dir, now)
    try:
        passes = read_passes(data_dir, date)
    except Exception as exc:  # noqa: BLE001
        passes = []
        _err(errors, "passes.jsonl 读取失败", exc)
    rows = list(decisions or [])
    if date == shell["today"]:
        try:
            rows = broadcast_decisions(data_dir, date, now=now)
        except Exception as exc:  # noqa: BLE001 —— 现算失败退回报告时那份
            _err(errors, "待人决定现算失败", exc)
        rows.sort(key=lambda r: r.get("kind") not in REGISTER_KINDS)
    return {"shell": shell, "passes": passes,
            "glance": [glance(data_dir, i["issue"], i["deadline"]) for i in shell["issues"]],
            "decisions": [_linked(r) for r in rows], "errors": errors}


def _pass_error(data_dir: Path, channel: str, target: str, now: datetime) -> str | None:
    from nutmeg.decision.bj_time import parse_bj
    from nutmeg.decision.lineup_watch import active_issues, issue_doc

    if channel == "zucai":
        if target not in active_issues(data_dir, now):
            return f"期 {target or '（空）'} 不在售"
        doc = issue_doc(data_dir, target) or {}
        deadline = parse_bj(doc.get("sale_deadline") or doc.get("sale_stop"))
        if deadline is not None and deadline <= now:
            return f"期 {target} 已停售（{deadline.strftime('%H:%M')}），空仓登记要在停售前"
        return None
    if channel == "jczq":
        try:
            if _DAY.fullmatch(target):
                _date.fromisoformat(target)
                return None
        except ValueError:
            pass
        return "竞彩空仓的目标须为 YYYY-MM-DD"
    return "channel 须为 zucai 或 jczq"


def register_shell(app: FastAPI, templates) -> None:
    def _shell() -> dict:
        try:
            return shell_state(app.state.data_dir, app_now(app))
        except Exception as exc:  # noqa: BLE001 —— 导航坏了也不能让页面 500
            return {"today": None, "issues": [], "brake": None, "issue_brake": {},
                    "drafts": None, "inbox": None, "errors": [f"外壳读取失败：{exc!r}"[:200]]}

    templates.env.globals["shell"] = _shell

    @app.get("/api/shell")
    def shell_api() -> dict:
        return _shell()

    @app.post("/action/pass")
    def pass_action(payload: dict = Body(...)) -> Any:  # noqa: B008
        """登记空仓：写当日 `daily/<日>/passes.jsonl`（不进 betslips.jsonl）。
        同日同目标只记第一次；理由为空记「同意机器默认空仓」。"""
        from nutmeg.decision.day_decisions import append_pass

        data_dir, now = app.state.data_dir, app_now(app)
        channel = str(payload.get("channel") or "")
        target = str(payload.get("target") or "").strip()
        if (error := _pass_error(data_dir, channel, target, now)) is not None:
            return JSONResponse({"ok": False, "error": error}, status_code=400)
        reason = str(payload.get("reason") or "").strip() or DEFAULT_PASS_REASON
        row, existed = append_pass(data_dir, _bj_date(now), channel=channel, target=target,
                                   reason=reason, at=now.isoformat(timespec="seconds"))
        return {"ok": True, "pass": row, "existed": existed}
