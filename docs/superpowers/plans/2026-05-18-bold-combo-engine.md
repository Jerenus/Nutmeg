# Bold-Combo Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An entertainment-purpose JCZQ parlay generator — picks bold 1X2 legs from real board signals (体彩-vs-欧赔 conflict, contrarian, heat, odds drift, bookmaker dispersion), assembles creative 3/4/5-fold parlays, modulated by a day-level chaos value — with a hard 🎲 entertainment label welded into every output.

**Architecture:** A new `nutmeg/services/jczq_bold_combos.py` consumes 体彩 odds (from the day's `context.json`) + 国际欧赔 (from the extended `Fcom500OddsProvider`). Five pure signal functions → a per-(match,outcome) boldness score → one bold leg per match → a chaos-modulated candidate pool → ranked 3/4/5串 combos + one 稳健底仓. **No predictive model is imported.** Output carries a welded honest label and no advantage wording.

**Tech Stack:** Python 3.13, `uv run pytest`, existing `nutmeg/data/fcom500.py` parsers, Typer CLI.

**Spec:** `docs/superpowers/specs/2026-05-18-bold-combo-engine-design.md`

---

## Scope note

B operates on the **胜平负 (1X2)** market — that is where both 体彩 odds and 欧赔 exist cleanly, so all five signals are well-defined. 让球/总进球/比分 are out of scope for this plan (a later extension). One bold leg per match = a 1X2 pick (胜/平/负).

## File Structure

- `nutmeg/data/fcom500.py` — **modify**: extend 欧赔 parsing to also expose opening odds + per-bookmaker odds (needed for the drift + dispersion signals).
- `nutmeg/services/jczq_bold_combos.py` — **create**: signal functions, boldness composition, day chaos value, leg selection, combination generation, 稳健底仓, the `BoldComboEngine` + output dataclasses + the welded label constant.
- `nutmeg/interfaces/cli/jczq.py` — **modify**: add the `jczq-bold-combos` command.
- `tests/test_fcom500.py` — **modify**: tests for the extended 欧赔 parsing.
- `tests/test_jczq_bold_combos.py` — **create**: signal / composition / chaos / combination / engine tests + the label & no-edge-word assertions.
- `tests/test_cli.py` — **modify**: a `jczq-bold-combos` smoke test.

---

## Task 1: Extend 欧赔 parsing — opening odds + per-bookmaker odds

**Files:** Modify `nutmeg/data/fcom500.py` (`MarketOdds`, `parse_european_1x2`); Test `tests/test_fcom500.py`

The 欧赔 page's per-bookmaker `pl_table_data` table has two `<tr>`: opening (first 3 cells) + live (last 3). `parse_european_1x2` currently keeps only the live average. The drift signal needs the opening odds; the dispersion signal needs the per-bookmaker spread.

- [ ] **Step 1: Write the failing test** — extend an existing `parse_european_1x2` test (recorded `tests/fixtures/fcom500/ouzhi-*.html`): assert the returned `MarketOdds` now also exposes `opening_odds` (dict home/draw/away, the international-book average of the OPENING row) and `per_book_odds` (dict home/draw/away → list[float] of each international book's live odds). Assert `len(per_book_odds['home']) == bookmaker_count` and that `opening_odds` differs from `odds` on the fixture.
- [ ] **Step 2: Run — fails** (`MarketOdds` has no `opening_odds`/`per_book_odds`).
- [ ] **Step 3: Implement** — add `opening_odds: dict[str, float] = field(default_factory=dict)` and `per_book_odds: dict[str, list[float]] = field(default_factory=dict)` to `MarketOdds`. In `parse_european_1x2`, for each international book row collect BOTH the opening triple and the live triple; return live average in `odds` (unchanged), opening average in `opening_odds`, and the per-book live lists in `per_book_odds`.
- [ ] **Step 4: Run — passes; run the whole `tests/test_fcom500.py`.**
- [ ] **Step 5: Commit** (`feat(fcom500): expose opening + per-bookmaker 欧赔 for drift/dispersion`).

## Task 2: The five boldness signals (pure functions)

**Files:** Create `nutmeg/services/jczq_bold_combos.py`; Test `tests/test_jczq_bold_combos.py`

Five pure functions, each returning a score in roughly [0, 1]. Inputs are plain numbers/dicts (no I/O). `OUTCOMES = ("home", "draw", "away")`.

- [ ] **Step 1: Write failing tests** — for each signal, a test with synthetic inputs and an asserted score:
  - `conflict_score(tc_fair, euro_fair) -> dict[str,float]`: per outcome `abs(tc_fair[o] - euro_fair[o])`, clipped to [0,1]. Test: 体彩 home 0.30 vs 欧赔 home 0.45 → conflict home == 0.15.
  - `contrarian_score(tc_fair) -> dict[str,float]`: per outcome `1 - tc_fair[o]` for the two non-favorite outcomes, `0.0` for the 体彩 favorite (argmax of `tc_fair`). Test: tc_fair home 0.55/draw 0.25/away 0.20 → contrarian == {home:0.0, draw:0.75, away:0.80}.
  - `drift_score(opening, live) -> dict[str,float]`: per outcome `min(abs(1/live[o] - 1/opening[o]) * DRIFT_GAIN, 1.0)` — implied-probability movement. Test: opening home 2.0 / live home 1.6 → non-zero, away unchanged → 0.
  - `dispersion_score(per_book_odds) -> dict[str,float]`: per outcome, the population stdev of `1/odds` across books, `* DISPERSION_GAIN`, clipped [0,1]. Test: all books equal → 0; spread books → >0.
  - `heat_score(match_tags, vig) -> float`: a per-MATCH scalar — `+HEAT_TAG` per tag in {强胆场, 舒服盘, coinflip, draw_friendly, hi-vol} present, `+ (vig - 0.12) * HEAT_VIG_GAIN`, clipped [0,1]. Test: 2 tags + vig 0.13 → asserted value.
- [ ] **Step 2: Run — fail (module/functions absent).**
- [ ] **Step 3: Implement** the five functions + the named-constant gains (`DRIFT_GAIN`, `DISPERSION_GAIN`, `HEAT_TAG`, `HEAT_VIG_GAIN`) at module level with documented default values.
- [ ] **Step 4: Run — pass.**
- [ ] **Step 5: Commit** (`feat(bold-combos): five board-signal scoring functions`).

## Task 3: Boldness composition + bold-leg selection

**Files:** Modify `nutmeg/services/jczq_bold_combos.py`; Test `tests/test_jczq_bold_combos.py`

- [ ] **Step 1: Write failing test** — `boldness(match) -> dict[str,float]` combines the five signals for one match into a per-outcome score: `WEIGHT_CONFLICT*conflict + WEIGHT_CONTRARIAN*contrarian + WEIGHT_DRIFT*drift + WEIGHT_DISPERSION*dispersion + WEIGHT_HEAT*heat` (heat is the per-match scalar added to every outcome). Weights are module constants, default all equal (0.2). `bold_leg(match) -> BoldLeg` returns the argmax-boldness outcome with its 体彩 odds + a human 大胆理由 string naming the dominant signal. Test: a synthetic match where away has the top boldness → `bold_leg().pick == "away"`, and `.reason` mentions the dominant signal.
- [ ] **Step 2: Run — fails.**
- [ ] **Step 3: Implement** `boldness`, `bold_leg`, the `BoldLeg` dataclass (`match_no, league, home, away, pick, tc_odds, boldness, reason`), and the `WEIGHT_*` constants.
- [ ] **Step 4: Run — pass.**
- [ ] **Step 5: Commit** (`feat(bold-combos): boldness composition + bold-leg selection`).

## Task 4: Day chaos value

**Files:** Modify `nutmeg/services/jczq_bold_combos.py`; Test `tests/test_jczq_bold_combos.py`

- [ ] **Step 1: Write failing test** — `day_chaos(matches) -> int` (0-100): per match `uncertainty = mean(dispersion) + mean(conflict)` over outcomes; day chaos = `round(median(uncertainties) * CHAOS_SCALE)`, clamped [0,100]. `chaos_pool_size(chaos) -> int` maps chaos to the candidate-pool `N`: linear from `POOL_MIN` (chaos 0) to `POOL_MAX` (chaos 100). Test: low-dispersion/low-conflict matches → chaos near 0 → `N == POOL_MIN`; high → near 100 → `N == POOL_MAX`. `chaos_band(chaos) -> str` → "平静"/"中等"/"混乱".
- [ ] **Step 2: Run — fails.**
- [ ] **Step 3: Implement** `day_chaos`, `chaos_pool_size`, `chaos_band` + constants `CHAOS_SCALE`, `POOL_MIN=4`, `POOL_MAX=10`.
- [ ] **Step 4: Run — pass.**
- [ ] **Step 5: Commit** (`feat(bold-combos): day-level chaos value + pool sizing`).

## Task 5: Combination generation + 稳健底仓

**Files:** Modify `nutmeg/services/jczq_bold_combos.py`; Test `tests/test_jczq_bold_combos.py`

- [ ] **Step 1: Write failing tests** —
  - `bold_combos(legs, chaos) -> list[BoldTicket]`: from the candidate `legs` (already the top-N by boldness) generate 3/4/5串1 combinations; each `BoldTicket` carries `legs, fold, total_odds (=product of leg tc_odds), avg_boldness`; rank by `total_odds * avg_boldness` desc; when `chaos` is high, bias the returned mix toward 4/5串 (more long tickets), when low toward 3串. Every ticket's legs are distinct matches (Rule O — different `match_no`). Test: 6 legs → tickets returned, each `fold in (3,4,5)`, no ticket repeats a `match_no`, `total_odds` == product.
  - `anchor_ticket(matches) -> BoldTicket`: 2-3 legs, the matches whose 体彩 favorite has the LOWEST odds (highest implied prob); pick = that favorite; `fold` 2 or 3. Test: assert it picks the lowest-odds favorites and `fold in (2,3)`.
- [ ] **Step 2: Run — fails.**
- [ ] **Step 3: Implement** `bold_combos`, `anchor_ticket`, the `BoldTicket` dataclass (`id, kind, legs, fold, total_odds, avg_boldness, note`). Rule O = legs are distinct `match_no` (all picks are 胜平负, so distinct matches is sufficient).
- [ ] **Step 4: Run — pass.**
- [ ] **Step 5: Commit** (`feat(bold-combos): 3/4/5-fold combination generation + anchor ticket`).

## Task 6: Engine assembly + welded honest label

**Files:** Modify `nutmeg/services/jczq_bold_combos.py`; Test `tests/test_jczq_bold_combos.py`

- [ ] **Step 1: Write failing tests** —
  - `HARD_LABEL` module constant == exactly `"🎲 娱乐性质 · 非 edge · 长期约 −13% 抽水期望 · 仅用娱乐预算下注"`.
  - `BoldComboEngine(odds_provider).generate(run_date, matches) -> BoldComboPlan` — `BoldComboPlan` has `run_date, day_chaos, chaos_band, anchor, tickets (list[BoldTicket]), label`. Build from injected fakes (a fake odds provider returning recorded-style `MarketOdds`, synthetic 体彩 matches). Assert: `plan.label == HARD_LABEL`; `plan.anchor.kind == "稳健底仓"`; `plan.tickets` non-empty with folds in {3,4,5}; the anchor's `note` contains "高命中" and "≠ +EV".
  - `render_bold_plan(plan) -> str` markdown — assert the output **starts with** `HARD_LABEL` and the chaos line, and assert the rendered text contains **none** of: `胜率`, `edge`, `+EV`, `正期望`, `推荐下注`, `重仓`.
- [ ] **Step 2: Run — fails.**
- [ ] **Step 3: Implement** `BoldComboEngine` (orchestrates Tasks 2-5: per-match boldness → bold legs → day chaos → pool N → combos + anchor), `BoldComboPlan`, `render_bold_plan`, `HARD_LABEL`. The renderer welds `HARD_LABEL` + the chaos line at the top of every output; legs show `match_no/选项/体彩赔率/大胆理由`; tickets show `total_odds` and `avg_boldness` (labelled "大胆分", never "胜率/信心"). No probability/EV fields.
- [ ] **Step 4: Run — pass.**
- [ ] **Step 5: Commit** (`feat(bold-combos): BoldComboEngine + honest-labelled renderer`).

## Task 7: CLI command `jczq-bold-combos`

**Files:** Modify `nutmeg/interfaces/cli/jczq.py`; Test `tests/test_cli.py`

- [ ] **Step 1: Write failing test** — a `tests/test_cli.py` smoke test invoking `jczq-bold-combos --replay <date>` over a recorded day; assert exit 0 and the output contains `HARD_LABEL`.
- [ ] **Step 2: Run — fails (no such command).**
- [ ] **Step 3: Implement** the `jczq-bold-combos` command: `--date` (live) / `--replay` (stored `context.json`) / `--write`. It wires the day's 体彩 matches + `Fcom500OddsProvider` into `BoldComboEngine`, prints/writes `render_bold_plan`. Graceful degradation: no 欧赔 / fetch failure → that match's conflict/drift/dispersion signals are 0 (heat+contrarian still work), never crash.
- [ ] **Step 4: Run — pass; spot-check `uv run nutmeg jczq-bold-combos --help`.**
- [ ] **Step 5: Commit** (`feat(cli): jczq-bold-combos command`).

## Task 8: Acceptance

**Files:** verification only.

- [ ] **Step 1:** `uv run pytest tests/ -q` — fully green.
- [ ] **Step 2:** `uv run ruff check nutmeg/services/jczq_bold_combos.py nutmeg/data/fcom500.py nutmeg/interfaces/cli/jczq.py` — clean.
- [ ] **Step 3:** Confirm `nutmeg/services/jczq_bold_combos.py` does **not** import `dixon_coles`, `ValueBoardService`, or any predictive model (grep — spec §7).
- [ ] **Step 4:** Run `jczq-bold-combos` on a recorded day; eyeball that the 🎲 label is at the top, the 稳健底仓 + bold tickets render, and no "胜率/edge/+EV" wording appears.
- [ ] **Step 5: Commit** any doc touch-ups (`docs: mark bold-combo engine delivered`).

---

## Self-Review

**1. Spec coverage:** spec §2 inputs (体彩+欧赔, no model) → Task 1 + Task 7 wiring. §3 five signals → Task 2. §3.5 day chaos value + jitter → Task 4 (chaos drives pool N). §4 leg selection + chaos-modulated combos → Task 3 (leg) + Task 5 (combos). §5 output: anchor + bold tickets, welded label, no 胜率/EV → Task 5 (anchor) + Task 6 (plan/label/renderer). §6 落地: new service + CLI → Task 6 + Task 7. §7 acceptance: label present, no-edge-words, no model import → Task 6 tests + Task 8. §8 范围外 (no prediction/calibration) → enforced by Task 8 Step 3. All covered.

**2. Placeholder scan:** No TBD/TODO. Signal formulas, dataclass fields, the `HARD_LABEL` text, the weight/gain/pool constants, and the no-edge-word list are all concrete. Constant *values* (`DRIFT_GAIN` etc.) are "documented default" — they are tunables; the plan fixes `POOL_MIN=4`/`POOL_MAX=10`/equal-0.2 weights as the defaults and the rest are named constants the implementer sets to a sensible documented default (this is a deliberate tunable, not a placeholder).

**3. Type consistency:** `MarketOdds` (extended with `opening_odds`/`per_book_odds`), `BoldLeg`, `BoldTicket`, `BoldComboPlan`, `HARD_LABEL` are named consistently across Tasks 1-7. `OUTCOMES = ("home","draw","away")` is the single outcome vocabulary throughout. Signal functions return `dict[str,float]` keyed by outcome (except `heat_score` → per-match `float`), consistent in Task 2 and consumed in Task 3.
