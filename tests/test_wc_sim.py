"""worldcup.sim — 确定性蒙特卡洛(spec §3.4)。"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

from nutmeg.services.worldcup.ratings import TeamRating
from nutmeg.services.worldcup.sim import (
    load_sim,
    sample_match,
    save_sim,
    seed_for,
    simulate_tournament,
)
from nutmeg.services.worldcup.tournament import Tournament
from tests.test_wc_tournament import _mini_tournament_dict


def _full_group_tournament() -> Tournament:
    """1 组 4 队全 6 场 + 2 场淘汰(1A vs 2A 进决赛槽)— 模拟闭环最小集。"""
    raw = _mini_tournament_dict()
    teams = [t["id"] for t in raw["teams"]]
    matches = []
    i = 1
    for a in range(4):
        for b in range(a + 1, 4):
            matches.append({
                "match_id": f"M{i:02d}", "stage": "group", "group": "A",
                "date_utc": "2026-06-12", "home": teams[a], "away": teams[b],
                "venue_country": "USA",
            })
            i += 1
    matches.append({"match_id": "M07", "stage": "final", "date_utc": "2026-07-19",
                    "home_slot": "1A", "away_slot": "2A", "venue_country": "USA"})
    raw["matches"] = matches
    return Tournament.from_dict(raw)


RATINGS = {
    "Mexico": TeamRating(980.0, 980.0), "Poland": TeamRating(940.0, 940.0),
    "Senegal": TeamRating(900.0, 900.0), "Jordan": TeamRating(820.0, 820.0),
}


def test_seed_for_is_stable() -> None:
    assert seed_for("2026-06-12") == seed_for("2026-06-12")
    assert seed_for("2026-06-12") != seed_for("2026-06-13")


def test_sample_match_with_anchor_respects_outcome_distribution() -> None:
    rng = random.Random(7)
    anchor = {"home": 1.0, "draw": 0.0, "away": 0.0}
    for _ in range(50):
        gh, ga = sample_match(rng, 1.4, 1.1, anchor=anchor)
        assert gh > ga  # 锚定 100% 主胜 → 必须主胜比分


def test_simulate_is_deterministic() -> None:
    t = _full_group_tournament()
    a = simulate_tournament(t, [], RATINGS, {}, run_date="2026-06-12", n_sims=300)
    b = simulate_tournament(t, [], RATINGS, {}, run_date="2026-06-12", n_sims=300)
    assert a.probs == b.probs


def test_champion_probs_sum_to_one_and_favor_strong() -> None:
    t = _full_group_tournament()
    out = simulate_tournament(t, [], RATINGS, {}, run_date="2026-06-12", n_sims=2000)
    total = sum(p["champion"] for p in out.probs.values())
    assert abs(total - 1.0) < 1e-9
    assert out.probs["Mexico"]["champion"] > out.probs["Jordan"]["champion"]


def test_played_matches_are_respected() -> None:
    from nutmeg.services.worldcup.results import WcResult

    t = _full_group_tournament()
    # 钉死约旦赢了已踢的 2 场 → 出线概率应显著高于裸评级基线
    base = simulate_tournament(t, [], RATINGS, {}, run_date="2026-06-12", n_sims=1500)
    wins = [
        WcResult("M03", "Mexico", "Jordan", "FT", "away", 0, 2, None),
        WcResult("M05", "Poland", "Jordan", "FT", "away", 0, 2, None),
    ]
    boosted = simulate_tournament(t, wins, RATINGS, {}, run_date="2026-06-12",
                                  n_sims=1500)
    assert (boosted.probs["Jordan"]["qualify"]
            > base.probs["Jordan"]["qualify"] + 0.1)


# ---------- anchor_probs 落盘回读(spec §3.5 市场 Brier 完整对比的前置) ----------


ANCHOR_M01 = {"home": 0.5, "draw": 0.3, "away": 0.2}


def test_simulate_records_anchor_probs_for_anchored_matches() -> None:
    t = _full_group_tournament()
    anchors = {frozenset(("Mexico", "Poland")): dict(ANCHOR_M01)}
    out = simulate_tournament(t, [], RATINGS, anchors,
                              run_date="2026-06-12", n_sims=50)
    assert out.anchored == ["M01"]
    assert out.anchor_probs == {"M01": ANCHOR_M01}  # 概率本体与输入一致
    # 未锚定场次不出现
    assert "M02" not in out.anchor_probs


def test_sim_save_load_roundtrip_preserves_anchor_probs(tmp_path: Path) -> None:
    t = _full_group_tournament()
    anchors = {frozenset(("Mexico", "Poland")): dict(ANCHOR_M01)}
    out = simulate_tournament(t, [], RATINGS, anchors,
                              run_date="2026-06-12", n_sims=50)
    p = tmp_path / "sim-2026-06-12.json"
    save_sim(p, out)
    loaded = load_sim(p)
    assert loaded is not None
    assert loaded.anchor_probs == {"M01": ANCHOR_M01}
    assert loaded.probs == out.probs


def test_load_sim_tolerates_old_format_without_anchor_probs(tmp_path: Path) -> None:
    """红线:.nutmeg-data 里 6/11 的真实 sim 文件没有 anchor_probs 键,必须能读。"""
    p = tmp_path / "sim-2026-06-11.json"
    p.write_text(json.dumps({
        "run_date": "2026-06-11", "seed": 1, "n_sims": 10,
        "probs": {"Mexico": {"champion": 0.5}}, "anchored": ["M01"],
    }), encoding="utf-8")
    loaded = load_sim(p)
    assert loaded is not None
    assert loaded.anchor_probs == {}
    assert loaded.anchored == ["M01"]


def test_simulation_speed_budget() -> None:
    """N=2000 在迷你赛制上 <5s — 真实 104 场 N=20000 约为 70 倍工作量,
    launchd 离线跑可接受;此测试防止实现退化到不可用。"""
    t = _full_group_tournament()
    t0 = time.monotonic()
    simulate_tournament(t, [], RATINGS, {}, run_date="2026-06-12", n_sims=2000)
    assert time.monotonic() - t0 < 5.0
