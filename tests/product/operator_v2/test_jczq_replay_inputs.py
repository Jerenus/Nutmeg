import json
import os
from pathlib import Path

import pytest

from nutmeg.product.jczq_replay_inputs import ReplayInputManifest, freeze_replay_inputs


def _write(path: Path, document: object) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    _write(source / "sporttery_markets.json", {"lastUpdateTime": "2026-09-19 17:13:39"})
    _write(source / "market.json", {"updated_at": "2026-09-19T17:13:39+08:00"})
    _write(source / "reads.json", [{"made_at": "2026-09-19T12:00:00+08:00"}])
    _write(source / "research-周六001.json", {"captured_at": "2026-09-19T12:03:42+08:00"})
    _write(source / "research-周六002.rejected.json", {"error": "rejected"})
    _write(source / "results.json", {"published_at": "2026-09-20T06:00:00+08:00"})
    return source


def test_freeze_records_hash_size_time_and_order_independent_manifest(tmp_path: Path) -> None:
    source = _source(tmp_path)
    os.utime(source / "research-周六002.rejected.json", (1, 1))
    manifest = freeze_replay_inputs(source, tmp_path / "frozen")

    assert len(manifest.entries) == 6
    assert all(entry.byte_size > 0 and len(entry.sha256) == 64 for entry in manifest.entries)
    assert all(not Path(entry.relative_path).is_absolute() for entry in manifest.entries)
    assert manifest.entry("research-周六001.json").semantic_timestamp == (
        "2026-09-19T12:03:42+08:00"
    )
    rejected = manifest.entry("research-周六002.rejected.json")
    assert rejected.semantic_timestamp is None
    assert rejected.temporal_status == "unknown"
    assert manifest.quarantined == (
        manifest.quarantined[0],
    )
    assert manifest.quarantined[0].relative_path == rejected.relative_path
    assert rejected.relative_path not in manifest.evidence_paths()

    reordered = ReplayInputManifest(
        root=manifest.root,
        entries=tuple(reversed(manifest.entries)),
        quarantined=manifest.quarantined,
    )
    assert reordered.manifest_hash == manifest.manifest_hash


def test_manifest_detects_copied_byte_mutation(tmp_path: Path) -> None:
    manifest = freeze_replay_inputs(_source(tmp_path), tmp_path / "frozen")
    copied = Path(manifest.root) / "reads.json"
    copied.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="source_manifest_changed"):
        manifest.verify()


def test_missing_time_on_accepted_research_is_rejected(tmp_path: Path) -> None:
    source = _source(tmp_path)
    _write(source / "research-周六001.json", {"summary": "no time"})
    with pytest.raises(ValueError, match="semantic timestamp missing"):
        freeze_replay_inputs(source, tmp_path / "frozen")


def test_research_run_metadata_is_not_treated_as_match_evidence(tmp_path: Path) -> None:
    source = _source(tmp_path)
    _write(source / "research-run-2026-09-19.json", {"status": "complete"})

    manifest = freeze_replay_inputs(source, tmp_path / "frozen")

    assert all(
        entry.relative_path != "research-run-2026-09-19.json"
        for entry in manifest.entries
    )
