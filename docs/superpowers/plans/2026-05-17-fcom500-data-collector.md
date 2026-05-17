# 500.com Data Collector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A 500.com-based market-odds collector that replaces API-Football as the conflict engine's data source — quota-free, ~100% JCZQ coverage by matching on the 竞彩 number.

**Architecture:** A new `nutmeg/data/fcom500.py` fetches and parses 500.com pages (static HTML, gb2312-encoded) into per-JCZQ-match `Fixture` + `OddsSnapshot` objects covering 4 markets. The conflict engine (`ValueBoardService`) and everything downstream are unchanged — only the odds source is swapped. Scraping work is recon-driven: each parser task begins by recording a real page as a test fixture, then is built TDD against that fixture.

**Tech Stack:** Python 3.13, `uv run pytest`, an HTTP client (`tls_requests`/`httpx` — match the existing soccerdata stack), HTML parsing (stdlib `html.parser` or `lxml` if already a dep — confirm in Task A1).

**Spec:** `docs/superpowers/specs/2026-05-17-fcom500-data-collector-design.md`

---

## Reconnaissance findings (2026-05-17, pre-plan)

- `odds.500.com` and `trade.500.com/jczq/` both serve **static HTML, gb2312-encoded** (`curl` → HTTP 200, ~184 KB; no JS rendering needed). The collector must decode gb2312.
- `odds.500.com`: each match is a `<tr data-fid="NNNNN" data-cid="..." data-mid="...">`; `data-fid` is 500.com's internal match id; odds cells are `<td class="border_r_c5">`.
- The 竞彩 number (周日NNN / 001-034) lives on the 竞彩 page `trade.500.com/jczq/`; the international 欧赔 is on `odds.500.com` keyed by `data-fid`. **The join (竞彩号 ↔ data-fid) must be established in Task A1** — the 竞彩 page links to each match's detail/欧赔 pages.
- Per-match analysis sub-pages: `odds.500.com/fenxi/ouzhi-[fid].shtml` (欧赔), and 比分 / 总进球 analysis pages.

## File Structure

- `nutmeg/data/fcom500.py` — **create**: the collector. `Fcom500Client` (fetch+decode), the per-page parsers, `Fcom500OddsProvider` (assembles per-JCZQ-match `Fixture`+`OddsSnapshot`).
- `nutmeg/services/jczq_value_wiring.py` — **modify**: wire `Fcom500OddsProvider` as the conflict engine's odds source (API-Football path kept as fallback).
- `nutmeg/services/fixture_snapshot*.py` (or wherever `FixtureSnapshotService` lives) — **modify (Stage B)**: degrade to soccerdata-only when API-Football is unavailable.
- `tests/fixtures/fcom500/` — **create**: recorded real 500.com HTML pages (gb2312-decoded to UTF-8), the test corpus.
- `tests/test_fcom500.py` — **create**: parser + provider unit tests.
- `tests/test_daily_pipeline_acceptance.py` — **modify**: an end-to-end case through the 500.com provider.

---

## Stage A — Fcom500OddsProvider

### Task A1: Reconnaissance — record real pages, document structure

**Files:**
- Create: `tests/fixtures/fcom500/` (recorded HTML), `docs/superpowers/notes/fcom500-page-structure.md` (the structure note)

- [ ] **Step 1: Record the live pages**

`curl` (UA `Mozilla/5.0`, `iconv -f gb2312 -t utf-8`) and save to `tests/fixtures/fcom500/`:
- `trade.500.com/jczq/` → `jczq-list.html` (the 竞彩 match list — 周日NNN numbers)
- `odds.500.com/` → `odds-list.html`
- for **2 real matches** picked from the list: their 欧赔 page `ouzhi-[fid].html`, 让球/亚盘 page, 总进球 page, 比分 page.

- [ ] **Step 2: Document the structure**

Write `docs/superpowers/notes/fcom500-page-structure.md`: for each recorded page — the CSS/DOM path to (a) the 竞彩 number, (b) team names + league, (c) the join key between 竞彩号 and `data-fid`, (d) each market's odds table and cells. This note is the contract the parser tasks build against.

- [ ] **Step 3: Confirm the §4 ⚠️ items**

In the structure note, explicitly state for `total_goals` and `correct_score`: does 500.com expose **international** odds (independent of 体彩), or only 竞彩 odds? Record the verdict — it determines whether those markets are true conflict signals or flagged "model-vs-体彩" weak signals (per spec §4).

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/fcom500/ docs/superpowers/notes/fcom500-page-structure.md
git commit -m "chore(fcom500): record 500.com page fixtures + structure note"
```

### Task A2: Fetch+decode client

**Files:** Create `nutmeg/data/fcom500.py` (the `Fcom500Client`), `tests/test_fcom500.py`

- [ ] **Step 1: Write the failing test** — `Fcom500Client.get(path)` returns UTF-8 text; gb2312 decoding is handled; an injected fake transport returns recorded bytes (no live network). Test asserts a known Chinese string from a recorded fixture is decoded correctly.
- [ ] **Step 2: Run it — fails (module/class absent).**
- [ ] **Step 3: Implement** `Fcom500Client`: an HTTP client wrapper (UA, timeout, gb2312→UTF-8 decode, optional per-(url,date) in-memory cache). Transport injectable for tests.
- [ ] **Step 4: Run — passes.**
- [ ] **Step 5: Commit** (`feat(fcom500): gb2312-decoding fetch client`).

### Task A3: Parse the 竞彩 match list

**Files:** `nutmeg/data/fcom500.py`, `tests/test_fcom500.py`, uses `tests/fixtures/fcom500/jczq-list.html`

- [ ] **Step 1: Write the failing test** — `parse_jczq_list(html)` over the recorded `jczq-list.html` returns one record per match: 竞彩号 (周日NNN), home/away team, league, kickoff, and the join key to the 欧赔 detail (`data-fid` or detail URL). Assert count and a couple of known matches.
- [ ] **Step 2: Run — fails.**
- [ ] **Step 3: Implement** `parse_jczq_list` per the Task A1 structure note.
- [ ] **Step 4: Run — passes.**
- [ ] **Step 5: Commit** (`feat(fcom500): parse the 竞彩 match list`).

### Task A4: Parse 欧赔 (1X2 international odds)

**Files:** `nutmeg/data/fcom500.py`, `tests/test_fcom500.py`, uses recorded `ouzhi-*.html`

- [ ] **Step 1: Write the failing test** — `parse_european_1x2(html)` returns home/draw/away odds and the de-vigged `fair_probability` for each. Assert against the recorded fixture's known values.
- [ ] **Step 2: Run — fails.**
- [ ] **Step 3: Implement** the parser + de-vig (fair probability = (1/odds) normalized to sum 1, consistent with how `OutcomeOddsSnapshot.fair_probability` is produced elsewhere).
- [ ] **Step 4: Run — passes.**
- [ ] **Step 5: Commit** (`feat(fcom500): parse 1X2 European odds`).

### Task A5: Parse 让球 (handicap)

**Files:** `nutmeg/data/fcom500.py`, `tests/test_fcom500.py`

- [ ] **Step 1: Write the failing test** — `parse_handicap(html)` returns the handicap line + home/draw/away odds + fair probabilities, against the recorded fixture.
- [ ] **Step 2: Run — fails. Step 3: Implement. Step 4: Run — passes.**
- [ ] **Step 5: Commit** (`feat(fcom500): parse handicap odds`).

### Task A6: Parse 总进球 + 比分

**Files:** `nutmeg/data/fcom500.py`, `tests/test_fcom500.py`

- [ ] **Step 1: Write the failing tests** — `parse_total_goals(html)` and `parse_correct_score(html)` return per-outcome odds + fair probabilities, against recorded fixtures. Honour the Task A1 §4 verdict: if only 体彩 odds exist for a market, the parser still returns them but tags `independent=False`.
- [ ] **Step 2: Run — fails. Step 3: Implement. Step 4: Run — passes.**
- [ ] **Step 5: Commit** (`feat(fcom500): parse total-goals and correct-score odds`).

### Task A7: Fcom500OddsProvider — assemble per-match Fixture + OddsSnapshot

**Files:** `nutmeg/data/fcom500.py`, `tests/test_fcom500.py`

- [ ] **Step 1: Write the failing test** — `Fcom500OddsProvider.collect(run_date)` (fed recorded fixtures via the injected client) returns, per JCZQ match, a synthetic `Fixture` (id `fcom500:周日NNN`, teams/league/date) + an `OddsSnapshot` whose `markets` cover `match_winner`/`handicap`/`total_goals`/`correct_score` with `OutcomeOddsSnapshot.fair_probability` set. Assert shape, JCZQ-number keying, and graceful degradation when a market page is missing.
- [ ] **Step 2: Run — fails. Step 3: Implement.** Compose A3-A6; map each market to `MarketOddsSnapshot`/`OutcomeOddsSnapshot` using the exact outcome keys the conflict engine expects (`home`/`draw`/`away`, `total_N`, `score_H_A`, `handicap_home_*` — confirm against `nutmeg/services/value.py` `_market_probabilities` + `OddsSnapshot`).
- [ ] **Step 4: Run — passes.**
- [ ] **Step 5: Commit** (`feat(fcom500): Fcom500OddsProvider assembles per-match odds snapshots`).

### Task A8: Wire into the conflict engine

**Files:** `nutmeg/services/jczq_value_wiring.py`, `tests/test_jczq_value_wiring.py`, `tests/test_daily_pipeline_acceptance.py`

- [ ] **Step 1: Write the failing test** — the JCZQ value bridge, given a 500.com-backed odds source, produces conflicts for matches keyed by 竞彩 number with NO API-Football call and NO alias-table alignment.
- [ ] **Step 2: Run — fails.**
- [ ] **Step 3: Implement** — add a 500.com path to `build_jczq_value_bridge`: when enabled, the bridge consumes `Fcom500OddsProvider`'s `Fixture`+`OddsSnapshot` directly (by 竞彩 number) instead of `MatchAligner`→API-Football. API-Football path stays as fallback. The model side still calls `snapshot_service` (soccerdata) — unchanged here (Stage B makes it API-Football-free).
- [ ] **Step 4: Run — passes; add an end-to-end case to `test_daily_pipeline_acceptance.py`.**
- [ ] **Step 5: Commit** (`feat(jczq): conflict engine consumes the 500.com odds source`).

---

## Stage B — model snapshot API-Football independence

### Task B1: Snapshot degrades to soccerdata-only

**Files:** the `FixtureSnapshotService` module + its test

- [ ] **Step 1: Write the failing test** — `build_snapshot` with an API-Football client that raises (simulating quota exhaustion) still returns a snapshot whose `matchup.home_trend`/`away_trend` (soccerdata) are populated, so `expected_goals_from_snapshot` succeeds. Currently it raises.
- [ ] **Step 2: Run — fails.**
- [ ] **Step 3: Implement** — wrap the API-Football-sourced enrichment so its failure degrades that section to `None` rather than aborting the whole snapshot; the soccerdata-sourced `matchup` trends remain. Record a warning.
- [ ] **Step 4: Run — passes; full suite `uv run pytest tests/ -q` green.**
- [ ] **Step 5: Commit** (`fix(snapshot): degrade to soccerdata-only when API-Football is unavailable`).

---

## Self-Review

**1. Spec coverage:** spec §3 architecture → Tasks A2-A8. spec §4 four markets → A4 (1X2), A5 (handicap), A6 (total/score) + the A1 §3 independence verdict. spec §5 fetch/robustness/graceful-degradation → A2 (client) + degradation asserts in A7. spec §6 Stage A → Tasks A*, Stage B → Task B1. spec §8 TDD-with-recorded-fixtures → A1 records fixtures, every parser task tests against them. spec §9 acceptance → A8 end-to-end. All covered.

**2. Placeholder scan:** The parser tasks (A3-A6) intentionally say "parse per the Task A1 structure note" rather than literal selectors — this is honest and unavoidable for scraping work: the real DOM is only known after A1's recon. Every such task still has a concrete failing-test-first contract (what the function returns, asserted against a recorded fixture). This is a deliberate recon-driven structure, not vague placeholders.

**3. Type consistency:** `Fcom500Client`, `Fcom500OddsProvider`, `parse_jczq_list`/`parse_european_1x2`/`parse_handicap`/`parse_total_goals`/`parse_correct_score` are named consistently across tasks. Output types are the existing `Fixture` + `OddsSnapshot`/`MarketOddsSnapshot`/`OutcomeOddsSnapshot` (domain types A7 maps onto) — confirmed against the spec; A7 Step 3 explicitly cross-checks the outcome-key vocabulary against `nutmeg/services/value.py`.
