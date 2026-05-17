"""JCZQ ↔ 价值引擎桥接。

Phase 3b piece 2。把当天的 JCZQ 比赛对齐到 API-Football fixture（``MatchAligner``），
对每个对齐成功的 fixture 跑 ``ValueBoardService``（模型概率 vs 市场公允概率 → edge →
EV → quarter-Kelly），再把得到的 ``ValueCandidate`` 按 JCZQ ``match_no`` 归组成
"每场冲突点"。

输出 ``JczqValueReport`` 喂给 brief 的「赔率冲突点」节与串关构造器。未对齐 / 无
API-Football 数据的比赛带 ``coverage_note`` 如实标注，绝不补空信号。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nutmeg.domain.fixtures import Fixture
from nutmeg.domain.jczq_daily import JczqDailyMatch
from nutmeg.domain.value import ValueCandidate
from nutmeg.services.jczq_match_align import MatchAligner
from nutmeg.services.value import ValueBoardService


@dataclass(slots=True, frozen=True)
class JczqMatchConflicts:
    """一个 JCZQ 比赛的价值引擎冲突点。

    ``aligned`` 为 ``False`` 或 ``conflicts`` 为空时 ``coverage_note`` 说明原因
    （未对齐 / API-Football 无该 fixture 的可用赔率 / 无 +edge 冲突）。
    """

    match_no: str
    league: str
    home_team: str
    away_team: str
    aligned: bool
    fixture_id: str | None = None
    orientation_swapped: bool = False
    conflicts: list[ValueCandidate] = field(default_factory=list)
    coverage_note: str | None = None


@dataclass(slots=True, frozen=True)
class JczqValueReport:
    matches: list[JczqMatchConflicts]

    @property
    def aligned_count(self) -> int:
        return sum(1 for m in self.matches if m.aligned)

    @property
    def coverage_pct(self) -> float:
        if not self.matches:
            return 0.0
        return round(self.aligned_count / len(self.matches), 4)

    def conflicts_for(self, match_no: str) -> list[ValueCandidate]:
        for entry in self.matches:
            if entry.match_no == match_no:
                return entry.conflicts
        return []


class _FixedFixtureRepository:
    """A FixtureRepository shim returning exactly the supplied fixtures.

    ``ValueBoardService.build_board`` is the public, well-tested entry point but
    it is keyed by league+days. The bridge wants to evaluate a specific set of
    aligned fixtures, so it feeds them through this shim and lets build_board do
    the snapshot/odds/pricing exactly as it does in production.
    """

    def __init__(self, fixtures: list[Fixture]) -> None:
        self._fixtures = fixtures

    def list_upcoming(self, league: str, days: int) -> list[Fixture]:
        del league, days
        return list(self._fixtures)

    def get_fixture(self, fixture_id: str) -> Fixture | None:
        for fixture in self._fixtures:
            if fixture.fixture_id == fixture_id:
                return fixture
        return None

    def get_latest_finished_for_team_before(self, **_kwargs) -> Fixture | None:
        return None

    def upsert_many(self, fixtures: list[Fixture]) -> int:
        del fixtures
        return 0


class JczqValueBridge:
    def __init__(
        self,
        *,
        aligner: MatchAligner,
        value_service: ValueBoardService,
        min_edge: float = 0.03,
    ) -> None:
        self._aligner = aligner
        self._value_service = value_service
        self._min_edge = min_edge

    def evaluate_day(self, matches: list[JczqDailyMatch]) -> JczqValueReport:
        """对齐当天 JCZQ 比赛并产出每场的价值引擎冲突点。"""
        alignments = self._aligner.align_day(matches)

        aligned_fixtures: list[Fixture] = [
            a.fixture
            for a in alignments
            if a.matched and a.fixture is not None
        ]
        # 一次 build_board 评估全部对齐 fixture；按 fixture_id 归组冲突候选。
        conflicts_by_fixture = self._value_conflicts(aligned_fixtures)

        entries: list[JczqMatchConflicts] = []
        for match, alignment in zip(matches, alignments, strict=True):
            if not alignment.matched or alignment.fixture_id is None:
                entries.append(
                    JczqMatchConflicts(
                        match_no=match.match_no,
                        league=match.league,
                        home_team=match.home_team,
                        away_team=match.away_team,
                        aligned=False,
                        coverage_note=(
                            f"无 API-Football 数据：{alignment.reason}"
                        ),
                    )
                )
                continue

            conflicts = conflicts_by_fixture.get(alignment.fixture_id, [])
            coverage_note = None
            if not conflicts:
                coverage_note = (
                    "已对齐 API-Football，但无 +edge 冲突点"
                    "（赔率市场缺失或模型无优势）"
                )
            entries.append(
                JczqMatchConflicts(
                    match_no=match.match_no,
                    league=match.league,
                    home_team=match.home_team,
                    away_team=match.away_team,
                    aligned=True,
                    fixture_id=alignment.fixture_id,
                    orientation_swapped=alignment.orientation_swapped,
                    conflicts=conflicts,
                    coverage_note=coverage_note,
                )
            )
        return JczqValueReport(matches=entries)

    def _value_conflicts(
        self, fixtures: list[Fixture]
    ) -> dict[str, list[ValueCandidate]]:
        if not fixtures:
            return {}
        # Swap in a fixed-list repository so build_board evaluates exactly the
        # aligned fixtures; limit is generous so no candidate is dropped.
        original_repo = self._value_service._fixture_repository
        self._value_service._fixture_repository = _FixedFixtureRepository(fixtures)
        try:
            board = self._value_service.build_board(
                league="jczq-bridge",
                days=3,
                limit=len(fixtures) * 64,
                min_edge=self._min_edge,
            )
        finally:
            self._value_service._fixture_repository = original_repo

        grouped: dict[str, list[ValueCandidate]] = {}
        for candidate in board.candidates:
            grouped.setdefault(candidate.fixture_id, []).append(candidate)
        # build_board already ranks by edge desc; preserve that per fixture.
        for candidates in grouped.values():
            candidates.sort(key=lambda c: (-c.edge, -c.quarter_kelly_fraction))
        return grouped
