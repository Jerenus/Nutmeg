"""forecast_scorecards projection: three cohorted scorecards, no single total.

Aggregates the per-revision forecast scores into cohorts (by market) for three
independent scorecards — Forecast Truth (Brier skill vs the same-match prior),
Market Information (closing skill), Calibration & Selectivity (follow-market vs
divergent participation). Brier skill is ``None`` when the prior denominator is 0
(never a divide-by-zero or a default); intervals use a documented normal approx.
"""
from __future__ import annotations

import json
import math
import statistics

from sqlalchemy import Engine

from nutmeg.analytics.forecast_projection import compute_forecast_score_rows
from nutmeg.analytics.scoring import brier_skill
from nutmeg.analytics.substrate import ProjectionContext

SCORECARD_COLUMNS = {
    'scorecard': 'VARCHAR',
    'cohort_key': 'VARCHAR',
    'cohort_value': 'VARCHAR',
    'n': 'BIGINT',
    'coverage': 'DOUBLE',
    'raw_brier': 'DOUBLE',
    'prior_brier': 'DOUBLE',
    'brier_skill': 'DOUBLE',
    'skill_low': 'DOUBLE',
    'skill_high': 'DOUBLE',
    'extra_json': 'VARCHAR',
}

_Z = 1.96


def _skill_interval(
    briers: list[float], prior_briers: list[float]
) -> tuple[float | None, float | None, float | None, float | None, float | None]:
    """Return (raw_brier, prior_brier, skill, low, high) with a normal-approx interval."""
    if not briers:
        return None, None, None, None, None
    raw = statistics.fmean(briers)
    prior = statistics.fmean(prior_briers)
    skill = brier_skill(briers, prior_briers)
    if skill is None or len(briers) < 2 or prior == 0:
        return raw, prior, skill, None, None
    gains = [pb - b for b, pb in zip(briers, prior_briers, strict=True)]
    se = (statistics.pstdev(gains) / math.sqrt(len(gains))) / prior
    return raw, prior, skill, skill - _Z * se, skill + _Z * se


def compute_scorecard_rows(engine: Engine) -> list[dict[str, object]]:
    score_rows = compute_forecast_score_rows(engine)
    cohorts: dict[str, list[dict[str, object]]] = {}
    for row in score_rows:
        cohorts.setdefault(row['market_definition_id'], []).append(row)

    out: list[dict[str, object]] = []
    for market_id, rows in sorted(cohorts.items()):
        total = len(rows)

        scored = [r for r in rows if r['has_outcome']]
        raw, prior, skill, low, high = _skill_interval(
            [r['brier'] for r in scored], [r['prior_brier'] for r in scored]
        )
        out.append(_card('forecast_truth', market_id, len(scored), total,
                         raw, prior, skill, low, high, {}))

        closing = [r for r in rows if r['has_closing']]
        mean_csd = (
            statistics.fmean([r['closing_skill_delta'] for r in closing]) if closing else None
        )
        mean_da = (
            statistics.fmean([r['directional_alignment'] for r in closing]) if closing else None
        )
        out.append(_card('market_information', market_id, len(closing), total,
                         None, None, None, None, None,
                         {'mean_closing_skill_delta': mean_csd,
                          'mean_directional_alignment': mean_da}))

        follow = sum(1 for r in rows if r['follow_market'])
        out.append(_card('calibration', market_id, len(scored), total,
                         raw, prior, skill, low, high,
                         {'follow_market': follow, 'divergent': total - follow}))
    return out


def _card(scorecard, market_id, n, total, raw, prior, skill, low, high, extra):
    return {
        'scorecard': scorecard,
        'cohort_key': 'market_definition_id',
        'cohort_value': market_id,
        'n': n,
        'coverage': (n / total) if total else 0.0,
        'raw_brier': raw,
        'prior_brier': prior,
        'brier_skill': skill,
        'skill_low': low,
        'skill_high': high,
        'extra_json': json.dumps(extra, sort_keys=True),
    }


class ForecastScorecardProjector:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def project(self, context: ProjectionContext) -> None:
        context.write('forecast_scorecards', compute_scorecard_rows(self._engine),
                      column_types=SCORECARD_COLUMNS)
