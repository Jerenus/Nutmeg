# Dixon-Coles Model Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the conflict-engine's Dixon-Coles model produce trustworthy expected goals — differentiating strong from weak teams and accounting for home advantage — so "model vs market" is real signal, not a systematic fade-the-favorite bias.

**Architecture:** Two small, surgical changes (Stage 1 of the spec). (1) The model estimates team strength from a season-spanning match window instead of the last 5 (kills streak noise). (2) `expected_goals_from_snapshot` applies a home-advantage multiplier in both of its branches. Plus a small pure calibration-stats helper for the acceptance gate. The `(attack + opponent_defense)/2` formula structure and all pricing/downstream code are left unchanged.

**Tech Stack:** Python 3.13, `uv run pytest`, existing `nutmeg/models/dixon_coles.py` + `nutmeg/services/value.py`.

**Spec:** `docs/superpowers/specs/2026-05-17-dixon-coles-model-calibration-design.md`

---

## File Structure

- `nutmeg/models/dixon_coles.py` — **modify**: add `_HOME_ADVANTAGE` module constant; apply it in both branches of `expected_goals_from_snapshot`.
- `nutmeg/services/value.py` — **modify**: add `_STRENGTH_WINDOW_MATCHES` module constant; `_evaluate_fixture` requests that window from `build_snapshot`.
- `nutmeg/services/value_calibration.py` — **create**: pure `calibration_stats` helper (direction-agreement + correlation) for the §5 acceptance gate.
- `tests/test_dixon_coles.py` — **modify**: update one existing test for the new home-advantage values; add home-advantage + season-fallback tests.
- `tests/test_value_service.py` — **modify**: add one test asserting `_evaluate_fixture` requests the wide window.
- `tests/test_value_calibration.py` — **create**: unit tests for `calibration_stats`.

---

## Task 1: Home-advantage multiplier in the recent-xg-matchup branch

**Files:**
- Modify: `nutmeg/models/dixon_coles.py:13` (add constant after `_HANDICAP_LINES`) and `nutmeg/models/dixon_coles.py:254-258` (the `recent-xg-matchup` return)
- Test: `tests/test_dixon_coles.py`

- [ ] **Step 1: Update the existing test to the post-calibration values**

In `tests/test_dixon_coles.py`, the existing `test_expected_goals_from_snapshot_uses_recent_xg_matchup` currently asserts the un-adjusted values. The `_snapshot()` helper gives `home_trend` xg_for=2.0 / xg_against=0.8 and `away_trend` xg_for=1.0 / xg_against=1.8, so the raw matchup is home `(2.0+1.8)/2=1.9`, away `(1.0+0.8)/2=0.9`. After the home-advantage multiplier `_HOME_ADVANTAGE=1.18`: home `1.9*1.18=2.242→2.24`, away `0.9/1.18=0.7627→0.76`.

Replace the test body:

```python
def test_expected_goals_from_snapshot_uses_recent_xg_matchup() -> None:
    expected_goals = expected_goals_from_snapshot(_snapshot())

    # raw matchup home 1.9 / away 0.9, then home-advantage 1.18 applied:
    # home 1.9 * 1.18 = 2.24, away 0.9 / 1.18 = 0.76
    assert expected_goals.home == 2.24
    assert expected_goals.away == 0.76
    assert expected_goals.source == 'recent-xg-matchup'
```

- [ ] **Step 2: Add a test that home advantage alone tilts identical teams**

Append to `tests/test_dixon_coles.py`:

```python
def _snapshot_with_trends(
    *,
    home_xg_for: float,
    home_xg_against: float,
    away_xg_for: float,
    away_xg_against: float,
) -> FixtureSnapshot:
    base = _snapshot()
    return FixtureSnapshot(
        fixture=base.fixture,
        home=base.home,
        away=base.away,
        deferred_sections=[],
        generated_at=base.generated_at,
        matchup=MatchupTrendContext(
            head_to_head=None,
            home_split=None,
            away_split=None,
            home_trend=TeamTrendSummary(
                sample_size=38,
                goals_for_per_match=home_xg_for,
                xg_for_per_match=home_xg_for,
                goals_against_per_match=home_xg_against,
                xg_against_per_match=home_xg_against,
                set_piece_shot_share=None,
                source='test',
            ),
            away_trend=TeamTrendSummary(
                sample_size=38,
                goals_for_per_match=away_xg_for,
                xg_for_per_match=away_xg_for,
                goals_against_per_match=away_xg_against,
                xg_against_per_match=away_xg_against,
                set_piece_shot_share=None,
                source='test',
            ),
        ),
    )


def test_expected_goals_from_snapshot_applies_home_advantage() -> None:
    # Two teams with identical trend numbers: any home/away split in expected
    # goals must come purely from the home-advantage multiplier.
    snapshot = _snapshot_with_trends(
        home_xg_for=1.5,
        home_xg_against=1.5,
        away_xg_for=1.5,
        away_xg_against=1.5,
    )

    expected_goals = expected_goals_from_snapshot(snapshot)

    assert expected_goals.home > expected_goals.away
    # raw matchup is 1.5 for both sides; 1.5 * 1.18 = 1.77, 1.5 / 1.18 = 1.27
    assert expected_goals.home == 1.77
    assert expected_goals.away == 1.27
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_dixon_coles.py::test_expected_goals_from_snapshot_uses_recent_xg_matchup tests/test_dixon_coles.py::test_expected_goals_from_snapshot_applies_home_advantage -v`
Expected: FAIL — `test_..._uses_recent_xg_matchup` asserts 2.24 but gets 1.9; `test_..._applies_home_advantage` asserts home==1.77 but gets 1.5 (no multiplier yet).

- [ ] **Step 4: Add the `_HOME_ADVANTAGE` constant**

In `nutmeg/models/dixon_coles.py`, after the `_HANDICAP_LINES` definition (line 13), add:

```python
# Home-advantage multiplier for expected goals: the home side's goal
# expectation is scaled up and the away side's down by the same factor.
# ~1.18 reflects the roughly 55/45 home/away goal split in major European
# leagues, kept slightly conservative. A named constant so it is easy to
# re-tune from backtests.
_HOME_ADVANTAGE = 1.18
```

- [ ] **Step 5: Apply the multiplier in the recent-xg-matchup branch**

In `nutmeg/models/dixon_coles.py`, the `recent-xg-matchup` return (currently lines 254-258) is:

```python
            return ExpectedGoals(
                home=round((home_attack + away_defense) / 2, 2),
                away=round((away_attack + home_defense) / 2, 2),
                source='recent-xg-matchup',
            )
```

Replace it with:

```python
            return ExpectedGoals(
                home=round((home_attack + away_defense) / 2 * _HOME_ADVANTAGE, 2),
                away=round((away_attack + home_defense) / 2 / _HOME_ADVANTAGE, 2),
                source='recent-xg-matchup',
            )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_dixon_coles.py -v`
Expected: PASS — all dixon-coles tests green.

- [ ] **Step 7: Commit**

```bash
git add nutmeg/models/dixon_coles.py tests/test_dixon_coles.py
git commit -m "feat(model): apply home-advantage multiplier to expected goals

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Home-advantage in the season-xg-per-match fallback branch

**Files:**
- Modify: `nutmeg/models/dixon_coles.py:262-267` (the `season-xg-per-match` return)
- Test: `tests/test_dixon_coles.py`

- [ ] **Step 1: Write the failing test**

The fallback branch is reached when `matchup` is `None`. It reads each team's `season_metrics` via `_season_xg_per_match`, which returns `_first_number(metrics.xg, metrics.goals) / metrics.matches`. Append to `tests/test_dixon_coles.py`:

```python
def _team_with_season(name: str, *, goals: float, matches: float) -> TeamEnrichment:
    return TeamEnrichment(
        canonical_name=name,
        source_names={},
        season_metrics=TeamSeasonMetrics(
            matches=matches,
            goals=goals,
            shots=None,
            shots_on_target=None,
            xg=None,
            non_penalty_xg=None,
        ),
        recent_form=None,
        shot_summary=None,
        market_value=None,
        injuries=[],
        lineup=None,
    )


def test_expected_goals_from_snapshot_season_fallback_applies_home_advantage() -> None:
    # matchup=None forces the season-xg-per-match fallback branch.
    base = _snapshot()
    snapshot = FixtureSnapshot(
        fixture=base.fixture,
        home=_team_with_season('Arsenal', goals=36.0, matches=36.0),  # 1.0 / match
        away=_team_with_season('Tottenham Hotspur', goals=18.0, matches=36.0),  # 0.5 / match
        deferred_sections=[],
        generated_at=base.generated_at,
        matchup=None,
    )

    expected_goals = expected_goals_from_snapshot(snapshot)

    assert expected_goals.source == 'season-xg-per-match'
    # home 1.0 * 1.18 = 1.18, away 0.5 / 1.18 = 0.4237 -> 0.42
    assert expected_goals.home == 1.18
    assert expected_goals.away == 0.42
```

Add `TeamSeasonMetrics` to the existing `from nutmeg.domain.snapshot import (...)` block at the top of `tests/test_dixon_coles.py` (it currently imports `FixtureSnapshot, MatchupTrendContext, TeamEnrichment, TeamTrendSummary`).

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_dixon_coles.py::test_expected_goals_from_snapshot_season_fallback_applies_home_advantage -v`
Expected: FAIL — current code uses `home_season * 1.08` (= 1.08, not 1.18) and `away_season * 0.92` (= 0.46, not 0.42).

- [ ] **Step 3: Replace the magic numbers with the constant**

In `nutmeg/models/dixon_coles.py`, the `season-xg-per-match` return (currently lines 263-267) is:

```python
        return ExpectedGoals(
            home=round(home_season * 1.08, 2),
            away=round(away_season * 0.92, 2),
            source='season-xg-per-match',
        )
```

Replace it with:

```python
        return ExpectedGoals(
            home=round(home_season * _HOME_ADVANTAGE, 2),
            away=round(away_season / _HOME_ADVANTAGE, 2),
            source='season-xg-per-match',
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_dixon_coles.py -v`
Expected: PASS — all dixon-coles tests green.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/models/dixon_coles.py tests/test_dixon_coles.py
git commit -m "feat(model): unify season-fallback home advantage on _HOME_ADVANTAGE

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Widen the strength-estimation window in the value engine

**Files:**
- Modify: `nutmeg/services/value.py` (add constant; `_evaluate_fixture` line 143)
- Test: `tests/test_value_service.py`

- [ ] **Step 1: Write the failing test**

`_evaluate_fixture` calls `self._snapshot_service.build_snapshot(fixture.fixture_id, recent_matches=5)`. The test asserts it now requests the season-spanning window. Append to `tests/test_value_service.py`:

```python
def test_evaluate_fixture_requests_season_window_snapshot() -> None:
    # Team strength must be estimated over a season-spanning window, not the
    # last 5 matches (5 matches is streak noise — see the calibration spec).
    from nutmeg.services.value import _STRENGTH_WINDOW_MATCHES

    fixture = _fixture('1379305')
    recorded: dict[str, int] = {}

    class _RecordingSnapshotService:
        def build_snapshot(self, fixture_id: str, *, recent_matches: int = 5):
            recorded['recent_matches'] = recent_matches
            return _snapshot(fixture)

    service = ValueBoardService(
        fixture_repository=None,  # type: ignore[arg-type]
        snapshot_service=_RecordingSnapshotService(),
        odds_service=FakeOddsService({fixture.fixture_id: _odds(fixture)}),
    )

    service.build_board_for_fixtures([fixture], min_edge=0.03)

    assert recorded['recent_matches'] == _STRENGTH_WINDOW_MATCHES
    assert _STRENGTH_WINDOW_MATCHES >= 34
```

This reuses the existing `_fixture`, `_snapshot`, `_odds`, `FakeOddsService` helpers already in `tests/test_value_service.py`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_value_service.py::test_evaluate_fixture_requests_season_window_snapshot -v`
Expected: FAIL — `ImportError: cannot import name '_STRENGTH_WINDOW_MATCHES'` (constant does not exist yet).

- [ ] **Step 3: Add the constant and use it**

In `nutmeg/services/value.py`, add a module-level constant near the top of the file (after the imports, before `class SnapshotService`):

```python
# Team-strength estimation window. A season-spanning window de-noises the
# expected-goals inputs — a 5-match window is dominated by streak noise and
# made the model fade the market favorite. 38 covers the longest European
# league season; the snapshot service truncates gracefully to whatever
# history is available.
_STRENGTH_WINDOW_MATCHES = 38
```

Then in `_evaluate_fixture`, change the snapshot call (currently line 143):

```python
        snapshot = self._snapshot_service.build_snapshot(fixture.fixture_id, recent_matches=5)
```

to:

```python
        snapshot = self._snapshot_service.build_snapshot(
            fixture.fixture_id, recent_matches=_STRENGTH_WINDOW_MATCHES
        )
```

Note: `_evaluate_fixture` is the single snapshot call site — both `build_board` and `build_board_for_fixtures` route through it, so this one change covers both paths.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_value_service.py -v`
Expected: PASS — all value-service tests green.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/value.py tests/test_value_service.py
git commit -m "feat(value): estimate team strength over a season window, not last 5

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Calibration-stats helper for the acceptance gate

**Files:**
- Create: `nutmeg/services/value_calibration.py`
- Test: `tests/test_value_calibration.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_value_calibration.py`:

```python
from __future__ import annotations

from nutmeg.services.value_calibration import (
    MatchWinnerView,
    calibration_stats,
)


def _view(
    fid: str,
    *,
    model: tuple[float, float, float],
    market: tuple[float, float, float],
) -> MatchWinnerView:
    return MatchWinnerView(
        fixture_id=fid,
        model_home=model[0],
        model_draw=model[1],
        model_away=model[2],
        market_home=market[0],
        market_draw=market[1],
        market_away=market[2],
    )


def test_calibration_stats_empty_input() -> None:
    stats = calibration_stats([])

    assert stats.fixtures == 0
    assert stats.direction_agreement == 0.0
    assert stats.home_prob_correlation == 0.0


def test_calibration_stats_direction_agreement() -> None:
    # 3 of 4 fixtures: model's argmax direction matches the market's.
    views = [
        _view('a', model=(0.6, 0.2, 0.2), market=(0.55, 0.25, 0.20)),  # both home
        _view('b', model=(0.2, 0.2, 0.6), market=(0.25, 0.25, 0.50)),  # both away
        _view('c', model=(0.5, 0.3, 0.2), market=(0.45, 0.35, 0.20)),  # both home
        _view('d', model=(0.6, 0.2, 0.2), market=(0.20, 0.25, 0.55)),  # model home, market away
    ]

    stats = calibration_stats(views)

    assert stats.fixtures == 4
    assert stats.direction_agreement == 0.75


def test_calibration_stats_home_prob_correlation_is_strong_when_aligned() -> None:
    # model P(home) tracks market P(home) closely -> correlation near 1.
    views = [
        _view('a', model=(0.20, 0.3, 0.5), market=(0.22, 0.3, 0.48)),
        _view('b', model=(0.45, 0.3, 0.25), market=(0.43, 0.3, 0.27)),
        _view('c', model=(0.70, 0.2, 0.1), market=(0.68, 0.2, 0.12)),
    ]

    stats = calibration_stats(views)

    assert stats.home_prob_correlation > 0.9


def test_calibration_stats_home_prob_correlation_negative_when_fading() -> None:
    # model fades the market: where the market likes home, the model doesn't.
    views = [
        _view('a', model=(0.70, 0.2, 0.10), market=(0.20, 0.3, 0.50)),
        _view('b', model=(0.45, 0.3, 0.25), market=(0.45, 0.3, 0.25)),
        _view('c', model=(0.20, 0.2, 0.60), market=(0.70, 0.2, 0.10)),
    ]

    stats = calibration_stats(views)

    assert stats.home_prob_correlation < 0.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_value_calibration.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nutmeg.services.value_calibration'`.

- [ ] **Step 3: Create the calibration module**

Create `nutmeg/services/value_calibration.py`:

```python
"""Calibration check for the conflict-engine model.

Measures whether the Dixon-Coles model's match-winner view tracks the market
rather than systematically fading the favorite. Used as the acceptance gate
for the model-calibration work (see the calibration spec §5). Pure functions
only — no I/O, no network — so it is unit-testable; the live data is gathered
by the acceptance run.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class MatchWinnerView:
    """One fixture's match-winner probabilities, from model and from market."""

    fixture_id: str
    model_home: float
    model_draw: float
    model_away: float
    market_home: float
    market_draw: float
    market_away: float


@dataclass(slots=True, frozen=True)
class CalibrationStats:
    """Aggregate calibration metrics over a set of fixtures."""

    fixtures: int
    direction_agreement: float  # share where model argmax == market argmax
    home_prob_correlation: float  # Pearson r of model vs market P(home win)


def _argmax3(home: float, draw: float, away: float) -> str:
    return max(
        (('home', home), ('draw', draw), ('away', away)),
        key=lambda pair: pair[1],
    )[0]


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0.0 or var_y == 0.0:
        return 0.0
    return cov / (var_x ** 0.5 * var_y ** 0.5)


def calibration_stats(views: list[MatchWinnerView]) -> CalibrationStats:
    """Direction-agreement rate and P(home) correlation between model and market.

    A calibrated model agrees with the market favorite most of the time and its
    home-win probabilities track the market's. A model that fades the favorite
    scores low agreement and zero/negative correlation.
    """
    if not views:
        return CalibrationStats(
            fixtures=0, direction_agreement=0.0, home_prob_correlation=0.0
        )
    agree = sum(
        1
        for v in views
        if _argmax3(v.model_home, v.model_draw, v.model_away)
        == _argmax3(v.market_home, v.market_draw, v.market_away)
    )
    correlation = _pearson(
        [v.model_home for v in views],
        [v.market_home for v in views],
    )
    return CalibrationStats(
        fixtures=len(views),
        direction_agreement=round(agree / len(views), 4),
        home_prob_correlation=round(correlation, 4),
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_value_calibration.py -v`
Expected: PASS — all 4 calibration tests green.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/value_calibration.py tests/test_value_calibration.py
git commit -m "feat(value): calibration-stats helper for model-vs-market agreement

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Full-suite check + live calibration acceptance (spec §5 gate)

**Files:** none modified — verification only.

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest tests/ -q`
Expected: PASS — every test green. If anything outside the dixon-coles / value / calibration tests fails, a downstream consumer depended on the old expected-goals values; investigate and fix before continuing.

- [ ] **Step 2: Re-generate today's brief with the calibrated model**

Run: `uv run nutmeg jczq-daily-brief --date 2026-05-17 --write /tmp/jczq-brief-calibrated.md`
Expected: exit 0, file written. The `## 赔率冲突点` section is the subject of the check below.

- [ ] **Step 3: Run the live calibration gate**

Save this snippet to `/tmp/calibration_check.py` and run `uv run python /tmp/calibration_check.py` (throwaway — do not commit):

```python
import logging
logging.basicConfig(level=logging.ERROR)
from nutmeg.interfaces.cli import build_value_board_service, _build_jczq_value_bridge_for_brief
from nutmeg.models.dixon_coles import DixonColesLiteModel, expected_goals_from_snapshot
from nutmeg.services.value_calibration import MatchWinnerView, calibration_stats

bridge = _build_jczq_value_bridge_for_brief('2026-05-17')
report = bridge.evaluate_day_from_context('2026-05-17')  # aligned fixtures for the day
svc, _ = build_value_board_service()
model = DixonColesLiteModel()
views = []
for entry in report.matches:
    if not entry.aligned or entry.fixture_id is None:
        continue
    try:
        snap = svc._snapshot_service.build_snapshot(entry.fixture_id, recent_matches=38)
        odds = svc._odds_service.build_snapshot(entry.fixture_id, persist_history=False)
        mw = odds.markets.get('match_winner')
        if mw is None:
            continue
        probs = model.price(expected_goals_from_snapshot(snap))
        fair = {o.selection: o.fair_probability for o in mw.outcomes}
        if None in fair.values() or len(fair) < 3:
            continue
        views.append(MatchWinnerView(
            fixture_id=entry.fixture_id,
            model_home=probs.home_win, model_draw=probs.draw, model_away=probs.away_win,
            market_home=fair['home'], market_draw=fair['draw'], market_away=fair['away'],
        ))
    except Exception as exc:
        print('skip', entry.fixture_id, exc)

stats = calibration_stats(views)
print(stats)
print('GATE 5.1 direction_agreement >= 0.60:', stats.direction_agreement >= 0.60)
print('GATE 5.2 home_prob_correlation > 0.50:', stats.home_prob_correlation > 0.50)
```

Note: the exact attribute names (`bridge.evaluate_day_from_context`, `report.matches[].aligned/.fixture_id`, `mw.outcomes`, `outcome.selection`, `outcome.fair_probability`) must be confirmed against `nutmeg/services/jczq_value_bridge.py` and `nutmeg/domain/odds.py` while writing the snippet — adjust to the real API. The snippet is throwaway; correctness of the gate numbers is what matters.

- [ ] **Step 4: Evaluate the §5 acceptance gates**

Expected (spec §5): `direction_agreement >= 0.60` AND `home_prob_correlation > 0.50`, and the brief's `## 赔率冲突点` section shows `strong`-rated edges only on a minority of matches (not ~13/14).

- **If the gates pass:** Stage 1 calibration succeeded. Mark the spec done (Step 5).
- **If the gates fail:** Stage 1 was insufficient. Do NOT declare success. Report the numbers and recommend Stage 2 (the league-normalized strength-ratio model — a separate spec). Stop here.

- [ ] **Step 5: Record the outcome**

Update `docs/superpowers/specs/2026-05-17-dixon-coles-model-calibration-design.md` — change the status line to `已完成` (gates passed) or `Stage 1 不达标，触发 Stage 2` (gates failed), and append the measured `direction_agreement` / `home_prob_correlation` numbers under §8.

```bash
git add docs/superpowers/specs/2026-05-17-dixon-coles-model-calibration-design.md
git commit -m "docs: record Dixon-Coles calibration Stage 1 acceptance result

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:**
- Spec §3 Stage 1 改动 1 (widen window) → Task 3. ✓
- Spec §3 Stage 1 改动 2 (home advantage, both branches) → Task 1 (recent-xg-matchup) + Task 2 (season fallback). ✓
- Spec §5 validation (calibration check + §5.1/§5.2 gates) → Task 4 (helper) + Task 5 (live gate). ✓
- Spec §6 testing strategy (strong/weak differentiation, home advantage, season fallback, value.py window) → Task 1 Step 2, Task 2 Step 1, Task 3 Step 1. ✓ Note: strong/weak *differentiation* is a property of the unchanged `(attack+opp_def)/2` formula given de-noised inputs; the existing `test_expected_goals_from_snapshot_uses_recent_xg_matchup` (asymmetric inputs → asymmetric output) already exercises it, and the window's real de-noising effect is validated live in Task 5.
- Spec §3 Stage 2 → explicitly out of scope; Task 5 Step 4 routes to it on failure. ✓

**2. Placeholder scan:** No TBD/TODO. Task 5's snippet carries an explicit "confirm attribute names against the real API" note — that is a deliberate, honest instruction for a throwaway acceptance script, not a placeholder in shipped code.

**3. Type consistency:** `_HOME_ADVANTAGE` (float, dixon_coles.py) and `_STRENGTH_WINDOW_MATCHES` (int, value.py) are used consistently. `MatchWinnerView` / `CalibrationStats` / `calibration_stats` names match between Task 4's implementation and test. `expected_goals_from_snapshot` returns `ExpectedGoals(home, away, source)` unchanged.
