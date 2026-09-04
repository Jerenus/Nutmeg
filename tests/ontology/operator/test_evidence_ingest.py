from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import func, insert, select, update

from nutmeg.ontology.actions.claim_actions import (
    ClaimActions,
    ClaimAdjudicationRequest,
    EvidenceSpanInput,
    ExtractClaimRequest,
)
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.operator.evidence_actions import (
    EvidenceActions,
    IngestOperatorEvidenceRequest,
)
from nutmeg.ontology.operator.evidence_manifest import EvidenceIntakeManifestV1
from nutmeg.ontology.operator.models import EvidenceCoverageReceiptRow
from nutmeg.ontology.repository import (
    schema,
    schema_context,
    schema_evidence,
    schema_identity,
    schema_market,
)
from nutmeg.ontology.repository import schema_operator_decision as sod
from nutmeg.ontology.repository import schema_operator_sale as sos
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.evidence import EvidenceRepository, ObservationRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.operator_decision import OperatorDecisionRepository
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.operator_contracts import OperatorLane
from nutmeg.product.operator_evidence import EvidenceState, OperatorEvidenceService
from nutmeg.product.operator_lanes import SaleOfferSnapshot, SaleSlateSnapshot, task_snapshot_hash
from nutmeg.product.repository import ProductReadRepository

AT = datetime(2026, 9, 4, 2, tzinfo=UTC)


def _expected_task_snapshot_hash() -> str:
    return task_snapshot_hash(
        SaleSlateSnapshot(
            lane=OperatorLane.JCZQ,
            business_key="2026-09-04",
            slate_revision_id="slate-1",
            content_hash="c" * 64,
            offers=(
                SaleOfferSnapshot(
                    official_offer_family_id="offer-family-1",
                    official_offer_revision_id="offer-revision-1",
                    match_id="match-1",
                    official_match_no="周五001",
                    market_definition_ids=("md-had",),
                    sale_opens_at=datetime(2026, 9, 4, 0, tzinfo=UTC),
                    sale_deadline_at=datetime(2026, 9, 4, 12, tzinfo=UTC),
                    source_status="on_sale",
                ),
            ),
        ),
        datetime(2026, 9, 4, 2, tzinfo=UTC),
    )


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "evidence-intake-v1",
        "lane": "jczq",
        "business_key": "2026-09-04",
        "slate_revision_id": "slate-1",
        "captured_at": "2026-09-04T10:00:00+08:00",
        "matches": [
            {
                "official_match_no": "周五001",
                "canonical_match_id": "match-1",
                "source_receipts": [
                    {
                        "source_kind": "authoritative_results",
                        "source_run_id": "run-1",
                        "artifact_retrieval_id": "retrieval-1",
                        "captured_at": "2026-09-04T09:55:00+08:00",
                    }
                ],
                "observations": [
                    {
                        "observation_schema": "recent_form_v1",
                        "subject_type": "team",
                        "canonical_subject_id": "team-home",
                        "valid_from": "2026-09-01T00:00:00+08:00",
                        "valid_to": None,
                        "observed_at": "2026-09-04T09:50:00+08:00",
                        "verification_method": "deterministic",
                        "value": {
                            "kind": "recent_form_v1",
                            "team_token": "team-home",
                            "sample_match_tokens": ["match-a", "match-b", "match-c"],
                            "wins": 1,
                            "draws": 1,
                            "losses": 1,
                            "goals_for": 4,
                            "goals_against": 3,
                        },
                        "artifact_retrieval_ids": ["retrieval-1"],
                    }
                ],
                "claims": [
                    {
                        "claim_schema": "availability_claim_v1",
                        "subject_type": "person",
                        "canonical_subject_id": "person-1",
                        "predicate": "availability",
                        "scope_match_id": "match-1",
                        "valid_from": "2026-09-04T00:00:00+08:00",
                        "valid_to": "2026-09-05T00:00:00+08:00",
                        "extractor": "main-loop",
                        "extractor_version": "1",
                        "value": {
                            "kind": "availability_claim_v1",
                            "team_token": "team-home",
                            "person_token": "person-1",
                            "availability": "out",
                            "status_kind": "injury",
                        },
                        "spans": [
                            {
                                "artifact_id": "artifact-1",
                                "artifact_retrieval_id": "retrieval-1",
                                "quote": "Player remains unavailable.",
                                "locator": "article:1",
                            }
                        ],
                    }
                ],
                "coverage_receipts": [
                    {
                        "requirement_id": "E6a",
                        "subject_scope": "team-home",
                        "evidence_ref_tokens": ["observation:0"],
                    }
                ],
            }
        ],
    }


def test_manifest_accepts_only_the_closed_typed_contract() -> None:
    parsed = EvidenceIntakeManifestV1.model_validate(_manifest())

    assert parsed.matches[0].observations[0].value.kind == "recent_form_v1"
    assert parsed.matches[0].claims[0].value.kind == "availability_claim_v1"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("unexpected",), True),
        (("task_snapshot_hash",), "a" * 64),
        (("matches", 0, "observations", 0, "scope_match_id"), "match-1"),
        (("matches", 0, "observations", 0, "value", "unknown"), True),
        (("matches", 0, "observations", 0, "value", "kind"), "free_form"),
        (("matches", 0, "observations", 0, "verification_method"), "rumour"),
        (("matches", 0, "claims", 0, "predicate"), "motivation"),
        (("matches", 0, "coverage_receipts", 0, "requirement_id"), "E7"),
        (("matches", 0, "observations", 0, "value", "wins"), -1),
    ],
)
def test_manifest_rejects_unknown_or_unbounded_values(path, value) -> None:
    document = deepcopy(_manifest())
    target = document
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value

    with pytest.raises(ValidationError):
        EvidenceIntakeManifestV1.model_validate(document)


def test_recent_form_requires_distinct_samples_and_matching_result_total() -> None:
    duplicate = deepcopy(_manifest())
    value = duplicate["matches"][0]["observations"][0]["value"]
    value["sample_match_tokens"] = ["match-a", "match-a", "match-c"]
    with pytest.raises(ValidationError, match="sample"):
        EvidenceIntakeManifestV1.model_validate(duplicate)

    mismatched = deepcopy(_manifest())
    value = mismatched["matches"][0]["observations"][0]["value"]
    value["losses"] = 0
    with pytest.raises(ValidationError, match="total"):
        EvidenceIntakeManifestV1.model_validate(mismatched)


@pytest.mark.parametrize(
    ("section", "subject_type", "subject_id", "message"),
    [
        ("observations", "person", "person-1", "observation subject"),
        ("claims", "team", "team-home", "claim subject"),
    ],
)
def test_manifest_binds_typed_values_to_their_canonical_subject(
    section: str,
    subject_type: str,
    subject_id: str,
    message: str,
) -> None:
    document = deepcopy(_manifest())
    item = document["matches"][0][section][0]
    item["subject_type"] = subject_type
    item["canonical_subject_id"] = subject_id

    with pytest.raises(ValidationError, match=message):
        EvidenceIntakeManifestV1.model_validate(document)


@pytest.mark.parametrize(
    ("target", "field"),
    [
        ("source", "captured_at"),
        ("observation", "observed_at"),
        ("observation", "valid_from"),
        ("claim", "valid_from"),
    ],
)
def test_manifest_rejects_source_or_fact_times_after_capture(
    target: str,
    field: str,
) -> None:
    document = deepcopy(_manifest())
    match = document["matches"][0]
    item = {
        "source": match["source_receipts"][0],
        "observation": match["observations"][0],
        "claim": match["claims"][0],
    }[target]
    item[field] = "2026-09-04T10:00:00.000001+08:00"

    with pytest.raises(ValidationError, match="captured_at"):
        EvidenceIntakeManifestV1.model_validate(document)


def test_manifest_rejects_clear_observation_lookback_after_capture() -> None:
    document = deepcopy(_manifest())
    observation = document["matches"][0]["observations"][0]
    observation.update(
        {
            "observation_schema": "team_availability_clear_v1",
            "verification_method": "official",
            "value": {
                "kind": "team_availability_clear_v1",
                "team_token": "team-home",
                "checked_source_kinds": ["club_official"],
                "lookback_started_at": "2026-09-03T10:00:00+08:00",
                "lookback_ended_at": "2026-09-04T10:00:00.000001+08:00",
                "finding_count": 0,
            },
        }
    )

    with pytest.raises(ValidationError, match="captured_at"):
        EvidenceIntakeManifestV1.model_validate(document)


def test_manifest_rejects_duplicate_source_and_evidence_references() -> None:
    source_duplicate = deepcopy(_manifest())
    match = source_duplicate["matches"][0]
    match["source_receipts"].append(deepcopy(match["source_receipts"][0]))
    with pytest.raises(ValidationError, match="source"):
        EvidenceIntakeManifestV1.model_validate(source_duplicate)

    evidence_duplicate = deepcopy(_manifest())
    coverage = evidence_duplicate["matches"][0]["coverage_receipts"][0]
    coverage["evidence_ref_tokens"] = ["observation:0", "observation:0"]
    with pytest.raises(ValidationError, match="evidence"):
        EvidenceIntakeManifestV1.model_validate(evidence_duplicate)


def _seed_intake_dependencies(engine) -> None:
    at = "2026-09-04T01:55:00+00:00"
    with engine.begin() as connection:
        connection.execute(
            insert(schema.source_runs),
            [
                {
                    "source_run_id": source_run_id,
                    "source_name": source_name,
                    "source_type": source_type,
                    "started_at": at,
                    "finished_at": at,
                    "status": "succeeded",
                    "error_code": None,
                    "error_detail": None,
                }
                for source_run_id, source_name, source_type in (
                    ("run-1", "results", "authoritative_results"),
                    ("run-market-official", "sporttery", "api"),
                    ("run-market-intl", "intl", "api"),
                )
            ],
        )
        connection.execute(
            insert(schema.source_artifacts),
            [
                {
                    "artifact_id": artifact_id,
                    "first_recorded_at": at,
                    "content_type": "application/json",
                    "storage_path": storage_path,
                    "byte_size": 10,
                    "content_hash": content_hash,
                }
                for artifact_id, storage_path, content_hash in (
                    ("artifact-1", "sha256/evidence-one", "b" * 64),
                    ("artifact-market-official", "sha256/market-official", "d" * 64),
                    ("artifact-market-intl", "sha256/market-intl", "e" * 64),
                )
            ],
        )
        connection.execute(
            insert(schema.artifact_retrievals),
            [
                {
                    "artifact_retrieval_id": retrieval_id,
                    "artifact_id": artifact_id,
                    "source_run_id": source_run_id,
                    "source_name": source_name,
                    "source_type": source_type,
                    "reported_content_type": "application/json",
                    "canonical_url": url,
                    "requested_url": url,
                    "published_at": at,
                    "retrieved_at": at,
                    "status": "stored",
                }
                for retrieval_id, artifact_id, source_run_id, source_name, source_type, url in (
                    (
                        "retrieval-1",
                        "artifact-1",
                        "run-1",
                        "results",
                        "authoritative_results",
                        "https://results.example.test/matches",
                    ),
                    (
                        "retrieval-market-official",
                        "artifact-market-official",
                        "run-market-official",
                        "sporttery",
                        "api",
                        "https://www.sporttery.cn/odds.json",
                    ),
                    (
                        "retrieval-market-intl",
                        "artifact-market-intl",
                        "run-market-intl",
                        "intl",
                        "api",
                        "https://odds.example.test/market.json",
                    ),
                )
            ],
        )
        connection.execute(
            insert(schema_identity.matches),
            [
                {"match_id": match_id, "current_revision_id": None}
                for match_id in ("match-1", "match-a", "match-b", "match-c")
            ],
        )
        connection.execute(
            insert(schema_identity.competitions).values(
                competition_id="competition-1",
                name="Test League",
                country="CN",
                kind="league",
            )
        )
        connection.execute(
            insert(schema_identity.competition_editions).values(
                competition_edition_id="competition-edition-1",
                competition_id="competition-1",
                name="2026",
                country="CN",
                format="league",
                season_label="2026",
                stage=None,
                valid_from="2026-01-01T00:00:00+00:00",
                valid_to=None,
            )
        )
        connection.execute(
            insert(schema_identity.match_revisions).values(
                match_revision_id="match-revision-1",
                match_id="match-1",
                version=1,
                competition_edition_id="competition-edition-1",
                scheduled_at="2026-09-04T14:00:00+00:00",
                schedule_status="scheduled",
                venue_id=None,
                status="scheduled",
                round_label=None,
                recorded_at=at,
                supersedes_revision_id=None,
            )
        )
        connection.execute(
            update(schema_identity.matches)
            .where(schema_identity.matches.c.match_id == "match-1")
            .values(current_revision_id="match-revision-1")
        )
        connection.execute(
            insert(schema_identity.teams),
            [
                {
                    "team_id": team_id,
                    "team_kind": "club",
                    "canonical_name": name,
                    "country": None,
                    "resolution_status": "resolved",
                    "created_at": at,
                }
                for team_id, name in (
                    ("team-home", "Home"),
                    ("team-away", "Away"),
                    ("team-other", "Other"),
                )
            ],
        )
        connection.execute(
            insert(schema_identity.team_appearances),
            [
                {
                    "team_appearance_id": "appearance-home",
                    "match_id": "match-1",
                    "team_id": "team-home",
                    "side": "home",
                },
                {
                    "team_appearance_id": "appearance-away",
                    "match_id": "match-1",
                    "team_id": "team-away",
                    "side": "away",
                },
            ],
        )
        connection.execute(
            insert(schema_context.persons).values(
                person_id="person-1",
                canonical_name="Player One",
                birth_date=None,
                nationality=None,
                resolution_status="resolved",
                created_at=at,
            )
        )
        connection.execute(
            insert(sos.official_sale_slate_revisions).values(
                slate_revision_id="slate-1",
                slate_family_id="slate-family-1",
                lane="jczq",
                business_key="2026-09-04",
                revision_no=1,
                source_artifact_retrieval_id="retrieval-1",
                published_at=at,
                retrieved_at=at,
                valid_from=at,
                supersedes_slate_revision_id=None,
                content_hash="c" * 64,
            )
        )
        connection.execute(
            insert(sos.official_offer_families).values(
                official_offer_family_id="offer-family-1",
                lane="jczq",
                business_key="2026-09-04",
                official_match_no="周五001",
                match_id="match-1",
                created_at=at,
            )
        )
        connection.execute(
            insert(sos.official_offer_revisions).values(
                official_offer_revision_id="offer-revision-1",
                official_offer_family_id="offer-family-1",
                slate_revision_id="slate-1",
                match_id="match-1",
                official_match_no="周五001",
                market_definition_ids_json='["md-had"]',
                sale_opens_at="2026-09-04T00:00:00+00:00",
                sale_deadline_at="2026-09-04T12:00:00+00:00",
                status="on_sale",
            )
        )
        connection.execute(
            insert(schema_market.market_quotes),
            [
                {
                    "quote_id": quote_id,
                    "match_id": "match-1",
                    "market_definition_id": "md-had",
                    "selection_id": "sel-had-home",
                    "provider": provider,
                    "bookmaker": None,
                    "decimal_odds": 2.0,
                    "captured_at": captured_at,
                    "artifact_retrieval_id": retrieval_id,
                    "quote_status": "active",
                }
                for quote_id, provider, captured_at, retrieval_id in (
                    (
                        "quote-official-1",
                        "sporttery",
                        "2026-09-04T01:50:00+00:00",
                        "retrieval-market-official",
                    ),
                    (
                        "quote-international-1",
                        "intl",
                        "2026-09-04T01:51:00+00:00",
                        "retrieval-market-intl",
                    ),
                )
            ],
        )
        connection.execute(
            insert(schema_market.market_snapshots),
            [
                {
                    "market_snapshot_id": "snapshot-official-1",
                    "match_id": "match-1",
                    "market_definition_id": "md-had",
                    "snapshot_kind": "read_time",
                    "as_of": "2026-09-04T01:50:00+00:00",
                    "fair_distribution_json": '{"away":0.3,"draw":0.3,"home":0.4}',
                    "devig_method": "proportional",
                    "method_version": "1",
                    "source_coverage_json": '{"providers":1,"quotes":1}',
                    "freshness_json": "{}",
                    "disagreement_json": "{}",
                },
                {
                    "market_snapshot_id": "snapshot-international-1",
                    "match_id": "match-1",
                    "market_definition_id": "md-had",
                    "snapshot_kind": "read_time",
                    "as_of": "2026-09-04T01:51:00+00:00",
                    "fair_distribution_json": '{"away":0.31,"draw":0.29,"home":0.4}',
                    "devig_method": "proportional",
                    "method_version": "1",
                    "source_coverage_json": '{"providers":1,"quotes":1}',
                    "freshness_json": "{}",
                    "disagreement_json": "{}",
                },
            ],
        )
        connection.execute(
            insert(schema_market.market_snapshot_quotes),
            [
                {
                    "market_snapshot_id": "snapshot-official-1",
                    "quote_id": "quote-official-1",
                },
                {
                    "market_snapshot_id": "snapshot-international-1",
                    "quote_id": "quote-international-1",
                },
            ],
        )


def _actions(tmp_path: Path) -> tuple[EvidenceActions, object]:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    _seed_intake_dependencies(engine)
    return EvidenceActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def _request(
    *,
    role: ActorRole = ActorRole.DETERMINISTIC_SYSTEM,
    key: str = "evidence-intake:1",
    document: dict[str, object] | None = None,
) -> IngestOperatorEvidenceRequest:
    return IngestOperatorEvidenceRequest(
        manifest=EvidenceIntakeManifestV1.model_validate(document or _manifest()),
        actor_id="system:operator-evidence",
        actor_role=role,
        idempotency_key=key,
        requested_at=AT,
    )


def test_ingest_commits_one_parent_action_and_reconciled_rows(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)

    result = actions.ingest_operator_evidence_manifest(_request())

    assert result.outcome.status is ActionStatus.COMMITTED
    assert result.receipt.committed_count == result.receipt.persisted_count == 2
    assert result.receipt.task_snapshot_hash == _expected_task_snapshot_hash()
    assert result.receipt.rejected_count == result.receipt.skipped_count == 0
    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(schema_evidence.observations)
        ) == 1
        assert connection.scalar(select(func.count()).select_from(schema_evidence.claims)) == 1
        assert connection.scalar(
            select(schema_evidence.claims.c.status)
        ) == "provisional"
        assert connection.scalar(
            select(func.count()).select_from(sod.operator_evidence_intake_objects)
        ) == 2
        assert connection.scalar(
            select(func.count()).select_from(sod.operator_evidence_coverage_receipts)
        ) == 1


def test_ingest_replay_returns_same_action_and_receipt(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)

    first = actions.ingest_operator_evidence_manifest(_request())
    replay = actions.ingest_operator_evidence_manifest(_request())

    assert replay == first
    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(sod.operator_evidence_intake_receipts)
        ) == 1
        assert connection.scalar(select(func.count()).select_from(schema.actions).where(
            schema.actions.c.action_type == "ingest_operator_evidence_manifest"
        )) == 1


def test_ingest_replay_survives_a_later_slate_revision(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    request = _request(key="evidence-intake:replay-after-slate")
    first = actions.ingest_operator_evidence_manifest(request)
    with engine.begin() as connection:
        connection.execute(
            insert(sos.official_sale_slate_revisions).values(
                slate_revision_id="slate-2",
                slate_family_id="slate-family-1",
                lane="jczq",
                business_key="2026-09-04",
                revision_no=2,
                source_artifact_retrieval_id="retrieval-1",
                published_at="2026-09-04T02:01:00+00:00",
                retrieved_at="2026-09-04T02:01:00+00:00",
                valid_from="2026-09-04T02:01:00+00:00",
                supersedes_slate_revision_id="slate-1",
                content_hash="d" * 64,
            )
        )
        connection.execute(
            insert(sos.official_offer_revisions).values(
                official_offer_revision_id="offer-revision-2",
                official_offer_family_id="offer-family-1",
                slate_revision_id="slate-2",
                match_id="match-1",
                official_match_no="周五001",
                market_definition_ids_json='["md-had"]',
                sale_opens_at="2026-09-04T00:00:00+00:00",
                sale_deadline_at="2026-09-04T11:00:00+00:00",
                status="on_sale",
            )
        )

    replay = actions.ingest_operator_evidence_manifest(request)

    assert replay == first
    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(sod.operator_evidence_intake_receipts)
        ) == 1


def test_ingest_denies_non_system_role_without_business_rows(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)

    result = actions.ingest_operator_evidence_manifest(
        _request(role=ActorRole.JUDGE_OPERATOR)
    )

    assert result.outcome.status is ActionStatus.REJECTED
    assert result.receipt is None
    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(sod.operator_evidence_intake_receipts)
        ) == 0
        assert connection.scalar(
            select(func.count()).select_from(schema_evidence.observations)
        ) == 0
        assert connection.scalar(select(func.count()).select_from(schema_evidence.claims)) == 0


def test_ingest_rejects_reference_mismatch_atomically(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    document = _manifest()
    document["matches"][0]["source_receipts"][0]["source_run_id"] = "wrong-run"

    with pytest.raises(ValueError, match="source run"):
        actions.ingest_operator_evidence_manifest(_request(document=document))

    with engine.connect() as connection:
        for table in (
            sod.operator_evidence_intake_receipts,
            sod.operator_evidence_intake_objects,
            sod.operator_evidence_coverage_receipts,
            schema_evidence.observations,
            schema_evidence.claims,
        ):
            assert connection.scalar(select(func.count()).select_from(table)) == 0
        assert connection.scalar(
            select(func.count())
            .select_from(schema.actions)
            .where(schema.actions.c.action_type == "ingest_operator_evidence_manifest")
        ) == 0


def test_ingest_rejects_manifest_captured_after_action_request(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    document = deepcopy(_manifest())
    document["captured_at"] = (AT + timedelta(microseconds=1)).isoformat()

    with pytest.raises(ValueError, match="captured_at"):
        actions.ingest_operator_evidence_manifest(
            _request(document=document, key="evidence-intake:future-capture")
        )

    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count())
            .select_from(schema.actions)
            .where(schema.actions.c.action_type == "ingest_operator_evidence_manifest")
        ) == 0


def test_ingest_rejects_manifest_source_kind_not_bound_to_retrieval(
    tmp_path: Path,
) -> None:
    actions, engine = _actions(tmp_path)
    document = deepcopy(_manifest())
    document["matches"][0]["source_receipts"][0]["source_kind"] = "club_official"

    with pytest.raises(ValueError, match="source kind"):
        actions.ingest_operator_evidence_manifest(
            _request(document=document, key="evidence-intake:non-authoritative-form")
        )

    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(sod.operator_evidence_intake_receipts)
        ) == 0


def test_existing_coverage_reference_must_belong_to_the_same_match(
    tmp_path: Path,
) -> None:
    actions, engine = _actions(tmp_path)
    with engine.begin() as connection:
        connection.execute(
            insert(schema_evidence.observations).values(
                observation_id="obs-other-match",
                observation_type="structural_context_v1",
                subject_type="team",
                subject_id="team-other",
                scope_match_id="match-a",
                value_json='{"kind":"structural_context_v1"}',
                schema_version="1",
                valid_from="2026-09-04T00:00:00+00:00",
                valid_to=None,
                observed_at="2026-09-04T01:00:00+00:00",
                recorded_at="2026-09-04T01:00:00+00:00",
                verification_method="official",
                quality_json="{}",
            )
        )
    document = deepcopy(_manifest())
    document["matches"][0]["coverage_receipts"][0]["evidence_ref_tokens"] = [
        "obs-other-match"
    ]

    with pytest.raises(ValueError, match="manifest match"):
        actions.ingest_operator_evidence_manifest(
            _request(document=document, key="evidence-intake:cross-match-coverage")
        )

    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(sod.operator_evidence_intake_receipts)
        ) == 0


def test_existing_coverage_reference_is_opaque_and_resolved_by_exact_id(
    tmp_path: Path,
) -> None:
    actions, engine = _actions(tmp_path)
    with OntologyUnitOfWork(engine) as uow:
        uow.evidence.insert_observation(
            ObservationRow(
                observation_id="observation-existing",
                observation_type="structural_context_v1",
                subject_type="team",
                subject_id="team-home",
                scope_match_id="match-1",
                value={
                    "kind": "structural_context_v1",
                    "team_token": "team-home",
                    "context_kind": "formation",
                    "state": "present",
                    "fact_text": "Existing exact-id evidence.",
                },
                schema_version="1",
                valid_from="2026-09-04T00:00:00+00:00",
                valid_to=None,
                observed_at="2026-09-04T01:00:00+00:00",
                recorded_at="2026-09-04T01:00:00+00:00",
                verification_method="official",
                quality={},
            ),
            artifact_retrieval_ids=("retrieval-1",),
        )
    document = deepcopy(_manifest())
    document["matches"][0]["coverage_receipts"][0]["evidence_ref_tokens"] = [
        "observation-existing"
    ]

    result = actions.ingest_operator_evidence_manifest(
        _request(document=document, key="evidence-intake:opaque-coverage")
    )

    assert result.outcome.status is ActionStatus.COMMITTED


def test_existing_coverage_reference_rejects_cross_table_id_collision(
    tmp_path: Path,
) -> None:
    actions, engine = _actions(tmp_path)
    with engine.begin() as connection:
        connection.execute(
            insert(schema_evidence.observations).values(
                observation_id="shared-evidence-id",
                observation_type="structural_context_v1",
                subject_type="team",
                subject_id="team-home",
                scope_match_id="match-1",
                value_json='{"kind":"structural_context_v1"}',
                schema_version="1",
                valid_from="2026-09-04T00:00:00+00:00",
                valid_to=None,
                observed_at="2026-09-04T01:00:00+00:00",
                recorded_at="2026-09-04T01:00:00+00:00",
                verification_method="official",
                quality_json="{}",
            )
        )
        connection.execute(
            insert(schema_evidence.claims).values(
                claim_id="shared-evidence-id",
                subject_type="team",
                subject_id="team-home",
                predicate="structural_context",
                value_json='{"kind":"structural_context_claim_v1"}',
                scope_match_id="match-1",
                valid_from="2026-09-04T00:00:00+00:00",
                valid_to=None,
                status="verified",
                extractor="fixture",
                extractor_version="1",
                created_at="2026-09-04T01:00:00+00:00",
                adjudicated_at="2026-09-04T01:01:00+00:00",
            )
        )
    document = deepcopy(_manifest())
    document["matches"][0]["coverage_receipts"][0]["evidence_ref_tokens"] = [
        "shared-evidence-id"
    ]

    with pytest.raises(ValueError, match="ambiguous"):
        actions.ingest_operator_evidence_manifest(
            _request(document=document, key="evidence-intake:ambiguous-coverage")
        )


def test_ingest_rejects_team_evidence_for_a_different_match(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    document = deepcopy(_manifest())
    observation = document["matches"][0]["observations"][0]
    observation["canonical_subject_id"] = "team-other"
    observation["value"]["team_token"] = "team-other"

    with pytest.raises(ValueError, match="team does not participate"):
        actions.ingest_operator_evidence_manifest(
            _request(document=document, key="evidence-intake:wrong-match-team")
        )

    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(sod.operator_evidence_intake_receipts)
        ) == 0
        assert connection.scalar(
            select(func.count())
            .select_from(schema.actions)
            .where(schema.actions.c.action_type == "ingest_operator_evidence_manifest")
        ) == 0


def test_ingest_rejects_noncurrent_slate_before_action_write(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    document = _manifest()
    document["slate_revision_id"] = "slate-missing"

    with pytest.raises(ValueError, match="slate"):
        actions.ingest_operator_evidence_manifest(
            _request(document=document, key="evidence-intake:stale-slate")
        )

    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count())
            .select_from(schema.actions)
            .where(schema.actions.c.action_type == "ingest_operator_evidence_manifest")
        ) == 0


def test_ingest_rolls_back_every_row_when_an_object_insert_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions, engine = _actions(tmp_path)
    original = OperatorDecisionRepository.insert_evidence_intake_object
    calls = 0

    def fail_second(repository, row):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected evidence object failure")
        return original(repository, row)

    monkeypatch.setattr(
        OperatorDecisionRepository,
        "insert_evidence_intake_object",
        fail_second,
    )

    with pytest.raises(RuntimeError, match="evidence object failure"):
        actions.ingest_operator_evidence_manifest(
            _request(key="evidence-intake:insert-failure")
        )

    with engine.connect() as connection:
        for table in (
            sod.operator_evidence_intake_receipts,
            sod.operator_evidence_intake_objects,
            sod.operator_evidence_coverage_receipts,
            schema_evidence.observations,
            schema_evidence.claims,
        ):
            assert connection.scalar(select(func.count()).select_from(table)) == 0
        failed = connection.execute(
            select(schema.actions.c.status, schema.actions.c.error_detail).where(
                schema.actions.c.action_type == "ingest_operator_evidence_manifest"
            )
        ).one()
        assert failed.status == "failed"
        assert "evidence object failure" in failed.error_detail


def test_ingest_count_mismatch_rolls_back_all_business_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions, engine = _actions(tmp_path)
    monkeypatch.setattr(
        OperatorDecisionRepository,
        "evidence_intake_object_count",
        lambda _repository, _receipt_id: 1,
    )

    with pytest.raises(ValueError, match="persisted count"):
        actions.ingest_operator_evidence_manifest(
            _request(key="evidence-intake:count-mismatch")
        )

    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(sod.operator_evidence_intake_receipts)
        ) == 0
        assert connection.scalar(
            select(func.count()).select_from(schema_evidence.observations)
        ) == 0
        assert connection.scalar(select(func.count()).select_from(schema_evidence.claims)) == 0


def test_evidence_service_loads_typed_task_snapshot_from_sqlite(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    result = actions.ingest_operator_evidence_manifest(
        _request(key="evidence-intake:sqlite-snapshot")
    )
    assert result.outcome.status is ActionStatus.COMMITTED
    service = OperatorEvidenceService(
        repository=ProductReadRepository(engine),
        unit_of_work_factory=lambda: OntologyUnitOfWork(engine),
    )

    snapshot = service.load_task_snapshot(
        lane="jczq",
        business_key="2026-09-04",
        as_of=AT,
    )

    assert snapshot.lane == "jczq"
    assert len(snapshot.matches) == 1
    match = snapshot.matches[0]
    assert match.identity.match_revision_ref_token == "match-revision-1"
    assert match.identity.team_ids == ("team-home", "team-away")
    assert not match.offer.source_official
    assert {market.source_kind for market in match.markets} == {
        "international_market",
        "sporttery_official",
    }
    assert match.observations[0].source_kinds == ("authoritative_results",)
    assert match.claims[0].observed_at == datetime(2026, 9, 4, 1, 55, tzinfo=UTC)
    assert match.claims[0].source_identity_tokens == (
        '{"source_name":"results","source_type":"authoritative_results"}',
    )

    status = service.evaluate_task(
        lane="jczq",
        business_key="2026-09-04",
        as_of=AT,
    )
    assert status.required_match_count == 1
    assert not status.ready


def test_evidence_service_surfaces_sqlite_alias_resolution_failures(tmp_path: Path) -> None:
    _, engine = _actions(tmp_path)
    with engine.begin() as connection:
        connection.execute(
            update(schema_identity.teams)
            .where(schema_identity.teams.c.team_id == "team-away")
            .values(resolution_status="provisional")
        )
        connection.execute(
            insert(schema_identity.teams).values(
                team_id="team-merged-home",
                team_kind="club",
                canonical_name="Old Home",
                country=None,
                resolution_status="merged",
                created_at="2026-09-04T01:55:00+00:00",
            )
        )
        connection.execute(
            insert(schema_identity.entity_aliases),
            [
                {
                    "entity_id": "team-home",
                    "entity_type": "team",
                    "normalized_alias": "shared club",
                    "language": "en",
                    "provider": "sporttery",
                },
                {
                    "entity_id": "team-other",
                    "entity_type": "team",
                    "normalized_alias": "shared club",
                    "language": "en",
                    "provider": "intl",
                },
                {
                    "entity_id": "team-away",
                    "entity_type": "team",
                    "normalized_alias": "away unresolved",
                    "language": "en",
                    "provider": "intl",
                },
                {
                    "entity_id": "team-merged-home",
                    "entity_type": "team",
                    "normalized_alias": "old home",
                    "language": "en",
                    "provider": "intl",
                },
            ],
        )
        connection.execute(
            insert(schema_identity.entity_merges).values(
                merge_id="merge-old-home",
                from_id="team-merged-home",
                into_id="team-home",
                entity_type="team",
                reason="fixture merge",
                evidence_retrieval_ids_json="[]",
                actor_id="judge:test",
                at="2026-09-04T01:56:00+00:00",
                reversible=1,
            )
        )
    service = OperatorEvidenceService(
        repository=ProductReadRepository(engine),
        unit_of_work_factory=lambda: OntologyUnitOfWork(engine),
    )

    snapshot = service.load_task_snapshot(
        lane="jczq",
        business_key="2026-09-04",
        as_of=AT,
    )

    identity = snapshot.matches[0].identity
    assert identity.unresolved_alias_ref_tokens == ("alias:team:away unresolved",)
    assert identity.ambiguous_alias_ref_tokens == ("alias:team:shared club",)
    assert identity.merged_away_ref_tokens == ("alias:team:old home",)


def test_evidence_service_uses_each_jczq_offer_deadline_from_sqlite(tmp_path: Path) -> None:
    _, engine = _actions(tmp_path)
    exact_deadline = AT + timedelta(hours=6)
    stale_deadline = exact_deadline + timedelta(microseconds=1)
    with engine.begin() as connection:
        connection.execute(
            update(sos.official_offer_revisions)
            .where(
                sos.official_offer_revisions.c.official_offer_revision_id
                == "offer-revision-1"
            )
            .values(sale_deadline_at=exact_deadline.isoformat())
        )
        connection.execute(
            update(schema_market.market_snapshots).values(as_of=AT.isoformat())
        )
        connection.execute(
            update(schema_market.market_quotes).values(captured_at=AT.isoformat())
        )
        connection.execute(
            insert(schema_identity.matches).values(
                match_id="match-2",
                current_revision_id="match-revision-2",
            )
        )
        connection.execute(
            insert(schema_identity.match_revisions).values(
                match_revision_id="match-revision-2",
                match_id="match-2",
                version=1,
                competition_edition_id="competition-edition-1",
                scheduled_at="2026-09-04T15:00:00+00:00",
                schedule_status="scheduled",
                venue_id=None,
                status="scheduled",
                round_label=None,
                recorded_at="2026-09-04T01:55:00+00:00",
                supersedes_revision_id=None,
            )
        )
        connection.execute(
            insert(schema_identity.team_appearances),
            [
                {
                    "team_appearance_id": "appearance-home-2",
                    "match_id": "match-2",
                    "team_id": "team-home",
                    "side": "home",
                },
                {
                    "team_appearance_id": "appearance-away-2",
                    "match_id": "match-2",
                    "team_id": "team-away",
                    "side": "away",
                },
            ],
        )
        connection.execute(
            insert(sos.official_offer_families).values(
                official_offer_family_id="offer-family-2",
                lane="jczq",
                business_key="2026-09-04",
                official_match_no="周五002",
                match_id="match-2",
                created_at="2026-09-04T01:55:00+00:00",
            )
        )
        connection.execute(
            insert(sos.official_offer_revisions).values(
                official_offer_revision_id="offer-revision-2",
                official_offer_family_id="offer-family-2",
                slate_revision_id="slate-1",
                match_id="match-2",
                official_match_no="周五002",
                market_definition_ids_json='["md-had"]',
                sale_opens_at="2026-09-04T00:00:00+00:00",
                sale_deadline_at=stale_deadline.isoformat(),
                status="on_sale",
            )
        )
        connection.execute(
            insert(schema_market.market_quotes),
            [
                {
                    "quote_id": f"quote-{provider}-2",
                    "match_id": "match-2",
                    "market_definition_id": "md-had",
                    "selection_id": "sel-had-home",
                    "provider": provider,
                    "bookmaker": None,
                    "decimal_odds": 2.0,
                    "captured_at": AT.isoformat(),
                    "artifact_retrieval_id": retrieval_id,
                    "quote_status": "active",
                }
                for provider, retrieval_id in (
                    ("sporttery", "retrieval-market-official"),
                    ("intl", "retrieval-market-intl"),
                )
            ],
        )
        connection.execute(
            insert(schema_market.market_snapshots),
            [
                {
                    "market_snapshot_id": f"snapshot-{provider}-2",
                    "match_id": "match-2",
                    "market_definition_id": "md-had",
                    "snapshot_kind": "read_time",
                    "as_of": AT.isoformat(),
                    "fair_distribution_json": '{"away":0.3,"draw":0.3,"home":0.4}',
                    "devig_method": "proportional",
                    "method_version": "1",
                    "source_coverage_json": '{"providers":1,"quotes":1}',
                    "freshness_json": "{}",
                    "disagreement_json": "{}",
                }
                for provider in ("sporttery", "intl")
            ],
        )
        connection.execute(
            insert(schema_market.market_snapshot_quotes),
            [
                {
                    "market_snapshot_id": f"snapshot-{provider}-2",
                    "quote_id": f"quote-{provider}-2",
                }
                for provider in ("sporttery", "intl")
            ],
        )
    service = OperatorEvidenceService(
        repository=ProductReadRepository(engine),
        unit_of_work_factory=lambda: OntologyUnitOfWork(engine),
    )

    status = service.evaluate_task(
        lane="jczq",
        business_key="2026-09-04",
        as_of=AT,
    )

    matches = {match.match_id: match for match in status.matches}
    exact = {row.requirement_id: row for row in matches["match-1"].requirements}
    stale = {row.requirement_id: row for row in matches["match-2"].requirements}
    assert exact["E3"].state is EvidenceState.COMPLETE
    assert exact["E4"].state is EvidenceState.COMPLETE
    assert stale["E3"].state is EvidenceState.STALE
    assert stale["E4"].state is EvidenceState.STALE


def test_evidence_service_loads_existing_claim_named_by_coverage_receipt(
    tmp_path: Path,
) -> None:
    actions, engine = _actions(tmp_path)
    first = actions.ingest_operator_evidence_manifest(
        _request(key="evidence-intake:existing-claim-base")
    )
    with engine.begin() as connection:
        connection.execute(
            insert(schema_evidence.claims).values(
                claim_id="claim-existing-verified",
                subject_type="person",
                subject_id="person-1",
                predicate="availability",
                value_json=(
                    '{"availability":"out","kind":"availability_claim_v1",'
                    '"person_token":"person-1","status_kind":"injury",'
                    '"team_token":"team-home"}'
                ),
                scope_match_id="match-1",
                valid_from="2026-09-04T01:00:00+00:00",
                valid_to="2026-09-04T13:00:00+00:00",
                status="verified",
                extractor="main-loop",
                extractor_version="1",
                created_at="2026-09-04T01:56:00+00:00",
                adjudicated_at="2026-09-04T01:57:00+00:00",
            )
        )
        connection.execute(
            insert(schema_evidence.claim_evidence_spans).values(
                claim_evidence_span_id="span-existing-verified",
                claim_id="claim-existing-verified",
                artifact_id="artifact-1",
                artifact_retrieval_id="retrieval-1",
                quote="Player One is unavailable.",
                locator="line:1",
            )
        )
        connection.execute(
            insert(sod.operator_evidence_coverage_receipts).values(
                coverage_receipt_id="coverage-existing-verified",
                intake_receipt_id=first.receipt.intake_receipt_id,
                match_id="match-1",
                requirement_id="E5",
                subject_scope="person-1",
                evidence_ref_tokens_json='["claim-existing-verified"]',
            )
        )
    service = OperatorEvidenceService(
        repository=ProductReadRepository(engine),
        unit_of_work_factory=lambda: OntologyUnitOfWork(engine),
    )

    snapshot = service.load_task_snapshot(
        lane="jczq",
        business_key="2026-09-04",
        as_of=AT,
    )

    assert "claim-existing-verified" in {
        claim.ref_token for claim in snapshot.matches[0].claims
    }


def test_existing_claim_loader_excludes_retrievals_from_failed_source_runs(
    tmp_path: Path,
) -> None:
    actions, engine = _actions(tmp_path)
    intake = actions.ingest_operator_evidence_manifest(
        _request(key="evidence-intake:failed-source-lineage")
    )
    with engine.begin() as connection:
        connection.execute(
            insert(schema.source_runs).values(
                source_run_id="run-failed-media",
                source_name="failed-media",
                source_type="credible_media",
                started_at="2026-09-04T01:40:00+00:00",
                finished_at="2026-09-04T01:45:00+00:00",
                status="failed",
                error_code="upstream_error",
                error_detail="fixture failure",
            )
        )
        connection.execute(
            insert(schema.source_artifacts).values(
                artifact_id="artifact-failed-media",
                first_recorded_at="2026-09-04T01:45:00+00:00",
                content_type="application/json",
                storage_path="sha256/failed-media",
                byte_size=10,
                content_hash="f" * 64,
            )
        )
        connection.execute(
            insert(schema.artifact_retrievals).values(
                artifact_retrieval_id="retrieval-failed-media",
                artifact_id="artifact-failed-media",
                source_run_id="run-failed-media",
                source_name="failed-media",
                source_type="credible_media",
                reported_content_type="application/json",
                canonical_url="https://failed.example.test/report",
                requested_url="https://failed.example.test/report",
                published_at="2026-09-04T01:40:00+00:00",
                retrieved_at="2026-09-04T01:45:00+00:00",
                status="stored",
            )
        )
        connection.execute(
            insert(schema_evidence.claims).values(
                claim_id="claim-mixed-source-status",
                subject_type="person",
                subject_id="person-1",
                predicate="availability",
                value_json=(
                    '{"availability":"out","kind":"availability_claim_v1",'
                    '"person_token":"person-1","status_kind":"injury",'
                    '"team_token":"team-home"}'
                ),
                scope_match_id="match-1",
                valid_from="2026-09-04T01:00:00+00:00",
                valid_to="2026-09-04T13:00:00+00:00",
                status="verified",
                extractor="main-loop",
                extractor_version="1",
                created_at="2026-09-04T01:56:00+00:00",
                adjudicated_at="2026-09-04T01:57:00+00:00",
            )
        )
        connection.execute(
            insert(schema_evidence.claim_evidence_spans),
            [
                {
                    "claim_evidence_span_id": "span-mixed-valid",
                    "claim_id": "claim-mixed-source-status",
                    "artifact_id": "artifact-1",
                    "artifact_retrieval_id": "retrieval-1",
                    "quote": "Valid source statement.",
                    "locator": "line:1",
                },
                {
                    "claim_evidence_span_id": "span-mixed-failed",
                    "claim_id": "claim-mixed-source-status",
                    "artifact_id": "artifact-failed-media",
                    "artifact_retrieval_id": "retrieval-failed-media",
                    "quote": "Failed source statement.",
                    "locator": "line:1",
                },
            ],
        )
        connection.execute(
            insert(sod.operator_evidence_coverage_receipts).values(
                coverage_receipt_id="coverage-mixed-source-status",
                intake_receipt_id=intake.receipt.intake_receipt_id,
                match_id="match-1",
                requirement_id="E5",
                subject_scope="person-1",
                evidence_ref_tokens_json='["claim-mixed-source-status"]',
            )
        )
    service = OperatorEvidenceService(
        repository=ProductReadRepository(engine),
        unit_of_work_factory=lambda: OntologyUnitOfWork(engine),
    )

    snapshot = service.load_task_snapshot(
        lane="jczq",
        business_key="2026-09-04",
        as_of=AT,
    )

    claim = next(
        item
        for item in snapshot.matches[0].claims
        if item.ref_token == "claim-mixed-source-status"
    )
    assert claim.source_retrieval_ids == ("retrieval-1",)


def test_evidence_service_loads_governed_observation_adjudication_lineage(
    tmp_path: Path,
) -> None:
    actions, engine = _actions(tmp_path)
    intake = actions.ingest_operator_evidence_manifest(
        _request(key="evidence-intake:adjudicated-observation")
    )
    action_service = ActionService(lambda: OntologyUnitOfWork(engine))
    claim_actions = ClaimActions(action_service)
    extracted = claim_actions.extract_claim(
        ExtractClaimRequest(
            subject_type="person",
            subject_id="person-1",
            predicate="availability",
            value={"availability": "out"},
            scope_match_id="match-1",
            valid_from="2026-09-04T00:00:00+00:00",
            extractor="fixture",
            extractor_version="1",
            spans=[
                EvidenceSpanInput(
                    artifact_id="artifact-1",
                    artifact_retrieval_id="retrieval-1",
                    quote="Player One remains unavailable.",
                    locator="line:1",
                )
            ],
            actor_id="extractor:test",
            actor_role=ActorRole.AI_EXTRACTOR,
            idempotency_key="extract:adjudicated-observation",
            requested_at=datetime(2026, 9, 4, 1, 56, tzinfo=UTC),
        )
    )
    claim_id = extracted.result_refs[0].object_id
    verified = claim_actions.verify_claim(
        ClaimAdjudicationRequest(
            claim_id=claim_id,
            actor_id="judge:test",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="verify:adjudicated-observation",
            requested_at=datetime(2026, 9, 4, 1, 57, tzinfo=UTC),
        )
    )
    with OntologyUnitOfWork(engine) as uow:
        uow.evidence.insert_observation(
            ObservationRow(
                observation_id="observation-adjudicated",
                observation_type="team_availability_clear_v1",
                subject_type="team",
                subject_id="team-home",
                scope_match_id="match-1",
                value={
                    "kind": "team_availability_clear_v1",
                    "team_token": "team-home",
                    "checked_source_kinds": ["credible_media"],
                    "lookback_started_at": "2026-09-03T01:00:00+00:00",
                    "lookback_ended_at": "2026-09-04T01:50:00+00:00",
                    "finding_count": 0,
                },
                schema_version="1",
                valid_from="2026-09-04T00:00:00+00:00",
                valid_to="2026-09-04T12:00:00+00:00",
                observed_at="2026-09-04T01:50:00+00:00",
                recorded_at="2026-09-04T01:58:00+00:00",
                verification_method="adjudicated",
                quality={},
            ),
            artifact_retrieval_ids=("retrieval-1",),
        )
        uow.evidence.link_observation_claim("observation-adjudicated", claim_id)
        uow.operator_decision.insert_evidence_coverage_receipt(
            EvidenceCoverageReceiptRow(
                coverage_receipt_id="coverage-adjudicated-observation",
                intake_receipt_id=intake.receipt.intake_receipt_id,
                match_id="match-1",
                requirement_id="E5",
                subject_scope="team-home",
                evidence_ref_tokens=("observation-adjudicated",),
            )
        )
    service = OperatorEvidenceService(
        repository=ProductReadRepository(engine),
        unit_of_work_factory=lambda: OntologyUnitOfWork(engine),
    )

    snapshot = service.load_task_snapshot(
        lane="jczq",
        business_key="2026-09-04",
        as_of=AT,
    )

    observation = next(
        item
        for item in snapshot.matches[0].observations
        if item.ref_token == "observation-adjudicated"
    )
    assert observation.adjudication_ref_tokens == (verified.action_id,)


def test_ingest_reconciles_links_against_concrete_evidence_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions, engine = _actions(tmp_path)
    monkeypatch.setattr(
        EvidenceRepository,
        "insert_observation",
        lambda _repository, _row, artifact_retrieval_ids=(): None,
    )

    with pytest.raises(ValueError, match="persisted count"):
        actions.ingest_operator_evidence_manifest(
            _request(key="evidence-intake:missing-observation")
        )

    with engine.connect() as connection:
        for table in (
            sod.operator_evidence_intake_receipts,
            sod.operator_evidence_intake_objects,
            schema_evidence.observations,
            schema_evidence.claims,
        ):
            assert connection.scalar(select(func.count()).select_from(table)) == 0
