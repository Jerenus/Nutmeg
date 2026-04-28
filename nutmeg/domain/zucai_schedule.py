from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from nutmeg.domain.zucai import ZucaiArtifacts, ZucaiDispatch, ZucaiReport


@dataclass(slots=True, frozen=True)
class ZucaiScheduleSlot:
    name: str
    label: str
    scheduled_time: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class ZucaiIssueRegistryEntry:
    issue_id: str
    issue_file: str
    enabled: bool = True
    active_dates: list[str] = field(default_factory=list)
    odds_file: str | None = None
    overrides_file: str | None = None
    revision_odds_file: str | None = None
    revision_overrides_file: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class ZucaiScheduledRunRecord:
    run_date: str
    slot: str
    issue_id: str
    status: str
    generated_at: str
    report_json_path: str | None = None
    markdown_path: str | None = None
    pdf_path: str | None = None
    dispatch_status: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class ZucaiScheduledRunResult:
    run_date: str
    slot: str
    slot_label: str
    status: str
    generated_at: str
    issue_id: str | None = None
    skipped_reason: str | None = None
    artifacts: ZucaiArtifacts = field(default_factory=ZucaiArtifacts)
    dispatch: ZucaiDispatch = field(default_factory=lambda: ZucaiDispatch(status="skipped"))
    warnings: list[str] = field(default_factory=list)
    report: ZucaiReport | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_date": self.run_date,
            "slot": self.slot,
            "slot_label": self.slot_label,
            "issue_id": self.issue_id,
            "status": self.status,
            "generated_at": self.generated_at,
            "skipped_reason": self.skipped_reason,
            "artifacts": self.artifacts.to_dict(),
            "dispatch": self.dispatch.to_dict(),
            "warnings": self.warnings,
            "report": self.report.to_dict() if self.report is not None else None,
        }
