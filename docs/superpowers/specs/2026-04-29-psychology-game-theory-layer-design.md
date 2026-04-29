# Psychology & Game-Theory Layer — Design Spec

**Date**: 2026-04-29
**Status**: **SEALED v1.0 — 2026-04-29** (locked for implementation; changes require a follow-up spec)
**Owner**: jz71
**Related**:
- `nutmeg/services/value.py` (existing data-driven layer)
- `nutmeg/services/analysis.py` (existing tactical/odds analysis)
- `nutmeg/services/jczq.py` (existing parlay scheme builder)
- `nutmeg/services/daily_content.py` (per-match deep content)
- `nutmeg/services/operations.py` (`prediction-record` / `prediction-outcome`)

## 1. Motivation

The current Nutmeg prediction stack is data-driven: `ValueBoardService` computes
edge/Kelly fractions from market odds, `AnalysisService` adds tactical/odds
narrative, and `JczqMixedReportService` produces parlay schemes. On
2026-04-28 the Champions League SF1 prediction (PSG slightly favored, total
3–4 goals, score zone 2-1/1-1/2-2) diverged materially from the actual result
— a known failure mode of pure-market analysis when a tactical reset
(Kompany's compact 3-back vs PSG's high press) is not visible in the prior
data window.

We therefore add a parallel **Psychology & Game-Theory Layer** that produces
an independent verdict over the *same outcome space* (HHAD / handicap / total
goals) and is allowed, under guardrails, to **reverse** the data layer's pick.
A free-text **daily inspiration note** acts as the structured override gate
and is logged for later calibration.

## 2. Decisions Locked During Brainstorming

| # | Decision | Choice |
|---|---|---|
| 1 | Initial product scope | Shared engine; **JCZQ parlay first**, then back-fill into per-match deep analysis |
| 2 | Authority on conflict | **Full reversal allowed** (psychology layer can flip a leg) |
| 3 | v1 signal taxonomy | **b** Tournament-stage · **d** Contrarian-narrative · **g** Reflexive-tactic · **f** Personal-narrative |
| 4 | Role of "daily inspiration" | **Structured override gate + persisted for calibration** (`.nutmeg-data/inspiration/{date}/`) |
| 5 | External narrative sources | **Hybrid**: zhilio MCP (`get_today_hotlist` / `search_news` / `search_rss`) + self-hosted sports RSS aggregator |
| 6 | Guardrails | **v1**: BudgetGuard (≤1 reversal per scheme) + ConvictionGate (≥0.7). **v2**: rolling-calibration KillSwitch (auto-disable if 20-period hit-rate < baseline) |
| 7 | Output format | **Dashboard table + dual-scheme + decision section**, all in one markdown/PDF |

## 3. Architecture

```
        ┌────────────────────────────────────────────────────────────┐
        │              JCZQ Report / Per-match Deep Content          │
        │                  (consumers, existing)                     │
        └────────┬───────────────────────────────────┬───────────────┘
                 │ DataVerdict                        │ PsychologyVerdict
                 │                                    │
       ┌─────────▼──────────┐              ┌──────────▼─────────┐
       │ ValueBoard +       │              │ PsychologyEngine   │
       │ AnalysisService    │              │   (new)            │
       │ (existing)         │              └──────────┬─────────┘
       └─────────┬──────────┘                         │
                 │                  ┌─────────────────┼─────────────────┐
                 │                  │ b TournamentStage │ d ContrarianNarrative
                 │                  │ g ReflexiveTactic │ f PersonalNarrative
                 │                  │   (4 SignalProviders, parallel)   │
                 │                  └─────────────────┬─────────────────┘
                 │                                    │
                 ▼                                    ▼
       ┌──────────────────────────────────────────────────────────────┐
       │                    Reconciliator (new)                       │
       │  · GuardrailDecision: budget + threshold (v1)                │
       │                       + rolling calibration (v2)             │
       │  · InspirationParser: free-text note → structured tags       │
       │  · Output: DualSchemeReport (data + psy + final + dashboard) │
       └────────────────────────────┬─────────────────────────────────┘
                                    │
                                    ▼
                 ┌──────────────────────────────────────┐
                 │ Persistence + Calibration loop        │
                 │  .nutmeg-data/inspiration/{date}/    │
                 │  prediction-record / -outcome reuse  │
                 └──────────────────────────────────────┘
```

**Design principles**

- Data layer and psychology layer produce verdicts on the *same outcome
  space* and remain unaware of each other; the only place they meet is the
  Reconciliator.
- Guardrails and inspiration are consumed at the Reconciliator boundary —
  not inside individual providers.
- The 4 signals are independent `SignalProvider` instances, each
  individually disable-able and unit-testable. Adding a 5th signal
  (e.g. locker-room sentiment) is a new file under `signals/`, no engine
  change required.
- Persistence reuses the existing `prediction-record` / `prediction-outcome`
  closed loop rather than building a parallel one.

## 4. Components

### 4.1 Module layout

```
nutmeg/services/psychology/
  __init__.py
  schemas.py                # all dataclasses, no logic
  engine.py                 # PsychologyEngine — orchestrator
  reconciliator.py          # merges data + psychology verdicts, applies guardrails + inspiration
  inspiration.py            # InspirationParser — note text → structured tags
  guardrails.py             # BudgetGuard / ConvictionGate / (v2) CalibrationKillSwitch
  signals/
    base.py                 # SignalProvider Protocol + SignalReading
    tournament_stage.py     # b — pure rules
    contrarian_narrative.py # d — zhilio + RSS + LLM
    reflexive_tactic.py     # g — LLM reasoning over local tactics
    personal_narrative.py   # f — RSS + LLM
  sources/
    zhilio_provider.py      # zhilio MCP wrapper
    rss_provider.py         # self-hosted sports RSS aggregator
    news_cache.py           # 24h file cache
  calibration/
    recorder.py             # writes .nutmeg-data/inspiration/{date}/*.json
    review.py               # (v2) rolling hit-rate calc, psychology vs data baseline
```

### 4.2 Schemas (shape sketch)

```python
# nutmeg/services/psychology/schemas.py
@dataclass(frozen=True, slots=True)
class SignalReading:
    provider: str              # "tournament_stage" | "contrarian_narrative" | ...
    fixture_id: str
    market: str                # "HHAD" | "handicap" | "TTG"
    outcome_view: str | None   # e.g. "home_win" / "draw" / "away_win" / "over_3_5" / None if abstain
    conviction: float          # [0.0, 1.0]
    evidence: list[str]        # human-readable reasoning bullets
    source_refs: list[str]     # URLs / doc IDs / "rule:cup_first_leg_low_block"
    abstain_reason: str | None # if outcome_view is None

@dataclass(frozen=True, slots=True)
class PsychologyVerdict:
    fixture_id: str
    market_views: dict[str, OutcomeView]   # market → aggregated view
    conviction: float                       # overall [0,1]
    lean_direction: Literal["agree_data", "neutral", "diverge_data"]
    contributing_readings: list[SignalReading]

@dataclass(frozen=True, slots=True)
class OverrideCandidate:
    leg_id: str
    fixture_id: str
    market: str
    from_outcome: str          # data layer's pick
    to_outcome: str            # psychology layer's pick
    conviction: float
    reasoning: list[str]
    source_provider: str       # which signal drove this candidate

@dataclass(frozen=True, slots=True)
class GuardrailDecision:
    accepted: list[OverrideCandidate]
    rejected: list[tuple[OverrideCandidate, str]]   # (candidate, rejection_reason)
    guardrail_state: dict[str, str]                  # e.g. {"budget": "1/1", "kill_switch": "warming_up"}

@dataclass(frozen=True, slots=True)
class InspirationTags:
    lean: Literal["data", "psychology", "neutral"]   # which layer note favors
    conviction: Literal["low", "medium", "high"]      # parser-quantized
    focus: list[str]                                  # ["tournament_stage", ...] subset of provider names
    force_psychology: bool                            # bypass ConvictionGate flag
    force_data: bool                                  # force pure-data scheme

@dataclass(frozen=True, slots=True)
class InspirationNote:
    date: str                  # "2026-04-29"
    raw_text: str
    parsed_tags: InspirationTags
    parse_method: Literal["llm", "regex_fallback"]
    timestamp: str

@dataclass(frozen=True, slots=True)
class FinalScheme:
    legs: list[FinalLeg]       # each leg has provenance: "data" | "psychology" | "inspiration_forced"
    confidence: str
    notes: list[str]

@dataclass(frozen=True, slots=True)
class DualSchemeReport:
    data_scheme: Scheme
    psychology_scheme: Scheme
    final_scheme: FinalScheme
    dashboard_rows: list[DashboardRow]
    inspiration: InspirationNote | None
    guardrail: GuardrailDecision
```

### 4.3 Public interfaces

- `PsychologyEngine.evaluate(fixtures, snapshots, odds_snapshot) -> PsychologyVerdict[]`
- `Reconciliator.reconcile(data_verdict, psychology_verdict, inspiration) -> DualSchemeReport`
- `JczqMixedReportService.build_report(...)` — gains optional
  `psychology_engine` dependency; when absent, behaves exactly as today
  (feature-flagged off → zero behavior change). **v1 integration target.**
- `AnalysisService.analyze_match(...)` — same optional dependency.
  **v2 integration target** (per scope decision: JCZQ first, per-match
  deep content back-filled later).

### 4.4 New CLI commands

```
nutmeg psychology-inspect <fixture-id>      # v1 — debug: show 4 raw SignalReadings for a fixture
nutmeg inspiration-write [--date YYYYMMDD]  # v1 — opens $EDITOR, saves raw + parsed
nutmeg inspiration-show <date>              # v1 — prints note + parsed tags
nutmeg psychology-backtest --from <date> --to <date>   # v2 — replay historical verdicts
```

### 4.5 Signal provider responsibilities

| Provider | Input | Computation | External calls |
|---|---|---|---|
| `tournament_stage` | fixture metadata, season stage, leg #, head-to-head | Pure Python rules | none |
| `contrarian_narrative` | match keywords | zhilio + RSS fetch → LLM polarity extraction | zhilio MCP, RSS, LLM |
| `reflexive_tactic` | tactical snapshot from `AnalysisService` | LLM second-order reasoning prompt | LLM |
| `personal_narrative` | player/coach biographies, daily news | RSS keyword search + LLM tagging | RSS, LLM |

Each provider implements the same `SignalProvider` Protocol and is independently mockable. Engine reads which providers are enabled from config so any signal can be disabled to attribute alpha.

## 5. Data Flow (one trading day)

```
06:00  cron: data-driven morning run
       ValueBoardService + AnalysisService → DataVerdict
       → daily-content/{date}/data-verdict.json

10:00  cron: psychology layer morning run (independent of data flow)
       PsychologyEngine.evaluate(fixtures)
         ├─ tournament_stage   → SignalReading[]   (rules, ~50ms)
         ├─ contrarian_narr.   → zhilio + RSS in parallel → LLM polarity → SignalReading[]
         ├─ reflexive_tactic   → tactical snapshot → LLM → SignalReading[]
         └─ personal_narr.     → RSS keyword → LLM tag → SignalReading[]
       engine.reduce() → PsychologyVerdict per fixture
       → daily-content/{date}/psychology-verdict.json

14:00  human: write InspirationNote
       `nutmeg inspiration-write` → $EDITOR → 3-5 sentences in Chinese
       → .nutmeg-data/inspiration/{date}/raw.md
       InspirationParser auto-runs LLM → parsed.json
       (No note → reconciliator runs in default mode, guardrails only)

15:00  cron or manual: reconcile final scheme
       Reconciliator.reconcile(data_verdict, psy_verdict, inspiration)
         1. Collect every leg where psychology_view ≠ data_view → OverrideCandidate[]
         2. ConvictionGate filters candidates with conviction < threshold (default 0.7)
         3. BudgetGuard caps reversals (parlay length 3 → ≤1, length 4 → ≤1, single → ≤1)
         4. Apply inspiration tags:
              - lean=psychology + conviction=high → release highest-conviction candidate within budget
              - lean=data → force all-data scheme even if psychology passed gate
              - focus=<provider> → prioritize candidates from that provider
              - force_psychology=true → bypass ConvictionGate (BudgetGuard still applies)
         5. (v2) CalibrationKillSwitch: if last 20 periods psychology hit-rate < baseline → silent
       → DualSchemeReport: data_scheme + psychology_scheme + final_scheme + dashboard

15:30  render
       JczqMixedReportService renders D layout: dashboard table + dual-scheme + decision section
       → markdown + PDF

T+1    settlement
       prediction-outcome records actual results, recorder appends per-leg
       provenance hit/miss → feeds calibration loop (v2)
```

## 6. Error Handling & Failure Modes

| Failure | Mitigation |
|---|---|
| zhilio MCP unavailable | `news_cache.py` 24h cache; if empty, contrarian_narr provider returns abstain reading; reconciliator excludes from candidate set |
| RSS source timeout / parse failure | Per-source isolation; full RSS outage → same abstain path |
| LLM call failure / rate limit | Existing `nutmeg.agents.llm_provider` retry/timeout; on exhaustion the affected provider degrades to abstain reading; `reflexive_tactic` failure disables that signal for the day, never blocks engine |
| Inspiration LLM parse failure | Fallback to regex over Chinese keywords (lean/conviction/focus); always produces tags, possibly coarse |
| Data layer verdict missing | Psychology layer cannot run alone; reconciliator raises `IncompatibleVerdictError`, CLI exits 2 |
| All 4 signals degrade simultaneously | PsychologyVerdict empty → DualSchemeReport collapses to single (data) scheme; dashboard prints "psychology layer unavailable today" |
| Inspiration over-claims (force_psychology + 3 reversals on 3-leg parlay) | BudgetGuard rejects extras; decision section explicitly lists rejected candidates with reasons |
| Cold start (v2 KillSwitch < 20 samples) | KillSwitch state = `warming_up`; doesn't gate anything, recorder keeps accumulating |
| No JCZQ matches today / no data candidate | Skip psychology layer entirely (saves LLM cost) |

**Core principle**: psychology-layer failures **degrade, never block**. Data layer is always the fallback.

## 7. Testing Strategy

### Unit (pytest, no external IO)

```
tests/services/psychology/
  test_tournament_stage.py     # rules: first/second leg, KO/group, must-win
  test_contrarian_narrative.py # mock zhilio + RSS + LLM; reverse-polarity logic
  test_reflexive_tactic.py     # mock LLM; second-order prompt + output schema
  test_personal_narrative.py   # mock RSS + LLM; story-line extraction
  test_inspiration_parser.py   # real Chinese fixtures → expected tags (incl. fuzzy)
  test_guardrails.py           # BudgetGuard / ConvictionGate edges; cold-start kill switch
  test_reconciliator.py        # 6 scenarios: pure-data / psy-override / inspiration-force /
                               #              all-degrade / budget-overflow / conflict
  test_engine.py               # parallel scheduling + reduce
  test_recorder.py             # persistence schema + hit-rate back-fill
```

### Integration

- `tests/integration/test_psychology_jczq_integration.py`: real fixture
  (yesterday's PSG vs Bayern snapshot + actual result) end-to-end; asserts
  dashboard / dual-scheme / final-scheme provenance compliance
- `tests/integration/test_inspiration_lifecycle.py`: write note → parse →
  reconcile → record → review

### Regression baseline

- Lock a "psychology disabled vs enabled" pair on v1 completion day; ensure
  `psychology_disabled.final_scheme ≡ data_scheme` (feature flag off path
  untouched)
- Existing 343-passing pytest baseline must not regress; add ~50–80 tests;
  total suite < 60s

### Backtest (v2)

- `nutmeg psychology-backtest --from 2026-04-15 --to 2026-04-28`: replay
  historical verdicts + real outcomes through psychology + reconciliator,
  output "would have won/lost X EV"
- No look-ahead; replays only persisted verdicts; used to calibrate
  ConvictionGate threshold

## 8. Phased Delivery

**v1** (target: ~5–7 dev days)
- All 4 signal providers (tournament_stage in pure-rule form, others with mockable LLM seams)
- PsychologyEngine, Reconciliator, InspirationParser
- BudgetGuard + ConvictionGate (no rolling calibration yet)
- 3 new CLI commands (inspect / inspiration-write / inspiration-show)
- Wired into `JczqMixedReportService` only (per scope decision: JCZQ first)
- D-layout report (dashboard + dual + decision)
- Recorder writing `.nutmeg-data/inspiration/{date}/` JSON

**v2** (after ~20 production samples accumulated)
- CalibrationKillSwitch (rolling hit-rate)
- `psychology-backtest` CLI
- Wire into `AnalysisService` per-match deep content (back-fill scope)

**v3** (optional, when needed)
- Add 5th/6th signal classes (a bookmaker game-theory, c locker-room, e venue)
- Web/Telegram surfacing of dashboard

## 9. Out of Scope

- Live in-play reactions (this is a pre-match layer only)
- Cross-sport generalization (football / JCZQ only in v1)
- Automatic news source discovery (RSS list curated manually)
- Replacing existing data layer (psychology is *additional*, not a swap)
- Tying inspiration into stake sizing (v1 only flips picks, not stakes)

## 10. Open Questions (deferred)

- Exact ConvictionGate threshold (0.7 is initial guess; v2 backtest will tune)
- Whether `personal_narrative` should maintain stateful player/coach
  story-arc memory across days (v1 stateless; revisit if stories span weeks)
- Whether to expose dashboard via existing client/web surface (deferred to v3)
