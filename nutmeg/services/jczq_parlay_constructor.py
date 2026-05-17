"""串关构造器：把价值引擎冲突腿组装成 2/3/4串1 候选。

Phase 3b piece 4。``JczqValueBridge`` 产出每场 JCZQ 比赛的冲突点（``ValueCandidate``）；
本模块把这些冲突腿按信心层级（edge 量级）组合成候选串关，喂给 debate 工作流。

守两条体彩/集中度规则：
- **Rule O**（``jczq_diagnostics.check_same_match_pool_legality``）：单票内同一比赛
  不同玩法禁混合过关 —— 构造器保证每张串关每场只取一腿。
- **集中度上限**：单场跨串关出现次数受 ``max_match_appearances`` 限制，避免
  单点失败连锁拖垮多张票。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

from nutmeg.domain.jczq_daily import JczqDailyLeg, JczqDailyPlan
from nutmeg.domain.value import ValueCandidate
from nutmeg.services.jczq_value_bridge import JczqValueReport

# 价值引擎 market_key → JCZQ 彩池 + 玩法名。
_MARKET_TO_POOL: dict[str, tuple[str, str]] = {
    "match_winner": ("had", "胜平负"),
    "total_goals": ("ttg", "总进球"),
    "correct_score": ("crs", "比分"),
}

# match_winner / handicap 的 outcome_key → 中文 pick。
_MW_PICK: dict[str, str] = {"home": "胜", "draw": "平", "away": "负"}

# 信心层级阈值（edge 量级）。
_TIER_HIGH = 0.15
_TIER_MEDIUM = 0.08


def confidence_tier(edge: float) -> str:
    """按 edge 量级分档：high ≥ 0.15 / medium ≥ 0.08 / low 其余。"""
    if edge >= _TIER_HIGH:
        return "high"
    if edge >= _TIER_MEDIUM:
        return "medium"
    return "low"


@dataclass(slots=True, frozen=True)
class ParlayLeg:
    match_no: str
    pool: str
    play: str
    pick: str
    odds: float
    edge: float
    tier: str
    home_team: str
    away_team: str

    def to_daily_leg(self) -> JczqDailyLeg:
        """转成 ``JczqDailyLeg`` 以复用现有 diagnostics（Rule O 等）。"""
        return JczqDailyLeg(
            match_no=self.match_no,
            league="",
            home_team=self.home_team,
            away_team=self.away_team,
            pool=self.pool,
            play=self.play,
            pick=self.pick,
            odds=self.odds,
            logic=f"value-engine edge {self.edge:+.0%}",
        )


@dataclass(slots=True, frozen=True)
class ParlayCandidate:
    fold: int  # 2 / 3 / 4
    tier: str  # 该串关的最低信心档（木桶效应）
    legs: list[ParlayLeg]
    combined_odds: float
    average_edge: float

    @property
    def kind(self) -> str:
        return f"{self.fold}串1"

    def as_plan(self) -> JczqDailyPlan:
        """转成 ``JczqDailyPlan``，供 ``check_same_match_pool_legality`` 校验。"""
        return JczqDailyPlan(
            name=f"value-{self.tier}-{self.kind}",
            kind=f"value_parlay_{self.fold}",
            description=f"价值引擎 {self.tier} 档 {self.kind}",
            legs=[leg.to_daily_leg() for leg in self.legs],
            total_odds=round(self.combined_odds, 2),
            two_yuan_return=round(self.combined_odds * 2, 2),
            risk_note=f"avg edge {self.average_edge:+.1%}",
        )


def value_candidate_to_parlay_leg(
    match_no: str, candidate: ValueCandidate
) -> ParlayLeg:
    """把一个价值引擎 ``ValueCandidate`` 转成 JCZQ 串关腿。"""
    market_key = candidate.market_key
    if market_key.startswith("handicap_home_"):
        pool, play = "hhad", "让球胜平负"
        pick = _MW_PICK.get(candidate.outcome_key, candidate.outcome_name)
    elif market_key in _MARKET_TO_POOL:
        pool, play = _MARKET_TO_POOL[market_key]
        if market_key == "match_winner":
            pick = _MW_PICK.get(candidate.outcome_key, candidate.outcome_name)
        else:
            # ttg / crs：用人类可读的 outcome_name（"2" / "2:1"）。
            pick = candidate.outcome_name
    else:
        # 未知玩法：保守降级为原始 key，绝不静默丢弃。
        pool, play, pick = market_key, market_key, candidate.outcome_name
    return ParlayLeg(
        match_no=match_no,
        pool=pool,
        play=play,
        pick=pick,
        odds=candidate.best_odds,
        edge=candidate.edge,
        tier=confidence_tier(candidate.edge),
        home_team=candidate.home_team,
        away_team=candidate.away_team,
    )


class ParlayConstructor:
    def __init__(
        self,
        *,
        max_match_appearances: int = 3,
        max_per_fold: int = 6,
    ) -> None:
        self._max_match_appearances = max_match_appearances
        self._max_per_fold = max_per_fold

    def build(self, report: JczqValueReport) -> list[ParlayCandidate]:
        """从冲突点报告构造 2/3/4串1 候选。

        每场只取其 edge 最高的一腿（Rule O：单票同场一腿；且同场多腿组进同一
        串关本就非法）。腿按信心档（high/medium/low）分组，**每档内部**枚举
        2/3/4 串，再加一组跨全部腿的混合串关。所有组合守 Rule O + 集中度上限。
        """
        legs = self._best_leg_per_match(report)
        if len(legs) < 2:
            return []

        candidates: list[ParlayCandidate] = []
        appearances: dict[str, int] = {}
        seen: set[tuple[str, ...]] = set()

        # 先在每个信心档内部组串（high 优先消耗集中度配额），保证当 ≥2 条高信心
        # 腿存在时一定能产出纯 high 档串关供 debate 重点考虑。
        by_tier: dict[str, list[ParlayLeg]] = {"high": [], "medium": [], "low": []}
        for leg in legs:
            by_tier[leg.tier].append(leg)

        for tier in ("high", "medium", "low"):
            tier_legs = by_tier[tier]
            for fold in (4, 3, 2):
                if len(tier_legs) < fold:
                    continue
                candidates.extend(
                    self._build_fold(tier_legs, fold, appearances, seen)
                )

        # 再用全部腿组一组混合档串关——跨档串关让 debate 能权衡用一条强腿
        # 拉一条弱腿的取舍。集中度上限 + 去重在此继续生效。
        for fold in (4, 3, 2):
            if len(legs) < fold:
                continue
            candidates.extend(self._build_fold(legs, fold, appearances, seen))

        candidates.sort(key=lambda c: (-c.average_edge, c.fold))
        return candidates

    def _best_leg_per_match(self, report: JczqValueReport) -> list[ParlayLeg]:
        legs: list[ParlayLeg] = []
        for entry in report.matches:
            if not entry.aligned or not entry.conflicts:
                continue
            best = max(entry.conflicts, key=lambda c: c.edge)
            legs.append(value_candidate_to_parlay_leg(entry.match_no, best))
        # edge 降序：高信心腿优先进串关、优先消耗集中度配额。
        legs.sort(key=lambda leg: -leg.edge)
        return legs

    def _build_fold(
        self,
        legs: list[ParlayLeg],
        fold: int,
        appearances: dict[str, int],
        seen: set[tuple[str, ...]],
    ) -> list[ParlayCandidate]:
        out: list[ParlayCandidate] = []
        for combo in combinations(legs, fold):
            match_nos = [leg.match_no for leg in combo]
            # Rule O：一张串关每场至多一腿。
            if len(match_nos) != len(set(match_nos)):
                continue
            # 去重：同一组腿可能在档内枚举与混合枚举里各出现一次；只保留首次，
            # 且不让重复的那一份白白消耗集中度配额。
            key = tuple(
                sorted(f"{leg.match_no}:{leg.pool}:{leg.pick}" for leg in combo)
            )
            if key in seen:
                continue
            # 集中度上限：任一场跨串关出现次数不得超限。
            if any(
                appearances.get(mn, 0) >= self._max_match_appearances
                for mn in match_nos
            ):
                continue
            candidate = self._make_candidate(fold, list(combo))
            out.append(candidate)
            seen.add(key)
            for mn in match_nos:
                appearances[mn] = appearances.get(mn, 0) + 1
            if len(out) >= self._max_per_fold:
                break
        return out

    def _make_candidate(
        self, fold: int, legs: list[ParlayLeg]
    ) -> ParlayCandidate:
        combined = 1.0
        for leg in legs:
            combined *= leg.odds
        avg_edge = sum(leg.edge for leg in legs) / len(legs)
        # 木桶效应：整串信心取最低腿的档。
        tier_rank = {"high": 2, "medium": 1, "low": 0}
        weakest = min(legs, key=lambda leg: tier_rank[leg.tier])
        return ParlayCandidate(
            fold=fold,
            tier=weakest.tier,
            legs=legs,
            combined_odds=round(combined, 6),
            average_edge=round(avg_edge, 6),
        )
