from __future__ import annotations

from datetime import UTC, datetime

from typer.testing import CliRunner

from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.cli import app
from nutmeg.ontology import build_ontology_kernel
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.rsi_actions import RegisterExperimentRequest
from tests.ontology.test_rsi_actions import F2_DOC


def test_status_lists_pending_instrument_separately_from_gaps(tmp_path):
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path))
    kernel.initialize()
    doc = {
        **F2_DOC,
        "exp_id": "F5",
        "duties": [
            {
                **F2_DOC["duties"][0],
                "name": "price-band-observation",
                "status": "pending_instrument",
                "instrument": ["TODO"],
            }
        ],
    }
    kernel.rsi_actions.register_experiment(
        RegisterExperimentRequest(
            doc=doc,
            acted_by="Jun",
            actor_id="op:jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="reg:F5",
            requested_at=datetime(2026, 9, 20, tzinfo=UTC),
        )
    )

    result = CliRunner().invoke(app, ["rsi", "status", "--data-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "pending: F5:price-band-observation（待实现采集器）" in result.output
    assert "gaps=" not in result.output
