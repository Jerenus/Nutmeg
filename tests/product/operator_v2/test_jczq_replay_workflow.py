import json
import sqlite3

from nutmeg.product.jczq_replay import JczqReplayRunner
from tests.product.operator_v2.test_jczq_20260919_replay import _write_source_day


def test_replay_runs_candidate_audits_and_formal_no_ticket(tmp_path):
    source = tmp_path / "production"
    isolated = tmp_path / "isolated"
    _write_source_day(source)
    day_root = source / "jczq" / "daily" / "2026-09-19"
    (day_root / "results.json").write_text(
        json.dumps(
            {
                "published_at": "2026-09-20T12:00:00+08:00",
                "results": [
                    {
                        "match_id": f"jczq-sporttery-{2_000_000 + index}",
                        "score_90": "2-1",
                        "status": "final",
                    }
                    for index in range(1, 31)
                ],
            }
        ),
        encoding="utf-8",
    )

    JczqReplayRunner(source_root=source, isolated_root=isolated).run("2026-09-19")

    connection = sqlite3.connect(isolated / "ontology" / "ontology.db")
    try:
        set_rows = connection.execute(
            "SELECT set_kind, comparison_only FROM operator_candidate_set_revisions "
            "ORDER BY set_kind"
        ).fetchall()
        bands = connection.execute(
            "SELECT odds_band, status FROM operator_candidate_band_outcomes"
        ).fetchall()
        no_tickets = connection.execute(
            "SELECT task_family_id, deployment_outcome FROM operator_no_ticket_revisions"
        ).fetchall()
        protected = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "ticket_placements",
                "cash_transactions",
                "operator_confirmation_challenge_revisions",
            )
        }
        forecast_count = connection.execute(
            "SELECT COUNT(*) FROM forecast_revisions WHERE status = 'committed'"
        ).fetchone()[0]
        prediction_counts = connection.execute(
            "SELECT COUNT(*), SUM(status != 'pending') FROM predictions"
        ).fetchone()
        outcome_count = connection.execute(
            "SELECT COUNT(*) FROM match_outcomes WHERE status = 'final'"
        ).fetchone()[0]
        rsi_counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "rsi_observations",
                "rsi_grades",
                "rsi_verdicts",
                "rsi_deployments",
            )
        }
    finally:
        connection.close()

    assert set_rows == [
        ("conditional_market_counterfactual", 1),
        ("judgment_bound", 0),
    ]
    assert len(bands) == 8
    assert {row[0] for row in bands} == {"10x", "20x", "50x", "100x"}
    assert no_tickets == [("jczq:2026-09-19", "no_ticket")]
    assert protected == {
        "ticket_placements": 0,
        "cash_transactions": 0,
        "operator_confirmation_challenge_revisions": 0,
    }
    assert forecast_count == 30
    assert prediction_counts == (forecast_count, forecast_count)
    assert outcome_count == 30
    assert rsi_counts == {
        "rsi_observations": 0,
        "rsi_grades": 0,
        "rsi_verdicts": 0,
        "rsi_deployments": 0,
    }
