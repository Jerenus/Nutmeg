import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import insert

from nutmeg.decision.zucai_official import OfficialRenjiuHistory
from nutmeg.ontology.repository import schema_workflow as sw
from nutmeg.product.errors import ProductNotFoundError
from nutmeg.product.operator_artifacts import (
    FilesystemZucaiFixtureAdapter,
    ZucaiArtifactRepository,
)
from nutmeg.product.operator_contracts import OperatorLane
from nutmeg.product.operator_lanes import SaleOfferSnapshot, SaleSlateSnapshot
from nutmeg.product.operator_queries import OperatorQueryService
from nutmeg.product.repository import ProductReadRepository
from tests.ontology.operator import test_sale_actions as sale_fixtures
from tests.product.operator_fixtures import write_26112_bundle

NOW = datetime(2026, 8, 28, 10, tzinfo=UTC)


@dataclass
class FakeRepository:
    adjudications: dict[str, list[dict]] = field(default_factory=dict)
    predictions: dict[str, list[dict]] = field(default_factory=dict)
    tickets: list[dict] = field(default_factory=list)
    settlement_rows: list[dict] = field(default_factory=list)
    sale_slates: list[SaleSlateSnapshot] = field(default_factory=list)

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

    def operator_sale_slates(self, *, as_of: str):
        return tuple(self.sale_slates)


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


def _official_slate(
    business_key: str,
    *,
    lane: OperatorLane = OperatorLane.ZUCAI,
) -> SaleSlateSnapshot:
    count = 14 if lane is OperatorLane.ZUCAI else 1
    offers = tuple(
        SaleOfferSnapshot(
            official_offer_family_id=f"{lane.value}:{business_key}:family:{index}",
            official_offer_revision_id=f"{lane.value}:{business_key}:offer:{index}:r1",
            match_id=f"{lane.value}:{business_key}:match:{index}",
            official_match_no=(str(index) if lane is OperatorLane.ZUCAI else "周五001"),
            market_definition_ids=("md-had",),
            sale_opens_at=NOW - timedelta(hours=1),
            sale_deadline_at=NOW + timedelta(days=1),
            source_status="on_sale",
        )
        for index in range(1, count + 1)
    )
    return SaleSlateSnapshot(
        lane=lane,
        business_key=business_key,
        slate_revision_id=f"{lane.value}:{business_key}:slate:r1",
        content_hash="a" * 64,
        offers=offers,
    )


def test_product_history_window_is_policy_versioned() -> None:
    from nutmeg.product import operator_queries as module

    assert module._renjiu_history_window("26113", available_rows=20) == 12
    assert module._renjiu_history_window("26112", available_rows=3) == 3


def test_product_repository_reads_temporal_current_official_slates(tmp_path: Path) -> None:
    actions, engine = sale_fixtures._setup(tmp_path)
    first = actions.import_official_sale_slate(
        replace(
            sale_fixtures._request(sale_fixtures._manifest(), key="sale:r1"),
            requested_at=datetime(2026, 9, 4, 0, 1, tzinfo=UTC),
        )
    )
    assert first.slate is not None
    second_hash = sale_fixtures._add_official_retrieval(
        engine,
        "retrieval-r2",
        retrieved_at="2026-09-04T08:02:00+08:00",
        hash_character="c",
    )
    second = actions.import_official_sale_slate(
        replace(
            sale_fixtures._request(
                sale_fixtures._manifest(
                    retrieved_at="2026-09-04T08:02:00+08:00",
                    official_source_content_hash=second_hash,
                    official_source_artifact_retrieval_id="retrieval-r2",
                    supersedes_slate_revision_id=first.slate.slate_revision_id,
                    offers=[
                        sale_fixtures._offer(
                            sale_deadline_at="2026-09-04T20:00:00+08:00"
                        )
                    ],
                ),
                key="sale:r2",
            ),
            requested_at=datetime(2026, 9, 4, 0, 2, tzinfo=UTC),
        )
    )
    assert second.slate is not None
    repository = ProductReadRepository(engine)

    before = repository.operator_sale_slates(
        as_of="2026-09-04T00:01:30+00:00"
    )
    after = repository.operator_sale_slates(
        as_of="2026-09-04T00:02:30+00:00"
    )

    assert [slate.slate_revision_id for slate in before] == [
        first.slate.slate_revision_id
    ]
    assert [slate.slate_revision_id for slate in after] == [
        second.slate.slate_revision_id
    ]
    assert after[0].offers[0].sale_deadline_at.utcoffset() is not None


@pytest.fixture
def artifact_root(tmp_path: Path) -> Path:
    root = write_26112_bundle(tmp_path / "zucai")
    (root / "26113-rx.json").write_text("{", "utf-8")
    return root


@pytest.fixture
def repository() -> FakeRepository:
    return FakeRepository(
        sale_slates=[_official_slate("26112"), _official_slate("26113")]
    )


@pytest.fixture
def operator_queries(artifact_root: Path, repository: FakeRepository) -> OperatorQueryService:
    return OperatorQueryService(
        repository=repository,
        product_queries=FakeProductQueries(),
        legacy_fixture_adapter=FilesystemZucaiFixtureAdapter(
            ZucaiArtifactRepository(artifact_root)
        ),
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


def test_production_status_words_skip_resolved_and_superseded_adjudications(
    artifact_root: Path,
    operator_queries: OperatorQueryService,
) -> None:
    path = artifact_root / "26112-rx.json"
    payload = json.loads(path.read_text("utf-8"))
    payload["pending_adjudications"] = [
        {"id": "ADJ-1", "status": "已行权", "q": "任九档位"},
        {"id": "ADJ-2", "status": "我已裁", "q": "场1保持全包"},
        {"id": "ADJ-3", "status": "我已裁", "q": "场13保持单3"},
        {
            "id": "ADJ-4",
            "status": "待终核",
            "q": "场14触发线终核",
            "default": "开赛前首发公布时复核",
        },
        {"id": "ADJ-5", "status": "已被ADJ-6取代", "q": "旧SFC裁决"},
        {"id": "ADJ-6", "status": "已行权A版", "q": "大胆SFC定稿"},
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")

    task = operator_queries.task("zucai:26112", as_of=NOW)

    assert task.step.kind == "judge_matches"
    assert task.step.item_key == "ADJ-4"
    assert task.step.options == ["开赛前首发公布时复核"]
    assert task.progress.completed == 0
    assert task.progress.total == 1


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


def test_official_slate_survives_missing_rx_without_artifact_discovery(
    tmp_path: Path,
) -> None:
    class NoDiscoveryArtifacts(ZucaiArtifactRepository):
        def discover_issues(self) -> list[str]:
            raise AssertionError("legacy filename discovery must not run")

    repository = FakeRepository(sale_slates=[_official_slate("26117")])
    service = OperatorQueryService(
        repository=repository,
        product_queries=FakeProductQueries(),
        legacy_fixture_adapter=FilesystemZucaiFixtureAdapter(
            NoDiscoveryArtifacts(tmp_path / "empty")
        ),
        official_history_provider=_history,
        clock=lambda: NOW,
    )

    worklist = service.worklist(as_of=NOW)

    assert [task.task_id for task in worklist.tasks] == ["zucai:26117"]
    assert worklist.tasks[0].state == "prepare"


def test_production_query_without_legacy_adapter_stays_prepare_and_hides_evidence(
    repository: FakeRepository,
) -> None:
    repository.sale_slates = [_official_slate("26112")]
    service = OperatorQueryService(
        repository=repository,
        product_queries=FakeProductQueries(),
        official_history_provider=_history,
        clock=lambda: NOW,
    )

    first = service.task("zucai:26112", as_of=NOW)
    second = service.task("zucai:26112", as_of=NOW)

    assert first.selected.state == "prepare"
    assert first.step.kind == "prepare"
    assert second.mutation_token == first.mutation_token
    with pytest.raises(ProductNotFoundError, match="evidence"):
        service.evidence("zucai:26112", "rx-capital", as_of=NOW)


def test_rx_file_cannot_create_task_without_official_slate(tmp_path: Path) -> None:
    root = write_26112_bundle(tmp_path / "zucai")
    service = OperatorQueryService(
        repository=FakeRepository(),
        product_queries=FakeProductQueries(),
        legacy_fixture_adapter=FilesystemZucaiFixtureAdapter(
            ZucaiArtifactRepository(root)
        ),
        official_history_provider=_history,
        clock=lambda: NOW,
    )

    assert service.worklist(as_of=NOW).tasks == []
    with pytest.raises(ProductNotFoundError):
        service.task("zucai:26112", as_of=NOW)


def test_official_jczq_slate_survives_missing_ticket(tmp_path: Path) -> None:
    service = OperatorQueryService(
        repository=FakeRepository(
            sale_slates=[
                _official_slate("2026-08-28", lane=OperatorLane.JCZQ)
            ]
        ),
        product_queries=FakeProductQueries(),
        legacy_fixture_adapter=FilesystemZucaiFixtureAdapter(
            ZucaiArtifactRepository(tmp_path / "empty")
        ),
        official_history_provider=_history,
        clock=lambda: NOW,
    )

    task = service.task("jczq:2026-08-28", as_of=NOW)

    assert task.selected.state == "prepare"


def test_ticket_cannot_create_jczq_task_without_official_slate(tmp_path: Path) -> None:
    repository = FakeRepository(
        tickets=[
            {
                "run_date": "2026-08-28",
                "ticket_batch_revision_id": "orphan-revision",
            }
        ]
    )
    service = OperatorQueryService(
        repository=repository,
        product_queries=FakeProductQueries(),
        legacy_fixture_adapter=FilesystemZucaiFixtureAdapter(
            ZucaiArtifactRepository(tmp_path / "empty")
        ),
        official_history_provider=_history,
        clock=lambda: NOW,
    )

    assert service.worklist(as_of=NOW).tasks == []


def test_orphan_rx_evidence_is_not_found(tmp_path: Path) -> None:
    root = write_26112_bundle(tmp_path / "zucai")
    service = OperatorQueryService(
        repository=FakeRepository(),
        product_queries=FakeProductQueries(),
        legacy_fixture_adapter=FilesystemZucaiFixtureAdapter(
            ZucaiArtifactRepository(root)
        ),
        official_history_provider=_history,
        clock=lambda: NOW,
    )

    with pytest.raises(ProductNotFoundError, match="evidence"):
        service.evidence("zucai:26112", "rx-capital", as_of=NOW)


def test_invalid_bundle_is_visible_block_not_exception(operator_queries) -> None:
    worklist = operator_queries.worklist(as_of=NOW)
    task = next(item for item in worklist.tasks if item.business_key == "26113")
    assert task.state == "blocked"
    assert task.block_reason_code == "source_contract_invalid"


def test_unknown_task_is_not_found(operator_queries) -> None:
    with pytest.raises(ProductNotFoundError):
        operator_queries.task("zucai:99999", as_of=NOW)


def test_prep_evidence_is_fixed_business_fields(operator_queries) -> None:
    detail = operator_queries.evidence(
        "zucai:26112", "prep-match-1", as_of=NOW
    )

    assert detail.title == "场 1 水晶宫-曼彻斯特城"
    assert detail.source_label == "足彩 26112 下午准备数据"
    assert detail.freshness_label == "2026-08-28 14:00"
    assert [(field.label, field.value) for field in detail.fields] == [
        ("赛事", "英超"),
        ("开球", "2026-08-29 03:00"),
        ("胜", "19.56%"),
        ("平", "23.43%"),
        ("负", "57.02%"),
        ("让球", "+1"),
    ]
    serialized = detail.model_dump_json()
    assert "forecast_revision_id" not in serialized
    assert "sporttery_match_num" not in serialized
    assert "fit_loss" not in serialized


def test_unknown_evidence_key_is_not_found(operator_queries) -> None:
    with pytest.raises(ProductNotFoundError, match="evidence"):
        operator_queries.evidence(
            "zucai:26112", "raw-json", as_of=NOW
        )


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
        legacy_fixture_adapter=FilesystemZucaiFixtureAdapter(
            ZucaiArtifactRepository(artifact_root)
        ),
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
        legacy_fixture_adapter=FilesystemZucaiFixtureAdapter(
            ZucaiArtifactRepository(artifact_root)
        ),
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
