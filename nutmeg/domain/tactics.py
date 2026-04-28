from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from nutmeg.domain.fixtures import Fixture


@dataclass(slots=True, frozen=True)
class TacticalVisualArtifact:
    name: str
    title: str
    status: str
    format: str
    svg: str
    source: str
    description: str
    path: str | None = None


@dataclass(slots=True, frozen=True)
class TacticalVisualPack:
    fixture: Fixture
    generated_at: datetime
    artifacts: list[TacticalVisualArtifact]
    insights: list[str]
    unavailable_sections: list[str] = field(default_factory=list)

