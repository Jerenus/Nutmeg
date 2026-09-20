"""Immutable input manifests for isolated JCZQ historical replay."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from nutmeg.ontology.actions.models import canonical_json


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class ReplayInputEntry:
    relative_path: str
    kind: str
    byte_size: int
    sha256: str
    semantic_timestamp: str | None
    temporal_status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "kind": self.kind,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
            "semantic_timestamp": self.semantic_timestamp,
            "temporal_status": self.temporal_status,
        }


@dataclass(frozen=True, slots=True)
class QuarantinedReplayInput:
    relative_path: str
    temporal_status: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "relative_path": self.relative_path,
            "temporal_status": self.temporal_status,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ReplayInputManifest:
    root: str
    entries: tuple[ReplayInputEntry, ...]
    quarantined: tuple[QuarantinedReplayInput, ...]

    @property
    def manifest_hash(self) -> str:
        material = {
            "entries": [
                entry.to_dict()
                for entry in sorted(self.entries, key=lambda item: item.relative_path)
            ],
            "quarantined": [
                item.to_dict()
                for item in sorted(
                    self.quarantined, key=lambda item: item.relative_path
                )
            ],
        }
        return _sha256(canonical_json(material).encode("utf-8"))

    def entry(self, relative_path: str) -> ReplayInputEntry:
        for entry in self.entries:
            if entry.relative_path == relative_path:
                return entry
        raise KeyError(relative_path)

    def evidence_paths(self) -> tuple[str, ...]:
        excluded = {item.relative_path for item in self.quarantined}
        return tuple(
            entry.relative_path
            for entry in self.entries
            if entry.relative_path not in excluded
        )

    def verify(self) -> None:
        root = Path(self.root)
        for entry in self.entries:
            path = root / entry.relative_path
            data = path.read_bytes()
            if len(data) != entry.byte_size or _sha256(data) != entry.sha256:
                raise ValueError(f"source_manifest_changed:{entry.relative_path}")


def _input_kind(path: Path) -> str | None:
    name = path.name.lower()
    if name == "sporttery_markets.json":
        return "board"
    if name == "reads.json":
        return "read"
    if name == "jczq-legs-base.json":
        return "identity"
    if name.startswith("research-") and name.endswith(".json"):
        return "research"
    if "result" in name and name.endswith(".json"):
        return "result"
    if "market" in name and name.endswith(".json"):
        return "market"
    return None


def _find_timestamps(document: object, keys: frozenset[str]) -> list[str]:
    found: list[str] = []
    if isinstance(document, dict):
        for key, value in document.items():
            if key in keys and isinstance(value, str) and value.strip():
                found.append(value)
            found.extend(_find_timestamps(value, keys))
    elif isinstance(document, list):
        for value in document:
            found.extend(_find_timestamps(value, keys))
    return found


def _semantic_timestamp(kind: str, document: object) -> str | None:
    keys = {
        "board": frozenset({"lastUpdateTime", "updated_at"}),
        "market": frozenset({"updated_at", "lastUpdateTime"}),
        "read": frozenset({"made_at"}),
        "research": frozenset({"captured_at"}),
        "result": frozenset({"published_at", "captured_at"}),
        "identity": frozenset(),
    }[kind]
    values = _find_timestamps(document, keys)
    if kind == "board" and not values and isinstance(document, dict):
        groups = document.get("matchInfoList")
        if isinstance(groups, list):
            for group in groups:
                if not isinstance(group, dict):
                    continue
                rows = group.get("subMatchList")
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    if isinstance(row, dict) and row.get("matchDate") and row.get("matchTime"):
                        values.append(f"{row['matchDate']}T{row['matchTime']}")
    return min(values) if values else None


def freeze_replay_inputs(source_root: Path, destination_root: Path) -> ReplayInputManifest:
    source_root = Path(source_root).resolve()
    destination_root = Path(destination_root).resolve()
    destination_root.mkdir(parents=True, exist_ok=False)
    entries: list[ReplayInputEntry] = []
    quarantined: list[QuarantinedReplayInput] = []
    for source in sorted(path for path in source_root.rglob("*") if path.is_file()):
        kind = _input_kind(source)
        if kind is None:
            continue
        relative = source.relative_to(source_root)
        data = source.read_bytes()
        try:
            document = json.loads(data)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid replay input: {relative}") from error
        timestamp = _semantic_timestamp(kind, document)
        rejected_research = kind == "research" and ".rejected." in source.name
        if timestamp is None and not rejected_research and kind != "identity":
            raise ValueError(f"semantic timestamp missing:{relative}")
        temporal_status = "known" if timestamp is not None else "unknown"
        target = destination_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        entries.append(
            ReplayInputEntry(
                relative_path=relative.as_posix(),
                kind=kind,
                byte_size=len(data),
                sha256=_sha256(data),
                semantic_timestamp=timestamp,
                temporal_status=temporal_status,
            )
        )
        if rejected_research and timestamp is None:
            quarantined.append(
                QuarantinedReplayInput(
                    relative_path=relative.as_posix(),
                    temporal_status="unknown",
                    reason="rejected_research_capture_time_missing",
                )
            )
    return ReplayInputManifest(
        root=str(destination_root),
        entries=tuple(entries),
        quarantined=tuple(quarantined),
    )


__all__ = [
    "QuarantinedReplayInput",
    "ReplayInputEntry",
    "ReplayInputManifest",
    "freeze_replay_inputs",
]
