from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class RenjiuMatchAnalysis:
    match_no: int
    competition: str
    home_team: str
    away_team: str
    odds: dict[str, float]
    primary_pick: str
    suggested_pick: str
    uncertainty_score: float
    risk_labels: list[str] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class RenjiuTicket:
    ticket_id: str
    name: str
    picks: list[str]
    omitted_matches: list[int]
    stake_count: int
    cost_yuan: int
    note: str

    @property
    def code(self) -> str:
        return " ".join(self.picks)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["code"] = self.code
        return payload


@dataclass(slots=True, frozen=True)
class RenjiuArtifacts:
    markdown_path: str | None = None
    json_path: str | None = None
    pdf_path: str | None = None
    context_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class RenjiuDispatch:
    status: str
    caption: str | None = None
    document_path: str | None = None
    chat_ids: list[int] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class RenjiuDailyReport:
    run_date: str
    issue_id: str
    generated_at: str
    sale_stop: str | None
    odds_captured_at: str | None
    match_analysis: list[RenjiuMatchAnalysis]
    least_confident_matches: list[int]
    tickets: list[RenjiuTicket]
    recommended_ticket_id: str
    artifacts: RenjiuArtifacts
    dispatch: RenjiuDispatch
    sources: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_date": self.run_date,
            "issue_id": self.issue_id,
            "generated_at": self.generated_at,
            "sale_stop": self.sale_stop,
            "odds_captured_at": self.odds_captured_at,
            "match_analysis": [item.to_dict() for item in self.match_analysis],
            "least_confident_matches": self.least_confident_matches,
            "tickets": [ticket.to_dict() for ticket in self.tickets],
            "recommended_ticket_id": self.recommended_ticket_id,
            "artifacts": self.artifacts.to_dict(),
            "dispatch": self.dispatch.to_dict(),
            "sources": self.sources,
            "warnings": self.warnings,
        }
