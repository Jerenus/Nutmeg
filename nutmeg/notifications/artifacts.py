from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from uuid import uuid4

from nutmeg.notifications.models import NotificationAttachment, StoredArtifact


class ArtifactStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def snapshot(
        self, notification_id: str, attachment: NotificationAttachment
    ) -> StoredArtifact:
        source = attachment.path.resolve()
        if not source.is_file():
            raise FileNotFoundError(f"notification attachment not found: {source}")

        destination_dir = self.root / notification_id
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / attachment.resolved_filename
        digest = hashlib.sha256()
        size_bytes = 0
        with source.open("rb") as source_handle, destination.open("xb") as target_handle:
            while chunk := source_handle.read(1024 * 1024):
                target_handle.write(chunk)
                digest.update(chunk)
                size_bytes += len(chunk)

        return StoredArtifact(
            artifact_id=f"A-{uuid4().hex}",
            notification_id=notification_id,
            path=destination,
            original_name=attachment.resolved_filename,
            media_type=attachment.media_type,
            size_bytes=size_bytes,
            sha256=digest.hexdigest(),
        )

    def remove_notification(self, notification_id: str) -> None:
        path = self.root / notification_id
        if path.exists():
            shutil.rmtree(path)
