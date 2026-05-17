"""Record value-engine conflicts into the conflict store (Phase 3 piece 3).

The value bridge (``JczqValueBridge``) produces a ``JczqValueReport`` of
model-vs-odds conflicts. To close the self-validation loop, the day's
match_winner conflicts are persisted as ``CrossCheckSignal`` rows in
``ConflictStore``; the next-day ``jczq-daily-review`` (``grade_conflict_store``)
grades them against results so the stake ladder accrues a live ROI.

``grade_conflict_store`` is **had-pool only**, so only ``match_winner``
conflicts are recorded — one (highest-edge) signal per match. ttg / crs /
handicap conflicts still render in the brief but are not yet graded.

Recording is idempotent per run date: the day's rows are rewritten on each
call, so re-running the brief never double-records.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from nutmeg.data.european_odds import CrossCheckSignal
from nutmeg.domain.jczq_daily import JczqDailyMatch
from nutmeg.services.jczq_conflict_store import ConflictStore
from nutmeg.services.jczq_daily import _report_from_dict
from nutmeg.services.jczq_value_bridge import JczqValueReport

logger = logging.getLogger(__name__)

__all__ = ["record_conflict_signals", "value_report_to_signals"]

# match_winner outcome_key → JCZQ had-pool 中文 pick.
_MW_PICK: dict[str, str] = {"home": "胜", "draw": "平", "away": "负"}


def value_report_to_signals(
    report: JczqValueReport,
) -> tuple[list[CrossCheckSignal], dict[str, float]]:
    """Flatten a value report into had-pool ``CrossCheckSignal`` rows.

    Returns ``(signals, sporttery_odds)`` where ``sporttery_odds`` maps
    ``match_no`` → the decimal odds of that signal's pick (the payout
    multiplier used by ``ConflictStore`` once graded).

    Only ``match_winner`` conflicts are kept (grading is had-only). When a
    match has several match_winner conflicts, the highest-edge one wins.
    """

    signals: list[CrossCheckSignal] = []
    odds: dict[str, float] = {}
    for entry in report.matches:
        if not entry.aligned or not entry.conflicts:
            continue
        had_conflicts = [
            c for c in entry.conflicts if c.market_key == "match_winner"
        ]
        if not had_conflicts:
            continue
        best = max(had_conflicts, key=lambda c: c.edge)
        pick = _MW_PICK.get(best.outcome_key, best.outcome_name)
        signals.append(
            CrossCheckSignal(
                match_no=entry.match_no,
                pool="had",
                pick=pick,
                # The model is the independent ("European") view; the market
                # is Sporttery's fair probability. delta = model - market = edge.
                sporttery_implied=best.market_probability,
                european_implied=best.model_probability,
                dispersion=0.0,
                delta=best.edge,
            )
        )
        odds[entry.match_no] = best.best_odds
    return signals, odds


def _matches_from_context(output_dir: Path, run_date: str) -> list[JczqDailyMatch]:
    """Load the day's JCZQ matches from the saved brief context.json."""

    ctx_path = Path(output_dir) / "daily" / run_date / "context.json"
    if not ctx_path.exists():
        return []
    try:
        ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    return list(_report_from_dict(ctx).matches)


def record_conflict_signals(
    *,
    value_bridge,
    run_date: str,
    output_dir: Path,
    matches: list[JczqDailyMatch] | None = None,
) -> int:
    """Run the bridge and persist the day's conflict signals; return the count.

    ``matches`` defaults to the JCZQ matches saved in the run date's
    ``context.json`` (written by ``build_brief``). The conflict store lives at
    ``<output_dir>/memory/conflict-signals.json`` — the same path
    ``jczq-daily-review`` grades the next day.
    """

    if matches is None:
        matches = _matches_from_context(output_dir, run_date)
    if not matches:
        return 0

    report = value_bridge.evaluate_day(matches)
    signals, sporttery_odds = value_report_to_signals(report)
    if not signals:
        return 0

    store = ConflictStore(Path(output_dir) / "memory" / "conflict-signals.json")
    # Idempotent per run date: drop any rows already recorded for this date
    # before re-recording, so re-running the brief never double-counts.
    store.drop_date(run_date)
    store.record(run_date, signals, sporttery_odds=sporttery_odds)
    logger.info("recorded %d conflict signal(s) for %s", len(signals), run_date)
    return len(signals)
