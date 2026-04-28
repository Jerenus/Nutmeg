from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass(slots=True, frozen=True)
class FootballEvent:
    event_id: str
    fixture_id: str
    provider: str
    team: str | None
    player: str | None
    event_type: str
    period: int
    minute: int
    second: int
    x: float | None = None
    y: float | None = None
    end_x: float | None = None
    end_y: float | None = None
    outcome: str = 'unknown'
    xg: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            'event_id': self.event_id,
            'fixture_id': self.fixture_id,
            'provider': self.provider,
            'team': self.team,
            'player': self.player,
            'event_type': self.event_type,
            'period': self.period,
            'minute': self.minute,
            'second': self.second,
            'x': self.x,
            'y': self.y,
            'end_x': self.end_x,
            'end_y': self.end_y,
            'outcome': self.outcome,
            'xg': self.xg,
            'metadata': dict(self.metadata),
        }


@dataclass(slots=True, frozen=True)
class EventDataQuality:
    fixture_id: str
    provider: str
    status: str
    event_count: int
    teams: list[str] = field(default_factory=list)
    players: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC).replace(microsecond=0))

    def to_dict(self) -> dict[str, Any]:
        return {
            'fixture_id': self.fixture_id,
            'provider': self.provider,
            'status': self.status,
            'event_count': self.event_count,
            'teams': list(self.teams),
            'players': list(self.players),
            'warnings': list(self.warnings),
            'generated_at': _serialize_datetime(self.generated_at),
        }


@dataclass(slots=True, frozen=True)
class PassNetwork:
    model_label: str = 'pass-network-from-events-v0'
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            'model_label': self.model_label,
            'nodes': list(self.nodes),
            'edges': list(self.edges),
            'warnings': list(self.warnings),
        }


@dataclass(slots=True, frozen=True)
class SpatialValueSummary:
    model_label: str = 'xT-lite-v0'
    pitch: dict[str, int] = field(default_factory=lambda: {'length': 120, 'width': 80})
    grid: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    players: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            'model_label': self.model_label,
            'pitch': dict(self.pitch),
            'grid': list(self.grid),
            'actions': list(self.actions),
            'players': list(self.players),
            'warnings': list(self.warnings),
        }


@dataclass(slots=True, frozen=True)
class PlayerContributionSummary:
    model_label: str = 'VAEP-lite-heuristic-v0'
    players: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            'model_label': self.model_label,
            'players': list(self.players),
            'warnings': list(self.warnings),
        }


@dataclass(slots=True, frozen=True)
class EventVisualArtifact:
    artifact_id: str
    title: str
    kind: str
    description: str
    svg: str
    file_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            'artifact_id': self.artifact_id,
            'title': self.title,
            'kind': self.kind,
            'description': self.description,
            'svg': self.svg,
            'file_path': self.file_path,
        }


@dataclass(slots=True, frozen=True)
class EventTacticalReport:
    fixture_id: str
    quality: EventDataQuality
    pass_network: PassNetwork = field(default_factory=PassNetwork)
    spatial_value: SpatialValueSummary = field(default_factory=SpatialValueSummary)
    player_contributions: PlayerContributionSummary = field(
        default_factory=PlayerContributionSummary
    )
    artifacts: list[EventVisualArtifact] = field(default_factory=list)
    unavailable_sections: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC).replace(microsecond=0))

    @classmethod
    def empty(
        cls,
        *,
        fixture_id: str,
        quality: EventDataQuality,
    ) -> 'EventTacticalReport':
        return cls(
            fixture_id=fixture_id,
            quality=quality,
            unavailable_sections=['pass_network', 'spatial_value', 'player_contributions'],
            warnings=list(quality.warnings),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'fixture_id': self.fixture_id,
            'quality': self.quality.to_dict(),
            'pass_network': self.pass_network.to_dict(),
            'spatial_value': self.spatial_value.to_dict(),
            'player_contributions': self.player_contributions.to_dict(),
            'artifacts': [artifact.to_dict() for artifact in self.artifacts],
            'unavailable_sections': list(self.unavailable_sections),
            'warnings': list(self.warnings),
            'generated_at': _serialize_datetime(self.generated_at),
        }
