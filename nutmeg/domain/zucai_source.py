from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from nutmeg.domain.zucai import ZucaiIssue


@dataclass(slots=True, frozen=True)
class ParsedZucaiIssue:
    issue_id: str
    issue: ZucaiIssue
    source_label: str
    source_url: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "issue": self.issue.to_dict(),
            "source_label": self.source_label,
            "source_url": self.source_url,
            "warnings": self.warnings,
        }


@dataclass(slots=True, frozen=True)
class ZucaiSourceSyncResult:
    generated_at: str
    run_date: str
    source_label: str
    parsed_count: int
    written_issue_paths: dict[str, str]
    registry_path: str
    active_issue_ids: list[str]
    warnings: list[str] = field(default_factory=list)
    source_url: str | None = None
    source_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
