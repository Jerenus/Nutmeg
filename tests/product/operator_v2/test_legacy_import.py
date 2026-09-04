from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from typer.testing import CliRunner

from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.cli import app
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.workflow_actions import RegisterPredictionRequest
from nutmeg.ontology.errors import IdempotencyConflictError
from nutmeg.ontology.repository import schema, schema_operator_sale, schema_workflow
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.product.operator_legacy_import import (
    LEGACY_ISSUE_CONTRACT,
    LEGACY_PREP_CONTRACT,
    LEGACY_RX_V2_CONTRACT,
    LEGACY_RX_V3_CONTRACT,
    LegacyImportReceipt,
    LegacyOperatorImporter,
    LegacyQuarantineReport,
)

NOW = datetime(2026, 9, 4, 8, tzinfo=UTC)
FIXTURES = Path(__file__).parents[1] / "fixtures" / "operator" / "legacy"


@pytest.fixture
def kernel(tmp_path: Path):
    value = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    value.initialize()
    return value


@pytest.fixture
def importer(kernel) -> LegacyOperatorImporter:
    return LegacyOperatorImporter(
        artifact_ingest=kernel.artifact_ingest,
        workflow=kernel.workflow,
    )


def _count(kernel, table) -> int:
    with kernel.engine.connect() as connection:
        return int(connection.scalar(select(func.count()).select_from(table)) or 0)


@pytest.mark.parametrize(
    (
        "issue",
        "contract_version",
        "prediction_count",
        "adjudication_total",
        "adjudication_committed",
        "adjudication_skipped",
        "face_drafts",
        "summaries",
    ),
    [
        ("26113", LEGACY_RX_V2_CONTRACT, 5, 6, 4, 2, 0, 4),
        ("26114", LEGACY_RX_V2_CONTRACT, 5, 7, 5, 2, 0, 3),
        ("26115", LEGACY_RX_V3_CONTRACT, 6, 5, 5, 0, 0, 4),
        ("26116", LEGACY_RX_V3_CONTRACT, 8, 7, 4, 3, 8, 4),
    ],
)
def test_legacy_import_golden_counts_and_quarantines_every_candidate(
    kernel,
    importer: LegacyOperatorImporter,
    issue: str,
    contract_version: str,
    prediction_count: int,
    adjudication_total: int,
    adjudication_committed: int,
    adjudication_skipped: int,
    face_drafts: int,
    summaries: int,
) -> None:
    receipt = importer.import_path(
        FIXTURES / f"{issue}-rx.json",
        contract_version=contract_version,
        imported_at=NOW,
    )

    assert isinstance(receipt, LegacyImportReceipt)
    assert receipt.status == "imported"
    assert receipt.business_key == issue
    assert receipt.prediction_count == prediction_count
    assert receipt.adjudication_total_count == adjudication_total
    assert receipt.adjudication_committed_count == adjudication_committed
    assert receipt.adjudication_skipped_count == adjudication_skipped
    assert len(receipt.workflow_action_ids) == prediction_count + adjudication_committed
    assert sum(draft.faces is not None for draft in receipt.candidate_drafts) == face_drafts
    assert sum(draft.faces is None for draft in receipt.candidate_drafts) == summaries
    assert all(draft.deployable is False for draft in receipt.candidate_drafts)
    assert {
        draft.reason_code for draft in receipt.candidate_drafts if draft.faces is None
    } <= {"legacy_faces_missing"}
    assert {
        draft.reason_code for draft in receipt.candidate_drafts if draft.faces is not None
    } <= {"legacy_audit_required"}
    assert receipt.source_artifact_id.startswith("sha256:")
    assert receipt.source_artifact_retrieval_id.startswith("RET-")
    if contract_version == LEGACY_RX_V2_CONTRACT:
        assert all(
            draft.legacy_text == "sanitized summary"
            for draft in receipt.candidate_drafts
        )
    assert _count(kernel, schema_workflow.predictions) == prediction_count
    assert _count(kernel, schema_workflow.adjudications) == adjudication_committed
    assert all(
        row[0] == "pending"
        for row in kernel.engine.connect().execute(
            select(schema_workflow.predictions.c.status)
        )
    )

    action_count = _count(kernel, schema.actions)
    replay = importer.import_path(
        FIXTURES / f"{issue}-rx.json",
        contract_version=contract_version,
        imported_at=NOW,
    )
    assert replay == receipt
    assert _count(kernel, schema.actions) == action_count


def test_content_replay_is_idempotent_when_import_time_changes(
    kernel, importer: LegacyOperatorImporter
) -> None:
    first = importer.import_path(
        FIXTURES / "26113-rx.json",
        contract_version=LEGACY_RX_V2_CONTRACT,
        imported_at=NOW,
    )
    action_count = _count(kernel, schema.actions)

    replay = importer.import_path(
        FIXTURES / "26113-rx.json",
        contract_version=LEGACY_RX_V2_CONTRACT,
        imported_at=NOW.replace(hour=9),
    )

    assert replay == first
    assert _count(kernel, schema.actions) == action_count


def test_existing_child_conflict_is_detected_before_any_import_action(
    kernel, importer: LegacyOperatorImporter
) -> None:
    seeded = kernel.workflow.register_prediction(
        RegisterPredictionRequest(
            match_id=None,
            subject_type="issue",
            subject_id="26113",
            claim="conflicting pre-existing claim",
            falsifier="conflicting pre-existing falsifier",
            actor_id="operator:jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="rx:26113:P2",
            requested_at=NOW,
        )
    )
    assert seeded.is_success
    action_count = _count(kernel, schema.actions)

    with pytest.raises(IdempotencyConflictError):
        importer.import_path(
            FIXTURES / "26113-rx.json",
            contract_version=LEGACY_RX_V2_CONTRACT,
            imported_at=NOW,
        )

    assert _count(kernel, schema.actions) == action_count
    assert _count(kernel, schema.artifact_retrievals) == 0
    assert _count(kernel, schema_workflow.predictions) == 1
    assert _count(kernel, schema_workflow.adjudications) == 0


@pytest.mark.parametrize("issue", ["26113", "26114", "26115", "26116"])
@pytest.mark.parametrize(
    ("suffix", "contract_version"),
    [("issue", LEGACY_ISSUE_CONTRACT), ("prep", LEGACY_PREP_CONTRACT)],
)
def test_legacy_issue_and_prep_import_as_replay_only_receipts(
    kernel,
    importer: LegacyOperatorImporter,
    issue: str,
    suffix: str,
    contract_version: str,
) -> None:
    receipt = importer.import_path(
        FIXTURES / f"{issue}-{suffix}.json",
        contract_version=contract_version,
        imported_at=NOW,
    )

    assert isinstance(receipt, LegacyImportReceipt)
    assert receipt.business_key == issue
    assert receipt.document_kind == suffix
    assert receipt.provenance_state == "legacy_replay"
    assert receipt.official_match_nos == tuple(str(index) for index in range(1, 15))
    assert receipt.record_count == 14
    assert receipt.workflow_action_ids == ()
    assert _count(kernel, schema_operator_sale.official_sale_slate_revisions) == 0

    action_count = _count(kernel, schema.actions)
    assert (
        importer.import_path(
            FIXTURES / f"{issue}-{suffix}.json",
            contract_version=contract_version,
            imported_at=NOW,
        )
        == receipt
    )
    assert _count(kernel, schema.actions) == action_count


def test_unknown_contract_quarantines_before_any_action(
    kernel, importer: LegacyOperatorImporter
) -> None:
    result = importer.import_path(
        FIXTURES / "26113-rx.json",
        contract_version="zucai-legacy-rx-v999",
        imported_at=NOW,
    )

    assert isinstance(result, LegacyQuarantineReport)
    assert result.reason_code == "unknown_contract_version"
    assert result.committed_workflow_action_count == 0
    assert _count(kernel, schema.actions) == 0


def test_missing_required_field_quarantines_without_partial_actions(
    tmp_path: Path, kernel, importer: LegacyOperatorImporter
) -> None:
    payload = json.loads((FIXTURES / "26113-rx.json").read_text("utf-8"))
    payload.pop("predictions")
    path = tmp_path / "26113-rx.json"
    path.write_text(json.dumps(payload), "utf-8")

    result = importer.import_path(
        path,
        contract_version=LEGACY_RX_V2_CONTRACT,
        imported_at=NOW,
    )

    assert isinstance(result, LegacyQuarantineReport)
    assert result.reason_code == "manifest_invalid"
    assert _count(kernel, schema.actions) == 0
    assert _count(kernel, schema_workflow.predictions) == 0
    assert _count(kernel, schema_workflow.adjudications) == 0


def test_issue_without_source_provenance_is_quarantined(
    tmp_path: Path, kernel, importer: LegacyOperatorImporter
) -> None:
    payload = json.loads((FIXTURES / "26113-issue.json").read_text("utf-8"))
    payload["sources"] = []
    path = tmp_path / "26113-issue.json"
    path.write_text(json.dumps(payload), "utf-8")

    result = importer.import_path(
        path,
        contract_version=LEGACY_ISSUE_CONTRACT,
        imported_at=NOW,
    )

    assert isinstance(result, LegacyQuarantineReport)
    assert result.reason_code == "manifest_invalid"
    assert _count(kernel, schema.actions) == 0


def test_prep_record_with_undeclared_field_is_quarantined(
    tmp_path: Path, kernel, importer: LegacyOperatorImporter
) -> None:
    payload = json.loads((FIXTURES / "26113-prep.json").read_text("utf-8"))
    payload["records"]["1"]["undeclared_probe"] = "must not survive"
    path = tmp_path / "26113-prep.json"
    path.write_text(json.dumps(payload), "utf-8")

    result = importer.import_path(
        path,
        contract_version=LEGACY_PREP_CONTRACT,
        imported_at=NOW,
    )

    assert isinstance(result, LegacyQuarantineReport)
    assert result.reason_code == "manifest_invalid"
    assert _count(kernel, schema.actions) == 0


def test_prep_record_with_wrong_scalar_type_is_quarantined(
    tmp_path: Path, kernel, importer: LegacyOperatorImporter
) -> None:
    payload = json.loads((FIXTURES / "26113-prep.json").read_text("utf-8"))
    payload["records"]["1"]["ttg_anchor"] = "false"
    path = tmp_path / "26113-prep.json"
    path.write_text(json.dumps(payload), "utf-8")

    result = importer.import_path(
        path,
        contract_version=LEGACY_PREP_CONTRACT,
        imported_at=NOW,
    )

    assert isinstance(result, LegacyQuarantineReport)
    assert result.reason_code == "manifest_invalid"
    assert _count(kernel, schema.actions) == 0


def test_empty_candidate_faces_are_quarantined(
    tmp_path: Path, kernel, importer: LegacyOperatorImporter
) -> None:
    payload = json.loads((FIXTURES / "26116-rx.json").read_text("utf-8"))
    payload["ticket_versions"][0]["faces"] = {}
    payload["ticket_versions"][0]["drop"] = list(range(1, 15))
    path = tmp_path / "26116-rx.json"
    path.write_text(json.dumps(payload), "utf-8")

    result = importer.import_path(
        path,
        contract_version=LEGACY_RX_V3_CONTRACT,
        imported_at=NOW,
    )

    assert isinstance(result, LegacyQuarantineReport)
    assert result.reason_code == "manifest_invalid"
    assert _count(kernel, schema.actions) == 0


def test_import_receipt_is_durable_and_rebuildable_across_kernel_instances(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    first_kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    first_kernel.initialize()
    first_importer = LegacyOperatorImporter(
        artifact_ingest=first_kernel.artifact_ingest,
        workflow=first_kernel.workflow,
    )
    first = first_importer.import_path(
        FIXTURES / "26113-rx.json",
        contract_version=LEGACY_RX_V2_CONTRACT,
        imported_at=NOW,
    )
    assert isinstance(first, LegacyImportReceipt)

    with first_kernel.engine.connect() as connection:
        payload_json = connection.scalar(
            select(schema.actions.c.payload_json).where(
                schema.actions.c.action_id == first.source_action_id
            )
        )
    assert payload_json is not None
    durable = json.loads(payload_json)["legacy_import_receipt"]
    assert durable["prediction_count"] == 5
    assert durable["adjudication_committed_count"] == 4
    assert durable["workflow_action_ids"] == list(first.workflow_action_ids)
    assert durable["candidate_drafts"][0]["legacy_text"] == "sanitized summary"

    rebuilt_kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    rebuilt_importer = LegacyOperatorImporter(
        artifact_ingest=rebuilt_kernel.artifact_ingest,
        workflow=rebuilt_kernel.workflow,
    )
    replay = rebuilt_importer.import_path(
        FIXTURES / "26113-rx.json",
        contract_version=LEGACY_RX_V2_CONTRACT,
        imported_at=NOW.replace(hour=10),
    )

    assert replay == first


def test_malformed_json_quarantines_without_any_action(
    tmp_path: Path, kernel, importer: LegacyOperatorImporter
) -> None:
    path = tmp_path / "26113-rx.json"
    path.write_text("{", "utf-8")

    result = importer.import_path(
        path,
        contract_version=LEGACY_RX_V2_CONTRACT,
        imported_at=NOW,
    )

    assert isinstance(result, LegacyQuarantineReport)
    assert result.reason_code == "manifest_invalid"
    assert _count(kernel, schema.actions) == 0


def test_ambiguous_face_string_quarantines_whole_rx(
    tmp_path: Path, kernel, importer: LegacyOperatorImporter
) -> None:
    payload = json.loads((FIXTURES / "26116-rx.json").read_text("utf-8"))
    payload["ticket_versions"][1]["faces"]["1"] = "3/1"
    path = tmp_path / "26116-rx.json"
    path.write_text(json.dumps(payload), "utf-8")

    result = importer.import_path(
        path,
        contract_version=LEGACY_RX_V3_CONTRACT,
        imported_at=NOW,
    )

    assert isinstance(result, LegacyQuarantineReport)
    assert result.reason_code == "manifest_invalid"
    assert _count(kernel, schema.actions) == 0


def test_filename_issue_mismatch_is_quarantined_before_actions(
    tmp_path: Path, kernel, importer: LegacyOperatorImporter
) -> None:
    path = tmp_path / "99999-rx.json"
    path.write_bytes((FIXTURES / "26113-rx.json").read_bytes())

    result = importer.import_path(
        path,
        contract_version=LEGACY_RX_V2_CONTRACT,
        imported_at=NOW,
    )

    assert isinstance(result, LegacyQuarantineReport)
    assert result.reason_code == "issue_binding_mismatch"
    assert _count(kernel, schema.actions) == 0


def test_import_legacy_operator_cli_prints_one_machine_receipt(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    kernel.initialize()

    result = CliRunner().invoke(
        app,
        [
            "workflow",
            "import-legacy-operator",
            "--manifest",
            str(FIXTURES / "26113-rx.json"),
            "--contract-version",
            LEGACY_RX_V2_CONTRACT,
            "--data-dir",
            str(data_dir),
            "--imported-at",
            NOW.isoformat(),
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["kind"] == "legacy_import_receipt_v1"
    assert payload["business_key"] == "26113"
    assert payload["prediction_count"] == 5
    assert payload["adjudication_committed_count"] == 4
    assert payload["candidate_drafts"][0]["deployable"] is False


def test_import_legacy_operator_cli_default_time_replays_same_receipt(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    kernel.initialize()
    args = [
        "workflow",
        "import-legacy-operator",
        "--manifest",
        str(FIXTURES / "26113-rx.json"),
        "--contract-version",
        LEGACY_RX_V2_CONTRACT,
        "--data-dir",
        str(data_dir),
    ]

    first = CliRunner().invoke(app, args)
    second = CliRunner().invoke(app, args)

    assert first.exit_code == 0, first.stdout
    assert second.exit_code == 0, second.stdout
    assert json.loads(second.stdout) == json.loads(first.stdout)


def test_import_legacy_operator_cli_rejects_quarantine(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    kernel.initialize()

    result = CliRunner().invoke(
        app,
        [
            "workflow",
            "import-legacy-operator",
            "--manifest",
            str(FIXTURES / "26113-rx.json"),
            "--contract-version",
            "unknown",
            "--data-dir",
            str(data_dir),
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["kind"] == "legacy_quarantine_report_v1"
    assert payload["reason_code"] == "unknown_contract_version"
    assert _count(kernel, schema.actions) == 0
