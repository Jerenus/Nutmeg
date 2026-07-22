"""Kernel-backed daily verbs — the Ontology Kernel v2 go-live seam.

When ``NUTMEG_ONTOLOGY_V2`` is set, the live ``decision-*`` commands route here instead
of the old JSONL ``nutmeg.decision.verbs`` path. This module reuses the same fetch and
result types as the old path, but routes the *store writes* through the kernel's typed
Actions (``market_day_ingest``) rather than the append-only JSONL store.

``decision-am`` is cut over first: it is the data-base verb (ingest market snapshots),
with **no money and no push**. In the kernel the market snapshot *is* the market
baseline, so the old JSONL "backfill shadow" step is unnecessary. close/settle follow as
their own builds. The result is a ``DecisionWorkflowResult`` so the CLI renders it
identically to the old path.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

_MARKET_MAP = {'had': 'md-had', 'hhad': 'md-hhad', 'ttg': 'md-ttg', 'crs': 'md-crs'}
_RESULT_SCORE = {'home': '1-0', 'draw': '0-0', 'away': '0-1'}
_ACCOUNT = 'acct-jczq'


def _default_kernel():
    from nutmeg.config.settings import get_settings
    from nutmeg.ontology.wiring import build_ontology_kernel

    kernel = build_ontology_kernel(get_settings())
    kernel.initialize()
    return kernel


def _ingest_market_day(kernel, run_date: str, output_dir, requested_at: datetime) -> str:
    from nutmeg.decision.market_data import load_sporttery_snapshot
    from nutmeg.ontology.actions.models import ActorRole
    from nutmeg.ontology.ingest.market_day import MarketDayIngestRequest

    sporttery = load_sporttery_snapshot(run_date, output_dir)
    if not sporttery:
        return f"decision-sense-v2 {run_date}: 无 sporttery 快照 — 空盘(合法)"
    bold_path = Path(output_dir) / "daily" / run_date / "bold_odds.json"
    intl = json.loads(bold_path.read_text(encoding="utf-8")) if bold_path.exists() else None

    result = kernel.market_day_ingest.ingest(MarketDayIngestRequest(
        business_date=run_date, sporttery_value=sporttery, intl_value=intl,
        actor_id="source:sporttery", actor_role=ActorRole.CONNECTOR,
        requested_at=requested_at))
    intl_note = "" if intl else " | 无国际欧赔(降级体彩-only)"
    return (f"decision-sense-v2 {run_date}: 入库 {result.matches} 场 Match + "
            f"{result.snapshots} Snapshot（{result.teams} 队）{intl_note}")


def run_decision_am_v2(run_date: str, output_dir, *, kernel=None, fetch: bool = True):
    """am on the kernel: fetch (best-effort) → market_day_ingest. No judgment, no push."""
    from nutmeg.decision.verbs import _compose, _now_iso

    stamp = _now_iso()
    requested_at = datetime.fromisoformat(stamp)
    active_kernel = kernel if kernel is not None else _default_kernel()

    steps: list = []
    if fetch:
        from nutmeg.decision.fetch import fetch_day
        steps.append(("fetch", lambda: fetch_day(run_date, output_dir)))
    steps.append(
        ("sense-v2", lambda: _ingest_market_day(active_kernel, run_date, output_dir, requested_at))
    )
    return _compose("decision-am", run_date, "数据入库(ontology v2 kernel)", steps)


def run_decision_read_v2(reads_file, output_dir, *, kernel=None) -> str:
    """Commit each judged Read payload as a kernel ForecastRevision (no money, no push).

    Read payloads carry kernel match ids + the market string. Old-style factors
    (direction/weight_pp) cannot be replayed as per-outcome deltas, so the belief is
    committed follow-market and the drop is counted, never faked; new-style factors that
    carry a per-outcome ``delta`` reconstructing belief−prior are kept.
    """
    from nutmeg.ontology.actions.forecast_actions import (
        CommitForecastRequest,
        FactorInput,
        ForecastActions,
    )
    from nutmeg.ontology.actions.models import ActorRole
    from nutmeg.ontology.actions.service import ActionService
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

    payloads = json.loads(Path(reads_file).read_text(encoding="utf-8"))
    active_kernel = kernel if kernel is not None else _default_kernel()
    forecasts = ForecastActions(
        ActionService(lambda: OntologyUnitOfWork(active_kernel.engine)))

    committed = 0
    dropped_factors = 0
    rejected: list[str] = []
    for payload in payloads:
        read_id = str(payload.get("read_id", ""))
        market = _MARKET_MAP.get(str(payload.get("market")))
        if market is None:
            rejected.append(f"{read_id}:unmapped_market")
            continue
        prior = payload.get("prior")
        belief = payload.get("belief")
        factors: list[FactorInput] = []
        for factor in payload.get("factors") or []:
            if isinstance(factor, dict) and isinstance(factor.get("delta"), dict):
                factors.append(FactorInput(
                    str(factor["factor_id"]), factor["delta"],
                    factor.get("scope_entity_ids", []), [], factor.get("note")))
            else:
                dropped_factors += 1
        try:
            outcome = forecasts.commit_forecast(CommitForecastRequest(
                match_id=str(payload["match_id"]), market_definition_id=market,
                decision_session_id=None, prior_distribution=prior, belief_distribution=belief,
                factors=factors, commitment_tier=str(payload.get("commitment_tier", "commit")),
                evidence_bundle_id=None, prior_snapshot_id=payload.get("snapshot_id"),
                falsifier=payload.get("falsifier"), actor_id="judge:owner",
                actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key=f"read:{read_id}",
                requested_at=datetime.fromisoformat(payload["made_at"])))
        except (ValueError, KeyError) as error:
            rejected.append(f"{read_id}:{error}")
            continue
        if outcome.status.is_success:
            committed += 1
        else:
            rejected.append(f"{read_id}:{outcome.status.value}")

    msg = f"decision-read-v2: 摄取 {committed}/{len(payloads)} 条 Read(kernel)"
    if dropped_factors:
        msg += f" | 旧式因子丢弃 {dropped_factors}"
    if rejected:
        msg += " | 拒绝: " + "; ".join(rejected)
    return msg


def run_decision_express_v2(legs_file, output_dir, *, kernel=None, made_at=None) -> str:
    """legs.json → kernel Tickets. The ¥400 cap is enforced by ``compose_tickets`` (the
    single authoritative source, reused); the kernel only stores its deterministic
    allocation. Each ticket is idempotency-keyed by its deterministic id, so a re-run
    replays rather than double-books. A leg with no committed Read (or no matching
    selection) is skipped and counted — never a fabricated bet."""
    from nutmeg.decision.express import compose_tickets, load_budget
    from nutmeg.decision.verbs import _now_iso
    from nutmeg.ontology.actions.models import ActorRole
    from nutmeg.ontology.actions.ticket_actions import LegInput
    from nutmeg.ontology.finance.express_flow import ExpressRequest
    from nutmeg.ontology.repository.finance import CashAccountRow
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

    legs = json.loads(Path(legs_file).read_text(encoding="utf-8"))
    if not legs:
        return "decision-express-v2 jczq: 0 票 / 总注 ¥0(空仓合法)"
    active_kernel = kernel if kernel is not None else _default_kernel()
    stamp = made_at or _now_iso()
    requested_at = datetime.fromisoformat(stamp)

    summary = compose_tickets(legs, load_budget(), channel="jczq", made_at=stamp, store=None)

    with OntologyUnitOfWork(active_kernel.engine) as uow:
        uow.finance.ensure_account(
            CashAccountRow(account_id=_ACCOUNT, channel_scope="jczq", currency="CNY",
                           status="active"))

    approved = 0
    total_stake = 0
    skipped: list[str] = []
    for ticket in summary["tickets"]:
        share = ticket["stake_yuan"] / ticket["n_legs"]
        leg_inputs: list = []
        resolvable = True
        for leg in ticket["legs"]:
            market = _MARKET_MAP.get(str(leg.get("market")))
            match_id = str(leg.get("match_id") or "")
            if market is None or not match_id:
                resolvable = False
                break
            with OntologyUnitOfWork(active_kernel.engine) as uow:
                series = uow.decision.ensure_series(match_id, market)
                revision = uow.decision.current_committed_revision(series)
                # Resolve the selection by outcome key only — the handicap/line lives on
                # the bet leg, not on the (line-agnostic) selection definition.
                selection = uow.market.selection_id_for(market, str(leg.get("selection")))
            if revision is None or selection is None:
                resolvable = False
                break
            leg_inputs.append(LegInput(
                match_id=match_id, market_definition_id=market, selection_id=selection,
                forecast_revision_id=revision.forecast_revision_id, bucket=str(ticket["bucket"]),
                stake=share, entry_quote_id=None, line=leg.get("line")))
        if not resolvable:
            skipped.append(str(ticket["ticket_id"]))
            continue
        result = active_kernel.express.approve_for_match(ExpressRequest(
            channel="jczq", account_id=_ACCOUNT, decision_session_id=None, legs=leg_inputs,
            actor_id="judge:owner", actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=f"express:{ticket['ticket_id']}", requested_at=requested_at))
        if result.approved:
            approved += 1
            total_stake += int(ticket["stake_yuan"])

    msg = f"decision-express-v2 jczq: {approved} 票 / 总注 ¥{total_stake}"
    if summary["scaled"]:
        msg += "(超 ¥400 硬顶已缩)"
    if skipped:
        msg += f" | 跳过 {len(skipped)}(无判读/无匹配选项)"
    return msg


def _render_report_markdown(kernel, run_date: str, stage: str) -> str:
    import json as _json

    from nutmeg.analytics.integrity_action import compute_integrity_action_rows

    status = kernel.status()
    cards = {r["scorecard"]: _json.loads(r["metrics_json"])
             for r in compute_integrity_action_rows(kernel.engine)}
    action = cards.get("action_finance", {})
    integrity = cards.get("evidence_integrity", {})
    return "\n".join([
        f"# 决策日报 v2 — {run_date} [{stage}]",
        "",
        f"- 场次 {status.match_count} | 判读(forecast) {status.forecast_count}",
        f"- 票 {int(action.get('ticket_count', 0))} | "
        f"结算 {int(action.get('settlement_count', 0))}",
        f"- 注金 ¥{action.get('stake_total', 0):.0f} | 回款 ¥{action.get('payout_total', 0):.0f}"
        f" | 账户净额 ¥{action.get('ledger_balance', 0):.0f}",
        f"- 覆盖 outcome {integrity.get('outcome_completeness', 0):.0%}"
        f" / closing {integrity.get('closing_coverage', 0):.0%}",
        f"- 校准 scorecards {status.scorecard_count} | factor_estimates "
        f"{status.factor_estimate_count} | proposals {status.lifecycle_proposal_count}",
        "",
        "> 空仓永远合法;本报告只读 kernel,判断永不入脚本。",
    ])


def _report_v2(kernel, run_date: str, output_dir, stage: str, dispatch: bool, dry_run: bool,
               notification_service=None) -> str:
    from nutmeg.notifications.models import NotificationRequest, semantic_fingerprint

    markdown = _render_report_markdown(kernel, run_date, stage)
    report_path = Path(output_dir) / "daily" / run_date / f"decision-report-v2-{run_date}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(markdown, encoding="utf-8")

    note = ""
    if dispatch:
        if notification_service is None:
            from nutmeg.notifications.wiring import build_notification_service
            notification_service = build_notification_service()
        request = NotificationRequest(
            kind=f"decision.{stage}.report.v2", business_key=run_date, stage=stage,
            semantic_fingerprint=semantic_fingerprint({"stage": stage, "markdown": markdown}),
            subject=f"决策日报 v2 {run_date}", caption=f"决策日报 v2 {run_date}", body=markdown,
            metadata={"run_date": run_date, "stage": stage})
        outcome = notification_service.publish(request, dry_run=dry_run)
        note = f" | 推送 {outcome.status.value}"
    return f"decision-report-v2 {run_date} [{stage}]: {report_path.name}{note}"


def _capture_closing_v2(kernel, run_date: str, output_dir, requested_at) -> str:
    """Ingest a closing market snapshot (CLV reference) from a saved closing-odds file.

    Reuses ``market_day_ingest`` with ``snapshot_kind='closing'`` and the closing
    ``bold_odds_closing.json`` as the international odds; sporttery gives match identity.
    Absent closing file → skip (CLV stays empty; Brier/settlement unaffected)."""
    from nutmeg.decision.market_data import load_sporttery_snapshot
    from nutmeg.ontology.actions.models import ActorRole
    from nutmeg.ontology.ingest.market_day import MarketDayIngestRequest

    sporttery = load_sporttery_snapshot(run_date, output_dir)
    if not sporttery:
        return f"decision-capture-closing-v2 {run_date}: 无 sporttery 快照 — 跳过"
    closing_path = Path(output_dir) / "daily" / run_date / "bold_odds_closing.json"
    if not closing_path.exists():
        return f"decision-capture-closing-v2 {run_date}: 无收盘欧赔文件 — 跳过(CLV 空)"
    closing = json.loads(closing_path.read_text(encoding="utf-8"))
    # Same actor as am so the idempotent team/match upserts replay rather than conflict;
    # sporttery_snapshots=False so the closing fair is the intl closing odds only (not the
    # read-time sporttery odds re-marked closing) — the true CLV reference.
    result = kernel.market_day_ingest.ingest(MarketDayIngestRequest(
        business_date=run_date, sporttery_value=sporttery, intl_value=closing,
        actor_id="source:sporttery", actor_role=ActorRole.CONNECTOR, snapshot_kind="closing",
        sporttery_snapshots=False, requested_at=requested_at))
    return f"decision-capture-closing-v2 {run_date}: 收盘快照 {result.snapshots} 条"


def run_decision_close_v2(run_date: str, output_dir, *, kernel=None, dispatch: bool = False,
                          dry_run: bool = True, notification_service=None):
    """close on the kernel: capture-closing (CLV) → express legs → tickets → report."""
    from pathlib import Path as _Path

    from nutmeg.decision.verbs import _compose, _now_iso

    active_kernel = kernel if kernel is not None else _default_kernel()
    requested_at = datetime.fromisoformat(_now_iso())
    legs_path = _Path(output_dir) / "daily" / run_date / "legs.json"

    def _express() -> str:
        if legs_path.exists():
            return run_decision_express_v2(legs_path, output_dir, kernel=active_kernel)
        return f"decision-express-v2: 无 daily/{run_date}/legs.json → 空票(合法)"

    steps = [
        ("capture-closing",
         lambda: _capture_closing_v2(active_kernel, run_date, output_dir, requested_at)),
        ("express", _express),
        ("report", lambda: _report_v2(active_kernel, run_date, output_dir, "close", dispatch,
                                      dry_run, notification_service)),
    ]
    return _compose("decision-close", run_date, "出票(ontology v2 kernel)", steps)


def _reconcile_v2(kernel, run_date: str, output_dir, requested_at) -> str:
    """Record outcomes + settle each match's tickets from a results source. A match with
    no result is skipped (never a pending settlement). Results: daily/<date>/results.json
    ``{kernel_match_id: home|draw|away}``."""
    from nutmeg.ontology.actions.models import ActorRole
    from nutmeg.ontology.finance.reconcile_flow import ReconcileRequest

    results_path = Path(output_dir) / "daily" / run_date / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8")) if results_path.exists() else {}
    settled = 0
    for match_id, result_key in results.items():
        score = _RESULT_SCORE.get(str(result_key))
        if score is None:
            continue
        outcome = kernel.reconcile.settle_match(ReconcileRequest(
            match_id=str(match_id), account_id=_ACCOUNT, score_90=score, status="final",
            source_artifact_retrieval_ids=[], actor_id="system:reconcile",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key=f"reconcile:{run_date}:{match_id}", requested_at=requested_at))
        settled += len(outcome.settled_ticket_ids)
    return f"decision-reconcile-v2 {run_date}: 结算 {len(results)} 场结果 / {settled} 票"


def _calibrate_v2(kernel, stamp: str) -> str:
    from nutmeg.analytics.calibrate_flow import CalibrateRequest

    result = kernel.calibrate.build(CalibrateRequest(as_of=stamp, built_at=stamp))
    return (f"decision-calibrate-v2: {result.status} | scorecards={result.scorecard_count} "
            f"factor_estimates={result.factor_estimate_count} "
            f"proposals={result.lifecycle_proposal_count}")


def run_decision_settle_v2(run_date: str, output_dir, *, kernel=None, dispatch: bool = False,
                           dry_run: bool = True, notification_service=None):
    """settle on the kernel: reconcile (record outcomes + settle tickets) → calibrate → report."""
    from nutmeg.decision.verbs import _compose, _now_iso

    stamp = _now_iso()
    requested_at = datetime.fromisoformat(stamp)
    active_kernel = kernel if kernel is not None else _default_kernel()
    steps = [
        ("reconcile", lambda: _reconcile_v2(active_kernel, run_date, output_dir, requested_at)),
        ("calibrate", lambda: _calibrate_v2(active_kernel, stamp)),
        ("report", lambda: _report_v2(active_kernel, run_date, output_dir, "settle", dispatch,
                                      dry_run, notification_service)),
    ]
    return _compose("decision-settle", run_date, "复盘(结算+校准,ontology v2 kernel)", steps)
