from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class ZucaiOddsSyncResult:
    generated_at: str
    issue_id: str
    slot: str
    captured_at: str
    source_label: str
    parsed_count: int
    odds_path: str
    registry_path: str
    warnings: list[str] = field(default_factory=list)
    source_url: str | None = None
    source_path: str | None = None
    archive_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
