from pathlib import Path

import pytest

from nutmeg.ontology.artifacts import ContentAddressedArtifactStore


def test_put_bytes_uses_hash_path_and_does_not_rewrite(tmp_path: Path) -> None:
    store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    first = store.put_bytes(b"same evidence")
    first_mtime = first.absolute_path.stat().st_mtime_ns
    second = store.put_bytes(b"same evidence")
    assert first.artifact_id == f"sha256:{first.content_hash}"
    assert first.relative_path == Path("sha256") / first.content_hash[:2] / first.content_hash
    assert first.absolute_path.read_bytes() == b"same evidence"
    assert second == first
    assert second.absolute_path.stat().st_mtime_ns == first_mtime
    assert list((tmp_path / "artifacts").rglob("*.tmp")) == []


def test_put_file_rejects_non_file_and_preserves_bytes(tmp_path: Path) -> None:
    store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    source = tmp_path / "source.json"
    source.write_bytes(b'{"ok":true}')
    blob = store.put_file(source)
    assert blob.byte_size == len(b'{"ok":true}')
    assert blob.absolute_path.read_bytes() == source.read_bytes()
    with pytest.raises(FileNotFoundError):
        store.put_file(tmp_path / "missing.json")
