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
