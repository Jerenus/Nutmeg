from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class ZucaiMatch:
    match_no: int
    competition: str
    home_team: str
    away_team: str
    match_date: str | None = None
    notes: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class ZucaiIssue:
    issue_id: str
    game_type: str
    matches: list[ZucaiMatch]
    sale_start: str | None = None
    sale_stop: str | None = None
    draw_date: str | None = None
    sources: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "game_type": self.game_type,
            "sale_start": self.sale_start,
            "sale_stop": self.sale_stop,
            "draw_date": self.draw_date,
            "sources": self.sources,
            "matches": [match.to_dict() for match in self.matches],
        }


@dataclass(slots=True, frozen=True)
class ZucaiOdds:
    match_no: int
    home: float | None = None
    draw: float | None = None
    away: float | None = None
    providers: list[dict[str, Any]] = field(default_factory=list)

    def to_code_dict(self) -> dict[str, float] | None:
        if self.home is None or self.draw is None or self.away is None:
            return None
        return {"3": self.home, "1": self.draw, "0": self.away}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class ZucaiRecommendation:
    match_no: int
    pick: str
    primary: str
    confidence: float
    risk_tier: str
    rationale: str
    odds_average: dict[str, float] | None = None
    override_applied: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class ZucaiPlan:
    name: str
    plan_type: str
    code: str
    stake_count: int
    cost_yuan: int
    selected_matches: list[int]
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class ZucaiArtifacts:
    markdown_path: str | None = None
    pdf_path: str | None = None
    report_json_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class ZucaiDispatch:
    status: str
    caption: str | None = None
    document_path: str | None = None
    chat_ids: list[int] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class ZucaiReport:
    issue: ZucaiIssue
    generated_at: str
    recommendations: list[ZucaiRecommendation]
    plans: list[ZucaiPlan]
    artifacts: ZucaiArtifacts
    dispatch: ZucaiDispatch
    warnings: list[str] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue": self.issue.to_dict(),
            "generated_at": self.generated_at,
            "recommendations": [item.to_dict() for item in self.recommendations],
            "plans": [plan.to_dict() for plan in self.plans],
            "artifacts": self.artifacts.to_dict(),
            "dispatch": self.dispatch.to_dict(),
            "warnings": self.warnings,
            "sources": self.sources,
        }


@dataclass(slots=True, frozen=True)
class ZucaiMatchGrade:
    match_no: int
    pick: str
    result: str | None
    hit: bool
    unresolved: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class ZucaiPlanGrade:
    name: str
    plan_type: str
    selected_count: int
    hit_count: int
    covered: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class ZucaiGradeReport:
    issue_id: str
    match_results: list[ZucaiMatchGrade]
    plan_results: list[ZucaiPlanGrade]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "match_results": [item.to_dict() for item in self.match_results],
            "plan_results": [item.to_dict() for item in self.plan_results],
            "warnings": self.warnings,
        }
