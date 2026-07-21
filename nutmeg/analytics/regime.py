"""RegimeVector: a pre-match thermometer, never a thermostat (design §11).

Each match with a committed forecast gets a pre-match RegimeVector with five sensor
axes. Package 4B computes two real axes — market_shape (from the fair distribution)
and portfolio_risk (from the match's tickets); the other three carry coverage and
``percentile_unavailable`` because their sensor inputs are not all in the store yet.
Post-match research labels live in a *separate* projection so a pre-match vector can
never leak a result. Regime never changes a direction or a stake.
"""
from __future__ import annotations

import json
import math

from sqlalchemy import Engine

from nutmeg.analytics.substrate import ProjectionContext
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

_UNAVAILABLE = {'raw': None, 'coverage': 0.0, 'percentile': 'percentile_unavailable'}


def market_shape(fair: dict[str, float]) -> dict[str, float]:
    if len(fair) < 2:
        return {
            'normalized_entropy': 0.0,
            'favorite_concentration': max(fair.values(), default=0.0),
            'draw_mass': fair.get('draw', 0.0),
        }
    entropy = -sum(p * math.log(p) for p in fair.values() if p > 0)
    return {
        'normalized_entropy': entropy / math.log(len(fair)),
        'favorite_concentration': max(fair.values()),
        'draw_mass': fair.get('draw', 0.0),
    }


def _labels(shape: dict[str, float]) -> list[str]:
    labels: list[str] = []
    if shape['favorite_concentration'] >= 0.60:
        labels.append('favorite_heavy')
    if shape['draw_mass'] >= 0.35:
        labels.append('draw_leaning')
    if not labels:
        labels.append('balanced')
    return labels


def _result_key(score_90: str) -> str:
    home, away = (int(x) for x in score_90.split('-'))
    return 'home' if home > away else 'away' if home < away else 'draw'


def compute_regime_vector_rows(engine: Engine) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    with OntologyUnitOfWork(engine) as uow:
        for revision in uow.decision.iter_committed_revisions():
            if revision.match_id in seen:
                continue
            seen.add(revision.match_id)
            fair = uow.market.latest_fair(revision.match_id, revision.market_definition_id)
            if not fair:
                fair = revision.prior_distribution
            shape = market_shape(fair)
            ticket_ids = uow.finance.tickets_for_match(revision.match_id)
            stake_exposure = 0.0
            for ticket_id in ticket_ids:
                stake_exposure += sum(
                    leg.stake_share or 0.0 for leg in uow.finance.bet_legs_for(ticket_id)
                )
            axes = {
                'market_shape': {'raw': shape, 'coverage': 1.0,
                                 'percentile': 'percentile_unavailable'},
                'portfolio_risk': {
                    'raw': {'ticket_count': len(ticket_ids), 'stake_exposure': stake_exposure},
                    'coverage': 1.0, 'percentile': 'percentile_unavailable'},
                'information_weather': dict(_UNAVAILABLE),
                'fixture_pressure': dict(_UNAVAILABLE),
                'data_health': dict(_UNAVAILABLE),
            }
            rows.append({
                'regime_id': f'match:{revision.match_id}',
                'scope_type': 'match',
                'scope_id': revision.match_id,
                'as_of': revision.made_at,
                'axes_json': json.dumps(axes, sort_keys=True),
                'labels_json': json.dumps(_labels(shape)),
            })
    return rows


def compute_regime_postmatch_rows(engine: Engine) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    with OntologyUnitOfWork(engine) as uow:
        for revision in uow.decision.iter_committed_revisions():
            if revision.match_id in seen:
                continue
            seen.add(revision.match_id)
            outcome = uow.finance.current_outcome(revision.match_id)
            if outcome is None:
                continue
            fair = uow.market.latest_fair(revision.match_id, revision.market_definition_id)
            if not fair:
                fair = revision.prior_distribution
            favorite = max(fair, key=fair.get)
            result = _result_key(outcome.score_90)
            labels = ['upset'] if favorite != result else ['chalk']
            rows.append({
                'match_id': revision.match_id,
                'labels_json': json.dumps(labels),
            })
    return rows


REGIME_VECTOR_COLUMNS = {
    'regime_id': 'VARCHAR', 'scope_type': 'VARCHAR', 'scope_id': 'VARCHAR',
    'as_of': 'VARCHAR', 'axes_json': 'VARCHAR', 'labels_json': 'VARCHAR',
}

REGIME_POSTMATCH_COLUMNS = {'match_id': 'VARCHAR', 'labels_json': 'VARCHAR'}


class RegimeVectorProjector:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def project(self, context: ProjectionContext) -> None:
        context.write('regime_vectors', compute_regime_vector_rows(self._engine),
                      column_types=REGIME_VECTOR_COLUMNS)


class RegimePostmatchProjector:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def project(self, context: ProjectionContext) -> None:
        context.write('regime_postmatch_labels', compute_regime_postmatch_rows(self._engine),
                      column_types=REGIME_POSTMATCH_COLUMNS)
