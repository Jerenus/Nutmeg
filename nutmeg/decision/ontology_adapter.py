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
