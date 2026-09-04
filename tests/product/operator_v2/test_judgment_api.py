from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.operator_api import (
    CommitMatchJudgmentCommandV2,
    mount_operator_api,
)
from nutmeg.ontology.actions.models import (
    ActionOutcome,
    ActionStatus,
    ActorRole,
    ObjectRef,
)
from nutmeg.ontology.operator.decision_actions import OperatorDecisionActions
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.product.errors import ProductActionBlockedError
from nutmeg.product.operator_actions import OperatorActionService
from nutmeg.product.operator_contracts import (
    JudgeMatchesStep,
    OperatorCommandReceipt,
    OperatorLane,
    OperatorTaskState,
)
from nutmeg.product.operator_lanes import SaleSlateSnapshot
from nutmeg.product.operator_queries import OperatorQueryService
from nutmeg.product.operator_tokens import (
    OperatorCommandKind,
    OperatorSnapshotTokenCodec,
    OperatorSnapshotTokenError,
    OperatorSnapshotTokenPayloadV1,
)
from nutmeg.product.repository import ProductReadRepository
from nutmeg.product.wiring import build_product_services
from tests.ontology.operator.test_judgment_actions import (
    _baseline_request,
    _create_baseline_and_envelope,
    _fixture,
    _judgment_request,
)

NOW = datetime(2026, 9, 4, 9, tzinfo=UTC)
KEY = b"package-six-api-signing-key-is-long-enough"


def _token(kind: OperatorCommandKind) -> str:
    return OperatorSnapshotTokenCodec(KEY).encode(
        OperatorSnapshotTokenPayloadV1(
            task_snapshot_hash="c" * 64,
            work_item_id="jczq:2026-09-04:wave:current",
            command_kind=kind,
            dependency_revision_ids=[
                "baseline:baseline-1",
                "bundle:bundle-1",
                "envelope:envelope-1",
            ],
        )
    )


class _Actions:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, str, ActorRole]] = []

    @staticmethod
    def _verify(command, expected: OperatorCommandKind) -> None:
        payload = OperatorSnapshotTokenCodec(KEY).decode(command.expected_snapshot_token)
        if payload.command_kind is not expected:
            raise OperatorSnapshotTokenError("invalid_request")

    def record_baseline_envelope(self, command, *, actor_id, actor_role):
        self._verify(command, OperatorCommandKind.RECORD_BASELINE_ENVELOPE)
        self.calls.append(("envelope", command, actor_id, actor_role))
        return OperatorCommandReceipt(
            command_kind="record_baseline_envelope",
            status="completed",
            task_key="jczq:2026-09-04",
        )

    def commit_match_judgment(self, command, *, actor_id, actor_role):
        self._verify(command, OperatorCommandKind.COMMIT_MATCH_JUDGMENT)
        self.calls.append(("judgment", command, actor_id, actor_role))
        return OperatorCommandReceipt(
            command_kind="commit_match_judgment",
            status="completed",
            task_key="jczq:2026-09-04",
        )

    def freeze_judgment_prescription(self, command, *, actor_id, actor_role):
        self._verify(command, OperatorCommandKind.FREEZE_JUDGMENT_PRESCRIPTION)
        self.calls.append(("prescription", command, actor_id, actor_role))
        return OperatorCommandReceipt(
            command_kind="freeze_judgment_prescription",
            status="completed",
            task_key="jczq:2026-09-04",
        )


def _client(actions: object) -> TestClient:
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


class _DecisionQueries:
    task_key = "jczq:2026-09-04"
    snapshot_hash = "c" * 64
    work_item_id = "jczq:2026-09-04:wave:current"
    dependencies = (
        "baseline:baseline-1",
        "bundle:bundle-1",
        "envelope:envelope-1",
    )

    @staticmethod
    def now() -> datetime:
        return NOW

    def baseline_envelope_context(self, task_key: str, *, as_of: datetime):
        assert task_key == self.task_key
        assert as_of == NOW
        return SimpleNamespace(
            task_key=task_key,
            task_snapshot_hash=self.snapshot_hash,
            work_item_id=self.work_item_id,
            dependency_revision_ids=self.dependencies,
            task_evidence_bundle_revision_id="bundle-1",
            expected_current_revision_no=3,
        )

    def match_judgment_context(
        self,
        task_key: str,
        official_match_no: str,
        market_code: str,
        *,
        as_of: datetime,
    ):
        assert (task_key, official_match_no, market_code, as_of) == (
            self.task_key,
            "001",
            "had",
            NOW,
        )
        return SimpleNamespace(
            task_key=task_key,
            task_snapshot_hash=self.snapshot_hash,
            work_item_id=self.work_item_id,
            dependency_revision_ids=self.dependencies,
            task_evidence_bundle_revision_id="bundle-1",
            market_prior_baseline_revision_id="baseline-1",
            baseline_envelope_revision_id="envelope-1",
            match_id="match-internal-1",
            official_offer_revision_id="offer-internal-1",
            market_definition_id="market-internal-had",
            prior=(
                ("3", "0.400000000000"),
                ("1", "0.300000000000"),
                ("0", "0.300000000000"),
            ),
            expected_current_revision_no=7,
        )

    def judgment_prescription_context(self, task_key: str, *, as_of: datetime):
        assert task_key == self.task_key
        assert as_of == NOW
        return SimpleNamespace(
            task_key=task_key,
            task_snapshot_hash=self.snapshot_hash,
            work_item_id=self.work_item_id,
            dependency_revision_ids=self.dependencies,
            task_evidence_bundle_revision_id="bundle-1",
            market_prior_baseline_revision_id="baseline-1",
            baseline_envelope_revision_id="envelope-1",
            judgment_revision_tokens=("opaque.judgment-1",),
            judgment_revision_ids=("judgment-internal-1",),
            expected_current_revision_no=5,
        )


class _DecisionActions:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def record_baseline_envelope(self, request) -> ActionOutcome:
        self.calls.append(("envelope", request))
        return ActionOutcome(
            action_id="action-envelope-1",
            action_type="record_baseline_envelope",
            status=ActionStatus.COMMITTED,
            result_refs=(ObjectRef("baseline_envelope_revision", "envelope-1"),),
        )

    def commit_operator_match_judgment(self, request) -> ActionOutcome:
        self.calls.append(("judgment", request))
        return ActionOutcome(
            action_id="action-judgment-1",
            action_type="commit_operator_match_judgment",
            status=ActionStatus.COMMITTED,
            result_refs=(
                ObjectRef("forecast_revision", "forecast-1"),
                ObjectRef(
                    "operator_match_judgment_revision",
                    "judgment-internal-1",
                ),
            ),
        )

    def freeze_judgment_prescription(self, request) -> ActionOutcome:
        self.calls.append(("prescription", request))
        return ActionOutcome(
            action_id="action-prescription-1",
            action_type="freeze_judgment_prescription",
            status=ActionStatus.COMMITTED,
            result_refs=(ObjectRef("judgment_prescription_revision", "prescription-1"),),
        )


def _real_actions() -> tuple[OperatorActionService, _DecisionActions]:
    decision_actions = _DecisionActions()
    service = OperatorActionService(
        queries=_DecisionQueries(),
        action_gateway=SimpleNamespace(),
        decision_actions=decision_actions,
        snapshot_tokens=OperatorSnapshotTokenCodec(KEY),
        clock=lambda: NOW,
    )
    return service, decision_actions


def _decision_token(kind: OperatorCommandKind) -> str:
    return OperatorSnapshotTokenCodec(KEY).encode(
        OperatorSnapshotTokenPayloadV1(
            task_snapshot_hash=_DecisionQueries.snapshot_hash,
            work_item_id=_DecisionQueries.work_item_id,
            command_kind=kind,
            dependency_revision_ids=list(_DecisionQueries.dependencies),
        )
    )


def _envelope_document(**updates: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "2",
        "kind": "record_baseline_envelope",
        "expected_snapshot_token": _token(OperatorCommandKind.RECORD_BASELINE_ENVELOPE),
        "idempotency_key": "browser:envelope:1",
        "task_key": "jczq:2026-09-04",
        "ticket_kind": "jczq_pass",
        "capital_cap_minor": 20000,
        "currency": "CNY",
        "maximum_ticket_count": 2,
        "offer_constraints": [
            {
                "official_match_no": "001",
                "market_code": "had",
                "allowed_face_bundles": [
                    {"bundle_code": "home", "face_codes": ["3"]},
                    {"bundle_code": "home_draw", "face_codes": ["3", "1"]},
                ],
                "omission_allowed": False,
            }
        ],
        "structure_templates": [
            {
                "kind": "jczq_pass",
                "structure_code": "single-1",
                "eligible_official_match_nos": ["001"],
                "pass_size": 1,
                "required_offer_count": 1,
                "maximum_groups": 1,
            }
        ],
        "maximum_exhaustive_candidate_count": 100,
    }
    document.update(updates)
    return document


def _judgment_document(**updates: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "2",
        "kind": "commit_match_judgment",
        "expected_snapshot_token": _token(OperatorCommandKind.COMMIT_MATCH_JUDGMENT),
        "idempotency_key": "browser:judgment:001:1",
        "task_key": "jczq:2026-09-04",
        "official_match_no": "001",
        "market_code": "had",
        "belief": [
            {"face_code": "3", "probability_decimal": "0.450000000000"},
            {"face_code": "1", "probability_decimal": "0.280000000000"},
            {"face_code": "0", "probability_decimal": "0.270000000000"},
        ],
        "factors": [
            {
                "factor_id": "factor-lineup-v1",
                "scope_key": "match:001",
                "evidence_ref_tokens": ["evidence:lineup:001"],
                "offsets": [
                    {"face_code": "3", "offset_probability_decimal": "0.050000000000"},
                    {"face_code": "1", "offset_probability_decimal": "-0.020000000000"},
                    {"face_code": "0", "offset_probability_decimal": "-0.030000000000"},
                ],
            }
        ],
        "expression_bundles": [{"bundle_code": "home_draw", "face_codes": ["3", "1"]}],
        "rule_ids": ["k"],
        "evidence_ref_tokens": ["evidence:lineup:001"],
        "falsifier": "首发阵容不再支持已登记的结构前提。",
        "rationale": "依据冻结证据登记本场判断。",
    }
    document.update(updates)
    return document


def test_envelope_command_uses_closed_nested_inputs_and_server_judge_role() -> None:
    actions = _Actions()
    response = _client(actions).post(
        "/api/v2/operator",
        json=_envelope_document(),
    )

    assert response.status_code == 200
    assert response.json()["command_kind"] == "record_baseline_envelope"
    kind, command, actor_id, actor_role = actions.calls[0]
    assert kind == "envelope"
    assert command.offer_constraints[0].allowed_face_bundles[1].face_codes == ["3", "1"]
    assert actor_id == "jun"
    assert actor_role is ActorRole.JUDGE_OPERATOR

    for field in ("actor_id", "actor_role", "policy_version", "baseline_revision_id"):
        rejected = _client(_Actions()).post(
            "/api/v2/operator",
            json=_envelope_document(**{field: "browser-controlled"}),
        )
        assert rejected.status_code == 422


def test_judgment_command_rejects_floats_anonymous_mappings_and_extra_fields() -> None:
    client = _client(_Actions())

    float_probability = _judgment_document()
    float_probability["belief"][0]["probability_decimal"] = 0.45  # type: ignore[index]
    anonymous_factor = _judgment_document(factors=[{"factor-lineup-v1": {"3": "0.050000000000"}}])
    extra_nested = _judgment_document()
    extra_nested["expression_bundles"][0]["confidence"] = 0.9  # type: ignore[index]

    for document in (float_probability, anonymous_factor, extra_nested):
        assert client.post("/api/v2/operator", json=document).status_code == 422


def test_judgment_and_prescription_commands_are_named_and_command_bound() -> None:
    actions = _Actions()
    client = _client(actions)

    judgment = client.post("/api/v2/operator", json=_judgment_document())
    prescription = client.post(
        "/api/v2/operator",
        json={
            "schema_version": "2",
            "kind": "freeze_judgment_prescription",
            "expected_snapshot_token": _token(OperatorCommandKind.FREEZE_JUDGMENT_PRESCRIPTION),
            "idempotency_key": "browser:prescription:1",
            "task_key": "jczq:2026-09-04",
            "judgment_revision_tokens": ["judgment:001:current"],
        },
    )
    cross_command = client.post(
        "/api/v2/operator",
        json=_judgment_document(
            expected_snapshot_token=_token(OperatorCommandKind.RECORD_BASELINE_ENVELOPE)
        ),
    )

    assert judgment.status_code == 200
    assert prescription.status_code == 200
    assert [call[0] for call in actions.calls] == ["judgment", "prescription"]
    assert all(call[3] is ActorRole.JUDGE_OPERATOR for call in actions.calls)
    assert cross_command.status_code == 422
    assert cross_command.json()["code"] == "invalid_request"


@pytest.mark.parametrize(
    "field",
    ["role", "request", "payload", "deterministic_system", "match_id"],
)
def test_judgment_command_has_no_authority_or_internal_id_escape_hatch(field: str) -> None:
    response = _client(_Actions()).post(
        "/api/v2/operator",
        json=_judgment_document(**{field: "browser-controlled"}),
    )

    assert response.status_code == 422


def test_real_service_delegates_envelope_with_server_resolved_lineage() -> None:
    service, decision_actions = _real_actions()
    response = _client(service).post(
        "/api/v2/operator",
        json=_envelope_document(
            expected_snapshot_token=_decision_token(OperatorCommandKind.RECORD_BASELINE_ENVELOPE)
        ),
    )

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "1",
        "command_kind": "record_baseline_envelope",
        "status": "completed",
        "task_key": "jczq:2026-09-04",
        "source_high_watermark": None,
        "projection_high_watermark": None,
    }
    kind, request = decision_actions.calls[0]
    assert kind == "envelope"
    assert request.task_evidence_bundle_revision_id == "bundle-1"
    assert request.work_item_id == _DecisionQueries.work_item_id
    assert request.actor_id == "jun"
    assert request.actor_role is ActorRole.JUDGE_OPERATOR
    assert request.offer_constraints[0].allowed_face_bundles[1].face_codes == (
        "3",
        "1",
    )
    assert request.expected_current_revision_no == 3


def test_real_service_resolves_match_ids_prior_and_forecast_cas() -> None:
    service, decision_actions = _real_actions()
    response = _client(service).post(
        "/api/v2/operator",
        json=_judgment_document(
            expected_snapshot_token=_decision_token(OperatorCommandKind.COMMIT_MATCH_JUDGMENT)
        ),
    )

    assert response.status_code == 200
    kind, request = decision_actions.calls[0]
    assert kind == "judgment"
    assert request.match_id == "match-internal-1"
    assert request.official_offer_revision_id == "offer-internal-1"
    assert request.market_definition_id == "market-internal-had"
    assert (
        tuple((item.face_code, item.probability_decimal) for item in request.prior)
        == _DecisionQueries()
        .match_judgment_context(
            "jczq:2026-09-04",
            "001",
            "had",
            as_of=NOW,
        )
        .prior
    )
    assert request.expected_current_revision_no == 7
    assert request.commitment_tier == "commit"
    assert request.factors[0].scope_key == "match-internal-1"


def test_real_service_rejects_factor_scope_outside_selected_match() -> None:
    service, decision_actions = _real_actions()
    response = _client(service).post(
        "/api/v2/operator",
        json=_judgment_document(
            expected_snapshot_token=_decision_token(OperatorCommandKind.COMMIT_MATCH_JUDGMENT),
            factors=[
                {
                    "factor_id": "factor-lineup-v1",
                    "scope_key": "match:999",
                    "evidence_ref_tokens": ["evidence:lineup:001"],
                    "offsets": [
                        {
                            "face_code": "3",
                            "offset_probability_decimal": "0.050000000000",
                        },
                        {
                            "face_code": "1",
                            "offset_probability_decimal": "-0.020000000000",
                        },
                        {
                            "face_code": "0",
                            "offset_probability_decimal": "-0.030000000000",
                        },
                    ],
                }
            ],
        ),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert decision_actions.calls == []


def test_real_service_resolves_opaque_judgment_tokens_for_prescription() -> None:
    service, decision_actions = _real_actions()
    response = _client(service).post(
        "/api/v2/operator",
        json={
            "schema_version": "2",
            "kind": "freeze_judgment_prescription",
            "expected_snapshot_token": _decision_token(
                OperatorCommandKind.FREEZE_JUDGMENT_PRESCRIPTION
            ),
            "idempotency_key": "browser:prescription:real:1",
            "task_key": "jczq:2026-09-04",
            "judgment_revision_tokens": ["opaque.judgment-1"],
        },
    )

    assert response.status_code == 200
    kind, request = decision_actions.calls[0]
    assert kind == "prescription"
    assert request.judgment_revision_ids == ("judgment-internal-1",)
    assert request.market_prior_baseline_revision_id == "baseline-1"
    assert request.baseline_envelope_revision_id == "envelope-1"
    assert request.expected_current_revision_no == 5


def test_real_service_rejects_stale_command_before_domain_action() -> None:
    service, decision_actions = _real_actions()
    stale = OperatorSnapshotTokenCodec(KEY).encode(
        OperatorSnapshotTokenPayloadV1(
            task_snapshot_hash="d" * 64,
            work_item_id=_DecisionQueries.work_item_id,
            command_kind=OperatorCommandKind.COMMIT_MATCH_JUDGMENT,
            dependency_revision_ids=list(_DecisionQueries.dependencies),
        )
    )
    response = _client(service).post(
        "/api/v2/operator",
        json=_judgment_document(expected_snapshot_token=stale),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "task_snapshot_changed"
    assert decision_actions.calls == []


def test_real_service_denies_non_judge_before_context_resolution() -> None:
    service, decision_actions = _real_actions()
    command = CommitMatchJudgmentCommandV2.model_validate(
        _judgment_document(
            expected_snapshot_token=_decision_token(OperatorCommandKind.COMMIT_MATCH_JUDGMENT)
        )
    )

    with pytest.raises(ProductActionBlockedError, match="judge_operator"):
        service.commit_match_judgment(
            command,
            actor_id="agent",
            actor_role=ActorRole.AI_ANALYST,
        )
    assert decision_actions.calls == []


def test_real_query_context_resolves_current_lineage_prior_and_opaque_tokens(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)
    codec = OperatorSnapshotTokenCodec(KEY)
    queries = OperatorQueryService(
        repository=SimpleNamespace(),
        product_queries=SimpleNamespace(),
        official_history_provider=lambda: [],
        clock=lambda: NOW,
        unit_of_work_factory=lambda: OntologyUnitOfWork(fixture.engine),
        snapshot_tokens=codec,
    )

    envelope = queries.baseline_envelope_context(
        "jczq:2026-09-04",
        as_of=NOW,
    )
    judgment = queries.match_judgment_context(
        "jczq:2026-09-04",
        "001",
        "had",
        as_of=NOW,
    )

    assert envelope.task_evidence_bundle_revision_id == fixture.task_bundle_revision_id
    assert envelope.market_prior_baseline_revision_id == baseline_id
    assert envelope.expected_current_revision_no == 1
    assert judgment.baseline_envelope_revision_id == envelope_id
    assert judgment.match_id == "match-1"
    assert judgment.official_offer_revision_id == "offer-revision-1"
    assert judgment.market_definition_id == "md-had"
    assert judgment.prior == (
        ("3", "0.400000000000"),
        ("1", "0.300000000000"),
        ("0", "0.300000000000"),
    )
    assert judgment.expected_current_revision_no == 0

    committed = fixture.decision_actions.commit_operator_match_judgment(
        _judgment_request(fixture, baseline_id, envelope_id)
    )
    judgment_id = next(
        ref.object_id
        for ref in committed.result_refs
        if ref.object_type == "operator_match_judgment_revision"
    )
    prescription = queries.judgment_prescription_context(
        "jczq:2026-09-04",
        as_of=NOW + timedelta(seconds=1),
    )

    assert prescription.judgment_revision_ids == (judgment_id,)
    assert prescription.expected_current_revision_no == 0
    assert prescription.judgment_revision_tokens != (judgment_id,)
    token_payload = codec.decode(prescription.judgment_revision_tokens[0])
    assert token_payload.command_kind is OperatorCommandKind.FREEZE_JUDGMENT_PRESCRIPTION
    assert token_payload.dependency_revision_ids == [f"judgment:{judgment_id}"]


def test_kernel_and_product_wiring_expose_one_operator_decision_action_service(
    tmp_path: Path,
) -> None:
    settings = AppSettings(
        data_dir=tmp_path / "data",
        operator_token_signing_key=KEY.decode("ascii"),
        _env_file=None,
    )
    kernel = build_ontology_kernel(settings)
    kernel.initialize()

    assert isinstance(kernel.decision_actions, OperatorDecisionActions)
    services = build_product_services(settings)
    assert services.operator_actions is not None
    assert services.operator_actions.decision_actions is services.kernel.decision_actions


def _task_queries(
    fixture,
    *,
    repository: object | None = None,
    legacy_fixture_adapter: object | None = None,
) -> OperatorQueryService:
    return OperatorQueryService(
        repository=repository or ProductReadRepository(fixture.engine),
        product_queries=SimpleNamespace(),
        official_history_provider=lambda: [],
        clock=lambda: NOW,
        legacy_fixture_adapter=legacy_fixture_adapter,
        unit_of_work_factory=lambda: OntologyUnitOfWork(fixture.engine),
        snapshot_tokens=OperatorSnapshotTokenCodec(KEY),
    )


def _seed_task_identity(fixture) -> None:
    recorded_at = NOW - timedelta(hours=1)
    with fixture.engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO competitions "
            "(competition_id, name, country, kind) VALUES "
            "('competition-1', 'Test League', 'Testland', 'league')"
        )
        connection.exec_driver_sql(
            "INSERT INTO competition_editions "
            "(competition_edition_id, competition_id, name, country, format, "
            "season_label, stage, valid_from, valid_to) VALUES "
            "('edition-1', 'competition-1', 'Test League 2026', 'Testland', "
            "'league', '2026', NULL, ?, NULL)",
            (recorded_at.isoformat(),),
        )
        for suffix, name in (("home", "Home FC"), ("away", "Away FC")):
            connection.exec_driver_sql(
                "INSERT INTO teams "
                "(team_id, team_kind, canonical_name, country, resolution_status, "
                "created_at) VALUES (?, 'club', ?, 'Testland', 'resolved', ?)",
                (f"team-{suffix}", name, recorded_at.isoformat()),
            )
        connection.exec_driver_sql(
            "INSERT INTO match_revisions "
            "(match_revision_id, match_id, version, competition_edition_id, scheduled_at, "
            "schedule_status, venue_id, status, round_label, recorded_at, "
            "supersedes_revision_id) VALUES "
            "('match-revision-1', 'match-1', 1, 'edition-1', ?, 'confirmed', NULL, "
            "'scheduled', 'Round 1', ?, NULL)",
            ((recorded_at + timedelta(hours=3)).isoformat(), recorded_at.isoformat()),
        )
        connection.exec_driver_sql(
            "UPDATE matches SET current_revision_id = 'match-revision-1' WHERE match_id = 'match-1'"
        )
        for suffix, side in (("home", "home"), ("away", "away")):
            connection.exec_driver_sql(
                "INSERT INTO team_appearances "
                "(team_appearance_id, match_id, team_id, side) VALUES (?, 'match-1', ?, ?)",
                (f"appearance-{suffix}", f"team-{suffix}", side),
            )


def test_public_task_advances_through_current_formal_judgment_phases(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    _seed_task_identity(fixture)
    baseline = fixture.decision_actions.freeze_market_prior_baseline(_baseline_request(fixture))
    queries = _task_queries(fixture)
    codec = OperatorSnapshotTokenCodec(KEY)

    envelope_task = queries.task("jczq:2026-09-04", as_of=NOW)

    assert envelope_task.selected.state is OperatorTaskState.JUDGE_MATCHES
    assert isinstance(envelope_task.step, JudgeMatchesStep)
    assert envelope_task.step.mode == "baseline_envelope"
    assert envelope_task.progress.completed == 0
    assert envelope_task.progress.total == 1
    envelope_token = codec.decode(envelope_task.step.envelope_command_token or "")
    assert envelope_token.command_kind is OperatorCommandKind.RECORD_BASELINE_ENVELOPE
    assert f"baseline:{baseline.result_refs[0].object_id}" in envelope_token.dependency_revision_ids

    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)
    judgment_task = queries.task("jczq:2026-09-04", as_of=NOW)

    assert isinstance(judgment_task.step, JudgeMatchesStep)
    assert judgment_task.step.mode == "match_judgment"
    assert judgment_task.step.completed_match_count == 0
    assert judgment_task.step.required_match_count == 1
    assert judgment_task.step.editor is not None
    assert judgment_task.step.editor.official_match_no == "001"
    assert [face.prior_probability_decimal for face in judgment_task.step.editor.faces] == [
        "0.400000000000",
        "0.300000000000",
        "0.300000000000",
    ]
    judgment_token = codec.decode(judgment_task.step.judgment_command_token or "")
    assert judgment_token.command_kind is OperatorCommandKind.COMMIT_MATCH_JUDGMENT

    fixture.decision_actions.commit_operator_match_judgment(
        _judgment_request(fixture, baseline_id, envelope_id)
    )
    prescription_task = queries.task(
        "jczq:2026-09-04",
        as_of=NOW + timedelta(seconds=1),
    )

    assert isinstance(prescription_task.step, JudgeMatchesStep)
    assert prescription_task.step.mode == "prescription_ready"
    assert prescription_task.progress.completed == 1
    assert prescription_task.progress.total == 1
    assert prescription_task.step.judgment_revision_tokens
    prescription_token = codec.decode(prescription_task.step.prescription_command_token or "")
    assert prescription_token.command_kind is OperatorCommandKind.FREEZE_JUDGMENT_PRESCRIPTION


class _ZucaiSlateRepository:
    def __init__(self, delegate: ProductReadRepository) -> None:
        self._delegate = delegate

    def operator_sale_slates(self, *, as_of: str) -> tuple[SaleSlateSnapshot, ...]:
        (slate,) = self._delegate.operator_sale_slates(as_of=as_of)
        (offer,) = slate.offers
        return (
            replace(
                slate,
                offers=tuple(
                    replace(
                        offer,
                        official_offer_family_id=f"zucai-family-{index}",
                        official_offer_revision_id=f"zucai-offer-{index}",
                        official_match_no=str(index),
                    )
                    for index in range(1, 15)
                ),
            ),
        )

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)


class _ForbiddenLegacyAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def load_optional(self, _issue: str):
        self.calls += 1
        raise AssertionError("formal judgment lineage must precede legacy rx loading")


def _convert_fixture_to_zucai(fixture) -> None:
    with fixture.engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER operator_evidence_freeze_request_no_update")
        connection.exec_driver_sql("DROP TRIGGER task_evidence_bundle_revision_no_update")
        connection.exec_driver_sql(
            "UPDATE official_sale_slate_revisions SET slate_family_id = 'zucai:26116', "
            "lane = 'zucai', business_key = '26116' WHERE slate_revision_id = 'slate-1'"
        )
        connection.exec_driver_sql(
            "UPDATE official_offer_families SET lane = 'zucai', business_key = '26116', "
            "official_match_no = '1' WHERE official_offer_family_id = 'offer-family-1'"
        )
        connection.exec_driver_sql(
            "UPDATE official_offer_revisions SET official_match_no = '1' "
            "WHERE official_offer_revision_id = 'offer-revision-1'"
        )
        connection.exec_driver_sql(
            "UPDATE operator_evidence_freeze_requests SET task_family_id = 'zucai:26116', "
            "lane = 'zucai', business_key = '26116'"
        )
        connection.exec_driver_sql(
            "UPDATE operator_task_evidence_bundle_revisions SET "
            "task_family_id = 'zucai:26116', lane = 'zucai', business_key = '26116'"
        )


def test_zucai_public_task_does_not_fall_back_while_baseline_job_is_pending(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    _convert_fixture_to_zucai(fixture)
    legacy = _ForbiddenLegacyAdapter()

    task = _task_queries(
        fixture,
        repository=_ZucaiSlateRepository(ProductReadRepository(fixture.engine)),
        legacy_fixture_adapter=legacy,
    ).task("zucai:26116", as_of=NOW)

    assert task.selected.state is OperatorTaskState.PREPARE
    assert legacy.calls == 0


def test_zucai_public_task_prefers_formal_judgment_over_legacy_rx(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    _convert_fixture_to_zucai(fixture)
    fixture.decision_actions.freeze_market_prior_baseline(_baseline_request(fixture))
    legacy = _ForbiddenLegacyAdapter()
    repository = _ZucaiSlateRepository(ProductReadRepository(fixture.engine))

    task = _task_queries(
        fixture,
        repository=repository,
        legacy_fixture_adapter=legacy,
    ).task("zucai:26116", as_of=NOW)

    assert task.selected.lane is OperatorLane.ZUCAI
    assert isinstance(task.step, JudgeMatchesStep)
    assert task.step.mode == "baseline_envelope"
    assert legacy.calls == 0
