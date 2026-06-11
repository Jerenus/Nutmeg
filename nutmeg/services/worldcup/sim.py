"""确定性整届蒙特卡洛(spec §3.4)。

确定性:seed = sha256(run_date) 前 8 hex;同日同输入 → 同输出(决策包 §32 原则)。
市场锚定:anchors[(home,away)] 的 de-vig 胜平负概率优先于 Elo(spec §3.3),
比分在锚定结果类别内用 Poisson 拒绝采样。
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .ratings import TeamRating, expected_lambdas
from .results import WcResult
from .tournament import Tournament, allocate_best_thirds, rank_group, rank_thirds

STAGE_KEYS = ("qualify", "r32", "r16", "qf", "sf", "final", "champion")
_STAGE_TO_KEY = {"r32": "r32", "r16": "r16", "qf": "qf", "sf": "sf", "final": "final"}
MAX_REJECTION_TRIES = 30
PEN_ELO_CAP = 0.10  # 点球上限 60/40(spec §3.4)


@dataclass(slots=True)
class SimOutput:
    run_date: str
    seed: int
    n_sims: int
    probs: dict[str, dict[str, float]]
    anchored: list[str] = field(default_factory=list)


def seed_for(run_date: str) -> int:
    return int(hashlib.sha256(run_date.encode("utf-8")).hexdigest()[:8], 16)


def _poisson(rng: random.Random, lam: float) -> int:
    """Knuth 采样 — λ 在 0.2~4 区间,足够快。"""
    threshold = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        p *= rng.random()
        if p <= threshold:
            return k
        k += 1


def _outcome(gh: int, ga: int) -> str:
    return "home" if gh > ga else "away" if gh < ga else "draw"


def sample_match(
    rng: random.Random, lam_h: float, lam_a: float,
    anchor: dict[str, float] | None = None,
) -> tuple[int, int]:
    if anchor is None:
        return _poisson(rng, lam_h), _poisson(rng, lam_a)
    r, acc = rng.random(), 0.0
    target = "away"
    for key in ("home", "draw", "away"):
        acc += anchor.get(key, 0.0)
        if r < acc:
            target = key
            break
    for _ in range(MAX_REJECTION_TRIES):
        gh, ga = _poisson(rng, lam_h), _poisson(rng, lam_a)
        if _outcome(gh, ga) == target:
            return gh, ga
    return {"home": (1, 0), "draw": (1, 1), "away": (0, 1)}[target]


def _knockout_winner(
    rng: random.Random, home: str, away: str,
    ratings: dict[str, TeamRating], host: bool,
) -> tuple[str, str]:
    """返回 (胜者, 90分钟 outcome)。平局 → 加时(λ/3)→ 点球。"""
    lam_h, lam_a = expected_lambdas(ratings[home], ratings[away], host_advantage=host)
    gh, ga = _poisson(rng, lam_h), _poisson(rng, lam_a)
    out90 = _outcome(gh, ga)
    if out90 != "draw":
        return (home if out90 == "home" else away), out90
    eh, ea = _poisson(rng, lam_h / 3.0), _poisson(rng, lam_a / 3.0)
    if eh != ea:
        return (home if eh > ea else away), out90
    diff = ratings[home].overall - ratings[away].overall
    p_home = 0.5 + max(-PEN_ELO_CAP, min(PEN_ELO_CAP, diff / 4000.0))
    return (home if rng.random() < p_home else away), out90


def simulate_tournament(
    tournament: Tournament,
    results: list[WcResult],
    ratings: dict[str, TeamRating],
    anchors: dict[frozenset[str], dict[str, float]],
    *,
    run_date: str,
    n_sims: int = 20000,
) -> SimOutput:
    seed = seed_for(run_date)
    rng = random.Random(seed)
    teams = list(tournament.teams)
    counters = {t: dict.fromkeys(STAGE_KEYS, 0) for t in teams}
    by_id = {r.match_id: r for r in results}
    group_matches = [m for m in tournament.matches if m.stage == "group"]
    ko_matches = sorted(
        (m for m in tournament.matches if m.stage not in ("group", "third")),
        key=lambda m: (m.date_utc, m.match_id),
    )
    lam_cache: dict[tuple[str, str, bool], tuple[float, float]] = {}

    def lams(h: str, a: str, host: bool) -> tuple[float, float]:
        key = (h, a, host)
        if key not in lam_cache:
            lam_cache[key] = expected_lambdas(ratings[h], ratings[a], host_advantage=host)
        return lam_cache[key]

    def is_host_match(m, home_team: str) -> bool:
        t = tournament.teams.get(home_team)
        return bool(t and t.host and m.venue_country == home_team)

    for _ in range(n_sims):
        goals: dict[tuple[str, str], tuple[int, int]] = {}
        for m in group_matches:
            r = by_id.get(m.match_id)
            if r is not None and r.goals_h_90 is not None:
                goals[(m.home, m.away)] = (r.goals_h_90, r.goals_a_90)
                continue
            anchor = anchors.get(frozenset((m.home, m.away)))
            lh, la = lams(m.home, m.away, is_host_match(m, m.home))
            goals[(m.home, m.away)] = sample_match(rng, lh, la, anchor=anchor)

        slots: dict[str, str] = {}
        thirds: list[tuple[str, str, int, int, int]] = []
        for g, members in tournament.groups.items():
            order = rank_group(members, goals, rng)
            slots[f"1{g}"] = order[0]
            slots[f"2{g}"] = order[1]
            rows = _group_row(order[2], members, goals)
            thirds.append((g, order[2], *rows))
            for team in order[:2]:
                counters[team]["qualify"] += 1
        ranked = rank_thirds(thirds, rng)
        third_slots = {
            m.away_slot: m.away_slot.removeprefix("3:")
            for m in ko_matches if m.away_slot.startswith("3:")
        } | {
            m.home_slot: m.home_slot.removeprefix("3:")
            for m in ko_matches if m.home_slot.startswith("3:")
        }
        alloc = allocate_best_thirds(ranked, third_slots)
        for slot_id, team in alloc.items():
            slots[slot_id] = team
            counters[team]["qualify"] += 1

        winners: dict[str, str] = {}
        for m in ko_matches:
            home = _resolve(m.home_slot, slots, winners)
            away = _resolve(m.away_slot, slots, winners)
            key = _STAGE_TO_KEY[m.stage]
            counters[home][key] += 1
            counters[away][key] += 1
            r = by_id.get(m.match_id)
            if r is not None and r.advanced:
                winners[m.match_id] = r.advanced
                continue
            win, _ = _knockout_winner(
                rng, home, away, ratings, is_host_match(m, home)
            )
            winners[m.match_id] = win
        final = ko_matches[-1]
        counters[winners[final.match_id]]["champion"] += 1

    probs = {
        t: {k: c[k] / n_sims for k in STAGE_KEYS} for t, c in counters.items()
    }
    anchored = sorted(
        m.match_id for m in group_matches
        if frozenset((m.home, m.away)) in anchors
    )
    return SimOutput(run_date=run_date, seed=seed, n_sims=n_sims,
                     probs=probs, anchored=anchored)


def _group_row(
    team: str, members: list[str],
    goals: dict[tuple[str, str], tuple[int, int]],
) -> tuple[int, int, int]:
    pts = gd = gf = 0
    for (h, a), (gh, ga) in goals.items():
        if h == team:
            pts += 3 if gh > ga else 1 if gh == ga else 0
            gd += gh - ga
            gf += gh
        elif a == team:
            pts += 3 if ga > gh else 1 if gh == ga else 0
            gd += ga - gh
            gf += ga
    return pts, gd, gf


def _resolve(slot: str, slots: dict[str, str], winners: dict[str, str]) -> str:
    if slot.startswith("W"):
        return winners[f"M{int(slot[1:]):02d}"]
    if slot.startswith("3:"):
        return slots[slot]
    return slots[slot]


def save_sim(path: Path, out: SimOutput) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(out), ensure_ascii=False), encoding="utf-8")


def load_sim(path: Path) -> SimOutput | None:
    if not path.exists():
        return None
    return SimOutput(**json.loads(path.read_text(encoding="utf-8")))
