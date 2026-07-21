"""Factor lifecycle proposals: calibrate proposes, a typed Action applies.

A versioned policy reads the shrinkage factor estimates and the factor's current
status and proposes transitions (probation→active when the skill-contribution
interval is entirely positive with enough samples; active→retired when it is entirely
negative). Thresholds are policy data, not hard-coded eternal truths. This projector
only writes ``factor_lifecycle_proposals`` — the status change itself is the existing
judge_operator ``apply_factor_status`` Action.
"""
from __future__ import annotations

import json

from sqlalchemy import Engine

from nutmeg.analytics.factor_projection import compute_factor_estimate_rows
from nutmeg.analytics.substrate import ProjectionContext
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

LIFECYCLE_POLICY = {
    'policy_version': 'lifecycle-v1',
    'min_n': 3,
    'active_factor_cap': 12,
}

PROPOSAL_COLUMNS = {
    'proposal_id': 'VARCHAR',
    'factor_definition_id': 'VARCHAR',
    'from_status': 'VARCHAR',
    'to_status': 'VARCHAR',
    'rationale_json': 'VARCHAR',
    'policy_version': 'VARCHAR',
}


def compute_lifecycle_proposal_rows(engine: Engine) -> list[dict[str, object]]:
    min_n = LIFECYCLE_POLICY['min_n']
    policy_version = LIFECYCLE_POLICY['policy_version']
    rows: list[dict[str, object]] = []
    estimates = compute_factor_estimate_rows(engine)
    with OntologyUnitOfWork(engine) as uow:
        for estimate in estimates:
            factor_id = estimate['factor_definition_id']
            status = uow.decision.factor_status(factor_id)
            if status is None:
                continue
            n = estimate['n_eff']
            low = estimate['interval_low']
            high = estimate['interval_high']
            target: str | None = None
            if status == 'probation' and n >= min_n and low is not None and low > 0:
                target = 'active'
            elif status == 'active' and n >= min_n and high is not None and high < 0:
                target = 'retired'
            if target is None:
                continue
            rows.append(
                {
                    'proposal_id': f'{factor_id}:{status}->{target}',
                    'factor_definition_id': factor_id,
                    'from_status': status,
                    'to_status': target,
                    'rationale_json': json.dumps(
                        {'n_eff': n, 'interval_low': low, 'interval_high': high,
                         'shrunk_mean': estimate['shrunk_mean']},
                        sort_keys=True,
                    ),
                    'policy_version': policy_version,
                }
            )
    return rows


class FactorLifecycleProjector:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def project(self, context: ProjectionContext) -> None:
        context.write('factor_lifecycle_proposals', compute_lifecycle_proposal_rows(self._engine),
                      column_types=PROPOSAL_COLUMNS)
