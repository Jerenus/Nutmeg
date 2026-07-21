from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.wiring import build_ontology_kernel


def _request(key: str) -> ArtifactIngestRequest:
    return ArtifactIngestRequest(
        content=b"restart-safe-evidence",
        content_type="application/octet-stream",
        source_name="package1-e2e",
        source_type="test",
        actor_id="source:e2e",
        actor_role=ActorRole.CONNECTOR,
        idempotency_key=key,
        retrieved_at=datetime(2026, 7, 21, 9, tzinfo=UTC),
    )


def test_kernel_reopens_with_same_schema_action_and_artifact(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    first = build_ontology_kernel(settings)
    first.initialize()
    outcome = first.artifact_ingest.ingest(_request("e2e:restart"))
    assert outcome.status is ActionStatus.COMMITTED

    reopened = build_ontology_kernel(settings)
    assert reopened.initialize().applied_versions == ()
    status = reopened.status()
    assert status.integrity_check == "ok"
    assert status.action_counts == {"committed": 1}
    assert status.artifact_count == 1
    assert status.retrieval_count == 1
    digest = outcome.result_refs[0].object_id.removeprefix("sha256:")
    assert (settings.ontology_artifact_dir / "sha256" / digest[:2] / digest).read_bytes() == (
        b"restart-safe-evidence"
    )


def test_concurrent_same_key_commits_one_action_and_retrieval(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _index: kernel.artifact_ingest.ingest(
            _request("e2e:concurrent")
        ), range(2)))
    assert len({outcome.action_id for outcome in outcomes}) == 1
    assert kernel.status().action_counts == {"committed": 1}
    assert kernel.status().artifact_count == 1
    assert kernel.status().retrieval_count == 1
