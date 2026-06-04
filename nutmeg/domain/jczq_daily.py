from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class JczqDailyLeg:
    match_no: str
    league: str
    home_team: str
    away_team: str
    pool: str
    play: str
    pick: str
    odds: float
    logic: str
    goal_line: str = ""
    odds_update: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_no": self.match_no,
            "league": self.league,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "pool": self.pool,
            "play": self.play,
            "pick": self.pick,
            "odds": self.odds,
            "logic": self.logic,
            "goal_line": self.goal_line,
            "odds_update": self.odds_update,
        }


@dataclass(slots=True, frozen=True)
class JczqDailyMatch:
    match_no: str
    match_date: str
    match_time: str
    league: str
    home_team: str
    away_team: str
    status: str
    hot_direction: str
    role: str
    confidence_note: str
    candidates: list[JczqDailyLeg] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_no": self.match_no,
            "match_date": self.match_date,
            "match_time": self.match_time,
            "league": self.league,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "status": self.status,
            "hot_direction": self.hot_direction,
            "role": self.role,
            "confidence_note": self.confidence_note,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


@dataclass(slots=True, frozen=True)
class JczqDailyPlan:
    name: str
    kind: str
    description: str
    legs: list[JczqDailyLeg]
    total_odds: float
    two_yuan_return: float
    risk_note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "description": self.description,
            "legs": [leg.to_dict() for leg in self.legs],
            "total_odds": self.total_odds,
            "two_yuan_return": self.two_yuan_return,
            "risk_note": self.risk_note,
        }


@dataclass(slots=True, frozen=True)
class JczqDailyAdvisorReport:
    run_date: str
    generated_at: str
    official_last_update: str | None
    source_page: str
    source_api: str
    matches: list[JczqDailyMatch]
    plans: list[JczqDailyPlan]
    summary: str
    revision: dict[str, Any] = field(default_factory=lambda: {"version": 1})
    artifacts: dict[str, str | None] = field(default_factory=dict)
    dispatch: dict[str, Any] = field(default_factory=lambda: {"status": "skipped"})
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_date": self.run_date,
            "generated_at": self.generated_at,
            "official_last_update": self.official_last_update,
            "source_page": self.source_page,
            "source_api": self.source_api,
            "matches": [match.to_dict() for match in self.matches],
            "plans": [plan.to_dict() for plan in self.plans],
            "summary": self.summary,
            "revision": self.revision,
            "artifacts": self.artifacts,
            "dispatch": self.dispatch,
            "warnings": self.warnings,
        }


# --- dict → domain 解析器（spec §33：从退役 services.jczq_daily 剥离） -----------
# 仅 ``jczq_conflict_bridge`` 仍需从 context.json 还原 matches；保留在 domain 层，
# 与类型同居，不依赖任何退役 generator 代码。


def leg_from_dict(payload: dict[str, Any]) -> JczqDailyLeg:
    return JczqDailyLeg(
        match_no=str(payload.get("match_no") or ""),
        league=str(payload.get("league") or ""),
        home_team=str(payload.get("home_team") or ""),
        away_team=str(payload.get("away_team") or ""),
        pool=str(payload.get("pool") or ""),
        play=str(payload.get("play") or ""),
        pick=str(payload.get("pick") or ""),
        odds=float(payload.get("odds") or 0),
        logic=str(payload.get("logic") or ""),
        goal_line=str(payload.get("goal_line") or ""),
        odds_update=str(payload.get("odds_update") or ""),
    )


def match_from_dict(payload: dict[str, Any]) -> JczqDailyMatch:
    return JczqDailyMatch(
        match_no=str(payload.get("match_no") or ""),
        match_date=str(payload.get("match_date") or ""),
        match_time=str(payload.get("match_time") or ""),
        league=str(payload.get("league") or ""),
        home_team=str(payload.get("home_team") or ""),
        away_team=str(payload.get("away_team") or ""),
        status=str(payload.get("status") or ""),
        hot_direction=str(payload.get("hot_direction") or ""),
        role=str(payload.get("role") or ""),
        confidence_note=str(payload.get("confidence_note") or ""),
        candidates=[leg_from_dict(item) for item in payload.get("candidates") or []],
    )


def matches_from_context(payload: dict[str, Any]) -> list[JczqDailyMatch]:
    """Reconstruct the day's matches from a stored ``context.json`` dict."""
    return [match_from_dict(item) for item in payload.get("matches") or []]
