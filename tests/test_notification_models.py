from pathlib import Path

import pytest

from nutmeg.notifications.artifacts import ArtifactStore
from nutmeg.notifications.models import (
    NotificationAttachment,
    NotificationRequest,
    NotificationStatus,
    semantic_fingerprint,
)


def test_semantic_fingerprint_ignores_mapping_order() -> None:
    assert semantic_fingerprint({"stage": "close", "items": [1, 2]}) == semantic_fingerprint(
        {"items": [1, 2], "stage": "close"}
    )


def test_request_builds_stable_dedupe_key(tmp_path: Path) -> None:
    report = tmp_path / "report.pdf"
    report.write_bytes(b"%PDF-report")
    request = NotificationRequest(
        kind="decision.close.report",
        business_key="2026-07-17",
        stage="close",
        semantic_fingerprint="abc123",
        subject="Decision report",
        caption="Decision report 2026-07-17",
        attachments=(NotificationAttachment(report, "application/pdf"),),
    )

    assert request.dedupe_key == "decision.close.report:2026-07-17:close:abc123"
    assert NotificationStatus.SENT.is_success is True
    assert NotificationStatus.PARTIAL.is_success is False


def test_artifact_store_snapshots_once_and_rejects_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF-report")
    store = ArtifactStore(tmp_path / "artifacts")

    stored = store.snapshot("N-1", NotificationAttachment(source, "application/pdf"))

    assert stored.path.read_bytes() == b"%PDF-report"
    assert stored.size_bytes == len(b"%PDF-report")
    assert len(stored.sha256) == 64
    with pytest.raises(FileExistsError):
        store.snapshot("N-1", NotificationAttachment(source, "application/pdf"))


def test_text_request_requires_content() -> None:
    with pytest.raises(ValueError, match="text or attachment"):
        NotificationRequest(
            kind="operations.failure",
            business_key="am:2026-07-17",
            stage="am",
            semantic_fingerprint="failure",
            subject="AM failed",
        )
