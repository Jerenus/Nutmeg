"""世界杯伤病信号接线(spec §3.2)— 默认 fetcher 装配 + 折减应用 + 降级。"""
from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from nutmeg.data.api_football import ApiQuota, FixtureBatch
from nutmeg.domain.fixtures import Fixture
from nutmeg.domain.snapshot import InjuryStatus
from nutmeg.services.worldcup import (
    _default_injury_counts,
    _injury_counts,
    _live_update_and_simulate,
)
from nutmeg.services.worldcup.ratings import (
    TeamRating,
    apply_injury_adjustments,
    save_ratings,
)
from nutmeg.services.worldcup.sim import SimOutput
from nutmeg.services.worldcup.tournament import Tournament
from tests.test_wc_tournament import _mini_tournament_dict

# ---------- apply_injury_adjustments(纯函数) ----------


def test_apply_injury_adjustments_discounts_only_injured_team() -> None:
    ratings = {"Mexico": TeamRating(800.0, 760.0), "Poland": TeamRating(700.0, 700.0)}
    out = apply_injury_adjustments(ratings, {"Mexico": 3})
    assert out["Mexico"] == TeamRating(atk=800.0 * 0.95, dfn=760.0 * 0.95)
    assert out["Poland"] == ratings["Poland"]


def test_apply_injury_adjustments_below_threshold_is_noop() -> None:
    ratings = {"Mexico": TeamRating(800.0, 800.0)}
    assert apply_injury_adjustments(ratings, {"Mexico": 2}) == ratings


def test_apply_injury_adjustments_empty_counts_returns_ratings() -> None:
    ratings = {"Mexico": TeamRating(800.0, 800.0)}
    assert apply_injury_adjustments(ratings, {}) == ratings


# ---------- _injury_counts(契约:None/失败 → {}) ----------


def test_injury_counts_none_fetcher_returns_empty() -> None:
    assert _injury_counts(date(2026, 6, 12), None) == {}


def test_injury_counts_fetcher_failure_returns_empty() -> None:
    def boom(day: date) -> dict[str, int]:
        raise RuntimeError("injuries endpoint down")

    assert _injury_counts(date(2026, 6, 12), boom) == {}


# ---------- _default_injury_counts(默认装配:当日 WC 场次 → 队名计数) ----------


def _fixture(fid: str, home: str, away: str, home_id: int, away_id: int) -> Fixture:
    return Fixture(
        fixture_id=fid, league_code="World Cup", provider_league_id=1, season=2026,
        kickoff_at=datetime(2026, 6, 12, 18, tzinfo=UTC),
        home_team_id=home_id, away_team_id=away_id,
        home_team=home, away_team=away, source="api-football",
    )


def _inj(name: str = "Player") -> InjuryStatus:
    return InjuryStatus(player_name=name, status="Missing Fixture", reason=None,
                        expected_return=None, source="api-football")


class _FakeClient:
    def __init__(self, fixtures: list[Fixture],
                 injuries: dict[str, dict[int, list[InjuryStatus]]]) -> None:
        self._fixtures = fixtures
        self._injuries = injuries
        self.injury_calls: list[str] = []

    def fetch_fixtures_by_date(self, day: date) -> FixtureBatch:
        return FixtureBatch(fixtures=self._fixtures, requests_made=1, quota=ApiQuota())

    def fetch_fixture_injuries(self, fixture_id: str) -> dict[int, list[InjuryStatus]]:
        self.injury_calls.append(fixture_id)
        return self._injuries.get(fixture_id, {})


def test_default_injury_counts_filters_wc_pairs_and_maps_team_ids() -> None:
    t = Tournament.from_dict(_mini_tournament_dict())
    client = _FakeClient(
        fixtures=[
            _fixture("9001", "Mexico", "Poland", home_id=1, away_id=2),
            _fixture("9002", "Arsenal", "Chelsea", home_id=3, away_id=4),  # 非 WC 队
        ],
        injuries={"9001": {
            1: [_inj("A"), _inj("B"), _inj("C")],  # Mexico 3 人
            2: [_inj("D")],                        # Poland 1 人
            99: [_inj("E")],                       # 未知 team_id → 忽略
        }},
    )
    counts = _default_injury_counts(client, t, date(2026, 6, 12))
    assert counts == {"Mexico": 3, "Poland": 1}
    assert client.injury_calls == ["9001"]  # 非 WC 场次不烧配额


# ---------- _live_update_and_simulate 接线(注入 fetcher,fake sim 捕获评级) ----------


def _capture_sim(monkeypatch: pytest.MonkeyPatch) -> dict:
    """monkeypatch sim.simulate_tournament,捕获实际送入模拟的 ratings。"""
    from nutmeg.services.worldcup import sim as sim_mod

    captured: dict = {}

    def fake(tournament, results, ratings, anchors, *, run_date, n_sims=20000):
        captured["ratings"] = ratings
        return SimOutput(run_date=run_date, seed=1, n_sims=1, probs={})

    monkeypatch.setattr(sim_mod, "simulate_tournament", fake)
    return captured


def _seed_ratings(wc_dir: Path, tournament: Tournament) -> None:
    save_ratings(
        wc_dir / "ratings.json",
        {team: TeamRating(800.0, 800.0) for team in tournament.teams},
        run_date="2026-06-11",
    )


def test_live_update_applies_injury_discount_to_sim_ratings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    t = Tournament.from_dict(_mini_tournament_dict())
    wc_dir = tmp_path / "wc2026"
    _seed_ratings(wc_dir, t)
    captured = _capture_sim(monkeypatch)

    sim = _live_update_and_simulate(
        run_date="2026-06-12", matches=[], tournament=t, wc_dir=wc_dir,
        fixtures_fetcher=lambda d: [],
        injuries_fetcher=lambda d: {"Mexico": 3},
    )
    assert sim is not None
    assert captured["ratings"]["Mexico"] == TeamRating(atk=800.0 * 0.95,
                                                       dfn=800.0 * 0.95)
    assert captured["ratings"]["Poland"] == TeamRating(800.0, 800.0)
    assert (wc_dir / "sim-2026-06-12.json").exists()
    # 不写回:盘面上的 ratings.json 保持未折减
    raw = (wc_dir / "ratings.json").read_text(encoding="utf-8")
    assert '"atk": 800.0' in raw


def test_live_update_survives_injuries_fetcher_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    t = Tournament.from_dict(_mini_tournament_dict())
    wc_dir = tmp_path / "wc2026"
    _seed_ratings(wc_dir, t)
    captured = _capture_sim(monkeypatch)

    def boom(day: date) -> dict[str, int]:
        raise RuntimeError("injuries endpoint down")

    sim = _live_update_and_simulate(
        run_date="2026-06-12", matches=[], tournament=t, wc_dir=wc_dir,
        fixtures_fetcher=lambda d: [], injuries_fetcher=boom,
    )
    assert sim is not None  # 伤病失败绝不拉挂决策包
    assert captured["ratings"]["Mexico"] == TeamRating(800.0, 800.0)  # 未折减
    assert (wc_dir / "sim-2026-06-12.json").exists()
