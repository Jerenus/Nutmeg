"""Factor contribution and estimate projections.

``factor_score_contributions`` attributes each committed forecast's Brier/closing
gain to its factors (paired for one factor, Shapley for many). A revision whose
factor subset leaves the simplex is written ``confounded=True`` with null
contributions and feeds no estimate. ``factor_estimates`` aggregates the honest
contributions per stratum with shrinkage toward the global mean — small samples pull
to the mean rather than reporting an extreme effect.
"""
from __future__ import annotations

import statistics

from sqlalchemy import Engine

from nutmeg.analytics.attribution import CONFOUNDED, attribute_closing, attribute_factors
from nutmeg.analytics.outcomes import outcome_one_hot
from nutmeg.analytics.substrate import ProjectionContext
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

_SHRINKAGE_K = 10.0
_Z = 1.96

CONTRIBUTION_COLUMNS = {
    'forecast_revision_id': 'VARCHAR',
    'factor_definition_id': 'VARCHAR',
    'factor_family': 'VARCHAR',
    'factor_version': 'BIGINT',
    'scope_key': 'VARCHAR',
    'market_definition_id': 'VARCHAR',
    'method': 'VARCHAR',
    'brier_contribution': 'DOUBLE',
    'closing_contribution': 'DOUBLE',
    'confounded': 'BOOLEAN',
}

ESTIMATE_COLUMNS = {
    'factor_definition_id': 'VARCHAR',
    'factor_family': 'VARCHAR',
    'factor_version': 'BIGINT',
    'scope_key': 'VARCHAR',
    'market_definition_id': 'VARCHAR',
    'cohort_key': 'VARCHAR',
    'n_eff': 'BIGINT',
    'raw_mean': 'DOUBLE',
    'shrunk_mean': 'DOUBLE',
    'interval_low': 'DOUBLE',
    'interval_high': 'DOUBLE',
}


def compute_factor_contribution_rows(engine: Engine) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with OntologyUnitOfWork(engine) as uow:
        for revision in uow.decision.iter_committed_revisions():
            factors = uow.decision.iter_factor_applications(revision.forecast_revision_id)
            if not factors:
                continue
            prior = revision.prior_distribution
            belief = revision.belief_distribution
            market_kind = uow.market.market_kind(revision.market_definition_id) or ''
            outcome = uow.finance.current_outcome(revision.match_id)
            y = (
                outcome_one_hot(market_kind, list(belief.keys()), outcome.score_90)
                if outcome is not None
                else None
            )
            closing = uow.market.closing_fair(revision.match_id, revision.market_definition_id)
            confounded = False
            brier_map: dict[str, float] | None = None
            closing_map: dict[str, float] | None = None
            if y is not None:
                result = attribute_factors(prior, belief, factors, y)
                if result is CONFOUNDED:
                    confounded = True
                else:
                    brier_map = result
            if closing is not None and not confounded:
                result = attribute_closing(prior, belief, factors, closing)
                if result is CONFOUNDED:
                    confounded = True
                else:
                    closing_map = result
            method = 'shapley' if len(factors) > 1 else 'paired'
            for factor_id, _delta in factors:
                definition = uow.decision.factor_definition(factor_id)
                rows.append(
                    {
                        'forecast_revision_id': revision.forecast_revision_id,
                        'factor_definition_id': factor_id,
                        'factor_family': definition.factor_family_id if definition else 'unknown',
                        'factor_version': definition.version if definition else 0,
                        'scope_key': definition.scope if definition else None,
                        'market_definition_id': revision.market_definition_id,
                        'method': method,
                        'brier_contribution': (
                            None if confounded or brier_map is None else brier_map[factor_id]
                        ),
                        'closing_contribution': (
                            None if confounded or closing_map is None else closing_map[factor_id]
                        ),
                        'confounded': confounded,
                    }
                )
    return rows


def compute_factor_estimate_rows(engine: Engine) -> list[dict[str, object]]:
    contributions = compute_factor_contribution_rows(engine)
    scored = [
        r for r in contributions if not r['confounded'] and r['brier_contribution'] is not None
    ]
    if not scored:
        return []
    global_mean = statistics.fmean([r['brier_contribution'] for r in scored])
    strata: dict[tuple, list[dict[str, object]]] = {}
    for row in scored:
        key = (
            row['factor_definition_id'], row['factor_family'], row['factor_version'],
            row['scope_key'], row['market_definition_id'],
        )
        strata.setdefault(key, []).append(row)

    out: list[dict[str, object]] = []
    for key, rows in sorted(strata.items(), key=lambda item: tuple(str(x) for x in item[0])):
        values = [r['brier_contribution'] for r in rows]
        n = len(values)
        raw = statistics.fmean(values)
        shrunk = (n * raw + _SHRINKAGE_K * global_mean) / (n + _SHRINKAGE_K)
        if n >= 2:
            se = statistics.pstdev(values) / (n ** 0.5)
            low, high = shrunk - _Z * se, shrunk + _Z * se
        else:
            low = high = None
        factor_id, family, version, scope, market = key
        out.append(
            {
                'factor_definition_id': factor_id, 'factor_family': family,
                'factor_version': version, 'scope_key': scope, 'market_definition_id': market,
                'cohort_key': 'factor_family_scope_market', 'n_eff': n, 'raw_mean': raw,
                'shrunk_mean': shrunk, 'interval_low': low, 'interval_high': high,
            }
        )
    return out


class FactorContributionsProjector:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def project(self, context: ProjectionContext) -> None:
        context.write('factor_score_contributions', compute_factor_contribution_rows(self._engine),
                      column_types=CONTRIBUTION_COLUMNS)


class FactorEstimatesProjector:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def project(self, context: ProjectionContext) -> None:
        context.write('factor_estimates', compute_factor_estimate_rows(self._engine),
                      column_types=ESTIMATE_COLUMNS)
