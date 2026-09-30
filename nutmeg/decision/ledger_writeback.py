"""实票入账到本体（Jun 2026-10-01，设计系列第 3 条「真实票路径」）。

真票只走 500 app + 分享卡登记，`betslip register` 因此是「没入账=没打」的唯一落点：
登记一张竞彩实票时，把它展开成注（每注一条 Ticket），用 express 同一条内核路径写入。
- 腿的身份来自当日 `jczq-legs-base.json`（场次代码 → match_id），不猜；
- 每注每腿一个选项，赔率取该选项自己的赔率；没有已提交 Read、没有选项定义、没有真实赔率的注
  跳过并计数——**绝不伪造**；
- 混合过关（如 2,3）目前不展开，如实报 `unsupported`；
- 内核不可用时登记照常成立，结果里写明 `error`：账本是事实源，内核是镜像。
足彩实票不进内核（内核市场是竞彩口径），其账在 `betslips.jsonl` 与 `scoreboard.json`。
"""

from __future__ import annotations

import json
from datetime import datetime
from itertools import product
from pathlib import Path

from nutmeg.decision.betslip import PRICE_PER_NOTE, BetSlip, normalize_selection

_MARKETS = {"had": "md-had", "hhad": "md-hhad", "ttg": "md-ttg", "crs": "md-crs"}
_ACCOUNT = "acct-jczq"


def code_to_match_id(data_dir: Path, day: str) -> dict[str, str]:
    path = Path(data_dir) / "jczq" / "daily" / day / "jczq-legs-base.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {code: str(leg.get("match_id")) for code, leg in (doc.get("legs") or {}).items()
            if leg.get("match_id")}


def expand_notes(slip: BetSlip) -> list[list[tuple[object, str, float | None]]]:
    """N 串 1 的复式票 → 每注 [(腿, 选项, 该选项赔率)]；混合过关返回空列表。"""
    sizes = tuple(slip.combo_sizes or ())
    if sizes not in ((), (len(slip.legs),)):
        return []
    choices = []
    for leg in slip.legs:
        options = []
        for index, selection in enumerate(leg.selections):
            odds = float(leg.odds[index]) if index < len(leg.odds) else None
            options.append((leg, str(selection), odds))
        choices.append(options)
    return [list(note) for note in product(*choices)]


def writeback_jczq_slip(slip: BetSlip, *, data_dir: Path, kernel=None,
                        requested_at: datetime | None = None) -> dict:
    """一张竞彩实票 → 内核 Ticket（每注一条）。返回入账计数与跳过原因。"""
    from nutmeg.ontology.actions.models import ActorRole
    from nutmeg.ontology.actions.ticket_actions import LegInput
    from nutmeg.ontology.finance.express_flow import ExpressRequest
    from nutmeg.ontology.repository.finance import CashAccountRow
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

    if slip.channel != "jczq":
        return {"status": "not_applicable", "reason": "足彩实票不进内核，账在 betslips/scoreboard"}
    notes = expand_notes(slip)
    if not notes:
        return {"status": "unsupported", "reason": "混合过关暂不展开", "notes": 0}
    if kernel is None:
        from nutmeg.decision.ontology_adapter import _default_kernel

        kernel = _default_kernel()
    when = requested_at or datetime.now().astimezone()
    match_of = code_to_match_id(data_dir, str(slip.placed_at)[:10])
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.finance.ensure_account(CashAccountRow(
            account_id=_ACCOUNT, channel_scope="jczq", currency="CNY", status="active"))
    stake_per_note = float(PRICE_PER_NOTE * slip.multiplier)
    booked = 0
    skipped: dict[str, int] = {}
    for index, note in enumerate(notes):
        leg_inputs: list = []
        reason = None
        for leg, selection, odds in note:
            market = _MARKETS.get(str(leg.market))
            match_id = match_of.get(leg.key)
            outcome = normalize_selection(leg.market, selection) or selection
            if market is None or not match_id:
                reason = "no_match_identity"
                break
            if odds is None or odds <= 1.0:
                reason = "no_price"
                break
            with OntologyUnitOfWork(kernel.engine) as uow:
                series = uow.decision.ensure_series(match_id, market)
                revision = uow.decision.current_committed_revision(series)
                selection_id = uow.market.selection_id_for(market, str(outcome))
            if revision is None:
                reason = "no_committed_read"
                break
            if selection_id is None:
                reason = "no_selection"
                break
            leg_inputs.append(LegInput(
                match_id=match_id, market_definition_id=market, selection_id=selection_id,
                forecast_revision_id=revision.forecast_revision_id, bucket="real",
                stake=stake_per_note / len(note), entry_odds=odds, entry_quote_id=None,
                line=None if leg.line is None else str(leg.line)))
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        result = kernel.express.approve_for_match(ExpressRequest(
            channel="jczq", account_id=_ACCOUNT, decision_session_id=None, legs=leg_inputs,
            actor_id="judge:owner", actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=f"betslip:{slip.slip_id}:{index}", requested_at=when))
        if result.approved:
            booked += 1
        else:
            skipped["not_approved"] = skipped.get("not_approved", 0) + 1
    return {"status": "booked" if booked else "skipped", "notes": len(notes),
            "booked": booked, "stake_booked": round(booked * stake_per_note, 2),
            "skipped": skipped}


def summary_line(result: dict) -> str:
    status = result.get("status")
    if status == "not_applicable":
        return "内核：足彩不入内核账（账在 betslips/scoreboard）"
    if status == "unsupported":
        return "⚠️内核：混合过关暂不展开，本票未入内核账"
    if status == "error":
        return f"⚠️内核入账失败：{result.get('error')}（登记已成立，内核未镜像）"
    skipped = ", ".join(f"{k}×{v}" for k, v in (result.get("skipped") or {}).items())
    return (f"内核：入账 {result.get('booked', 0)}/{result.get('notes', 0)} 注"
            f"（¥{result.get('stake_booked', 0):,.0f}）" + (f"｜跳过 {skipped}" if skipped else ""))
