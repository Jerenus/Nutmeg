from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from typer.testing import CliRunner

from nutmeg.interfaces.cli import app as cli_app
from nutmeg.interfaces.operator_api import mount_operator_api
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.protected_ticket_actions import ProtectedTicketActions
from nutmeg.ontology.actions.workflow_actions import WorkflowActions
from nutmeg.ontology.artifacts import ContentAddressedArtifactStore
from nutmeg.ontology.operator.decision_actions import SelectTicketCandidateRequest
from nutmeg.ontology.operator.result_actions import CandidateAuditFindingInput
from nutmeg.ontology.repository.finance import CashAccountRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.actions import ProductActionGateway
from nutmeg.product.operator_actions import OperatorActionService
from nutmeg.product.operator_contracts import (
    AuditDeploymentStep,
    ConfirmationStep,
    OperatorLane,
)
from nutmeg.product.operator_tokens import OperatorCommandKind, OperatorSnapshotTokenCodec
from nutmeg.product.operator_workers import CandidateGenerationWorker, audit_current_candidate
from tests.ontology.operator.test_candidate_actions import (
    _candidate,
    _generate,
    _generation_request,
)
from tests.ontology.operator.test_lineage_actions import (
    _create_operator_batch,
    _persisted_current_audit,
    _setup_override_fixture,
)
from tests.product.operator_v2.test_candidate_queries import _ready_queries
from tests.product.operator_v2.test_judgment_api import KEY, NOW, _seed_task_identity, _task_queries


def _replay_workspace(tmp_path: Path) -> Path:
    replay_root = os.environ.get("NUTMEG_P8_REPLAY_ROOT")
    replay_base = tmp_path if replay_root is None else Path(replay_root)
    workspace = replay_base / "data" / "ontology"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def _selected_fixture(tmp_path: Path, *, judgment_candidate=None):
    fixture, queries = _ready_queries(tmp_path)
    requested = fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(fixture)
    )
    _generate(
        fixture,
        request_id=requested.result_refs[0].object_id,
        judgment_candidate=judgment_candidate,
    )
    comparison = queries.task("jczq:2026-09-04", as_of=NOW)
    candidate_set = next(
        item for item in comparison.step.candidate_sets if not item.comparison_only
    )
    candidate_token = candidate_set.candidates[0].candidate_token
    assert candidate_token is not None
    context = queries.candidate_selection_context(
        "jczq:2026-09-04",
        candidate_token,
        as_of=NOW,
    )
    selected = fixture.judgment.decision_actions.select_ticket_candidate(
        SelectTicketCandidateRequest(
            candidate_set_revision_id=context.candidate_set_revision_id,
            candidate_revision_id=context.candidate_revision_id,
            reason="Jun selected the candidate for protected materialization.",
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="deployment-replay:selection:1",
            requested_at=NOW + timedelta(seconds=1),
            expected_current_revision_no=context.expected_current_revision_no,
        )
    )
    with OntologyUnitOfWork(fixture.judgment.engine) as uow:
        uow.finance.ensure_account(CashAccountRow("acct-jczq", "jczq", "CNY", "active"))
    return fixture, queries, selected.result_refs[0].object_id


def _client(fixture, queries, tmp_path: Path, *, clock=None) -> TestClient:
    clock_fn = clock or (lambda: NOW + timedelta(seconds=2))
    protected = ProtectedTicketActions(
        fixture.judgment.action_service,
        ContentAddressedArtifactStore(tmp_path / "approved-artifacts"),
        operator_decisions=fixture.judgment.decision_actions,
        operator_candidate_auditor=audit_current_candidate,
    )
    actions = OperatorActionService(
        queries=queries,
        action_gateway=ProductActionGateway(
            type("Kernel", (), {"workflow": WorkflowActions(fixture.judgment.action_service)})(),
            object(),
            clock=clock_fn,
        ),
        decision_actions=fixture.judgment.decision_actions,
        protected_tickets=protected,
        snapshot_tokens=OperatorSnapshotTokenCodec(KEY),
        clock=clock_fn,
    )
    app = FastAPI()

    async def allow(_request) -> None:
        return None

    mount_operator_api(
        app,
        require_mutation_session=allow,
        operator_actions=actions,
        actor_id="jun",
    )
    return TestClient(app)


def _command(step: AuditDeploymentStep, kind: str, **fields: object) -> dict[str, object]:
    return {
        "schema_version": "2",
        "kind": kind,
        "expected_snapshot_token": step.command_token,
        "idempotency_key": f"deployment-replay:{kind}:1",
        "task_key": "jczq:2026-09-04",
        **fields,
    }


def _adjudicate_current_warns(
    client: TestClient,
    queries,
    step: AuditDeploymentStep,
) -> AuditDeploymentStep:
    if step.mode != "adjudicate_audit_warn":
        return step
    response = client.post(
        "/api/v2/operator",
        json=_command(
            step,
            "adjudicate_audit_warn",
            ticket_batch_token=step.ticket_batch_token,
            findings=[
                {
                    "finding_token": finding.finding_token,
                    "reason": "Jun explicitly accepts this disclosed deterministic warning.",
                    "evidence_rejected_tokens": [],
                }
                for finding in step.findings
                if finding.severity == "warn"
            ],
        ),
    )
    assert response.status_code == 200, response.text
    refreshed = queries.task("jczq:2026-09-04", as_of=NOW + timedelta(seconds=2))
    assert isinstance(refreshed.step, AuditDeploymentStep)
    return refreshed.step


def test_isolated_artifact_approval_public_api_replay(tmp_path: Path) -> None:
    tmp_path = _replay_workspace(tmp_path)
    fixture, queries, selection_id = _selected_fixture(tmp_path)
    client = _client(fixture, queries, tmp_path)
    codec = OperatorSnapshotTokenCodec(KEY)

    selected = queries.task(
        "jczq:2026-09-04",
        as_of=NOW + timedelta(seconds=2),
    )
    assert isinstance(selected.step, AuditDeploymentStep)
    assert selected.step.surface_version == "2"
    assert selected.step.mode == "create_ticket_batch"
    assert selected.step.candidate_selection_token is not None
    selection_token = codec.decode(selected.step.candidate_selection_token)
    assert selection_token.command_kind is OperatorCommandKind.CREATE_TICKET_BATCH
    assert selection_token.dependency_revision_ids == [f"selection:{selection_id}"]

    created = client.post(
        "/api/v2/operator",
        json=_command(
            selected.step,
            "create_ticket_batch",
            candidate_selection_token=selected.step.candidate_selection_token,
        ),
    )

    assert created.status_code == 200, created.text
    assert created.json() == {
        "schema_version": "1",
        "command_kind": "create_ticket_batch",
        "status": "completed",
        "task_key": "jczq:2026-09-04",
        "source_high_watermark": None,
        "projection_high_watermark": None,
        "navigation_href": "/operator-next/jczq/2026-09-04",
    }
    draft = queries.task(
        "jczq:2026-09-04",
        as_of=NOW + timedelta(seconds=2),
    )
    assert isinstance(draft.step, AuditDeploymentStep)
    draft_step = _adjudicate_current_warns(client, queries, draft.step)
    assert draft_step.mode == "approve_ticket_batch"
    assert draft_step.ticket_batch_token is not None

    approved = client.post(
        "/api/v2/operator",
        json=_command(
            draft_step,
            "approve_ticket_batch",
            ticket_batch_token=draft_step.ticket_batch_token,
        ),
    )

    assert approved.status_code == 200, approved.text
    projected = queries.task_v2(
        OperatorLane.JCZQ,
        "2026-09-04",
        as_of=NOW + timedelta(seconds=2),
    )
    artifact_items = [
        item for item in projected.work_items if item.scope_kind == "artifact"
    ]
    assert len(artifact_items) == 1
    assert approved.json()["navigation_href"] == (
        f"/operator-next/jczq/2026-09-04/"
        f"{artifact_items[0].work_item_key}"
    )
    with OntologyUnitOfWork(fixture.judgment.engine) as uow:
        assert uow.tickets.count_batches() == 1
        assert uow.tickets.count_artifacts() == 1
        assert uow.tickets.count_placements() == 0
        lineage = uow.operator_result.ticket_decision_lineage_for_batch(
            codec.decode(draft_step.ticket_batch_token).dependency_revision_ids[0].removeprefix(
                "ticket_batch_revision:"
            )
        )
        assert lineage is not None
        assert lineage.candidate_selection_id == selection_id


def test_isolated_no_ticket_exact_cutoff_public_api_replay(tmp_path: Path) -> None:
    tmp_path = _replay_workspace(tmp_path)
    fixture, queries, _selection_id = _selected_fixture(tmp_path)
    clock = [NOW + timedelta(seconds=2)]
    client = _client(fixture, queries, tmp_path, clock=lambda: clock[0])

    selected = queries.task("jczq:2026-09-04", as_of=clock[0])
    assert isinstance(selected.step, AuditDeploymentStep)
    created = client.post(
        "/api/v2/operator",
        json=_command(
            selected.step,
            "create_ticket_batch",
            candidate_selection_token=selected.step.candidate_selection_token,
        ),
    )
    assert created.status_code == 200, created.text
    draft = queries.task("jczq:2026-09-04", as_of=clock[0])
    assert isinstance(draft.step, AuditDeploymentStep)
    draft_step = _adjudicate_current_warns(client, queries, draft.step)
    assert draft_step.mode == "approve_ticket_batch"
    approved = client.post(
        "/api/v2/operator",
        json=_command(
            draft_step,
            "approve_ticket_batch",
            ticket_batch_token=draft_step.ticket_batch_token,
        ),
    )
    assert approved.status_code == 200, approved.text
    task = queries.task_v2(
        OperatorLane.JCZQ,
        "2026-09-04",
        as_of=clock[0],
    )
    artifacts = [item for item in task.work_items if item.scope_kind == "artifact"]
    assert len(artifacts) == 1
    ready = queries.work_item_v2(
        OperatorLane.JCZQ,
        "2026-09-04",
        artifacts[0].work_item_key,
        as_of=clock[0],
    )
    assert isinstance(ready.step, ConfirmationStep)
    assert ready.no_ticket is not None

    with OntologyUnitOfWork(fixture.judgment.engine) as uow:
        artifact_id = uow.connection.execute(
            text("SELECT ticket_artifact_id FROM audited_ticket_artifacts LIMIT 1")
        ).scalar_one()
        artifact = uow.tickets.ticket_artifact(artifact_id)
        assert artifact is not None
        binding = uow.tickets.protected_artifact_binding(artifact.ticket_artifact_id)
        assert binding is not None
        cutoff = datetime.fromisoformat(binding.frozen_deadline_at)
    clock[0] = cutoff

    response = client.post(
        "/api/v2/operator",
        json=_command(
            ready.step,
            "record_no_ticket",
            expected_snapshot_token=ready.no_ticket.command_token,
            reason_code="operator_discretion",
            reason_basis="operator_judgment",
            reason_text="Jun explicitly closes the still-open scope.",
            rule_tokens=[],
            comparison_candidate_token=ready.no_ticket.comparison_candidate_token,
        ),
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "task_snapshot_changed"
    with OntologyUnitOfWork(fixture.judgment.engine) as uow:
        terminal = uow.tickets.artifact_terminal_receipt(artifact.ticket_artifact_id)
        counts = uow.connection.execute(
            text(
                "SELECT "
                "(SELECT COUNT(*) FROM operator_no_ticket_revisions), "
                "(SELECT COUNT(*) FROM operator_no_ticket_command_receipts), "
                "(SELECT COUNT(*) FROM tickets), "
                "(SELECT COUNT(*) FROM cash_transactions)"
            )
        ).one()
        receipt = uow.operator_result.no_ticket_command_receipt_for_action(
            uow.connection.execute(
                text(
                    "SELECT action_id FROM actions "
                    "WHERE action_type = 'record_no_ticket' ORDER BY rowid DESC LIMIT 1"
                )
            ).scalar_one()
        )
    assert terminal is not None
    assert terminal.terminal_kind == "shadow"
    assert terminal.terminal_reason == "confirmation_not_requested"
    assert counts == (0, 1, 0, 0)
    assert receipt is not None
    assert receipt.result == "task_snapshot_changed"


def test_pre_candidate_no_ticket_uses_the_public_api(tmp_path: Path) -> None:
    tmp_path = _replay_workspace(tmp_path)
    fixture, queries = _ready_queries(tmp_path)
    client = _client(fixture, queries, tmp_path)
    task = queries.task("jczq:2026-09-04", as_of=NOW)
    assert task.no_ticket is not None
    assert task.no_ticket.state == "available"

    response = client.post(
        "/api/v2/operator",
        json={
            "schema_version": "2",
            "kind": "record_no_ticket",
            "expected_snapshot_token": task.no_ticket.command_token,
            "idempotency_key": "deployment-replay:pre-candidate-no-ticket:1",
            "task_key": "jczq:2026-09-04",
            "reason_code": "operator_discretion",
            "reason_basis": "operator_judgment",
            "reason_text": "Jun explicitly closes this pre-candidate sale wave.",
            "rule_tokens": [],
            "comparison_candidate_token": None,
        },
    )

    assert response.status_code == 200, response.text
    with OntologyUnitOfWork(fixture.judgment.engine) as uow:
        revisions = uow.operator_result.current_no_ticket_revisions_for_task_family(
            "jczq:2026-09-04"
        )
        assert len(revisions) == 1
        assert revisions[0].phase == "envelope"
        assert uow.tickets.count_placements() == 0


def test_isolated_no_ticket_and_explicit_reopen_public_api_replay(tmp_path: Path) -> None:
    tmp_path = _replay_workspace(tmp_path)
    fixture, queries, _selection_id = _selected_fixture(tmp_path)
    clock = [NOW + timedelta(seconds=2)]
    client = _client(fixture, queries, tmp_path, clock=lambda: clock[0])
    selected = queries.task("jczq:2026-09-04", as_of=clock[0])
    assert isinstance(selected.step, AuditDeploymentStep)
    assert selected.step.no_ticket_command_token is not None

    recorded = client.post(
        "/api/v2/operator",
        json=_command(
            selected.step,
            "record_no_ticket",
            expected_snapshot_token=selected.step.no_ticket_command_token,
            reason_code="operator_discretion",
            reason_basis="operator_judgment",
            reason_text="Jun explicitly closes this remaining sale-wave scope.",
            rule_tokens=[],
            comparison_candidate_token=selected.step.comparison_candidate_token,
        ),
    )

    assert recorded.status_code == 200, recorded.text
    closed = queries.task("jczq:2026-09-04", as_of=clock[0])
    assert isinstance(closed.step, AuditDeploymentStep)
    assert closed.step.mode == "supersede_no_ticket"
    assert closed.step.command_token is not None
    assert closed.step.no_ticket_revision_token is not None
    superseded = client.post(
        "/api/v2/operator",
        json=_command(
            closed.step,
            "supersede_no_ticket",
            expected_snapshot_token=closed.step.command_token,
            no_ticket_revision_token=closed.step.no_ticket_revision_token,
            reason_text="Jun explicitly reopens the still-upcoming offer scope.",
        ),
    )

    assert superseded.status_code == 200, superseded.text
    reopened = queries.task("jczq:2026-09-04", as_of=clock[0])
    assert isinstance(reopened.step, AuditDeploymentStep)
    assert reopened.step.mode == "create_ticket_batch"
    with OntologyUnitOfWork(fixture.judgment.engine) as uow:
        revisions = uow.connection.execute(
            text(
                "SELECT deployment_outcome FROM operator_no_ticket_revisions "
                "ORDER BY recorded_at, revision_no"
            )
        ).scalars().all()
        counts = uow.connection.execute(
            text(
                "SELECT "
                "(SELECT COUNT(*) FROM audited_ticket_artifacts), "
                "(SELECT COUNT(*) FROM tickets), "
                "(SELECT COUNT(*) FROM cash_transactions)"
            )
        ).one()
    assert revisions == ["no_ticket", "reopened"]
    assert counts == (0, 0, 0)


def test_isolated_override_cli_regeneration_replay(tmp_path: Path, monkeypatch) -> None:
    tmp_path = _replay_workspace(tmp_path)
    monkeypatch.setenv(
        "NUTMEG_OPERATOR_TOKEN_SIGNING_KEY",
        "operator-audit-token-key-with-at-least-32-bytes",
    )
    candidate = replace(
        _candidate(set_kind="judgment_bound", content_hash="e" * 64),
        partition="audit_blocked",
        rank=None,
        deployable=False,
        audit_findings=(
            CandidateAuditFindingInput(
                finding_id="legs:001:low-confidence",
                audit_kind="legs",
                code="low_conf_single",
                severity="ERROR",
                message="single has insufficient confidence",
                official_match_no="001",
                rule_id="conf",
            ),
        ),
    )
    fixture = _setup_override_fixture(tmp_path, judgment_candidate=candidate)
    with fixture.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE official_offer_revisions SET sale_deadline_at = :deadline_at "
                "WHERE official_offer_revision_id = 'offer-revision-1'"
            ),
            {"deadline_at": (datetime.now().astimezone() + timedelta(hours=1)).isoformat()},
        )
    legs_file = tmp_path / "override-legs.json"
    legs_file.write_text(
        json.dumps(
            {
                "issue": "2026-09-04",
                "prescription": {"1": "3"},
                "deviation_registry": [
                    {
                        "match_no": 1,
                        "rule_ids": ["conf"],
                        "reason": "Jun explicitly accepts the disclosed confidence risk.",
                        "user_override": True,
                    }
                ],
                "legs": {
                    "1": {
                        "name": "Home FC - Away FC",
                        "faces": "3",
                        "fair": {"home": 0.4, "draw": 0.3, "away": 0.3},
                        "confidence": 3,
                        "anchor_integrity": "pass",
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli_app,
        [
            "decision-audit-legs",
            "--legs-file",
            str(legs_file),
            "--user-override",
            "--ticket-batch-token",
            fixture.batch_token,
            "--data-dir",
            str(tmp_path.parent),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "user override 已入账：1 个 ERROR -> 1 条 Adjudication" in result.stdout
    completed = CandidateGenerationWorker(
        action_service=fixture.action_service,
        result_actions=fixture.candidate_fixture.result_actions,
        worker_id="p8-override-replay-worker",
        lease_duration=timedelta(minutes=5),
    ).run_once(limit=1, as_of=datetime.now().astimezone())
    assert len(completed) == 1
    with OntologyUnitOfWork(fixture.engine) as uow:
        counts = uow.connection.execute(
            text(
                "SELECT "
                "(SELECT COUNT(*) FROM adjudications), "
                "(SELECT COUNT(*) FROM operator_ticket_audit_override_receipts), "
                "(SELECT COUNT(*) FROM operator_candidate_generation_override_links), "
                "(SELECT COUNT(*) FROM operator_candidate_set_revisions), "
                "(SELECT COUNT(*) FROM tickets), "
                "(SELECT COUNT(*) FROM cash_transactions)"
            )
        ).one()
    assert counts == (1, 1, 1, 4, 0, 0)

    with OntologyUnitOfWork(fixture.engine) as uow:
        candidate_set = uow.operator_result.current_candidate_set(
            task_family_id="jczq:2026-09-04",
            work_item_id="jczq:2026-09-04:wave:current",
            set_kind="judgment_bound",
        )
        assert candidate_set is not None
        regenerated_candidate = uow.operator_result.candidates_for_set(
            candidate_set.candidate_set_revision_id
        )[0]
    selected = fixture.actions.select_ticket_candidate(
        SelectTicketCandidateRequest(
            candidate_set_revision_id=candidate_set.candidate_set_revision_id,
            candidate_revision_id=regenerated_candidate.candidate_revision_id,
            reason="Jun explicitly reselects the overridden regenerated candidate.",
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="deployment-replay:override:reselect",
            requested_at=NOW + timedelta(seconds=13),
            expected_current_revision_no=1,
        )
    )
    protected = ProtectedTicketActions(
        fixture.action_service,
        ContentAddressedArtifactStore(tmp_path / "regenerated-artifacts"),
        operator_decisions=fixture.actions,
        operator_candidate_auditor=audit_current_candidate,
    )
    _create_operator_batch(
        protected,
        selected.result_refs[0].object_id,
        key="deployment-replay:override:fresh-batch",
    )
    _seed_task_identity(fixture.candidate_fixture.judgment)
    queries = _task_queries(
        fixture.candidate_fixture.judgment,
        operator_candidate_auditor=_persisted_current_audit,
    )

    refreshed = queries.task(
        "jczq:2026-09-04",
        as_of=NOW + timedelta(seconds=14),
    )

    assert isinstance(refreshed.step, AuditDeploymentStep)
    assert refreshed.step.audit_state == "pass"
    assert refreshed.step.mode == "approve_ticket_batch"
