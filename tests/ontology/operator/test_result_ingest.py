from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import func, insert, select, update
from typer.testing import CliRunner

from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.cli import app
from nutmeg.interfaces.cli import workflow as workflow_cli
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.operator.result_actions import (
    ImportResultEvidenceRequest,
    OperatorResultActions,
)
from nutmeg.ontology.operator.result_manifest import (
    ResultEvidenceManifestV1,
    normalize_match_result,
)
from nutmeg.ontology.repository import schema, schema_identity
from nutmeg.ontology.repository import schema_operator_result as sor
from nutmeg.ontology.repository import schema_operator_sale as sos
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.operator_result import OperatorResultRepository
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

AT = datetime(2026, 9, 5, 4, 0, tzinfo=UTC)


def _source(kind: str) -> dict[str, object]:
    return {
        "source_kind": kind,
        "receipt_state": "available",
        "artifact_retrieval_id": f"retrieval-{kind}",
        "captured_at": "2026-09-05T08:00:00+08:00",
        "source_disposition": "played_90",
        "home_90": 2,
        "away_90": 1,
        "invalid_code": None,
    }


def _manifest(*, lane: str = "jczq") -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "result-evidence-v1",
        "lane": lane,
        "business_key": "2026-09-05" if lane == "jczq" else "26120",
        "task_snapshot_token": "task-token",
        "slate_revision_token": "slate-token",
        "result_cutoff_at": "2026-09-05T09:00:00+08:00",
        "supersedes_result_set_token": None,
        "matches": [
            {
                "official_match_no": "周六001" if lane == "jczq" else "1",
                "canonical_match_id": "match-1",
                "sources": [
                    _source("api_football"),
                    _source("sporttery_game90"),
                    _source("okooo_manual"),
                ],
            }
        ],
        "zucai_prize_table": None,
    }
    return document


def _prize_table() -> dict[str, object]:
    return {
        "issue": "26120",
        "currency": "CNY",
        "published_at": "2026-09-05T10:00:00+08:00",
        "official_artifact_retrieval_id": "retrieval-sporttery-prize",
        "supersedes_prize_table_token": None,
        "tiers": [
            {
                "tier_code": "sfc_first",
                "ticket_kind": "sfc",
                "required_correct_count": 14,
                "official_winning_note_count": 12,
                "payout_minor_per_winning_note": 1_000_000,
            },
            {
                "tier_code": "sfc_second",
                "ticket_kind": "sfc",
                "required_correct_count": 13,
                "official_winning_note_count": 1_200,
                "payout_minor_per_winning_note": 20_000,
            },
            {
                "tier_code": "renjiu_first",
                "ticket_kind": "renjiu",
                "required_correct_count": 9,
                "official_winning_note_count": 10_000,
                "payout_minor_per_winning_note": 1_000,
            },
        ],
    }


def _parsed_manifest(*, lane: str = "jczq", **changes: object):
    document = _manifest(lane=lane)
    document["slate_revision_token"] = "slate-1"
    document.update(changes)
    return ResultEvidenceManifestV1.model_validate(document)


def _seed_result_dependencies(engine, *, lane: str = "jczq") -> None:
    business_key = "2026-09-05" if lane == "jczq" else "26120"
    official_match_no = "周六001" if lane == "jczq" else "1"
    captured_at = "2026-09-05T00:00:00+00:00"
    with engine.begin() as connection:
        connection.execute(
            insert(schema.source_runs),
            [
                {
                    "source_run_id": f"run-{kind}",
                    "source_name": source_name,
                    "source_type": kind,
                    "started_at": captured_at,
                    "finished_at": captured_at,
                    "status": "succeeded",
                    "error_code": None,
                    "error_detail": None,
                }
                for kind, source_name in (
                    ("api_football", "api-football"),
                    ("sporttery_game90", "sporttery"),
                    ("okooo_manual", "okooo-manual"),
                )
            ],
        )
        connection.execute(
            insert(schema.source_artifacts),
            [
                {
                    "artifact_id": f"artifact-{kind}",
                    "first_recorded_at": captured_at,
                    "content_type": "application/json",
                    "storage_path": f"sha256/{kind}",
                    "byte_size": 2,
                    "content_hash": character * 64,
                }
                for kind, character in (
                    ("api_football", "a"),
                    ("sporttery_game90", "b"),
                    ("okooo_manual", "c"),
                )
            ],
        )
        connection.execute(
            insert(schema.artifact_retrievals),
            [
                {
                    "artifact_retrieval_id": f"retrieval-{kind}",
                    "artifact_id": f"artifact-{kind}",
                    "source_run_id": f"run-{kind}",
                    "source_name": source_name,
                    "source_type": kind,
                    "reported_content_type": "application/json",
                    "canonical_url": url,
                    "requested_url": url,
                    "published_at": captured_at,
                    "retrieved_at": captured_at,
                    "status": "stored",
                }
                for kind, source_name, url in (
                    (
                        "api_football",
                        "api-football",
                        "https://v3.football.api-sports.io/fixtures?id=1",
                    ),
                    (
                        "sporttery_game90",
                        "sporttery",
                        "https://webapi.sporttery.cn/results/game90.json",
                    ),
                    (
                        "okooo_manual",
                        "okooo-manual",
                        "https://m.okooo.com/kaijiang/sport.php",
                    ),
                )
            ],
        )
        connection.execute(
            insert(schema_identity.matches).values(
                match_id="match-1",
                current_revision_id=None,
            )
        )
        connection.execute(
            insert(sos.official_sale_slate_revisions).values(
                slate_revision_id="slate-1",
                slate_family_id=f"slate-family-{lane}",
                lane=lane,
                business_key=business_key,
                revision_no=1,
                source_artifact_retrieval_id="retrieval-sporttery_game90",
                published_at=captured_at,
                retrieved_at=captured_at,
                valid_from=captured_at,
                supersedes_slate_revision_id=None,
                content_hash="d" * 64,
            )
        )
        connection.execute(
            insert(sos.official_offer_families).values(
                official_offer_family_id="offer-family-1",
                lane=lane,
                business_key=business_key,
                official_match_no=official_match_no,
                match_id="match-1",
                created_at=captured_at,
            )
        )
        connection.execute(
            insert(sos.official_offer_revisions).values(
                official_offer_revision_id="offer-revision-1",
                official_offer_family_id="offer-family-1",
                slate_revision_id="slate-1",
                match_id="match-1",
                official_match_no=official_match_no,
                market_definition_ids_json='["md-had"]',
                sale_opens_at=captured_at,
                sale_deadline_at="2026-09-05T01:00:00+00:00",
                status="on_sale",
            )
        )


def _seed_correction_retrievals(engine) -> None:
    captured_at = "2026-09-05T00:01:00+00:00"
    sources = (
        (
            "api_football",
            "api-football",
            "https://v3.football.api-sports.io/fixtures?id=1",
            "d",
        ),
        (
            "sporttery_game90",
            "sporttery",
            "https://webapi.sporttery.cn/results/game90.json",
            "e",
        ),
        (
            "okooo_manual",
            "okooo-manual",
            "https://m.okooo.com/kaijiang/sport.php",
            "f",
        ),
    )
    with engine.begin() as connection:
        connection.execute(
            insert(schema.source_runs),
            [
                {
                    "source_run_id": f"run-{kind}-correction",
                    "source_name": source_name,
                    "source_type": kind,
                    "started_at": captured_at,
                    "finished_at": captured_at,
                    "status": "succeeded",
                    "error_code": None,
                    "error_detail": None,
                }
                for kind, source_name, _url, _character in sources
            ],
        )
        connection.execute(
            insert(schema.source_artifacts),
            [
                {
                    "artifact_id": f"artifact-{kind}-correction",
                    "first_recorded_at": captured_at,
                    "content_type": "application/json",
                    "storage_path": f"sha256/{kind}-correction",
                    "byte_size": 2,
                    "content_hash": character * 64,
                }
                for kind, _source_name, _url, character in sources
            ],
        )
        connection.execute(
            insert(schema.artifact_retrievals),
            [
                {
                    "artifact_retrieval_id": f"retrieval-{kind}-correction",
                    "artifact_id": f"artifact-{kind}-correction",
                    "source_run_id": f"run-{kind}-correction",
                    "source_name": source_name,
                    "source_type": kind,
                    "reported_content_type": "application/json",
                    "canonical_url": url,
                    "requested_url": url,
                    "published_at": captured_at,
                    "retrieved_at": captured_at,
                    "status": "stored",
                }
                for kind, source_name, url, _character in sources
            ],
        )


def _setup_actions(tmp_path: Path, *, lane: str = "jczq"):
    engine = build_ontology_engine(tmp_path / f"{lane}.db")
    run_migrations(engine)
    _seed_result_dependencies(engine, lane=lane)
    actions = OperatorResultActions(ActionService(lambda: OntologyUnitOfWork(engine)))
    return actions, engine


def _setup_cli_data(tmp_path: Path, *, lane: str = "jczq") -> Path:
    data_dir = tmp_path / f"{lane}-data"
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir, _env_file=None))
    kernel.initialize()
    _seed_result_dependencies(kernel.engine, lane=lane)
    return data_dir


def _write_manifest(path: Path, document: object) -> Path:
    path.write_text(json.dumps(document, ensure_ascii=False), "utf-8")
    return path


def _invoke_result_cli(data_dir: Path, manifest: Path):
    return CliRunner().invoke(
        app,
        [
            "workflow",
            "ingest-results",
            "--manifest",
            str(manifest),
            "--data-dir",
            str(data_dir),
        ],
    )


def _import_request(
    manifest: ResultEvidenceManifestV1,
    *,
    key: str = "result-import:1",
    role: ActorRole = ActorRole.DETERMINISTIC_SYSTEM,
) -> ImportResultEvidenceRequest:
    return ImportResultEvidenceRequest(
        manifest=manifest,
        importer_version="three-source-result-v1",
        actor_id="system:result-import",
        actor_role=role,
        idempotency_key=key,
        requested_at=AT,
    )


def test_result_manifest_accepts_exact_three_source_contract() -> None:
    parsed = ResultEvidenceManifestV1.model_validate(_manifest())

    assert parsed.matches[0].sources[1].source_kind == "sporttery_game90"
    assert len(parsed.manifest_sha256) == 64


@pytest.mark.parametrize(
    ("state", "changes"),
    (
        (
            "missing",
            {
                "artifact_retrieval_id": None,
                "captured_at": None,
                "source_disposition": None,
                "home_90": None,
                "away_90": None,
                "invalid_code": None,
            },
        ),
        (
            "invalid",
            {
                "source_disposition": None,
                "home_90": None,
                "away_90": None,
                "invalid_code": "schema_mismatch",
            },
        ),
        (
            "available",
            {
                "source_disposition": "official_void",
                "home_90": None,
                "away_90": None,
            },
        ),
        (
            "available",
            {
                "source_disposition": "postponed",
                "home_90": None,
                "away_90": None,
            },
        ),
    ),
)
def test_source_receipt_valid_combinations_are_explicit(
    state: str,
    changes: dict[str, object],
) -> None:
    document = _manifest()
    source = document["matches"][0]["sources"][0]
    source["receipt_state"] = state
    source.update(changes)

    ResultEvidenceManifestV1.model_validate(document)


@pytest.mark.parametrize(
    "changes",
    (
        {"receipt_state": "missing", "artifact_retrieval_id": "unexpected"},
        {"receipt_state": "invalid", "invalid_code": None},
        {"receipt_state": "invalid", "source_disposition": "played_90"},
        {"receipt_state": "available", "artifact_retrieval_id": None},
        {"receipt_state": "available", "home_90": None},
        {"receipt_state": "available", "home_90": -1},
        {"receipt_state": "available", "invalid_code": "invalid_score"},
        {"receipt_state": "available", "source_disposition": "abandoned"},
    ),
)
def test_source_receipt_invalid_combinations_fail_closed(
    changes: dict[str, object],
) -> None:
    document = _manifest()
    document["matches"][0]["sources"][0].update(changes)

    with pytest.raises(ValidationError):
        ResultEvidenceManifestV1.model_validate(document)


def test_match_requires_each_configured_source_exactly_once() -> None:
    missing = _manifest()
    missing["matches"][0]["sources"].pop()
    with pytest.raises(ValidationError, match="exactly three configured"):
        ResultEvidenceManifestV1.model_validate(missing)

    duplicate = _manifest()
    duplicate["matches"][0]["sources"][2]["source_kind"] = "api_football"
    with pytest.raises(ValidationError, match="exactly three configured"):
        ResultEvidenceManifestV1.model_validate(duplicate)


def test_manifest_rejects_unknown_fields_naive_times_and_duplicate_matches() -> None:
    unknown = _manifest()
    unknown["payload"] = {}
    with pytest.raises(ValidationError):
        ResultEvidenceManifestV1.model_validate(unknown)

    naive = _manifest()
    naive["result_cutoff_at"] = "2026-09-05T09:00:00"
    with pytest.raises(ValidationError):
        ResultEvidenceManifestV1.model_validate(naive)

    duplicate = _manifest()
    duplicate["matches"].append(deepcopy(duplicate["matches"][0]))
    with pytest.raises(ValidationError, match="duplicate match"):
        ResultEvidenceManifestV1.model_validate(duplicate)


def test_manifest_rejects_empty_matches_and_sources_captured_after_cutoff() -> None:
    empty = _manifest()
    empty["matches"] = []
    with pytest.raises(ValidationError):
        ResultEvidenceManifestV1.model_validate(empty)

    late = _manifest()
    late["matches"][0]["sources"][0]["captured_at"] = (
        "2026-09-05T09:00:00.000001+08:00"
    )
    with pytest.raises(ValidationError, match="source capture follows"):
        ResultEvidenceManifestV1.model_validate(late)


@pytest.mark.parametrize("field", ("captured_at",))
def test_source_audit_timestamps_must_be_timezone_aware(field: str) -> None:
    document = _manifest()
    document["matches"][0]["sources"][0][field] = "2026-09-05T08:00:00"

    with pytest.raises(ValidationError):
        ResultEvidenceManifestV1.model_validate(document)


@pytest.mark.parametrize(
    ("target", "field"),
    (
        ("manifest", "result_cutoff_at"),
        ("source", "captured_at"),
        ("prize", "published_at"),
    ),
)
def test_result_manifest_timestamps_reject_numeric_epoch_values(
    target: str,
    field: str,
) -> None:
    document = _manifest(lane="zucai")
    document["zucai_prize_table"] = _prize_table()
    if target == "manifest":
        document[field] = 1_788_480_000
    elif target == "source":
        document["matches"][0]["sources"][0][field] = 1_788_480_000
    else:
        document["zucai_prize_table"][field] = 1_788_480_000

    with pytest.raises(ValidationError, match=field):
        ResultEvidenceManifestV1.model_validate(document)


def test_prize_table_is_zucai_only_and_has_exact_closed_tiers() -> None:
    jczq = _manifest()
    jczq["zucai_prize_table"] = _prize_table()
    with pytest.raises(ValidationError, match="JCZQ forbids"):
        ResultEvidenceManifestV1.model_validate(jczq)

    zucai = _manifest(lane="zucai")
    zucai["zucai_prize_table"] = _prize_table()
    parsed = ResultEvidenceManifestV1.model_validate(zucai)
    assert parsed.zucai_prize_table is not None

    missing_tier = deepcopy(zucai)
    missing_tier["zucai_prize_table"]["tiers"].pop()
    with pytest.raises(ValidationError, match="exactly the closed"):
        ResultEvidenceManifestV1.model_validate(missing_tier)

    duplicate_tier = deepcopy(zucai)
    duplicate_tier["zucai_prize_table"]["tiers"][2] = deepcopy(
        duplicate_tier["zucai_prize_table"]["tiers"][0]
    )
    with pytest.raises(ValidationError, match="exactly the closed"):
        ResultEvidenceManifestV1.model_validate(duplicate_tier)


def test_prize_table_rejects_issue_currency_and_timestamp_mismatches() -> None:
    wrong_issue = _manifest(lane="zucai")
    wrong_issue["zucai_prize_table"] = _prize_table()
    wrong_issue["zucai_prize_table"]["issue"] = "26121"
    with pytest.raises(ValidationError, match="issue does not match"):
        ResultEvidenceManifestV1.model_validate(wrong_issue)

    wrong_currency = _manifest(lane="zucai")
    wrong_currency["zucai_prize_table"] = _prize_table()
    wrong_currency["zucai_prize_table"]["currency"] = "USD"
    with pytest.raises(ValidationError):
        ResultEvidenceManifestV1.model_validate(wrong_currency)

    naive = _manifest(lane="zucai")
    naive["zucai_prize_table"] = _prize_table()
    naive["zucai_prize_table"]["published_at"] = "2026-09-05T10:00:00"
    with pytest.raises(ValidationError):
        ResultEvidenceManifestV1.model_validate(naive)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("official_winning_note_count", -1),
        ("payout_minor_per_winning_note", -1),
        ("payout_minor_per_winning_note", "1000"),
        ("required_correct_count", 13),
    ),
)
def test_prize_tier_rejects_invalid_integer_or_identity(
    field: str,
    value: object,
) -> None:
    document = _manifest(lane="zucai")
    document["zucai_prize_table"] = _prize_table()
    document["zucai_prize_table"]["tiers"][0][field] = value

    with pytest.raises(ValidationError):
        ResultEvidenceManifestV1.model_validate(document)


def test_normalization_distinguishes_missing_conflict_and_agreement() -> None:
    agreed = ResultEvidenceManifestV1.model_validate(_manifest()).matches[0].sources
    normalized = normalize_match_result(agreed)
    assert normalized.agreement_state == "agreed"
    assert (normalized.result_disposition, normalized.home_90, normalized.away_90) == (
        "played_90",
        2,
        1,
    )

    missing_document = _manifest()
    missing_document["matches"][0]["sources"][0].update(
        {
            "receipt_state": "missing",
            "artifact_retrieval_id": None,
            "captured_at": None,
            "source_disposition": None,
            "home_90": None,
            "away_90": None,
        }
    )
    missing = ResultEvidenceManifestV1.model_validate(missing_document)
    assert normalize_match_result(missing.matches[0].sources).agreement_state == "missing"

    conflict_document = _manifest()
    conflict_document["matches"][0]["sources"][2]["away_90"] = 0
    conflict = ResultEvidenceManifestV1.model_validate(conflict_document)
    assert normalize_match_result(conflict.matches[0].sources).agreement_state == "conflict"


def test_normalization_treats_invalid_or_disposition_disagreement_as_conflict() -> None:
    invalid_document = _manifest()
    invalid_document["matches"][0]["sources"][0].update(
        {
            "receipt_state": "invalid",
            "source_disposition": None,
            "home_90": None,
            "away_90": None,
            "invalid_code": "unsupported_status",
        }
    )
    invalid = ResultEvidenceManifestV1.model_validate(invalid_document)
    assert normalize_match_result(invalid.matches[0].sources).agreement_state == "conflict"

    disposition_document = _manifest()
    disposition_document["matches"][0]["sources"][2].update(
        {
            "source_disposition": "official_void",
            "home_90": None,
            "away_90": None,
        }
    )
    disagreement = ResultEvidenceManifestV1.model_validate(disposition_document)
    assert normalize_match_result(disagreement.matches[0].sources).agreement_state == (
        "conflict"
    )


@pytest.mark.parametrize("disposition", ("postponed", "official_void"))
def test_normalization_preserves_agreed_non_score_dispositions(
    disposition: str,
) -> None:
    document = _manifest()
    for source in document["matches"][0]["sources"]:
        source.update(
            {
                "source_disposition": disposition,
                "home_90": None,
                "away_90": None,
            }
        )
    parsed = ResultEvidenceManifestV1.model_validate(document)

    normalized = normalize_match_result(parsed.matches[0].sources)

    assert normalized.agreement_state == "agreed"
    assert normalized.result_disposition == disposition
    assert normalized.home_90 is None
    assert normalized.away_90 is None


def test_official_void_accepts_two_independent_non_completion_confirmations() -> None:
    document = _manifest()
    for source in document["matches"][0]["sources"]:
        source.update(
            {
                "source_disposition": "postponed",
                "home_90": None,
                "away_90": None,
            }
        )
    official = next(
        source
        for source in document["matches"][0]["sources"]
        if source["source_kind"] == "sporttery_game90"
    )
    official["source_disposition"] = "official_void"
    parsed = ResultEvidenceManifestV1.model_validate(document)

    normalized = normalize_match_result(parsed.matches[0].sources)

    assert normalized.agreement_state == "agreed"
    assert normalized.result_disposition == "official_void"
    assert normalized.home_90 is None
    assert normalized.away_90 is None


def test_import_result_evidence_set_writes_three_sources_and_outcome_atomically(
    tmp_path: Path,
) -> None:
    actions, engine = _setup_actions(tmp_path)

    result = actions.import_result_evidence_set(
        _import_request(_parsed_manifest())
    )

    assert result.outcome.status is ActionStatus.COMMITTED
    assert result.result_set is not None
    assert result.result_set.revision_no == 1
    assert result.result_set.task_family_id == "jczq:2026-09-05"
    assert result.result_set.task_snapshot_hash == "task-token"
    assert result.result_set.slate_revision_id == "slate-1"
    assert len(result.match_results) == 1
    assert len(result.source_receipts) == 3
    assert len(result.outcomes) == 1
    assert result.outcomes[0].result_disposition == "played_90"
    assert (result.outcomes[0].home_90, result.outcomes[0].away_90) == (2, 1)
    assert result.counts.agreement_counts == {
        "agreed": 1,
        "conflict": 0,
        "missing": 0,
    }
    assert result.counts.outcome_count == 1
    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(sor.operator_result_set_revisions)
        ) == 1
        assert connection.scalar(
            select(func.count()).select_from(sor.operator_result_source_receipts)
        ) == 3
        assert connection.scalar(
            select(func.count()).select_from(sor.operator_outcome_revisions)
        ) == 1


@pytest.mark.parametrize(
    ("state", "disposition", "expected_agreement", "expected_outcomes"),
    (
        ("missing", None, "missing", 0),
        ("invalid", None, "conflict", 0),
        ("available", "postponed", "agreed", 0),
        ("available", "official_void", "agreed", 1),
    ),
)
def test_import_result_outcome_creation_is_closed_by_agreement_and_disposition(
    tmp_path: Path,
    state: str,
    disposition: str | None,
    expected_agreement: str,
    expected_outcomes: int,
) -> None:
    actions, _engine = _setup_actions(tmp_path)
    document = _manifest()
    document["slate_revision_token"] = "slate-1"
    for source in document["matches"][0]["sources"]:
        if state == "missing":
            source.update(
                {
                    "receipt_state": "missing",
                    "artifact_retrieval_id": None,
                    "captured_at": None,
                    "source_disposition": None,
                    "home_90": None,
                    "away_90": None,
                }
            )
        elif state == "invalid":
            source.update(
                {
                    "receipt_state": "invalid",
                    "source_disposition": None,
                    "home_90": None,
                    "away_90": None,
                    "invalid_code": "schema_mismatch",
                }
            )
        else:
            source.update(
                {
                    "source_disposition": disposition,
                    "home_90": None,
                    "away_90": None,
                }
            )

    result = actions.import_result_evidence_set(
        _import_request(ResultEvidenceManifestV1.model_validate(document))
    )

    assert result.outcome.status is ActionStatus.COMMITTED
    assert result.match_results[0].agreement_state == expected_agreement
    assert len(result.outcomes) == expected_outcomes


def test_import_result_rejects_wrong_role_and_replays_exact_request(
    tmp_path: Path,
) -> None:
    actions, engine = _setup_actions(tmp_path)
    denied = actions.import_result_evidence_set(
        _import_request(
            _parsed_manifest(),
            key="result-import:denied",
            role=ActorRole.JUDGE_OPERATOR,
        )
    )
    assert denied.outcome.status is ActionStatus.REJECTED
    assert denied.result_set is None

    request = _import_request(_parsed_manifest())
    first = actions.import_result_evidence_set(request)
    replay = actions.import_result_evidence_set(request)

    assert replay == first
    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(sor.operator_result_set_revisions)
        ) == 1


@pytest.mark.parametrize(
    "failure_kind",
    (
        "missing_retrieval",
        "wrong_source_type",
        "false_official_url",
        "capture_mismatch",
        "slate_scope_mismatch",
        "match_set_mismatch",
    ),
)
def test_import_result_validates_every_reference_before_writing_business_rows(
    tmp_path: Path,
    failure_kind: str,
) -> None:
    actions, engine = _setup_actions(tmp_path)
    document = _manifest()
    document["slate_revision_token"] = "slate-1"
    if failure_kind == "missing_retrieval":
        document["matches"][0]["sources"][0]["artifact_retrieval_id"] = "absent"
    elif failure_kind == "wrong_source_type":
        with engine.begin() as connection:
            connection.execute(
                update(schema.artifact_retrievals)
                .where(
                    schema.artifact_retrievals.c.artifact_retrieval_id
                    == "retrieval-api_football"
                )
                .values(source_type="okooo_manual")
            )
    elif failure_kind == "false_official_url":
        with engine.begin() as connection:
            connection.execute(
                update(schema.artifact_retrievals)
                .where(
                    schema.artifact_retrievals.c.artifact_retrieval_id
                    == "retrieval-sporttery_game90"
                )
                .values(canonical_url="https://sporttery.example.test/results.json")
            )
    elif failure_kind == "capture_mismatch":
        document["matches"][0]["sources"][0]["captured_at"] = (
            "2026-09-05T08:00:01+08:00"
        )
    elif failure_kind == "slate_scope_mismatch":
        with engine.begin() as connection:
            connection.execute(
                update(sos.official_sale_slate_revisions)
                .where(sos.official_sale_slate_revisions.c.slate_revision_id == "slate-1")
                .values(business_key="2026-09-06")
            )
    else:
        document["matches"][0]["official_match_no"] = "周六002"

    with pytest.raises(ValueError):
        actions.import_result_evidence_set(
            _import_request(ResultEvidenceManifestV1.model_validate(document))
        )

    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(sor.operator_result_set_revisions)
        ) == 0
        assert connection.scalar(
            select(func.count()).select_from(sor.operator_result_match_revisions)
        ) == 0
        assert connection.scalar(
            select(func.count()).select_from(sor.operator_result_source_receipts)
        ) == 0
        assert connection.scalar(
            select(func.count()).select_from(sor.operator_outcome_revisions)
        ) == 0


def test_result_correction_requires_current_direct_predecessor_and_appends_outcome(
    tmp_path: Path,
) -> None:
    actions, engine = _setup_actions(tmp_path)
    first = actions.import_result_evidence_set(
        _import_request(_parsed_manifest())
    )
    assert first.result_set is not None

    correction_document = _manifest()
    correction_document["slate_revision_token"] = "slate-1"
    correction_document["supersedes_result_set_token"] = (
        first.result_set.result_set_revision_id
    )
    for source in correction_document["matches"][0]["sources"]:
        source["home_90"] = 1
        source["away_90"] = 1
    correction = actions.import_result_evidence_set(
        _import_request(
            ResultEvidenceManifestV1.model_validate(correction_document),
            key="result-import:2",
        )
    )

    assert correction.result_set is not None
    assert correction.result_set.revision_no == 2
    assert correction.result_set.supersedes_revision_id == (
        first.result_set.result_set_revision_id
    )
    assert correction.outcomes[0].supersedes_revision_id == (
        first.outcomes[0].outcome_revision_id
    )
    assert (correction.outcomes[0].home_90, correction.outcomes[0].away_90) == (1, 1)

    with pytest.raises(ValueError, match="current result set"):
        actions.import_result_evidence_set(
            _import_request(
                ResultEvidenceManifestV1.model_validate(correction_document),
                key="result-import:stale",
            )
        )
    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(sor.operator_result_set_revisions)
        ) == 2
        assert connection.scalar(
            select(func.count()).select_from(sor.operator_outcome_revisions)
        ) == 2


def test_zucai_import_writes_official_prize_table_and_corrects_direct_parent(
    tmp_path: Path,
) -> None:
    actions, engine = _setup_actions(tmp_path, lane="zucai")
    first_document = _manifest(lane="zucai")
    first_document["slate_revision_token"] = "slate-1"
    first_document["zucai_prize_table"] = _prize_table()
    first_document["zucai_prize_table"]["official_artifact_retrieval_id"] = (
        "retrieval-sporttery_game90"
    )
    first_document["zucai_prize_table"]["published_at"] = (
        "2026-09-05T08:00:00+08:00"
    )
    first = actions.import_result_evidence_set(
        _import_request(ResultEvidenceManifestV1.model_validate(first_document))
    )

    assert first.prize_table is not None
    assert first.prize_table.revision_no == 1
    assert len(first.prize_tiers) == 3
    assert first.result_set is not None
    assert first.result_set.zucai_prize_table_revision_id == (
        first.prize_table.prize_table_revision_id
    )

    correction_document = deepcopy(first_document)
    correction_document["supersedes_result_set_token"] = (
        first.result_set.result_set_revision_id
    )
    correction_document["zucai_prize_table"]["supersedes_prize_table_token"] = (
        first.prize_table.prize_table_revision_id
    )
    correction_document["zucai_prize_table"]["tiers"][0][
        "payout_minor_per_winning_note"
    ] = 1_200_000
    corrected = actions.import_result_evidence_set(
        _import_request(
            ResultEvidenceManifestV1.model_validate(correction_document),
            key="result-import:2",
        )
    )

    assert corrected.prize_table is not None
    assert corrected.prize_table.revision_no == 2
    assert corrected.prize_table.supersedes_revision_id == (
        first.prize_table.prize_table_revision_id
    )
    assert corrected.prize_tiers[0].payout_minor_per_winning_note == 1_200_000
    with engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(sor.zucai_prize_table_revisions)
        ) == 2
        assert connection.scalar(
            select(func.count()).select_from(sor.zucai_prize_table_tiers)
        ) == 6


def test_result_import_rolls_back_all_business_rows_when_a_child_insert_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions, engine = _setup_actions(tmp_path)
    original = OperatorResultRepository.insert_result_source_receipt
    call_count = 0

    def fail_second_receipt(repository, row):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("injected result receipt failure")
        return original(repository, row)

    monkeypatch.setattr(
        OperatorResultRepository,
        "insert_result_source_receipt",
        fail_second_receipt,
    )

    with pytest.raises(RuntimeError, match="injected result receipt failure"):
        actions.import_result_evidence_set(
            _import_request(_parsed_manifest())
        )

    with engine.connect() as connection:
        for table in (
            sor.operator_result_set_families,
            sor.operator_result_set_revisions,
            sor.operator_result_match_revisions,
            sor.operator_result_source_receipts,
            sor.operator_outcome_revisions,
        ):
            assert connection.scalar(select(func.count()).select_from(table)) == 0
        failed = connection.execute(
            select(schema.actions.c.status).where(
                schema.actions.c.action_type == "import_result_evidence_set"
            )
        ).scalars().all()
        assert failed == ["failed"]


def test_result_cli_reports_only_reconciled_business_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _setup_cli_data(tmp_path)
    document = _manifest()
    document["slate_revision_token"] = "slate-1"
    manifest = _write_manifest(tmp_path / "results.json", document)
    monkeypatch.setattr(workflow_cli, "_now", lambda: AT)

    result = _invoke_result_cli(data_dir, manifest)

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert set(payload) == {
        "agreement_counts",
        "business_key",
        "manifest_sha256",
        "outcome_count",
        "prize_table_state",
        "status",
    }
    assert payload == {
        "agreement_counts": {"agreed": 1, "conflict": 0, "missing": 0},
        "business_key": "2026-09-05",
        "manifest_sha256": ResultEvidenceManifestV1.model_validate(
            document
        ).manifest_sha256,
        "outcome_count": 1,
        "prize_table_state": "not_applicable",
        "status": "committed",
    }
    assert str(manifest) not in result.stdout
    assert "result_set_revision_id" not in result.stdout
    assert "source_artifact_retrieval" not in result.stdout


@pytest.mark.parametrize(
    ("result_case", "expected_agreement"),
    (
        ("missing", {"agreed": 0, "conflict": 0, "missing": 1}),
        ("conflict", {"agreed": 0, "conflict": 1, "missing": 0}),
        ("postponed", {"agreed": 1, "conflict": 0, "missing": 0}),
    ),
)
def test_result_cli_reports_nonsettleable_states_without_inventing_outcomes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    result_case: str,
    expected_agreement: dict[str, int],
) -> None:
    data_dir = _setup_cli_data(tmp_path)
    document = _manifest()
    document["slate_revision_token"] = "slate-1"
    sources = document["matches"][0]["sources"]
    if result_case == "missing":
        sources[0].update(
            {
                "receipt_state": "missing",
                "artifact_retrieval_id": None,
                "captured_at": None,
                "source_disposition": None,
                "home_90": None,
                "away_90": None,
                "invalid_code": None,
            }
        )
    elif result_case == "conflict":
        sources[-1]["away_90"] = 0
    else:
        for source in sources:
            source.update(
                {
                    "source_disposition": "postponed",
                    "home_90": None,
                    "away_90": None,
                }
            )
    manifest = _write_manifest(tmp_path / f"{result_case}.json", document)
    monkeypatch.setattr(workflow_cli, "_now", lambda: AT)

    result = _invoke_result_cli(data_dir, manifest)

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "committed"
    assert payload["agreement_counts"] == expected_agreement
    assert payload["outcome_count"] == 0
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir, _env_file=None))
    with kernel.engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(sor.operator_result_set_revisions)
        ) == 1
        assert connection.scalar(
            select(func.count()).select_from(sor.operator_result_source_receipts)
        ) == 3
        assert connection.scalar(
            select(func.count()).select_from(sor.operator_outcome_revisions)
        ) == 0


def test_result_cli_appends_one_direct_correction_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _setup_cli_data(tmp_path)
    document = _manifest()
    document["slate_revision_token"] = "slate-1"
    monkeypatch.setattr(workflow_cli, "_now", lambda: AT)
    first = _invoke_result_cli(
        data_dir,
        _write_manifest(tmp_path / "first.json", document),
    )
    assert first.exit_code == 0, first.stdout
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir, _env_file=None))
    with kernel.engine.connect() as connection:
        predecessor_id = connection.scalar(
            select(sor.operator_result_set_revisions.c.result_set_revision_id)
        )
    assert predecessor_id is not None
    _seed_correction_retrievals(kernel.engine)
    correction = deepcopy(document)
    correction["supersedes_result_set_token"] = predecessor_id
    correction["result_cutoff_at"] = "2026-09-05T09:01:00+08:00"
    for source in correction["matches"][0]["sources"]:
        source["home_90"] = 3
        source["captured_at"] = "2026-09-05T08:01:00+08:00"
        source["artifact_retrieval_id"] += "-correction"

    corrected = _invoke_result_cli(
        data_dir,
        _write_manifest(tmp_path / "corrected.json", correction),
    )

    assert corrected.exit_code == 0, corrected.stdout
    payload = json.loads(corrected.stdout)
    assert payload["agreement_counts"] == {
        "agreed": 1,
        "conflict": 0,
        "missing": 0,
    }
    assert payload["outcome_count"] == 1
    with kernel.engine.connect() as connection:
        result_sets = connection.execute(
            select(sor.operator_result_set_revisions).order_by(
                sor.operator_result_set_revisions.c.revision_no
            )
        ).mappings().all()
        outcomes = connection.execute(
            select(sor.operator_outcome_revisions).order_by(
                sor.operator_outcome_revisions.c.revision_no
            )
        ).mappings().all()
    assert [row["revision_no"] for row in result_sets] == [1, 2]
    assert result_sets[1]["supersedes_revision_id"] == predecessor_id
    assert [row["revision_no"] for row in outcomes] == [1, 2]
    assert outcomes[1]["supersedes_revision_id"] == outcomes[0]["outcome_revision_id"]


@pytest.mark.parametrize("failure_kind", ("malformed", "bad_reference"))
def test_result_cli_fails_closed_without_partial_business_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    data_dir = _setup_cli_data(tmp_path)
    if failure_kind == "malformed":
        document: object = {"schema_version": "result-evidence-v1"}
    else:
        document = _manifest()
        document["slate_revision_token"] = "missing-slate"
    manifest = _write_manifest(tmp_path / f"{failure_kind}.json", document)
    monkeypatch.setattr(workflow_cli, "_now", lambda: AT)

    result = _invoke_result_cli(data_dir, manifest)

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["code"] == "workflow_operation_blocked"
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir, _env_file=None))
    with kernel.engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(sor.operator_result_set_revisions)
        ) == 0
        assert connection.scalar(
            select(func.count()).select_from(sor.operator_result_source_receipts)
        ) == 0


def test_complete_zucai_result_fixture_covers_all_fourteen_matches() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "product"
        / "fixtures"
        / "operator"
        / "results"
        / "zucai-complete.json"
    )
    manifest = ResultEvidenceManifestV1.model_validate_json(
        fixture_path.read_text(encoding="utf-8")
    )

    assert manifest.lane == "zucai"
    assert [match.official_match_no for match in manifest.matches] == [
        str(number) for number in range(1, 15)
    ]
    assert len({match.canonical_match_id for match in manifest.matches}) == 14
    assert all(len(match.sources) == 3 for match in manifest.matches)
    assert manifest.zucai_prize_table is not None
    assert {tier.tier_code for tier in manifest.zucai_prize_table.tiers} == {
        "sfc_first",
        "sfc_second",
        "renjiu_first",
    }
