"""Immutable SHA-256 content-addressed artifact store.

Raw evidence is written once and never edited in place. A blob lives at
``sha256/<first-2>/<digest>`` under the store root; its digest *is* its identity.
Publication is atomic and immutability-preserving: bytes are written to a fsynced
temporary file, then hard-linked into place with ``os.link`` (not ``rename``,
which would clobber an existing identical blob and refresh its mtime). A
``FileExistsError`` means a concurrent writer already published the same content,
which is safe to reuse.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from nutmeg.ontology.errors import OntologyError

_CHUNK_SIZE = 1024 * 1024  # 1 MiB


@dataclass(frozen=True, slots=True)
class ArtifactBlob:
    artifact_id: str
    content_hash: str
    byte_size: int
    relative_path: Path
    absolute_path: Path


class ContentAddressedArtifactStore:
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def put_bytes(self, data: bytes) -> ArtifactBlob:
        digest = hashlib.sha256(data).hexdigest()
        byte_size = len(data)
        destination = self._destination(digest)
        if destination.exists() and destination.stat().st_size == byte_size:
            return self._blob(digest, byte_size)

        destination.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(delete=False, dir=destination.parent, suffix='.tmp') as temp:
            temp_path = Path(temp.name)
            try:
                temp.write(data)
                temp.flush()
                os.fsync(temp.fileno())
            except BaseException:
                temp_path.unlink(missing_ok=True)
                raise
        self._publish(temp_path, destination, byte_size)
        return self._blob(digest, byte_size)

    def put_file(self, source: Path | str) -> ArtifactBlob:
        source_path = Path(source).resolve()
        if not source_path.is_file():
            raise FileNotFoundError(source_path)

        self._root.mkdir(parents=True, exist_ok=True)
        hasher = hashlib.sha256()
        byte_size = 0
        with NamedTemporaryFile(delete=False, dir=self._root, suffix='.tmp') as temp:
            temp_path = Path(temp.name)
            try:
                with source_path.open('rb') as reader:
                    while chunk := reader.read(_CHUNK_SIZE):
                        hasher.update(chunk)
                        byte_size += len(chunk)
                        temp.write(chunk)
                temp.flush()
                os.fsync(temp.fileno())
            except BaseException:
                temp_path.unlink(missing_ok=True)
                raise

        digest = hasher.hexdigest()
        destination = self._destination(digest)
        if destination.exists() and destination.stat().st_size == byte_size:
            temp_path.unlink(missing_ok=True)
            return self._blob(digest, byte_size)
        self._publish(temp_path, destination, byte_size)
        return self._blob(digest, byte_size)

    def _publish(self, temp_path: Path, destination: Path, byte_size: int) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            try:
                os.link(temp_path, destination)
            except FileExistsError:
                # A concurrent writer already published this exact content.
                pass
        finally:
            temp_path.unlink(missing_ok=True)
            self._fsync_directory(destination.parent)
        published_size = destination.stat().st_size
        if published_size != byte_size:
            raise OntologyError(
                f'artifact size mismatch at {destination}: '
                f'expected {byte_size}, found {published_size}'
            )

    def _relative_path(self, digest: str) -> Path:
        return Path('sha256') / digest[:2] / digest

    def _destination(self, digest: str) -> Path:
        return self._root / self._relative_path(digest)

    def _blob(self, digest: str, byte_size: int) -> ArtifactBlob:
        relative = self._relative_path(digest)
        return ArtifactBlob(
            artifact_id=f'sha256:{digest}',
            content_hash=digest,
            byte_size=byte_size,
            relative_path=relative,
            absolute_path=self._root / relative,
        )

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
