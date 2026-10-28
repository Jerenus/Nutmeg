"""账房页的路由（2026-10-28 产品形态第 7 阶段 Task 7.1）。只读组装，不产生判断。

数全来自现有账：净值 / 渠道 / 待结 / 理由账 / 否决仍买＝`account.month_report`（不跑回放），
曲线＝`account.daily_curve`，逐期 / 逐日＝记分牌 tickets（归月口径只认 `bankroll.ticket_month`），
选择账＝`choice_ledger.build_choices`，桥后改动账＝`bridge.bridge_ledger`。

初稿账（`account.draft_board`）每次跑 gym 回放（沙盒 10 月 16 期 6.4 s），主接口不等它：单独走
`/api/ledger/{月}/draft`，进程内按（月，scoreboard.json 与 betslips.jsonl 的 mtime）缓存。
每块各自 try，失败只进 `errors`，接口不 500。
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import date as _date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse

from nutmeg.interfaces.decision_web_shell import _bj_date, _err, app_now

_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


def _check_month(month: str) -> str:
    if _MONTH.fullmatch(month):
        return month
    raise HTTPException(status_code=400, detail="月份须为 YYYY-MM")


def _json_ok(value: Any) -> bool:
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
        return True
    except (TypeError, ValueError):
        return False


def _block(errors: list[str], what: str, fn: Callable[[], Any], default: Any) -> Any:
    try:
        value = fn()
    except Exception as exc:  # noqa: BLE001 —— 一块账坏了不该拖垮整页
        _err(errors, f"{what}读取失败", exc)
        return default
    if not _json_ok(value):
        errors.append(f"{what}含不可 JSON 化的值，未给出")
        return default
    return value


def _report(data_dir: Path, month: str, errors: list[str]) -> dict:
    """`month_report` 不跑 gym 回放时可 JSON 化的部分（逐键查，坏键进 errors）。规则 v3 主指标
    （竞彩回放 5.8 s）不在账房页上，留在 `nutmeg account month`。"""
    from nutmeg.decision.account import month_report

    full = month_report(data_dir, month, with_draft=False, with_rule_v3=False)
    out = {}
    for key, value in full.items():
        if _json_ok(value):
            out[key] = value
        else:
            errors.append(f"月报 {key} 不可 JSON 化，未给出")
    return out


def _tickets(data_dir: Path, month: str) -> tuple[list[dict], list[dict]]:
    """本月足彩逐期 [{issue, stake, payout, net, slips}] 与竞彩有票日 [{day, stake, net}]。
    归月只认 `month_net`（即 `ticket_month`）挑出的键，金额照抄记分牌。"""
    from nutmeg.decision.bankroll import month_net, ticket_day
    from nutmeg.decision.files import read_json

    tickets = (read_json(Path(data_dir) / "scoreboard.json", {}) or {}).get("tickets") or {}
    issues, days = [], []
    for key, _net in sorted(month_net(data_dir, month)["entries"]):
        doc = tickets.get(key) or {}
        if key.startswith("jczq-"):
            if doc.get("stake"):
                days.append({"day": ticket_day(key, data_dir), "stake": doc.get("stake"),
                             "net": doc.get("net")})
            continue
        slips = doc.get("slips") if isinstance(doc.get("slips"), list) else []
        issues.append({"issue": key, "stake": doc.get("stake"), "payout": doc.get("payout"),
                       "net": doc.get("net"), "slips": len(slips)})
    return issues, days


def _payout(data_dir: Path, month: str) -> dict:
    """本月返奖 {payout, missing:[键]}：`month_net` 入账条目的记分牌 payout 之和（与月报净值同一组
    条目）。投入或返奖不是数字的条目（早期 26129 等）列进 missing，页面据此不出回收率。"""
    from nutmeg.decision.bankroll import month_net
    from nutmeg.decision.files import read_json

    tickets = (read_json(Path(data_dir) / "scoreboard.json", {}) or {}).get("tickets") or {}
    total, missing = 0.0, []
    for key, _net in sorted(month_net(data_dir, month)["entries"]):
        doc = tickets.get(key) or {}
        if not all(isinstance(doc.get(f), int | float) for f in ("stake", "payout")):
            missing.append(key)
            continue
        total += float(doc["payout"])
    return {"payout": round(total, 2), "missing": missing}


def month_issues(data_dir: Path, month: str) -> list[str]:
    """本月的足彩期（`zucai/<期>-issue.json` 的 sale_deadline 归月，含空仓期），升序。"""
    from nutmeg.decision.bankroll import ticket_month

    names = (p.name.split("-")[0] for p in (Path(data_dir) / "zucai").glob("*-issue.json"))
    return sorted(i for i in names if i.isdigit() and ticket_month(i, data_dir) == month)


def ledger_months(data_dir: Path) -> list[str]:
    """记分牌 tickets 出现过的月份，降序。"""
    from nutmeg.decision.bankroll import ticket_month
    from nutmeg.decision.files import read_json

    tickets = (read_json(Path(data_dir) / "scoreboard.json", {}) or {}).get("tickets") or {}
    return sorted({m for k in tickets if (m := ticket_month(k, data_dir))}, reverse=True)


def _bridges(data_dir: Path, issues: list[str], errors: list[str]) -> list[dict]:
    from nutmeg.decision.bridge import bridge_ledger

    out = []
    for issue in issues:
        row = _block(errors, f"期 {issue} 桥后改动账", lambda i=issue: bridge_ledger(data_dir, i),
                     None)
        if row and row.get("walked"):
            out.append({"issue": issue, **row})
    return out


def ledger_payload(data_dir: Path | str, month: str, *, today: _date | None = None) -> dict:
    """{month, months, report, payout, curve, issues, jczq_days, choices, bridges, errors}。
    初稿账不在这里（见 `/api/ledger/{月}/draft`）。"""
    from nutmeg.decision.account import daily_curve
    from nutmeg.decision.choice_ledger import build_choices

    data_dir = Path(data_dir)
    errors: list[str] = []
    issues_in_month = _block(errors, "本月期次", lambda: month_issues(data_dir, month), [])
    tickets = _block(errors, "记分牌逐期", lambda: _tickets(data_dir, month), ([], []))
    choices = {"start": None, "end": None, "rows": []}
    if issues_in_month:
        choices = _block(errors, "选择账", lambda: build_choices(
            data_dir, start=issues_in_month[0], end=issues_in_month[-1]), choices)
    return {
        "month": month,
        "months": _block(errors, "月份列表", lambda: ledger_months(data_dir), []),
        "report": _block(errors, "月报", lambda: _report(data_dir, month, errors), None),
        "payout": _block(errors, "本月返奖", lambda: _payout(data_dir, month), None),
        "curve": _block(errors, "曲线", lambda: daily_curve(data_dir, month, today=today), None),
        "issues": tickets[0], "jczq_days": tickets[1],
        "choices": choices,
        "bridges": _bridges(data_dir, issues_in_month, errors),
        "errors": errors,
    }


def _mtime(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def register_ledger_routes(app: FastAPI, templates) -> None:
    draft_cache: dict[tuple, dict] = {}

    def _today() -> _date:
        return _date.fromisoformat(_bj_date(app_now(app)))

    @app.get("/ledger")
    def ledger_now():
        return RedirectResponse(f"/ledger/{_today().strftime('%Y-%m')}", status_code=307)

    @app.get("/ledger/{month}")
    def ledger_page(request: Request, month: str):
        return templates.TemplateResponse(request, "decision/ledger.html",
                                          {"title": f"账房 {_check_month(month)}",
                                           "month": month})

    @app.get("/api/ledger/{month}")
    def ledger_api(month: str) -> dict:
        return ledger_payload(app.state.data_dir, _check_month(month), today=_today())

    @app.get("/api/ledger/{month}/draft")
    def ledger_draft(month: str) -> dict:
        """初稿账（gym 回放）：同月且记分牌 / 登记簿没动过 → 直接给上次的结果；回放失败不缓存。"""
        from nutmeg.decision.account import draft_board

        data_dir = Path(app.state.data_dir)
        key = (_check_month(month), _mtime(data_dir / "scoreboard.json"),
               _mtime(data_dir / "betslips.jsonl"))
        if key in draft_cache:
            return draft_cache[key]
        try:
            result = draft_board(data_dir, month)
        except Exception as exc:  # noqa: BLE001 —— draft_board 自己兜底；这里再兜一层，不 500
            return {"_error": repr(exc)[:200]}
        if not _json_ok(result):
            return {"_error": "初稿账含不可 JSON 化的值"}
        if "_error" not in result:
            draft_cache[key] = result
        return result
