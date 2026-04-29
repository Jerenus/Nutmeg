from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class JczqReportLeg:
    match_no: str
    match_date: str
    match_time: str
    league: str
    home_team: str
    away_team: str
    pool: str
    play: str
    pick: str
    odds: float
    logic: str
    goal_line: str = ""
    single: int | None = None
    all_up: int | None = None
    odds_update: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_no": self.match_no,
            "match_date": self.match_date,
            "match_time": self.match_time,
            "league": self.league,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "pool": self.pool,
            "play": self.play,
            "pick": self.pick,
            "odds": self.odds,
            "logic": self.logic,
            "goal_line": self.goal_line,
            "single": self.single,
            "all_up": self.all_up,
            "odds_update": self.odds_update,
        }


@dataclass(slots=True, frozen=True)
class JczqReportCombination:
    name: str
    risk: str
    legs: list[JczqReportLeg]
    total_odds: float
    two_yuan_return: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "risk": self.risk,
            "legs": [leg.to_dict() for leg in self.legs],
            "total_odds": self.total_odds,
            "two_yuan_return": self.two_yuan_return,
        }


@dataclass(slots=True, frozen=True)
class JczqReportArtifacts:
    markdown_path: str | None = None
    pdf_path: str | None = None
    report_json_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "markdown_path": self.markdown_path,
            "pdf_path": self.pdf_path,
            "report_json_path": self.report_json_path,
        }


@dataclass(slots=True, frozen=True)
class JczqReportDispatch:
    status: str = "skipped"
    caption: str | None = None
    chat_ids: list[int] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "caption": self.caption,
            "chat_ids": self.chat_ids,
            "error": self.error,
        }


@dataclass(slots=True, frozen=True)
class JczqMixedReport:
    generated_at: str
    official_last_update: str | None
    source_page: str
    source_api: str
    combinations: list[JczqReportCombination]
    artifacts: JczqReportArtifacts = field(default_factory=JczqReportArtifacts)
    dispatch: JczqReportDispatch = field(default_factory=JczqReportDispatch)
    warnings: list[str] = field(default_factory=list)
    psychology_reports: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "official_last_update": self.official_last_update,
            "source_page": self.source_page,
            "source_api": self.source_api,
            "combinations": [combo.to_dict() for combo in self.combinations],
            "artifacts": self.artifacts.to_dict(),
            "dispatch": self.dispatch.to_dict(),
            "warnings": self.warnings,
            "psychology_reports": {name: asdict(report) for name, report in self.psychology_reports.items()},
        }
