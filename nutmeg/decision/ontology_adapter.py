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
from datetime import UTC, datetime
from pathlib import Path

_MARKET_MAP = {"had": "md-had", "hhad": "md-hhad", "ttg": "md-ttg", "crs": "md-crs"}
_RESULT_SCORE = {"home": "1-0", "draw": "0-0", "away": "0-1"}
_ACCOUNT = "acct-jczq"


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

    result = kernel.market_day_ingest.ingest(
        MarketDayIngestRequest(
            business_date=run_date,
            sporttery_value=sporttery,
            intl_value=intl,
            actor_id="source:sporttery",
            actor_role=ActorRole.CONNECTOR,
            requested_at=requested_at,
        )
    )
    intl_note = "" if intl else " | 无国际欧赔(降级体彩-only)"
    return (
        f"decision-sense-v2 {run_date}: 入库 {result.matches} 场 Match + "
        f"{result.snapshots} Snapshot（{result.teams} 队）{intl_note}"
    )


def _ingest_zucai_issue(kernel, issue: str, zucai_dir, requested_at: datetime) -> str:
    """zucai 感知 on the kernel: 复用老 loader 读已存快照 → typed Actions 入库。

    与老路径同一 canonical 身份函数(canonical_match_id);源快照缺失 → 可见降级不抛断。"""
    from nutmeg.decision.sense_zucai import _default_loader
    from nutmeg.ontology.actions.entity_actions import EntityActions
    from nutmeg.ontology.actions.market_actions import MarketActions
    from nutmeg.ontology.actions.match_actions import MatchActions
    from nutmeg.ontology.actions.models import ActorRole
    from nutmeg.ontology.actions.service import ActionService
    from nutmeg.ontology.ingest.zucai_issue import (
        ZucaiIssueIngestRequest,
        ZucaiIssueIngestService,
        ZucaiRow,
    )
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

    try:
        matches, odds, dates = _default_loader(issue, zucai_dir)
    except FileNotFoundError as exc:
        return f"decision-sense-zucai-v2 {issue}: 源快照缺失 — {exc}"

    service_factory = ActionService(lambda: OntologyUnitOfWork(kernel.engine))
    service = ZucaiIssueIngestService(
        entity_actions=EntityActions(service_factory),
        match_actions=MatchActions(service_factory),
        market_actions=MarketActions(service_factory),
    )
    result = service.ingest(
        ZucaiIssueIngestRequest(
            issue=issue,
            rows=tuple(
                ZucaiRow(
                    match_no=m.match_no,
                    home=m.home_team,
                    away=m.away_team,
                    competition=m.competition,
                    match_date=dates.get(m.match_no),
                    odds=odds.get(m.match_no),
                )
                for m in matches
            ),
            actor_id="source:zucai",
            actor_role=ActorRole.CONNECTOR,
            requested_at=requested_at,
        )
    )
    skipped_note = f" | 跳过 {len(result.skipped)}" if result.skipped else ""
    return (
        f"decision-sense-zucai-v2 {issue}: 入库 {result.matches} 场 Match + "
        f"{result.snapshots} Snapshot（{result.teams} 队）{skipped_note}"
    )


def run_decision_am_v2(
    run_date: str,
    output_dir,
    *,
    kernel=None,
    fetch: bool = True,
    issue: str | None = None,
    zucai_dir=None,
):
    """am on the kernel: fetch (best-effort) → market_day_ingest (+可选 zucai 感知)。

    No judgment, no push. ``issue`` 给出时追加 zucai issue 入库(足彩泳道,与老路径同参数)。"""
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
    if issue:
        zdir = Path(zucai_dir) if zucai_dir is not None else Path(".nutmeg-data/zucai")
        steps.append(
            (
                "sense-zucai-v2",
                lambda: _ingest_zucai_issue(active_kernel, issue, zdir, requested_at),
            )
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
    forecasts = ForecastActions(ActionService(lambda: OntologyUnitOfWork(active_kernel.engine)))

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
                factors.append(
                    FactorInput(
                        str(factor["factor_id"]),
                        factor["delta"],
                        factor.get("scope_entity_ids", []),
                        [],
                        factor.get("note"),
                    )
                )
            else:
                dropped_factors += 1
        try:
            outcome = forecasts.commit_forecast(
                CommitForecastRequest(
                    match_id=str(payload["match_id"]),
                    market_definition_id=market,
                    decision_session_id=None,
                    prior_distribution=prior,
                    belief_distribution=belief,
                    factors=factors,
                    commitment_tier=str(payload.get("commitment_tier", "commit")),
                    evidence_bundle_id=None,
                    prior_snapshot_id=payload.get("snapshot_id"),
                    falsifier=payload.get("falsifier"),
                    actor_id="judge:owner",
                    actor_role=ActorRole.JUDGE_OPERATOR,
                    idempotency_key=f"read:{read_id}",
                    requested_at=datetime.fromisoformat(payload["made_at"]),
                )
            )
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
            CashAccountRow(
                account_id=_ACCOUNT, channel_scope="jczq", currency="CNY", status="active"
            )
        )

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
            odds = leg.get("odds")
            has_price = isinstance(odds, int | float) and float(odds) > 1.0
            if revision is None or selection is None or not has_price:
                resolvable = False  # no committed Read / no selection / no real price
                break
            leg_inputs.append(
                LegInput(
                    match_id=match_id,
                    market_definition_id=market,
                    selection_id=selection,
                    forecast_revision_id=revision.forecast_revision_id,
                    bucket=str(ticket["bucket"]),
                    stake=share,
                    entry_odds=float(odds),
                    entry_quote_id=None,
                    line=leg.get("line"),
                )
            )
        if not resolvable:
            skipped.append(str(ticket["ticket_id"]))
            continue
        result = active_kernel.express.approve_for_match(
            ExpressRequest(
                channel="jczq",
                account_id=_ACCOUNT,
                decision_session_id=None,
                legs=leg_inputs,
                actor_id="judge:owner",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key=f"express:{ticket['ticket_id']}",
                requested_at=requested_at,
            )
        )
        if result.approved:
            approved += 1
            total_stake += int(ticket["stake_yuan"])

    msg = f"decision-express-v2 jczq: {approved} 票 / 总注 ¥{total_stake}"
    if summary["scaled"]:
        msg += "(超 ¥400 硬顶已缩)"
    if skipped:
        msg += f" | 跳过 {len(skipped)}(无判读/无匹配选项/无赔)"
    return msg


def _render_report_markdown(kernel, run_date: str, stage: str) -> str:
    import json as _json

    from sqlalchemy import func, select

    from nutmeg.analytics.integrity_action import compute_integrity_action_rows
    from nutmeg.ontology.repository import schema_finance as sf

    status = kernel.status()
    cards = {
        r["scorecard"]: _json.loads(r["metrics_json"])
        for r in compute_integrity_action_rows(kernel.engine)
    }
    action = cards.get("action_finance", {})
    integrity = cards.get("evidence_integrity", {})
    day_prefix = f"{run_date}%"
    with kernel.engine.connect() as connection:
        day_ticket_count = connection.execute(
            select(func.count()).select_from(sf.tickets).where(
                sf.tickets.c.approved_at.like(day_prefix)
            )
        ).scalar_one()
        day_settlement_count = connection.execute(
            select(func.count()).select_from(sf.ticket_settlements).where(
                sf.ticket_settlements.c.settled_at.like(day_prefix)
            )
        ).scalar_one()
        day_transactions = dict(
            connection.execute(
                select(sf.cash_transactions.c.kind, func.sum(sf.cash_transactions.c.amount))
                .where(sf.cash_transactions.c.occurred_at.like(day_prefix))
                .group_by(sf.cash_transactions.c.kind)
            ).all()
        )
    day_stake = abs(float(day_transactions.get("stake", 0.0)))
    day_payout = float(day_transactions.get("payout", 0.0))
    return "\n".join(
        [
            f"# 决策日报 v2 — {run_date} [{stage}]",
            "",
            f"- 场次 {status.match_count} | 判读(forecast) {status.forecast_count}",
            f"- 当日票 {day_ticket_count} | 当日结算 {day_settlement_count}",
            f"- 当日注金 ¥{day_stake:.0f} | 当日回款 ¥{day_payout:.0f}"
            f" | 累计账户净额 ¥{action.get('ledger_balance', 0):.0f}",
            f"- 覆盖 outcome {integrity.get('outcome_completeness', 0):.0%}"
            f" / closing {integrity.get('closing_coverage', 0):.0%}",
            f"- 校准 scorecards {status.scorecard_count} | factor_estimates "
            f"{status.factor_estimate_count} | proposals {status.lifecycle_proposal_count}",
            "",
            "> 空仓永远合法;本报告只读 kernel,判断永不入脚本。",
        ]
    )


def _report_v2(
    kernel,
    run_date: str,
    output_dir,
    stage: str,
    dispatch: bool,
    dry_run: bool,
    notification_service=None,
) -> str:
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
            kind=f"decision.{stage}.report.v2",
            business_key=run_date,
            stage=stage,
            semantic_fingerprint=semantic_fingerprint({"stage": stage, "markdown": markdown}),
            subject=f"决策日报 v2 {run_date}",
            caption=f"决策日报 v2 {run_date}",
            body=markdown,
            metadata={"run_date": run_date, "stage": stage},
        )
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
    result = kernel.market_day_ingest.ingest(
        MarketDayIngestRequest(
            business_date=run_date,
            sporttery_value=sporttery,
            intl_value=closing,
            actor_id="source:sporttery",
            actor_role=ActorRole.CONNECTOR,
            snapshot_kind="closing",
            sporttery_snapshots=False,
            requested_at=requested_at,
        )
    )
    return f"decision-capture-closing-v2 {run_date}: 收盘快照 {result.snapshots} 条"


def run_decision_close_v2(
    run_date: str,
    output_dir,
    *,
    kernel=None,
    dispatch: bool = False,
    dry_run: bool = True,
    notification_service=None,
):
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
        (
            "capture-closing",
            lambda: _capture_closing_v2(active_kernel, run_date, output_dir, requested_at),
        ),
        ("express", _express),
        (
            "report",
            lambda: _report_v2(
                active_kernel,
                run_date,
                output_dir,
                "close",
                dispatch,
                dry_run,
                notification_service,
            ),
        ),
    ]
    return _compose("decision-close", run_date, "出票(ontology v2 kernel)", steps)


def _normalize_score(value: object) -> str | None:
    """ "2-1"/"2:1"/"2：1" → "2-1"; home/draw/away → canonical score; else None."""
    text = str(value or "").strip().replace("：", ":").replace(":", "-")
    parts = text.split("-")
    if len(parts) == 2 and all(p.isdigit() for p in parts):
        return f"{int(parts[0])}-{int(parts[1])}"
    return _RESULT_SCORE.get(str(value))


# A match cannot be final before kickoff + regulation + half-time + stoppage. Any
# auto-fetched "result" arriving earlier is poison (e.g. okooo's 开奖 page falls back to
# the latest *completed* day when the requested date has no results yet, and its row
# numbers collide with today's 竞彩号 — observed live on 2026-07-22).
_MIN_MATCH_MINUTES = 110


def _kickoff_passed(scheduled_at: str | None, now: datetime) -> bool:
    """True only when the match could physically be finished by ``now``."""
    if not scheduled_at:
        return False  # no kickoff on record → never auto-settle (manual override only)
    try:
        kickoff = datetime.fromisoformat(scheduled_at)
    except ValueError:
        return False
    if kickoff.tzinfo is None:
        return False
    return (now - kickoff).total_seconds() >= _MIN_MATCH_MINUTES * 60


def _results_v2(
    kernel, run_date: str, output_dir, live_fetcher=None, now: datetime | None = None
) -> dict[str, str]:
    """Final scores keyed by kernel match id: ``{match_id: "2-1"}``.

    ``daily/<date>/results.json`` (manual override, score or home/draw/away values) wins
    and is trusted as an explicit human action; otherwise fetch okooo live results and
    map 竞彩号 → sporttery matchId (saved snapshot) → kernel match. The auto path accepts
    a score **only for a match whose kickoff + 110min has passed** — a source claiming a
    result for an unplayed match is poison, not truth. Unfinished/unmappable matches are
    skipped — a missing result is never a pending settlement.
    """
    from nutmeg.decision.market_data import load_sporttery_snapshot
    from nutmeg.ontology.identity.models import EntityType
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

    results_path = Path(output_dir) / "daily" / run_date / "results.json"
    if results_path.exists():
        manual = json.loads(results_path.read_text(encoding="utf-8"))
        return {
            str(match_id): score
            for match_id, value in manual.items()
            if (score := _normalize_score(value)) is not None
        }

    if live_fetcher is None:
        from nutmeg.services.jczq_results import OkoooJczqResultProvider

        live_fetcher = OkoooJczqResultProvider().fetch_results
    try:
        okooo = live_fetcher(run_date) or {}
    except Exception:  # noqa: BLE001 — 抓不到赛果 → 全部跳过(不产 pending)
        return {}

    sporttery = load_sporttery_snapshot(run_date, output_dir) or {}
    no_to_external: dict[str, str] = {}
    for day in sporttery.get("matchInfoList") or []:
        for sub in day.get("subMatchList") or []:
            if sub.get("matchNumStr") and sub.get("matchId") is not None:
                no_to_external[str(sub["matchNumStr"])] = str(sub["matchId"])

    current_time = now if now is not None else datetime.now(UTC)
    results: dict[str, str] = {}
    with OntologyUnitOfWork(kernel.engine) as uow:
        for match_no, row in okooo.items():
            score = _normalize_score((row or {}).get("score"))
            external = no_to_external.get(str(match_no))
            if score is None or external is None:
                continue  # 未终局/未对上 → 跳过
            kernel_match = uow.identity.entity_by_external_id(
                EntityType.MATCH, provider="sporttery", external_id=external
            )
            if kernel_match is None:
                continue
            revision = uow.identity.current_match_revision(kernel_match)
            if not _kickoff_passed(revision.scheduled_at, current_time):
                continue  # 开球+110min 未到 → 物理上不可能终局,拒收(毒数据防线)
            results[kernel_match] = score
    return results


def _reconcile_v2(kernel, run_date: str, output_dir, requested_at, live_fetcher=None) -> str:
    """Record outcomes + settle each match's tickets. Results come from ``_results_v2``
    (manual override or okooo live); a match with no final result is skipped — never a
    pending settlement."""
    from nutmeg.ontology.actions.models import ActorRole
    from nutmeg.ontology.finance.reconcile_flow import ReconcileRequest

    results = _results_v2(kernel, run_date, output_dir, live_fetcher=live_fetcher)
    settled = 0
    for match_id, score in results.items():
        outcome = kernel.reconcile.settle_match(
            ReconcileRequest(
                match_id=str(match_id),
                account_id=_ACCOUNT,
                score_90=score,
                status="final",
                source_artifact_retrieval_ids=[],
                actor_id="system:reconcile",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key=f"reconcile:{run_date}:{match_id}",
                requested_at=requested_at,
            )
        )
        settled += len(outcome.settled_ticket_ids)
    return f"decision-reconcile-v2 {run_date}: 结算 {len(results)} 场结果 / {settled} 票"


def _calibrate_v2(kernel, stamp: str) -> str:
    from nutmeg.analytics.calibrate_flow import CalibrateRequest

    result = kernel.calibrate.build(CalibrateRequest(as_of=stamp, built_at=stamp))
    return (
        f"decision-calibrate-v2: {result.status} | scorecards={result.scorecard_count} "
        f"factor_estimates={result.factor_estimate_count} "
        f"proposals={result.lifecycle_proposal_count}"
    )


def run_decision_settle_v2(
    run_date: str,
    output_dir,
    *,
    kernel=None,
    dispatch: bool = False,
    dry_run: bool = True,
    notification_service=None,
    results_fetcher=None,
):
    """settle on the kernel: reconcile (record outcomes + settle tickets) → calibrate → report."""
    from nutmeg.decision.verbs import _compose, _now_iso

    stamp = _now_iso()
    requested_at = datetime.fromisoformat(stamp)
    active_kernel = kernel if kernel is not None else _default_kernel()
    steps = [
        (
            "reconcile",
            lambda: _reconcile_v2(
                active_kernel, run_date, output_dir, requested_at, live_fetcher=results_fetcher
            ),
        ),
        ("calibrate", lambda: _calibrate_v2(active_kernel, stamp)),
        (
            "report",
            lambda: _report_v2(
                active_kernel,
                run_date,
                output_dir,
                "settle",
                dispatch,
                dry_run,
                notification_service,
            ),
        ),
    ]
    return _compose("decision-settle", run_date, "复盘(结算+校准,ontology v2 kernel)", steps)
