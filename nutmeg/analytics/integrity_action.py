"""Integrity & Action scorecards (design §9.6).

Earning money never launders a bad probability, and a high Brier skill never
launders a lineage or finance violation — so these two cards are independent of the
forecast cards. The Action card computes ledger balance, stake/payout totals and
counts from real cash Transactions ("no entry = not bet"). The Integrity card reports
outcome completeness and closing coverage over committed forecasts.
"""
from __future__ import annotations

import json

from sqlalchemy import Engine, func, select

from nutmeg.analytics.forecast_projection import compute_forecast_score_rows
from nutmeg.analytics.substrate import ProjectionContext
from nutmeg.ontology.repository import schema_finance as sf
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

INTEGRITY_ACTION_COLUMNS = {
    'scorecard': 'VARCHAR',
    'metrics_json': 'VARCHAR',
}


def compute_integrity_action_rows(engine: Engine) -> list[dict[str, object]]:
    with OntologyUnitOfWork(engine) as uow:
        connection = uow.connection
        ledger_balance = connection.execute(
            select(func.coalesce(func.sum(sf.cash_transactions.c.amount), 0.0))
        ).scalar_one()
        by_kind = dict(
            connection.execute(
                select(sf.cash_transactions.c.kind, func.sum(sf.cash_transactions.c.amount))
                .group_by(sf.cash_transactions.c.kind)
            ).all()
        )
        ticket_count = uow.finance.count_tickets()
        settlement_count = uow.finance.count_settlements()

    score_rows = compute_forecast_score_rows(engine)
    n_revisions = len(score_rows)
    outcome_completeness = (
        sum(1 for r in score_rows if r['has_outcome']) / n_revisions if n_revisions else 0.0
    )
    closing_coverage = (
        sum(1 for r in score_rows if r['has_closing']) / n_revisions if n_revisions else 0.0
    )

    action_metrics = {
        'ledger_balance': float(ledger_balance),
        'stake_total': abs(float(by_kind.get('stake', 0.0))),
        'payout_total': float(by_kind.get('payout', 0.0)),
        'ticket_count': ticket_count,
        'settlement_count': settlement_count,
    }
    integrity_metrics = {
        'outcome_completeness': outcome_completeness,
        'closing_coverage': closing_coverage,
        'n_revisions': n_revisions,
    }
    return [
        {'scorecard': 'action_finance', 'metrics_json': json.dumps(action_metrics, sort_keys=True)},
        {'scorecard': 'evidence_integrity',
         'metrics_json': json.dumps(integrity_metrics, sort_keys=True)},
    ]


class IntegrityActionScorecardProjector:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def project(self, context: ProjectionContext) -> None:
        context.write('integrity_action_scorecards', compute_integrity_action_rows(self._engine),
                      column_types=INTEGRITY_ACTION_COLUMNS)
