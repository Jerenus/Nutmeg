import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import insert

from nutmeg.decision.zucai_official import OfficialRenjiuHistory
from nutmeg.ontology.repository import schema_workflow as sw
from nutmeg.product.errors import ProductNotFoundError
from nutmeg.product.operator_artifacts import ZucaiArtifactRepository
from nutmeg.product.operator_queries import OperatorQueryService
from nutmeg.product.repository import ProductReadRepository
from tests.product.operator_fixtures import write_26112_bundle

NOW = datetime(2026, 8, 28, 10, tzinfo=UTC)


@dataclass
class FakeRepository:
    adjudications: dict[str, list[dict]] = field(default_factory=dict)
    predictions: dict[str, list[dict]] = field(default_factory=dict)
    tickets: list[dict] = field(default_factory=list)
    settlement_rows: list[dict] = field(default_factory=list)

    def adjudications_for_subject(self, subject_type: str, subject_id: str, as_of: str):
        assert subject_type == "issue"
        return list(self.adjudications.get(subject_id, []))

    def predictions_for_subject(self, subject_type: str, subject_id: str, as_of: str):
        assert subject_type == "issue"
        return list(self.predictions.get(subject_id, []))

    def operator_ticket_artifacts(self, as_of: str):
        return list(self.tickets)

    def settlements(self, *, as_of: str):
        return list(self.settlement_rows)


class FakeProductQueries:
    def scoreboard(self, *, as_of: datetime):
        return SimpleNamespace(
            authority=SimpleNamespace(state="legacy"),
            health=SimpleNamespace(state="available", code=None),
        )

    def review(self, *, as_of: datetime):
        return SimpleNamespace(settlements=[])


def _history() -> list[OfficialRenjiuHistory]:
    return [
        OfficialRenjiuHistory(str(issue), "2026-08-20", 64, 1000.0, 100000.0)
        for issue in (26109, 26110, 26111)
    ]


@pytest.fixture
def artifact_root(tmp_path: Path) -> Path:
    root = write_26112_bundle(tmp_path / "zucai")
    (root / "26113-rx.json").write_text("{", "utf-8")
    return root


@pytest.fixture
def repository() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def operator_queries(artifact_root: Path, repository: FakeRepository) -> OperatorQueryService:
    return OperatorQueryService(
        repository=repository,
        product_queries=FakeProductQueries(),
        artifacts=ZucaiArtifactRepository(artifact_root),
        official_history_provider=_history,
        clock=lambda: NOW,
    )


def _record(
    repository: FakeRepository,
    alternative: dict,
    *,
    created_at: str = "2026-08-28T09:00:00+00:00",
) -> None:
    rows = repository.adjudications.setdefault("26112", [])
    rows.append(
        {
            "adjudication_id": f"adj-{len(rows) + 1}",
            "subject_type": "issue",
            "subject_id": "26112",
            "decision": "record",
            "actor_id": "operator:owner",
            "reason": "fixture",
            "evidence_rejected": [],
            "alternative": alternative,
            "created_at": created_at,
            "supersedes_adjudication_id": None,
        }
    )


def test_26112_query_selects_unresolved_adjudication(operator_queries) -> None:
    response = operator_queries.task("zucai:26112", as_of=NOW)

    assert response.selected.task_id == "zucai:26112"
    assert response.selected.state == "judge_matches"
    assert response.step.kind == "judge_matches"
    assert response.step.item_key == "ADJ-1"
    assert response.step.evidence[0].label == "资金"
    assert response.progress.completed == 0
    assert response.progress.total == 1


def test_query_computes_candidate_rows_without_parsing_rx_prose(
    operator_queries: OperatorQueryService, repository: FakeRepository
) -> None:
    _record(repository, {"rx_adjudication_id": "ADJ-1", "selected_option": "R432"})

    response = operator_queries.task("zucai:26112", as_of=NOW)

    assert response.step.kind == "construct_ticket"
    assert [item.candidate_id for item in response.step.candidates] == ["R432"]
    assert response.step.candidates[0].notes == 3
    assert response.step.candidates[0].cost_yuan == 6
    assert "human note" not in response.model_dump_json()


def test_selection_advances_to_audit_and_keeps_operator_choice(
    operator_queries: OperatorQueryService, repository: FakeRepository
) -> None:
    _record(repository, {"rx_adjudication_id": "ADJ-1", "selected_option": "R432"})
    _record(
        repository,
        {"candidate_id": "R432", "deviation_registry": []},
        created_at="2026-08-28T09:05:00+00:00",
    )

    response = operator_queries.task("zucai:26112", as_of=NOW)

    assert response.step.kind == "audit_deployment"
    assert response.step.candidate.candidate_id == "R432"
    assert response.step.gate_candidate_id == "R432"
    assert response.step.allowed_decisions[0] == "keep"


def test_explicit_indistinguishability_allows_but_does_not_select_empty_position(
    operator_queries: OperatorQueryService, repository: FakeRepository
) -> None:
    _record(repository, {"rx_adjudication_id": "ADJ-1"})
    _record(
        repository,
        {"candidate_id": "R432", "materially_indistinguishable": True},
        created_at="2026-08-28T09:05:00+00:00",
    )

    task = operator_queries.task("zucai:26112", as_of=NOW)
    assert "empty_position" in task.step.allowed_decisions
    assert task.step.allowed_decisions[0] == "keep"


def test_keep_without_formal_binding_is_truthful_block(
    operator_queries: OperatorQueryService, repository: FakeRepository
) -> None:
    _record(repository, {"rx_adjudication_id": "ADJ-1"})
    _record(repository, {"candidate_id": "R432"}, created_at="2026-08-28T09:05:00+00:00")
    _record(
        repository,
        {"deployment_decision": "keep"},
        created_at="2026-08-28T09:10:00+00:00",
    )

    task = operator_queries.task("zucai:26112", as_of=NOW)
    assert task.step.kind == "blocked"
    assert task.step.recovery.code == "protected_artifact_missing"


def test_worklist_prefers_earliest_actionable_deadline(operator_queries) -> None:
    worklist = operator_queries.worklist(as_of=NOW)
    assert worklist.selected.task_id == "zucai:26112"
    assert [item.priority_rank for item in worklist.tasks] == list(range(len(worklist.tasks)))


def test_invalid_bundle_is_visible_block_not_exception(operator_queries) -> None:
    worklist = operator_queries.worklist(as_of=NOW)
    task = next(item for item in worklist.tasks if item.business_key == "26113")
    assert task.state == "blocked"
    assert task.block_reason_code == "source_contract_invalid"


def test_unknown_task_is_not_found(operator_queries) -> None:
    with pytest.raises(ProductNotFoundError):
        operator_queries.task("zucai:99999", as_of=NOW)


def test_empty_position_completes_but_is_not_auto_selected(
    operator_queries: OperatorQueryService, repository: FakeRepository
) -> None:
    _record(repository, {"rx_adjudication_id": "ADJ-1"})
    _record(repository, {"candidate_id": "R432"}, created_at="2026-08-28T09:05:00+00:00")
    _record(
        repository,
        {"deployment_decision": "empty_position"},
        created_at="2026-08-28T09:10:00+00:00",
    )

    worklist = operator_queries.worklist(as_of=NOW)
    task = next(item for item in worklist.tasks if item.task_id == "zucai:26112")
    assert task.state == "complete"
    assert worklist.selected is not None
    assert worklist.selected.task_id != task.task_id


def test_mutation_token_changes_only_when_committed_snapshot_changes(
    operator_queries: OperatorQueryService, repository: FakeRepository
) -> None:
    first = operator_queries.task("zucai:26112", as_of=NOW).mutation_token
    second = operator_queries.task("zucai:26112", as_of=NOW).mutation_token
    assert first == second

    _record(repository, {"rx_adjudication_id": "ADJ-1"})
    assert operator_queries.task("zucai:26112", as_of=NOW).mutation_token != first


def test_official_history_outage_is_retryable_recovery(
    operator_queries: OperatorQueryService, repository: FakeRepository
) -> None:
    _record(repository, {"rx_adjudication_id": "ADJ-1"})
    _record(repository, {"candidate_id": "R432"}, created_at="2026-08-28T09:05:00+00:00")

    def unavailable():
        raise RuntimeError("offline")

    operator_queries._official_history = unavailable
    task = operator_queries.task("zucai:26112", as_of=NOW)

    assert task.step.kind == "blocked"
    assert task.step.recovery.code == "official_history_unavailable"
    assert task.step.recovery.retry_at is not None


def test_gate_names_cap_candidate_without_relabeling_operator_choice(
    artifact_root: Path, repository: FakeRepository
) -> None:
    base_leg = {
        "name": "fixture",
        "confidence": 4,
        "directional_flags": [],
        "nondirectional_flags": [],
        "anchor_integrity": "pass",
        "fair": {"home": 0.5, "draw": 0.3, "away": 0.2},
        "precedents": [],
    }
    r432 = {
        "issue": "26112",
        "version": "operator choice",
        "legs": {str(index): {**base_leg, "faces": "31"} for index in range(1, 10)},
    }
    v288_faces = {
        str(index): "31" if index <= 4 else "310" if index <= 6 else "3"
        for index in range(1, 10)
    }
    v288 = {
        "issue": "26112",
        "version": "cap candidate",
        "legs": {
            match_no: {**base_leg, "faces": faces}
            for match_no, faces in v288_faces.items()
        },
    }
    for name, payload in {
        "26112-legs-R432.json": r432,
        "26112-legs-V288.json": v288,
    }.items():
        (artifact_root / name).write_text(json.dumps(payload, ensure_ascii=False), "utf-8")
    _record(repository, {"rx_adjudication_id": "ADJ-1"})
    _record(repository, {"candidate_id": "R432"}, created_at="2026-08-28T09:05:00+00:00")
    service = OperatorQueryService(
        repository=repository,
        product_queries=FakeProductQueries(),
        artifacts=ZucaiArtifactRepository(artifact_root),
        official_history_provider=_history,
        clock=lambda: NOW,
    )

    task = service.task("zucai:26112", as_of=NOW)

    assert task.step.kind == "audit_deployment"
    assert task.step.candidate.candidate_id == "R432"
    assert task.step.gate_candidate_id == "V288"
    assert task.step.gate_candidate_cost_yuan == 288
    assert "keep" not in task.step.allowed_decisions


def test_result_ready_task_presents_one_pending_prediction_for_review(
    artifact_root: Path,
    operator_queries: OperatorQueryService,
    repository: FakeRepository,
) -> None:
    rx_path = artifact_root / "26112-rx.json"
    rx = json.loads(rx_path.read_text("utf-8"))
    rx["outcomes"] = {
        "settled_at": "2026-08-29T10:00:00+08:00",
        "source": "official 90-minute results",
        "draw_result": "fixture",
        "position": "placed",
        "prescription_score": "fixture",
        "ticket_counterfactuals": "fixture",
        "predictions": {},
        "adjudication_outcomes": {},
        "key_lessons": "must not be exposed",
    }
    rx_path.write_text(json.dumps(rx, ensure_ascii=False), "utf-8")
    _record(repository, {"rx_adjudication_id": "ADJ-1"})
    _record(
        repository,
        {"candidate_id": "R432"},
        created_at="2026-08-28T09:05:00+00:00",
    )
    _record(
        repository,
        {"deployment_decision": "keep", "ticket_artifact_id": "tat-1"},
        created_at="2026-08-28T09:10:00+00:00",
    )
    repository.tickets = [{
        "run_date": "2026-08-28",
        "ticket_batch_revision_id": "revision-1",
        "ticket_artifact_id": "tat-1",
        "confirmation_id": "confirmation-1",
        "consumed_at": "2026-08-28T09:12:00+00:00",
        "expires_at": "2026-08-28T09:15:00+00:00",
        "ticket_placement_id": "placement-1",
        "ticket_shadow_id": None,
        "ticket_id": "ticket-1",
        "amount": 100,
        "currency": "CNY",
        "deadline_at": "2026-08-29T03:00:00+08:00",
        "external_reference": "telegram:fixture",
    }]
    repository.predictions["26112"] = [
        {
            "prediction_id": "prediction-p1",
            "claim": "至少一场平",
            "falsifier": "全无平局",
            "status": "pending",
            "outcome": None,
            "registered_at": "2026-08-28T09:00:00+00:00",
            "settled_at": None,
        },
        {
            "prediction_id": "prediction-p2",
            "claim": "主队至少赢一场",
            "falsifier": "主队全不胜",
            "status": "pending",
            "outcome": None,
            "registered_at": "2026-08-28T09:01:00+00:00",
            "settled_at": None,
        },
    ]

    task = operator_queries.task("zucai:26112", as_of=NOW)

    assert task.selected.state == "review"
    assert task.step.kind == "review"
    assert task.step.current_item.item_id == "prediction-p1"
    assert task.step.current_item.title == "至少一场平"
    assert task.step.current_item.evidence[0].value == "全无平局"
    assert task.step.current_item.allowed_outcomes == ["hit", "miss", "na"]
    assert "must not be exposed" not in task.model_dump_json()


def test_fixture_rx_outcomes_are_not_rendered_as_operator_prose(
    artifact_root: Path, repository: FakeRepository
) -> None:
    path = artifact_root / "26112-rx.json"
    payload = json.loads(path.read_text("utf-8"))
    payload["outcomes"] = {
        "settled_at": "2026-08-29",
        "source": "fixture",
        "draw_result": "0",
        "position": "raw position prose",
        "prescription_score": "raw score prose",
        "ticket_counterfactuals": "raw counterfactual prose",
        "predictions": {},
        "adjudication_outcomes": {},
        "key_lessons": "raw lesson prose",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")
    service = OperatorQueryService(
        repository=repository,
        product_queries=FakeProductQueries(),
        artifacts=ZucaiArtifactRepository(artifact_root),
        official_history_provider=_history,
        clock=lambda: NOW,
    )

    assert "raw lesson prose" not in service.task("zucai:26112", as_of=NOW).model_dump_json()


def test_subject_reads_are_time_scoped_and_decode_json(seeded_product) -> None:
    with seeded_product.kernel.engine.begin() as connection:
        connection.execute(
            insert(sw.adjudications),
            [
                {
                    "adjudication_id": "operator-adj-before",
                    "subject_type": "issue",
                    "subject_id": "26112",
                    "decision": "record",
                    "actor_id": "operator:owner",
                    "reason": "before",
                    "evidence_rejected_json": "[]",
                    "alternative_json": '{"rx_adjudication_id":"ADJ-1"}',
                    "created_at": "2026-08-24T09:00:00+00:00",
                    "supersedes_adjudication_id": None,
                },
                {
                    "adjudication_id": "operator-adj-future",
                    "subject_type": "issue",
                    "subject_id": "26112",
                    "decision": "record",
                    "actor_id": "operator:owner",
                    "reason": "future",
                    "evidence_rejected_json": "[]",
                    "alternative_json": "{}",
                    "created_at": "2026-08-24T11:00:00+00:00",
                    "supersedes_adjudication_id": None,
                },
            ],
        )
        connection.execute(
            insert(sw.predictions),
            [
                {
                    "prediction_id": "operator-prediction-before",
                    "match_id": None,
                    "subject_type": "issue",
                    "subject_id": "26112",
                    "claim": "fixture",
                    "falsifier": "fixture",
                    "status": "pending",
                    "outcome": None,
                    "registered_at": "2026-08-24T09:00:00+00:00",
                    "settled_at": None,
                },
                {
                    "prediction_id": "operator-prediction-future",
                    "match_id": None,
                    "subject_type": "issue",
                    "subject_id": "26112",
                    "claim": "future",
                    "falsifier": "future",
                    "status": "pending",
                    "outcome": None,
                    "registered_at": "2026-08-24T11:00:00+00:00",
                    "settled_at": None,
                },
            ],
        )
    repository = ProductReadRepository(seeded_product.kernel.engine)
    cutoff = "2026-08-24T10:00:00+00:00"

    adjudications = repository.adjudications_for_subject("issue", "26112", cutoff)
    predictions = repository.predictions_for_subject("issue", "26112", cutoff)

    assert [row["adjudication_id"] for row in adjudications] == ["operator-adj-before"]
    assert adjudications[0]["alternative"] == {"rx_adjudication_id": "ADJ-1"}
    assert [row["prediction_id"] for row in predictions] == ["operator-prediction-before"]
    assert repository.operator_ticket_artifacts(cutoff) == []
