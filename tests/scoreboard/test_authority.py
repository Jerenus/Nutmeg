import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nutmeg.analytics.calibrate_flow import CalibrateRequest
from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.models import ActorRole, ObjectRef
from nutmeg.ontology.actions.scoreboard_actions import RecordScoreboardObservationRequest
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.scoreboard.authority import (
    ScoreboardAuthorityError,
    ScoreboardAuthorityService,
    ScoreboardExportDriftError,
    atomic_write,
    check_sop_authority,
)

AT = datetime(2026, 8, 24, 10, tzinfo=UTC)
FIXTURE_SOP = Path("tests/fixtures/m5/sop")


def _setup(tmp_path: Path):
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    kernel.scoreboard_actions.record_observation(
        RecordScoreboardObservationRequest(
            group_key="chains",
            metric_key="main",
            tally="1/1",
            detail="formalized legacy manual metric",
            status="active",
            numerator=1.0,
            denominator=1.0,
            value=1.0,
            unit="ratio",
            evidence_refs=[ObjectRef("adjudication", "adj-evidence")],
            effective_at=AT,
            supersedes_observation_id=None,
            actor_id="operator:jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="m5:authority:observation",
            requested_at=AT,
        )
    )
    projection = kernel.calibrate.build(
        CalibrateRequest(
            as_of=AT.isoformat(),
            built_at="2026-08-24T10:30:00+00:00",
        )
    )
    legacy = tmp_path / "scoreboard.json"
    legacy.write_bytes(
        b'{"updated_at":"2026-08-24T09:00:00Z","chains":{"main":1}}\n'
    )
    sop_root = tmp_path / "sop"
    shutil.copytree(FIXTURE_SOP, sop_root)
    service = ScoreboardAuthorityService(kernel)
    return kernel, service, legacy, sop_root, projection.high_watermark


def _classification(classification: str = "formal_manual") -> list[dict[str, object]]:
    item: dict[str, object] = {
        "group_key": "chains",
        "metric_key": "main",
        "classification": classification,
    }
    if classification == "formal_manual":
        item["target_ref"] = "scoreboard_observation:chains:main"
    if classification == "source_correction":
        item["reason"] = "legacy tally was transcribed incorrectly"
        item["evidence_refs"] = [
            {"object_type": "adjudication", "object_id": "adj-evidence"}
        ]
    return [item]


def test_sop_checker_requires_all_statements_in_all_five_documents(
    tmp_path: Path,
) -> None:
    _kernel, _service, _legacy, sop_root, _watermark = _setup(tmp_path)
    paths = [sop_root / name for name in (
        "CONSTITUTION.md", "RUNBOOK.md", "RULEBOOK.md", "AGENTS.md", "CLAUDE.md"
    )]

    assert check_sop_authority(paths).ready is True
    paths[2].write_text("scoreboard authority: ontology\n", encoding="utf-8")
    report = check_sop_authority(paths)
    assert report.ready is False
    assert report.missing_by_path[str(paths[2])]


def test_shadow_hashes_exact_bytes_and_requires_complete_explicit_classification(
    tmp_path: Path,
) -> None:
    kernel, service, legacy, _sop_root, watermark = _setup(tmp_path)
    digest = hashlib.sha256(legacy.read_bytes()).hexdigest()

    with pytest.raises(ScoreboardAuthorityError, match="acknowledge"):
        service.shadow(
            legacy_path=legacy,
            classification=[],
            projection_version="sb-v1",
            source_high_watermark=watermark,
            acknowledge_manual_source=False,
            requested_at=AT,
        )
    with pytest.raises(ScoreboardAuthorityError, match="classification coverage"):
        service.shadow(
            legacy_path=legacy,
            classification=[],
            projection_version="sb-v1",
            source_high_watermark=watermark,
            acknowledge_manual_source=True,
            requested_at=AT,
        )

    outcome = service.shadow(
        legacy_path=legacy,
        classification=_classification(),
        projection_version="sb-v1",
        source_high_watermark=watermark,
        acknowledge_manual_source=True,
        requested_at=AT,
    )
    review_id = outcome.result_refs[0].object_id
    with OntologyUnitOfWork(kernel.engine) as uow:
        review = uow.scoreboard.shadow_review(review_id)
    assert review is not None
    assert review.legacy_sha256 == digest
    assert review.manual_count == 1
    assert review.unexplained_count == 0


def test_unexplained_shadow_or_incomplete_sop_blocks_cutover(tmp_path: Path) -> None:
    _kernel, service, legacy, sop_root, watermark = _setup(tmp_path)
    review = service.shadow(
        legacy_path=legacy,
        classification=_classification("unexplained"),
        projection_version="sb-v1",
        source_high_watermark=watermark,
        acknowledge_manual_source=True,
        requested_at=AT,
    )
    with pytest.raises(ValueError, match="unexplained"):
        service.cutover(
            legacy_path=legacy,
            shadow_review_id=review.result_refs[0].object_id,
            expected_authority_version=1,
            sop_paths=list(sop_root.iterdir()),
            approve=True,
            requested_at=AT,
        )

    clean = service.shadow(
        legacy_path=legacy,
        classification=_classification(),
        projection_version="sb-v1",
        source_high_watermark=watermark,
        acknowledge_manual_source=True,
        requested_at=AT,
    )
    (sop_root / "CLAUDE.md").write_text("incomplete\n", encoding="utf-8")
    with pytest.raises(ScoreboardAuthorityError, match="SOP authority"):
        service.cutover(
            legacy_path=legacy,
            shadow_review_id=clean.result_refs[0].object_id,
            expected_authority_version=1,
            sop_paths=list(sop_root.iterdir()),
            approve=True,
            requested_at=AT,
        )


def test_clean_isolated_cutover_exports_canonical_bytes_and_detects_drift(
    tmp_path: Path,
) -> None:
    kernel, service, legacy, sop_root, watermark = _setup(tmp_path)
    review = service.shadow(
        legacy_path=legacy,
        classification=_classification(),
        projection_version="sb-v1",
        source_high_watermark=watermark,
        acknowledge_manual_source=True,
        requested_at=AT,
    )
    source_hash = hashlib.sha256(legacy.read_bytes()).hexdigest()
    cutover = service.cutover(
        legacy_path=legacy,
        shadow_review_id=review.result_refs[0].object_id,
        expected_authority_version=1,
        sop_paths=list(sop_root.iterdir()),
        approve=True,
        requested_at=AT,
    )
    assert cutover.status.value == "committed"

    destination = tmp_path / "compatibility" / "scoreboard.json"
    exported = service.export(destination, requested_at=AT)
    document = json.loads(destination.read_text(encoding="utf-8"))
    assert hashlib.sha256(destination.read_bytes()).hexdigest() == exported.sha256
    assert document["authority"]["state"] == "ontology"
    assert document["projection"]["version"] == "sb-v1"
    assert document["projection"]["source_high_watermark"] == watermark
    assert document["generation_action_ref"] == {
        "object_type": "action",
        "object_id": exported.action_id,
    }
    assert {"forecast", "money", "intervention", "lifecycle", "manual"} <= set(
        document["planes"]
    )
    assert hashlib.sha256(legacy.read_bytes()).hexdigest() == source_hash

    repeated = service.export(destination, requested_at=AT)
    assert repeated.sha256 == exported.sha256
    assert repeated.action_id == exported.action_id

    destination.write_text("manual edit\n", encoding="utf-8")
    with pytest.raises(ScoreboardExportDriftError, match="drift"):
        service.export(destination, requested_at=AT)
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.scoreboard.authority().state == "ontology"


def test_atomic_write_keeps_prior_complete_file_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "scoreboard.json"
    destination.write_bytes(b"prior-complete")

    def fail_replace(_source, _destination):
        raise OSError("injected replace failure")

    monkeypatch.setattr("nutmeg.scoreboard.authority.os.replace", fail_replace)
    with pytest.raises(OSError, match="injected"):
        atomic_write(destination, b"new-content")
    assert destination.read_bytes() == b"prior-complete"
    assert list(tmp_path.glob("*.tmp")) == []
