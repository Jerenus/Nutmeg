"""Zucai（足彩）↔ 价值引擎桥接。

Phase 3c。把一期足彩（任九 / 胜负彩）的 14 场比赛对齐到 API-Football fixture
（**复用 JCZQ 的 ``MatchAligner`` + 别名表**），对每个对齐成功的 fixture 跑
``ValueBoardService.build_board_for_fixtures``（Dixon-Coles 模型概率 vs 市场公允
概率 → edge → EV → quarter-Kelly），再为每场抽出一个**逐场 1X2（had）冲突信号**。

足彩任九/胜负彩本就是逐场 1X2（每场押 3=主胜 / 1=平 / 0=客胜），所以这里只关心
``match_winner`` 市场——把模型最看好且有 +edge 的那个结果映射成体彩 1X2 代码，作为
一条"模型 vs 赔率"的对照注解喂进每日报告。

**精简原则**：本桥**只产出注解信号**，不改写 Zucai 既有的 ``_double_pick`` /
``_uncertainty_score`` 选号算法——冲突信号是 debate / 人工额外权衡的一列。

未对齐 / 无 API-Football 数据 / 该场无 +edge had 结果的比赛带 ``coverage_note``
如实标注，绝不补空信号；下游报告对这些场不渲染注解，照常出整张方案。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nutmeg.domain.fixtures import Fixture
from nutmeg.domain.value import ValueCandidate
from nutmeg.domain.zucai import ZucaiIssue, ZucaiMatch
from nutmeg.services.jczq_match_align import MatchAligner

# API-Football match_winner 结果键 → 体彩 1X2 代码。
_OUTCOME_TO_PICK = {"home": "3", "draw": "1", "away": "0"}
_PICK_LABEL = {"3": "主胜", "1": "平", "0": "客胜"}


@dataclass(slots=True, frozen=True)
class ZucaiHadSignal:
    """一场比赛的逐场 1X2 冲突信号（``match_winner`` 市场的最优 +edge 结果）。

    ``pick`` 为体彩 1X2 代码（3/1/0）；``verdict`` 是供报告渲染的短注解。
    """

    pick: str
    model_probability: float
    market_probability: float
    edge: float
    best_odds: float
    expected_value: float
    rating: str
    verdict: str

    def to_dict(self) -> dict[str, object]:
        return {
            "pick": self.pick,
            "model_probability": self.model_probability,
            "market_probability": self.market_probability,
            "edge": self.edge,
            "best_odds": self.best_odds,
            "expected_value": self.expected_value,
            "rating": self.rating,
            "verdict": self.verdict,
        }


@dataclass(slots=True, frozen=True)
class ZucaiMatchConflict:
    """一场足彩比赛的价值引擎对齐结果 + had 冲突信号。

    ``aligned`` 为 ``False`` 或 ``had_signal`` 为 ``None`` 时 ``coverage_note``
    说明原因（未对齐 / API-Football 无该 fixture 的可用赔率 / 无 +edge had 结果）。
    """

    match_no: int
    competition: str
    home_team: str
    away_team: str
    aligned: bool
    fixture_id: str | None = None
    orientation_swapped: bool = False
    had_signal: ZucaiHadSignal | None = None
    coverage_note: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "match_no": self.match_no,
            "competition": self.competition,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "aligned": self.aligned,
            "fixture_id": self.fixture_id,
            "orientation_swapped": self.orientation_swapped,
            "had_signal": self.had_signal.to_dict() if self.had_signal else None,
            "coverage_note": self.coverage_note,
        }


@dataclass(slots=True, frozen=True)
class ZucaiValueReport:
    matches: list[ZucaiMatchConflict] = field(default_factory=list)

    @property
    def aligned_count(self) -> int:
        return sum(1 for m in self.matches if m.aligned)

    @property
    def signal_count(self) -> int:
        return sum(1 for m in self.matches if m.had_signal is not None)

    @property
    def coverage_pct(self) -> float:
        if not self.matches:
            return 0.0
        return round(self.aligned_count / len(self.matches), 4)

    def signal_for(self, match_no: int) -> ZucaiHadSignal | None:
        for entry in self.matches:
            if entry.match_no == match_no:
                return entry.had_signal
        return None

    def to_dict(self) -> dict[str, object]:
        return {
            "aligned_count": self.aligned_count,
            "signal_count": self.signal_count,
            "coverage_pct": self.coverage_pct,
            "matches": [m.to_dict() for m in self.matches],
        }


@dataclass(slots=True, frozen=True)
class _AlignableMatch:
    """把 ``ZucaiMatch`` 适配成 ``MatchAligner`` 期望的鸭子类型。

    ``MatchAligner`` 读 ``.match_no`` / ``.league`` / ``.home_team`` /
    ``.away_team`` / ``.match_date``——足彩用 ``competition`` 存联赛、``match_no``
    是整数、``match_date`` 可缺省，这里统一桥接成对齐器要的字段名。
    """

    match_no: str
    league: str
    home_team: str
    away_team: str
    match_date: str


class ZucaiValueBridge:
    def __init__(
        self,
        *,
        aligner: MatchAligner,
        value_service,
        min_edge: float = 0.03,
    ) -> None:
        self._aligner = aligner
        self._value_service = value_service
        self._min_edge = min_edge

    def evaluate_issue(self, issue: ZucaiIssue) -> ZucaiValueReport:
        """对齐一期足彩的 14 场并产出每场的逐场 had 冲突信号。"""
        entries: list[ZucaiMatchConflict] = []
        alignable: list[tuple[ZucaiMatch, _AlignableMatch | None]] = []
        for match in issue.matches:
            alignable.append((match, _to_alignable(match)))

        # 只对齐有比赛日期的场次；缺日期的直接当未对齐处理（不发查询）。
        to_align = [adapter for _match, adapter in alignable if adapter is not None]
        alignments_by_no = {}
        if to_align:
            for adapter, alignment in zip(
                to_align, self._aligner.align_day(to_align), strict=True
            ):
                alignments_by_no[adapter.match_no] = alignment

        aligned_fixtures: list[Fixture] = [
            alignment.fixture
            for alignment in alignments_by_no.values()
            if alignment.matched and alignment.fixture is not None
        ]
        conflicts_by_fixture = self._had_conflicts(aligned_fixtures)

        for match, adapter in alignable:
            if adapter is None:
                entries.append(
                    ZucaiMatchConflict(
                        match_no=match.match_no,
                        competition=match.competition,
                        home_team=match.home_team,
                        away_team=match.away_team,
                        aligned=False,
                        coverage_note="缺少比赛日期，无法对齐 API-Football fixture",
                    )
                )
                continue

            alignment = alignments_by_no.get(adapter.match_no)
            if (
                alignment is None
                or not alignment.matched
                or alignment.fixture_id is None
            ):
                reason = alignment.reason if alignment else "对齐失败"
                entries.append(
                    ZucaiMatchConflict(
                        match_no=match.match_no,
                        competition=match.competition,
                        home_team=match.home_team,
                        away_team=match.away_team,
                        aligned=False,
                        coverage_note=f"无 API-Football 数据：{reason}",
                    )
                )
                continue

            had_signal = self._best_had_signal(
                conflicts_by_fixture.get(alignment.fixture_id, []),
                orientation_swapped=alignment.orientation_swapped,
            )
            coverage_note = None
            if had_signal is None:
                coverage_note = (
                    "已对齐 API-Football，但 match_winner 市场无 +edge 冲突结果"
                    "（赔率公允或模型无优势）"
                )
            entries.append(
                ZucaiMatchConflict(
                    match_no=match.match_no,
                    competition=match.competition,
                    home_team=match.home_team,
                    away_team=match.away_team,
                    aligned=True,
                    fixture_id=alignment.fixture_id,
                    orientation_swapped=alignment.orientation_swapped,
                    had_signal=had_signal,
                    coverage_note=coverage_note,
                )
            )
        return ZucaiValueReport(matches=entries)

    def _had_conflicts(
        self, fixtures: list[Fixture]
    ) -> dict[str, list[ValueCandidate]]:
        """对齐 fixture 跑价值引擎，只保留 match_winner 市场的候选。"""
        if not fixtures:
            return {}
        board = self._value_service.build_board_for_fixtures(
            fixtures,
            min_edge=self._min_edge,
            league="zucai-bridge",
        )
        grouped: dict[str, list[ValueCandidate]] = {}
        for candidate in board.candidates:
            if candidate.market_key != "match_winner":
                continue
            grouped.setdefault(candidate.fixture_id, []).append(candidate)
        # build_board 已按 edge 降序；逐 fixture 保留该序。
        for candidates in grouped.values():
            candidates.sort(key=lambda c: (-c.edge, -c.quarter_kelly_fraction))
        return grouped

    def _best_had_signal(
        self,
        candidates: list[ValueCandidate],
        *,
        orientation_swapped: bool,
    ) -> ZucaiHadSignal | None:
        """把 match_winner 候选里 edge 最高的转成体彩 1X2 信号。

        ``orientation_swapped`` 为 ``True`` 时体彩名义主队是 API-Football 客队，
        ``home``/``away`` 结果对调后再映射成 1X2 代码（``draw`` 不受影响）。
        """
        for candidate in candidates:
            outcome_key = candidate.outcome_key
            if orientation_swapped:
                outcome_key = {"home": "away", "away": "home"}.get(
                    outcome_key, outcome_key
                )
            pick = _OUTCOME_TO_PICK.get(outcome_key)
            if pick is None:
                continue
            label = _PICK_LABEL[pick]
            verdict = (
                f"模型：{label} +{candidate.edge:.0%} edge"
                f"（公允 {candidate.market_probability:.0%} → "
                f"模型 {candidate.model_probability:.0%}）"
            )
            return ZucaiHadSignal(
                pick=pick,
                model_probability=candidate.model_probability,
                market_probability=candidate.market_probability,
                edge=candidate.edge,
                best_odds=candidate.best_odds,
                expected_value=candidate.expected_value,
                rating=candidate.rating,
                verdict=verdict,
            )
        return None


def _to_alignable(match: ZucaiMatch) -> _AlignableMatch | None:
    """``ZucaiMatch`` → ``MatchAligner`` 鸭子类型；缺比赛日期则返回 ``None``。"""
    match_date = (match.match_date or "").strip()
    if not match_date:
        return None
    return _AlignableMatch(
        match_no=str(match.match_no),
        league=match.competition,
        home_team=match.home_team,
        away_team=match.away_team,
        match_date=match_date,
    )
