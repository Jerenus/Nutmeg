from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class InformationReliability(StrEnum):
    OFFICIAL = 'official'
    CREDIBLE = 'credible'
    RUMOR = 'rumor'
    UNVERIFIED = 'unverified'


def _serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass(slots=True, frozen=True)
class InformationItem:
    item_id: str
    source_name: str
    source_type: str
    title: str
    summary: str
    url: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(UTC).replace(microsecond=0))
    reliability: InformationReliability = InformationReliability.UNVERIFIED
    fixture_ids: list[str] = field(default_factory=list)
    teams: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            'item_id': self.item_id,
            'source_name': self.source_name,
            'source_type': self.source_type,
            'title': self.title,
            'summary': self.summary,
            'url': self.url,
            'published_at': _serialize_datetime(self.published_at),
            'retrieved_at': _serialize_datetime(self.retrieved_at),
            'reliability': self.reliability.value,
            'fixture_ids': list(self.fixture_ids),
            'teams': list(self.teams),
            'tags': list(self.tags),
            'metadata': dict(self.metadata),
        }


@dataclass(slots=True, frozen=True)
class InformationSourceHealth:
    source_name: str
    source_type: str
    status: str
    item_count: int
    warnings: list[str] = field(default_factory=list)
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(UTC).replace(microsecond=0))

    def to_dict(self) -> dict[str, Any]:
        return {
            'source_name': self.source_name,
            'source_type': self.source_type,
            'status': self.status,
            'item_count': self.item_count,
            'warnings': list(self.warnings),
            'retrieved_at': _serialize_datetime(self.retrieved_at),
        }


@dataclass(slots=True, frozen=True)
class InformationSourceDefinition:
    source_name: str
    kind: str
    enabled: bool = True
    path: Path | None = None
    url: str | None = None
    reliability: InformationReliability = InformationReliability.UNVERIFIED
    fixture_ids: list[str] = field(default_factory=list)
    teams: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    cache_ttl_seconds: int | None = None
    timeout_seconds: float | None = None
    max_bytes: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            'source_name': self.source_name,
            'kind': self.kind,
            'enabled': self.enabled,
            'path': str(self.path) if self.path is not None else None,
            'url': self.url,
            'reliability': self.reliability.value,
            'fixture_ids': list(self.fixture_ids),
            'teams': list(self.teams),
            'tags': list(self.tags),
            'cache_ttl_seconds': self.cache_ttl_seconds,
            'timeout_seconds': self.timeout_seconds,
            'max_bytes': self.max_bytes,
            'metadata': dict(self.metadata),
        }


@dataclass(slots=True, frozen=True)
class InformationCacheEntry:
    cache_key: str
    url: str
    content_type: str
    status_code: int | None
    fetched_at: datetime
    body: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            'cache_key': self.cache_key,
            'url': self.url,
            'content_type': self.content_type,
            'status_code': self.status_code,
            'fetched_at': _serialize_datetime(self.fetched_at),
            'body': self.body,
            'warnings': list(self.warnings),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> 'InformationCacheEntry':
        fetched_at_raw = payload.get('fetched_at')
        fetched_at = (
            datetime.fromisoformat(str(fetched_at_raw))
            if fetched_at_raw
            else datetime.now(UTC).replace(microsecond=0)
        )
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=UTC)
        status_code = payload.get('status_code')
        return cls(
            cache_key=str(payload.get('cache_key') or ''),
            url=str(payload.get('url') or ''),
            content_type=str(payload.get('content_type') or ''),
            status_code=status_code if isinstance(status_code, int) else None,
            fetched_at=fetched_at.astimezone(UTC).replace(microsecond=0),
            body=str(payload.get('body') or ''),
            warnings=[str(item) for item in payload.get('warnings') or []],
        )


@dataclass(slots=True, frozen=True)
class FixtureInformationDigest:
    fixture_id: str
    status: str
    summary: str
    items: list[InformationItem] = field(default_factory=list)
    source_count: int = 0
    latest_published_at: datetime | None = None
    warnings: list[str] = field(default_factory=list)
    source_health: list[InformationSourceHealth] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC).replace(microsecond=0))

    @classmethod
    def unavailable(
        cls,
        *,
        fixture_id: str,
        warnings: list[str],
        source_health: list[InformationSourceHealth] | None = None,
    ) -> 'FixtureInformationDigest':
        return cls(
            fixture_id=fixture_id,
            status='unavailable',
            summary='Information unavailable.',
            items=[],
            source_count=0,
            latest_published_at=None,
            warnings=warnings,
            source_health=source_health or [],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'fixture_id': self.fixture_id,
            'status': self.status,
            'summary': self.summary,
            'source_count': self.source_count,
            'latest_published_at': _serialize_datetime(self.latest_published_at),
            'items': [item.to_dict() for item in self.items],
            'warnings': list(self.warnings),
            'source_health': [health.to_dict() for health in self.source_health],
            'generated_at': _serialize_datetime(self.generated_at),
        }
