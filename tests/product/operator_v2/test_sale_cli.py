from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, insert, select
from typer.testing import CliRunner

from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.cli import app
from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.repository import schema, schema_identity
from nutmeg.ontology.repository import schema_operator_sale as sos
from nutmeg.ontology.wiring import build_ontology_kernel


def _data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    kernel.initialize()
    at = "2026-09-04T08:01:00+08:00"
    with kernel.engine.begin() as connection:
        connection.execute(
            insert(schema.source_runs).values(
                source_run_id="run-official",
                source_name="sporttery",
                source_type="official_schedule",
                started_at=at,
                finished_at=at,
                status="succeeded",
                error_code=None,
                error_detail=None,
            )
        )
        for suffix, source_name in (
            ("official", "sporttery"),
            ("unofficial", "api-football"),
        ):
            connection.execute(
                insert(schema.source_artifacts).values(
                    artifact_id=f"artifact-{suffix}",
                    first_recorded_at=at,
                    content_type="application/json",
                    storage_path=f"sha256/{suffix}",
                    byte_size=2,
                    content_hash=("a" if suffix == "official" else "b") * 64,
                )
            )
            connection.execute(
                insert(schema.artifact_retrievals).values(
                    artifact_retrieval_id=f"retrieval-{suffix}",
                    artifact_id=f"artifact-{suffix}",
                    source_run_id="run-official",
                    source_name=source_name,
                    source_type=(
                        "official_sale_schedule" if suffix == "official" else "fixture"
                    ),
                    reported_content_type="application/json",
                    canonical_url=(
                        f"https://www.sporttery.cn/{suffix}.json"
                        if suffix == "official"
                        else f"https://example.test/{suffix}.json"
                    ),
                    requested_url=(
                        f"https://www.sporttery.cn/{suffix}.json"
                        if suffix == "official"
                        else f"https://example.test/{suffix}.json"
                    ),
                    published_at=at,
                    retrieved_at=at,
                    status="stored",
                )
            )
        connection.execute(
            insert(schema_identity.matches).values(match_id="match-1", current_revision_id=None)
        )
        connection.execute(
            insert(schema.source_artifacts).values(
                artifact_id="artifact-official-revision",
                first_recorded_at="2026-09-04T08:02:00+08:00",
                content_type="application/json",
                storage_path="sha256/official-revision",
                byte_size=2,
                content_hash="c" * 64,
            )
        )
        connection.execute(
            insert(schema.artifact_retrievals).values(
                artifact_retrieval_id="retrieval-official-revision",
                artifact_id="artifact-official-revision",
                source_run_id="run-official",
                source_name="sporttery",
                source_type="official_sale_schedule",
                reported_content_type="application/json",
                canonical_url="https://www.sporttery.cn/official-revision.json",
                requested_url="https://www.sporttery.cn/official-revision.json",
                published_at=at,
                retrieved_at="2026-09-04T08:02:00+08:00",
                status="stored",
            )
        )
    return data_dir


def _sale_document(**changes: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "official-sale-slate-v1",
        "lane": "jczq",
        "business_key": "2026-09-04",
        "published_at": "2026-09-04T08:00:00+08:00",
        "retrieved_at": "2026-09-04T08:01:00+08:00",
        "parser_contract_version": "sporttery-official-sale-parser-v1",
        "official_source_content_hash": "a" * 64,
        "official_source_artifact_retrieval_id": "retrieval-official",
        "supersedes_slate_revision_id": None,
        "offers": [
            {
                "canonical_match_id": "match-1",
                "official_match_no": "周五001",
                "market_definition_ids": ["md-had"],
                "sale_opens_at": "2026-09-04T08:00:00+08:00",
                "sale_deadline_at": "2026-09-04T19:00:00+08:00",
                "status": "on_sale",
            }
        ],
    }
    document.update(changes)
    return document


def _write(path: Path, document: object) -> Path:
    path.write_text(json.dumps(document, ensure_ascii=False), "utf-8")
    return path


def _invoke_sale(data_dir: Path, manifest: Path, version: str = "official-sale-slate-v1"):
    return CliRunner().invoke(
        app,
        [
            "workflow",
            "ingest-official-sale",
            "--manifest",
            str(manifest),
            "--contract-version",
            version,
            "--data-dir",
            str(data_dir),
        ],
    )


def test_sale_cli_commits_and_reports_persisted_counts(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    manifest = _write(tmp_path / "sale.json", _sale_document())

    result = _invoke_sale(data_dir, manifest)

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["contract_version"] == "official-sale-slate-v1"
    assert payload["action_id"].startswith("ACT-")
    assert payload["status"] == "committed"
    assert payload["lane"] == "jczq"
    assert payload["business_key"] == "2026-09-04"
    assert payload["revision_no"] == 1
    assert payload["committed_counts"] == {
        "slate_revisions": 1,
        "offer_families": 1,
        "offer_revisions": 1,
    }
    assert payload["created_counts"] == payload["committed_counts"]
    assert payload["persisted_counts"] == {
        "slate_revisions": 1,
        "offer_families": 1,
        "offer_revisions": 1,
    }


def test_sale_cli_accepts_approved_minimal_v1_manifest(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    document = _sale_document()
    document.pop("parser_contract_version")
    document.pop("official_source_content_hash")
    manifest = _write(tmp_path / "minimal-sale.json", document)

    result = _invoke_sale(data_dir, manifest)

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["status"] == "committed"


def test_sale_cli_revision_distinguishes_created_and_linked_counts(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    first_manifest = _write(tmp_path / "sale-first.json", _sale_document())
    first = _invoke_sale(data_dir, first_manifest)
    first_payload = json.loads(first.stdout)
    revised_offer = dict(_sale_document()["offers"][0])
    revised_offer["status"] = "sale_closed"
    revision_manifest = _write(
        tmp_path / "sale-revision.json",
        _sale_document(
            retrieved_at="2026-09-04T08:02:00+08:00",
            official_source_artifact_retrieval_id="retrieval-official-revision",
            official_source_content_hash="c" * 64,
            supersedes_slate_revision_id=first_payload["slate_revision_id"],
            offers=[revised_offer],
        ),
    )

    revision = _invoke_sale(data_dir, revision_manifest)

    assert revision.exit_code == 0, revision.stdout
    payload = json.loads(revision.stdout)
    assert payload["created_counts"] == {
        "slate_revisions": 1,
        "offer_families": 0,
        "offer_revisions": 1,
    }
    assert payload["committed_counts"] == payload["persisted_counts"] == {
        "slate_revisions": 1,
        "offer_families": 1,
        "offer_revisions": 1,
    }


def test_sale_cli_accepts_official_retrieval_from_artifact_ingest_service(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    kernel.initialize()
    at = "2026-09-04T08:01:00+08:00"
    with kernel.engine.begin() as connection:
        connection.execute(
            insert(schema.source_runs).values(
                source_run_id="run-official",
                source_name="sporttery",
                source_type="official_schedule",
                started_at=at,
                finished_at=at,
                status="succeeded",
                error_code=None,
                error_detail=None,
            )
        )
        connection.execute(
            insert(schema_identity.matches).values(
                match_id="match-1", current_revision_id=None
            )
        )
    ingest = kernel.artifact_ingest.ingest(
        ArtifactIngestRequest(
            content=b'{"sale":"official"}',
            content_type="application/json",
            source_name="sporttery",
            source_type="official_sale_schedule",
            actor_id="connector:sporttery",
            actor_role=ActorRole.CONNECTOR,
            idempotency_key="official-sale-retrieval:2026-09-04",
            retrieved_at=datetime(2026, 9, 4, 0, 1, tzinfo=UTC),
            source_run_id="run-official",
            canonical_url="https://www.sporttery.cn/official-sale.json",
        )
    )
    retrieval_id = next(
        ref.object_id for ref in ingest.result_refs if ref.object_type == "artifact_retrieval"
    )
    manifest = _write(
        tmp_path / "sale-from-ingest.json",
        _sale_document(
            official_source_artifact_retrieval_id=retrieval_id,
            official_source_content_hash=next(
                ref.object_id.removeprefix("sha256:")
                for ref in ingest.result_refs
                if ref.object_type == "source_artifact"
            ),
            retrieved_at="2026-09-04T00:01:00+00:00",
        ),
    )

    result = _invoke_sale(data_dir, manifest)

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["status"] == "committed"


def test_sale_cli_replay_uses_one_action_and_one_slate(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    manifest = _write(tmp_path / "sale.json", _sale_document())

    first = _invoke_sale(data_dir, manifest)
    replay = _invoke_sale(data_dir, manifest)

    assert first.exit_code == replay.exit_code == 0
    assert json.loads(first.stdout)["action_id"] == json.loads(replay.stdout)["action_id"]
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    with kernel.engine.connect() as connection:
        assert (
            connection.scalar(select(func.count()).select_from(sos.official_sale_slate_revisions))
            == 1
        )


def test_sale_cli_rejects_contract_and_source_without_partial_rows(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    mismatch = _write(tmp_path / "mismatch.json", _sale_document())
    unofficial = _write(
        tmp_path / "unofficial.json",
        _sale_document(official_source_artifact_retrieval_id="retrieval-unofficial"),
    )

    wrong_version = _invoke_sale(data_dir, mismatch, "official-sale-slate-v2")
    wrong_source = _invoke_sale(data_dir, unofficial)

    assert wrong_version.exit_code == 1
    assert "contract" in wrong_version.stdout
    assert wrong_source.exit_code == 1
    assert "official" in wrong_source.stdout
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    with kernel.engine.connect() as connection:
        assert (
            connection.scalar(select(func.count()).select_from(sos.official_sale_slate_revisions))
            == 0
        )


def test_schedule_check_cli_commits_exact_receipt(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    sale = _write(tmp_path / "sale.json", _sale_document())
    assert _invoke_sale(data_dir, sale).exit_code == 0
    check = _write(
        tmp_path / "check.json",
        {
            "schema_version": "official-schedule-check-v1",
            "lane": "jczq",
            "shanghai_check_date": "2026-09-04",
            "checked_at": "2026-09-04T08:02:00+08:00",
            "source_run_id": "run-official",
            "check_state": "slate_imported",
            "parser_contract_version": "sporttery-official-sale-parser-v1",
            "official_source_content_hash": "a" * 64,
            "official_source_artifact_retrieval_id": "retrieval-official",
            "observed_business_keys": ["2026-09-04"],
            "imported_business_keys": ["2026-09-04"],
            "error_code": None,
        },
    )

    result = CliRunner().invoke(
        app,
        [
            "workflow",
            "record-official-schedule-check",
            "--manifest",
            str(check),
            "--contract-version",
            "official-schedule-check-v1",
            "--data-dir",
            str(data_dir),
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["contract_version"] == "official-schedule-check-v1"
    assert payload["action_id"].startswith("ACT-")
    assert payload["status"] == "committed"
    assert payload["check_state"] == "slate_imported"
    assert payload["persisted_receipt_count"] == 1


def test_sale_cli_parses_complete_manifest_before_writing(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    malformed = _write(
        tmp_path / "malformed.json",
        {**_sale_document(), "offers": [{"canonical_match_id": "match-1"}]},
    )

    result = _invoke_sale(data_dir, malformed)

    assert result.exit_code == 1
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    with kernel.engine.connect() as connection:
        assert (
            connection.scalar(select(func.count()).select_from(sos.official_sale_slate_revisions))
            == 0
        )
        assert connection.scalar(select(func.count()).select_from(schema.actions)) == 0


def test_sale_cli_rejects_numeric_epoch_datetime_without_writing(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    malformed = _write(
        tmp_path / "numeric-time.json",
        _sale_document(published_at=1_788_480_000),
    )

    result = _invoke_sale(data_dir, malformed)

    assert result.exit_code == 1
    assert "published_at" in result.stdout
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    with kernel.engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(sos.official_sale_slate_revisions)
        ) == 0
        assert connection.scalar(select(func.count()).select_from(schema.actions)) == 0
