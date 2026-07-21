"""forecast_scores projection: score each committed forecast against truth + closing.

Each committed ForecastRevision is scored with the pure primitives — Brier vs the
one-hot outcome, Brier of the read-time prior, and (where a closing snapshot exists)
closing-skill and directional alignment. Missing inputs are recorded as flags with
NULL metrics, never a fabricated 0, so aggregation can exclude them from a metric's
denominator. The row list is a pure function of the SQLite snapshot.
"""
from __future__ import annotations

from sqlalchemy import Engine

from nutmeg.analytics.outcomes import outcome_one_hot
from nutmeg.analytics.scoring import (
    brier,
    closing_skill_delta,
    directional_alignment,
    log_score,
)
from nutmeg.analytics.substrate import ProjectionContext
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

_LOG_CLIP = 1e-9

FORECAST_SCORE_COLUMNS = {
    'forecast_revision_id': 'VARCHAR',
    'match_id': 'VARCHAR',
    'market_definition_id': 'VARCHAR',
    'made_at': 'VARCHAR',
    'n_outcomes': 'BIGINT',
    'brier': 'DOUBLE',
    'prior_brier': 'DOUBLE',
    'closing_skill_delta': 'DOUBLE',
    'directional_alignment': 'DOUBLE',
    'log_score': 'DOUBLE',
    'rps': 'DOUBLE',
    'has_outcome': 'BOOLEAN',
    'has_closing': 'BOOLEAN',
    'follow_market': 'BOOLEAN',
    'commitment_tier': 'VARCHAR',
    'judge_or_model': 'VARCHAR',
}


def compute_forecast_score_rows(engine: Engine) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with OntologyUnitOfWork(engine) as uow:
        for revision in uow.decision.iter_committed_revisions():
            q = revision.belief_distribution
            p = revision.prior_distribution
            market_kind = uow.market.market_kind(revision.market_definition_id) or ''
            outcome = uow.finance.current_outcome(revision.match_id)
            y = (
                outcome_one_hot(market_kind, list(q.keys()), outcome.score_90)
                if outcome is not None
                else None
            )
            closing = uow.market.closing_fair(revision.match_id, revision.market_definition_id)
            has_outcome = y is not None
            has_closing = closing is not None
            judge_or_model = (
                f'{revision.model_name}:{revision.model_version}'
                if revision.model_name is not None
                else revision.actor_id
            )
            rows.append(
                {
                    'forecast_revision_id': revision.forecast_revision_id,
                    'match_id': revision.match_id,
                    'market_definition_id': revision.market_definition_id,
                    'made_at': revision.made_at,
                    'n_outcomes': len(q),
                    'brier': brier(q, y) if y is not None else None,
                    'prior_brier': brier(p, y) if y is not None else None,
                    'closing_skill_delta': (
                        closing_skill_delta(q, p, closing) if has_closing else None
                    ),
                    'directional_alignment': (
                        directional_alignment(q, p, closing) if has_closing else None
                    ),
                    'log_score': log_score(q, y, _LOG_CLIP) if y is not None else None,
                    'rps': None,   # ordered-market RPS is a 4B follow-on
                    'has_outcome': has_outcome,
                    'has_closing': has_closing,
                    'follow_market': q == p,
                    'commitment_tier': revision.commitment_tier,
                    'judge_or_model': judge_or_model,
                }
            )
    return rows


class ForecastScoresProjector:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def project(self, context: ProjectionContext) -> None:
        context.write(
            'forecast_scores',
            compute_forecast_score_rows(self._engine),
            column_types=FORECAST_SCORE_COLUMNS,
        )
