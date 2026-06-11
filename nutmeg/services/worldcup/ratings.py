# nutmeg/services/worldcup/ratings.py
"""攻/防两维 Elo(spec §3.1)— 残差驱动更新,系数随校准日志可调(spec §3.5)。

种子:wc2026_elo_seed.json 的整体 Elo 按 atk=dfn=elo/2 拆分,首轮赛果后自然分化。
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

BASE_GOALS = 1.25       # 均势对阵单边期望进球
LAMBDA_SCALE = 350.0    # (atk-dfn) → λ 的指数尺度
HOST_BOOST = 1.10       # 东道主在本国境内 λ 乘子(spec §3.1)
K_GOAL = 15.0           # 每 1 球残差的评分增量
INJURY_MIN_OUT = 3      # spec §3.2:缺席 ≥3 人才折减
INJURY_FACTOR = 0.95


@dataclass(frozen=True, slots=True)
class TeamRating:
    atk: float
    dfn: float

    @property
    def overall(self) -> float:
        return self.atk + self.dfn


def expected_lambdas(
    home: TeamRating, away: TeamRating, *, host_advantage: bool
) -> tuple[float, float]:
    lam_h = BASE_GOALS * math.exp((home.atk - away.dfn) / LAMBDA_SCALE)
    lam_a = BASE_GOALS * math.exp((away.atk - home.dfn) / LAMBDA_SCALE)
    if host_advantage:
        lam_h *= HOST_BOOST
    return lam_h, lam_a


def update_after_match(
    home: TeamRating, away: TeamRating, *, goals_h: int, goals_a: int,
    host_advantage: bool,
) -> tuple[TeamRating, TeamRating]:
    """残差更新:进攻按(实际-期望进球),防守按(期望失球-实际失球)。"""
    lam_h, lam_a = expected_lambdas(home, away, host_advantage=host_advantage)
    res_h, res_a = goals_h - lam_h, goals_a - lam_a
    return (
        TeamRating(atk=home.atk + K_GOAL * res_h, dfn=home.dfn - K_GOAL * res_a),
        TeamRating(atk=away.atk + K_GOAL * res_a, dfn=away.dfn - K_GOAL * res_h),
    )


def injury_adjusted(rating: TeamRating, *, n_out: int) -> TeamRating:
    """伤病降级信号(spec §3.2)— 本场临时折减,不写回状态。"""
    if n_out < INJURY_MIN_OUT:
        return rating
    return TeamRating(atk=rating.atk * INJURY_FACTOR, dfn=rating.dfn * INJURY_FACTOR)


def load_seed() -> dict[str, TeamRating]:
    text = (
        resources.files("nutmeg.data")
        .joinpath("wc2026_elo_seed.json")
        .read_text(encoding="utf-8")
    )
    return {
        team: TeamRating(atk=elo / 2.0, dfn=elo / 2.0)
        for team, elo in json.loads(text)["elo"].items()
    }


def load_ratings(path: Path) -> dict[str, TeamRating] | None:
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {t: TeamRating(**v) for t, v in raw["ratings"].items()}


def save_ratings(path: Path, ratings: dict[str, TeamRating], *, run_date: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"updated": run_date,
             "ratings": {t: {"atk": r.atk, "dfn": r.dfn} for t, r in ratings.items()}},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
