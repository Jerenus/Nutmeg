from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from typer.testing import CliRunner

from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.cli import app
from nutmeg.interfaces.cli import workflow as workflow_cli
from nutmeg.ontology.actions.models import ActionOutcome, ActionStatus, ObjectRef
from nutmeg.ontology.operator.evidence_actions import EvidenceIntakeResult
from nutmeg.ontology.operator.evidence_manifest import (
    EvidenceIntakeManifestV1,
    evidence_manifest_sha256,
)
from nutmeg.ontology.repository import schema, schema_evidence
from nutmeg.ontology.repository.operator_decision import EvidenceIntakeReceiptRow
from nutmeg.ontology.wiring import build_ontology_kernel
from tests.ontology.operator.test_evidence_ingest import (
    _manifest as sqlite_manifest,
)
from tests.ontology.operator.test_evidence_ingest import (
    _seed_intake_dependencies,
)

FIXTURE = Path("tests/product/fixtures/operator/evidence/jczq-valid.json")


@dataclass
class _FakeEvidenceActions:
    result: EvidenceIntakeResult | Exception
    requests: list[object]

    def ingest_operator_evidence_manifest(self, request):
        self.requests.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@dataclass
class _FakeKernel:
    evidence_actions: _FakeEvidenceActions


def _committed_result() -> EvidenceIntakeResult:
    manifest_hash = evidence_manifest_sha256(
        EvidenceIntakeManifestV1.model_validate(json.loads(FIXTURE.read_text("utf-8")))
    )
    outcome = ActionOutcome(
        action_id="ACT-evidence-1",
        action_type="ingest_operator_evidence_manifest",
        status=ActionStatus.COMMITTED,
        result_refs=(ObjectRef("operator_evidence_intake_receipt", "EIR-1"),),
        committed_at="2026-09-04T02:01:00+00:00",
    )
    return EvidenceIntakeResult(
        outcome=outcome,
        receipt=EvidenceIntakeReceiptRow(
            intake_receipt_id="EIR-1",
            action_id=outcome.action_id,
            lane="jczq",
            business_key="2026-09-04",
            slate_revision_id="slate-jczq-1",
            task_snapshot_hash="a" * 64,
            captured_at="2026-09-04T02:00:00+00:00",
            manifest_sha256=manifest_hash,
            source_retrieval_ids=("retrieval-team-1",),
            committed_count=1,
            rejected_count=0,
            skipped_count=0,
            persisted_count=1,
            created_at="2026-09-04T02:01:00+00:00",
        ),
    )


def _invoke(path: Path):
    return CliRunner().invoke(
        app,
        ["workflow", "ingest-evidence", "--manifest", str(path)],
    )


def test_evidence_cli_calls_typed_action_and_reports_hash_and_counts(
    monkeypatch,
) -> None:
    service = _FakeEvidenceActions(_committed_result(), [])
    monkeypatch.setattr(workflow_cli, "_kernel", lambda _data_dir: _FakeKernel(service))

    result = _invoke(FIXTURE)

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    parsed_manifest = service.requests[0].manifest
    assert payload == {
        "action_id": "ACT-evidence-1",
        "business_key": "2026-09-04",
        "committed_count": 1,
        "contract_version": "evidence-intake-v1",
        "lane": "jczq",
        "manifest_sha256": evidence_manifest_sha256(parsed_manifest),
        "persisted_count": 1,
        "status": "committed",
    }
    request = service.requests[0]
    assert request.actor_role.value == "deterministic_system"
    assert request.idempotency_key == (
        f"evidence-intake-v1:{evidence_manifest_sha256(parsed_manifest)}"
    )


def test_evidence_cli_quarantines_invalid_manifest_before_service_construction(
    tmp_path: Path,
    monkeypatch,
) -> None:
    document = json.loads(FIXTURE.read_text("utf-8"))
    document["unknown"] = True
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(document), "utf-8")
    called = False

    def fail_if_called(_data_dir):
        nonlocal called
        called = True
        raise AssertionError("service construction must follow validation")

    monkeypatch.setattr(workflow_cli, "_kernel", fail_if_called)

    result = _invoke(invalid)

    assert result.exit_code == 1
    assert "unknown" in result.stdout
    assert not called


def test_evidence_cli_returns_nonzero_for_reference_or_count_reconciliation_failure(
    monkeypatch,
) -> None:
    for message in (
        "manifest task snapshot does not match the current slate",
        "evidence committed and persisted counts differ",
    ):
        service = _FakeEvidenceActions(ValueError(message), [])
        monkeypatch.setattr(
            workflow_cli,
            "_kernel",
            lambda _data_dir, service=service: _FakeKernel(service),
        )

        result = _invoke(FIXTURE)

        assert result.exit_code == 1
        assert message in result.stdout
        assert len(service.requests) == 1


def test_evidence_cli_rejected_action_is_quarantined(monkeypatch) -> None:
    rejected = EvidenceIntakeResult(
        outcome=ActionOutcome(
            action_id="ACT-rejected",
            action_type="ingest_operator_evidence_manifest",
            status=ActionStatus.REJECTED,
            result_refs=(),
            committed_at=None,
            error_code="permission_denied",
            error_detail="not allowed",
        ),
        receipt=None,
    )
    service = _FakeEvidenceActions(rejected, [])
    monkeypatch.setattr(workflow_cli, "_kernel", lambda _data_dir: _FakeKernel(service))

    result = _invoke(FIXTURE)

    assert result.exit_code == 1
    assert "not allowed" in result.stdout


def test_evidence_cli_real_kernel_commits_atomically_and_invalid_input_is_zero_delta(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "data"
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    kernel.initialize()
    _seed_intake_dependencies(kernel.engine)
    manifest_path = tmp_path / "evidence.json"
    manifest_path.write_text(json.dumps(sqlite_manifest()), "utf-8")
    monkeypatch.setattr(
        workflow_cli,
        "_now",
        lambda: datetime(2026, 9, 4, 2, tzinfo=UTC),
    )

    result = CliRunner().invoke(
        app,
        [
            "workflow",
            "ingest-evidence",
            "--manifest",
            str(manifest_path),
            "--data-dir",
            str(data_dir),
        ],
    )

    assert result.exit_code == 0, result.stdout
    with kernel.engine.connect() as connection:
        before = (
            connection.scalar(select(func.count()).select_from(schema.actions)),
            connection.scalar(select(func.count()).select_from(schema_evidence.observations)),
            connection.scalar(select(func.count()).select_from(schema_evidence.claims)),
        )
    assert before[1:] == (1, 1)

    invalid = sqlite_manifest()
    invalid["unknown"] = True
    manifest_path.write_text(json.dumps(invalid), "utf-8")
    rejected = CliRunner().invoke(
        app,
        [
            "workflow",
            "ingest-evidence",
            "--manifest",
            str(manifest_path),
            "--data-dir",
            str(data_dir),
        ],
    )

    assert rejected.exit_code == 1
    with kernel.engine.connect() as connection:
        after = (
            connection.scalar(select(func.count()).select_from(schema.actions)),
            connection.scalar(select(func.count()).select_from(schema_evidence.observations)),
            connection.scalar(select(func.count()).select_from(schema_evidence.claims)),
        )
    assert after == before
