from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from typer.testing import CliRunner

from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.cli import app
from nutmeg.interfaces.cli import workflow as workflow_cli
from nutmeg.ontology import build_ontology_kernel
from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.jczq_cutover import JczqCutoverGate


def test_cutover_refuses_without_accepted_replay(tmp_path) -> None:
    report = tmp_path / "replay.json"
    report.write_text(json.dumps({"accepted": False}), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "workflow",
            "jczq-cutover",
            "--day",
            "2026-09-20",
            "--replay-report",
            str(report),
            "--check-only",
            "--data-dir",
            str(tmp_path / "data"),
        ],
    )

    assert result.exit_code == 1
    assert "accepted replay is required" in result.stdout


def test_jczq_status_calls_the_authoritative_product_query(tmp_path, monkeypatch) -> None:
    calls = []

    class _Service:
        def status(self, day):
            calls.append(day)
            return {"business_date": day, "authority": "legacy_read_only"}

    monkeypatch.setattr(workflow_cli, "_jczq_workflow_service", lambda _data: _Service())

    result = CliRunner().invoke(
        app,
        [
            "workflow",
            "jczq-status",
            "--day",
            "2026-09-20",
            "--data-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == ["2026-09-20"]
    assert json.loads(result.stdout)["authority"] == "legacy_read_only"


def test_cutover_action_requires_valid_zero_side_effect_report(tmp_path) -> None:
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    service = ActionService(lambda: OntologyUnitOfWork(kernel.engine))
    gate = JczqCutoverGate(service, schema_version=kernel.status().schema_version)
    document = {
        "schema_version": kernel.status().schema_version,
        "accepted": True,
        "production_delta": {
            "objects": 0,
            "money_entries": 0,
            "dispatches": 0,
            "prospective_observations": 0,
        },
    }
    document["report_sha256"] = hashlib.sha256(
        canonical_json(document).encode("utf-8")
    ).hexdigest()
    report = tmp_path / "accepted.json"
    report.write_text(json.dumps(document), encoding="utf-8")

    checked = gate.check("2026-09-20", report)
    approved = gate.approve(
        "2026-09-20",
        report,
        actor_id="operator:jun",
        requested_at=datetime(2026, 9, 20, tzinfo=UTC),
    )

    assert checked.authority == "legacy_read_only"
    assert approved.authority == "ontology_v2_required"
    assert gate.authority() == "ontology_v2_required"
