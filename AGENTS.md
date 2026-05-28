<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan:
`.specify/specs/046-jczq-mixed-parlay-report-v0/plan.md`
<!-- SPECKIT END -->

## OpenClaw / Nutmeg Project Codex Mode

When this repository is reached through OpenClaw `nutmegbot`, treat the bot as a
project-level Codex entrypoint opened at `/Users/jz71/Projects/Nutmeg`.

- `nutmegbot` is no longer limited to the legacy Telegram safe router.
- It may read and edit project files, run tests/builds, call `uv run nutmeg ...`,
  use `scripts/openclaw/nutmeg_command_router.py`, and inspect project state.
- For implementation, debugging, review, refactor, verification, or multi-step
  analysis, it should behave like Codex in this repo root and can delegate to
  the fixed local Codex CLI when invoked from OpenClaw.
- The OpenClaw `coding-agent` skill is enabled for background worker delegation;
  default project execution still uses the fixed NVM Codex CLI.
- The router remains a deterministic helper for Telegram-friendly football
  command output; it is not the boundary for project work.
- Do not leak secrets. Ask once before public dispatch, real betting/funds
  actions, large destructive deletes, or irreversible system-level operations.

## JCZQ Daily Decision SOP

This project ships a complete daily-betting analysis pipeline for Chinese Sports
Lottery 竞彩足球 (JCZQ). Whenever a user asks for "today's plan" in this repo,
follow the SOP below — do not ask them to run scripts manually.

### Trigger phrases (any of these → execute the full SOP)

- "今天的 jczq 方案"
- "今天的方案"
- "今天竞彩怎么打"
- "出 5 张票"
- "做今天的投资建议"
- "today's jczq plan" / "today's bets"

### Execution order

The agent (you) handles the daily brief, workspace update, and ticket output;
the user only types one trigger phrase. Do not stop after Step 1 to ask
permission — keep going through the workspace write and ticket output unless
the brief reveals a fatal data gap.

#### Step 1: Generate the daily brief

```bash
uv run nutmeg jczq-daily-brief \
  --write .nutmeg-data/jczq/daily/$(date +%Y-%m-%d)/brief.md
```

Optional flags:
- `--date YYYY-MM-DD` — run live for a specific date
- `--replay YYYY-MM-DD` — replay from saved `context.json` (no Sporttery
  request); use this when network access is unavailable
- omit `--write` to dump to stdout

Brief contents (the script emits ~95 lines of structured Markdown):
1. Today's selling matches + role/bucket flags (强胆 / 舒服盘 / draw_friendly)
2. HAD pool implied probabilities + EV gap vs league prior
3. Bucket counts (decides whether `draw_cluster` / `upset_cluster` plans fire)
4. **Poisson +EV legs (edge ≥ +5%, sorted by edge)** — the highest-signal
   section; treat these legs as the foundation for the inspiration ticket
5. Generator's auto-tickets, with legs that Poisson strongly opposes
   (edge ≤ -20%) flagged
6. The prompt template the agent should follow

#### Step 2: Read the brief yourself

Use the Read tool on the brief.md path. Do not ask the user to paste it.

The brief now includes machine-checked sections you must consume before
forming opinions:

- **Section 5b — 规则误伤的 +EV 候选**: surfaces hafu/blocked legs whose
  Poisson edge crosses the watch threshold. Flag in your analysis if a hafu
  +EV pick exists; never override Rule H without ≥30 days of data.
- **Section 7a — 叙事多样性矩阵**: per-plan dominant narrative tag +
  diversity index. If `warning` is non-null (≥3 plans share a narrative),
  call this out explicitly in the analysis — that's exactly the
  single-signal failure pattern 5/06 hit.
- **Section 7b — 跨票场次集中度**: any match with budget exposure > 40% is
  flagged. Do not push that match further (e.g. don't string the单核 with
  it) without explicit human approval.
- **Section 7c — Poisson 单核 Kelly 建议**: shows current vs Half-Kelly.
  If `over_kelly_multiple > 2`, mention this in your "最看好" section so
  the human knows they're already重仓 the alpha.

#### Step 2.4: Data verification discipline (MANDATORY — 5/06 嘴算 bug 教训)

Any claim about Poisson edge / EV / hit-rate / leg correlation must come
from one of:

1. The brief's Section 4 (+EV legs) or Section 5 (rejected legs).
2. A direct call to `compute_poisson_edges` — example one-liner:
   ```python
   from nutmeg.services.jczq_intelligence import compute_poisson_edges, poisson_edge_index
   idx = poisson_edge_index(compute_poisson_edges(matches))
   idx[("周三007", "ttg", "4球")]  # → exact edge
   ```
3. The diagnostic helpers in `nutmeg.services.jczq_diagnostics`:
   `compute_kelly_advice`, `compute_match_concentration`,
   `find_safe_second_legs`.

**Never嘴算 ("按 1.52 主胜推算 home_λ ≈ 1.7 → ttg 4球 概率 ~14% → ...")**.
On 2026-05-06 Claude嘴算 ttg 4球 edge ≈ -40%; the actual edge was -16.4%
— the推算 was off by 24pp and led to a wrong "强烈反对" recommendation.

For串关 / 2串1 / second-leg suggestions, **always** run:
```bash
uv run nutmeg jczq-second-leg --date today --auto --top 8
```
This auto-loads the current `final-plan.json` and flags reverse-cover legs
(e.g. `001 主胜` when main pushes `001 平`) deterministically.

#### Step 2.5: Update the debate workspace

Every daily plan run must also update the local debate workspace so GPT,
Claude, and the human operator can compare independent judgments from the same
frozen input.

Initialize the workspace:

```bash
uv run nutmeg jczq-debate-init \
  --date today --output-dir .nutmeg-data/jczq --format json
```

Then read:

```text
.nutmeg-data/jczq/daily/$(date +%Y-%m-%d)/debate/shared-brief.md
```

If you are acting as GPT/Codex, write your complete independent analysis to:

```text
.nutmeg-data/jczq/daily/$(date +%Y-%m-%d)/debate/gpt-analysis.md
```

Use the template already in that file. Do not only answer in chat; the file is
the durable record used for review. If the user provides Claude's analysis,
save it to:

```text
.nutmeg-data/jczq/daily/$(date +%Y-%m-%d)/debate/claude-analysis.md
```

When both `gpt-analysis.md` and `claude-analysis.md` contain substantive
analysis, run:

```bash
uv run nutmeg jczq-debate-compare \
  --date today --output-dir .nutmeg-data/jczq --format json
```

This writes `disagreements.md`. Do **not** overwrite `human-notes.md`,
`final-plan.md`, or `final-plan.json` unless the user explicitly asks to
finalize after human review.

#### Step 3: Output 4-5 tickets in this exact format

Tickets, ordered safest → wildest. All numeric odds come from the brief
or the generator output — never invent odds.

- **A 稳健底仓 (~2-4x)** — 2-3 had/hhad legs priced **strictly above 1.40**
  (Rule B). No 1.24/1.34 chalk dumps as bankers anymore. hhad 让球 covers
  have anchored every winning day 5/13-5/15 — prefer them over straight had.
- **B 主方案 (~30-150x)** — mix of mid-priced had legs (>1.40), 让球 covers,
  and ttg medium-line picks. Avoid hafu (R27). Skip any match flagged
  ⚠coinflip from had pool (Rule E).
- **D 反大众盘口 (~80-200x)** — total goals + 让平 across draw_friendly /
  contrarian matches.
- **E 极限娱乐 (~1000-100000x)** — score-line lottery, tiny stake.

> **C Poisson 单核灵感票 retired (R28, 5/16).** The standalone "highest model
> edge, solo" ticket went 1/11 days / leg-hit 12.5% / realized -47.7% over
> 5/01-5/15. Do **not** reconstruct it. Model alpha (brief Section 4 edge
> ≥ +15%) is analysis evidence only — route it into B/D legs, never a票.

Stake allocation against a 100¥ entertainment budget:
**35 / 35 / 20 / 10** (A/B/D/E). A carries the biggest anchor allocation —
its hhad 让球 base has hit 3 days running.

Always mark which ticket the agent itself would back hardest, and why.

### Hard rules (Rules A-J encoded in the generator since 2026-05-05/06)

1. **Rule A — Poisson +EV ≥ +15% (poisson_solo ticket RETIRED by R28).**
   Brief Section 4 still lists every leg with edge ≥ +15% as analysis
   evidence. The generator no longer emits a standalone `poisson_solo`
   ticket — R28 (5/16) retired it after 1/11-day / 12.5%-leg / -47.7%
   realized performance. Route model alpha into B/D legs instead.
2. **Rule B — had ≤ 1.40 banned from stable_base / main / poisson_solo.**
   Strong-favorite chalk has empirically been a chalk-dump trap; require
   `odds > 1.40` for any banker-style leg.
3. **Rule C — high-volatility leagues downgrade low-side ttg picks.** When
   a league's rolling oracle ttg median ≥ 2.7, ttg picks of 0/1/2球 get a
   −0.5 score penalty. Brief Section 1 marks these matches with ⚠hi-vol.
4. **Rule D — hhad legs require an explicit handicap line.** Brief Section
   1 shows the goal_line column. Any hhad leg without it is dropped from
   selection (the 让胜/让平/让负 label semantics depend on the handicap).
5. **Rule E — three-way coin-flip matches: had pool excluded.** Marker
   ⚠coinflip = vig > 12.5% AND max(implied)−min(implied) < 10pp. These
   matches are forbidden from had-leg selection across all plans (hhad/
   ttg/crs still allowed).
6. **Rule F — burned teams from the previous review get −0.5 bias.**
   Strategy memory persists `decision_policy.reuse_guard.burned_teams`;
   if those teams reappear, every pick involving them loses score.
7. **Drop any leg that Poisson strongly opposes** (edge ≤ -20%). The
   generator already filters them, but verify in brief Section 5 before
   publishing.
8. **Rule H — hafu legs locked to the extreme ticket.** 4-day backtest hit
   0/9 across every non-extreme plan kind. The generator strips hafu from
   stable_base / main / inspiration / contrarian / false_signal / draw_cluster
   and replaces with the equivalent ttg or hhad pick. Only `extreme` keeps
   hafu candidates.
9. **Rule I-1 — high-odds had legs need Poisson EV.** had legs with odds
   ≥ 5.0 are dropped from `inspiration` unless their Poisson edge ≥ +5%.
   Catches "傻冷" leverage attempts that the heuristic scorer used to favor.
10. **Rule I-2 — contrarian rejects strongly-opposed legs.** Any priced
    leg (had/ttg/crs/hafu) with Poisson edge ≤ -15% is excluded from
    `contrarian`. Caught 5/05's `周二003 ttg 4球@5.8` (-22.5% edge) trap.
11. **Rule J — extreme crs needs Poisson support.** crs picks must clear
    edge ≥ -10%. Backtest crs hit 1/14 (7.1%); the surviving picks are now
    aligned with the joint Poisson scoreline distribution.
12. **R17 — poisson_solo collapses on low_goals narrative concentration.**
    When the 2 chosen legs are BOTH "low_goals" picks (ttg 0/1/2球 or crs
    0:0/0:1/1:0) AND any leg's expected_goals ≥ 2.3, the ticket drops to
    a single leg (keeping the highest-edge one). 5/11 C 票 007 0:0 (λ=1.9)
    × 001 ttg 1球 (λ=2.5) failure case: joint hit ≈3% even at +EV.
13. **R18 — extreme cap at 1 low_goals crs leg.** At most one crs pick in
    {0:0, 0:1, 1:0} per extreme ticket; extras dropped by lowest edge.
    5/11 E 票 001 0:0 × 007 0:1 × 009 0:0 (all "low scoring" macro bet
    packaged as 3 legs).
14. **R19 — contrarian/main hhad 让平 needs Poisson agreement.** hhad 让平
    legs need Poisson edge ≥ -5% (tighter than R7.1's -10% hhad floor).
    Catches the "draw_friendly bucket vs Poisson verdict contradiction"
    zone (5/11 007 hhad 让平 @4.10 was bucket-tagged draw_friendly but
    Poisson said -6.6%).
15. **R20 — stable_base had favorites need Poisson edge ≥ -10%.** Rule B
    (1.50 odds floor) is necessary but not sufficient; 1.50-1.70 chalk
    favorites with Poisson edge ≤ -10% also lose ("market priced beyond
    fair"). 5/11 005 had 胜 @1.60 (-10.56%) + 006 had 胜 @1.60 (-10.01%)
    both made A and both lost.
16. **R21 — main had legs need Poisson edge ≥ -10%.** Same threshold as R20,
    extended to main ticket; 5/12 main had three -10% had legs landed via
    luck (1/3 hit). Applied at `_select_leg` so main slot collapses to None
    if no eligible candidate.
17. **R22 — hi-vol crs low_goals hard reject.** Crs picks {0:0, 0:1, 1:0}
    in hi-vol leagues (HIGH_VOL_LEAGUE_OVERRIDE or league_volatility ≥ 2.7)
    are blocked from `poisson_solo`; hi-vol+coinflip 双标场 also blocked
    from `select_top_legs` (extreme/inspiration/contrarian/false_signal).
    5/13 D 票 004 (西甲 hi-vol+coinflip) Codex-driven 0:0 alpha lost 15 元.
18. **R23 — crs 0:0 needs Poisson edge ≥ +25% to enter poisson_solo.**
    10-day aggregate hit rate 1/16 = 6.25% (vs implied 8-15%). Other crs
    picks (0:1/1:0) and ttg/had/hhad/hafu still use the +15% default.
    5/13 005 crs 0:0 +40.4% would still pass; 5/12 006 crs 0:0 +16.3% no.
19. **R24 — Poisson 单核 cooling-off.** When the last 3 poisson_solo plans
    all missed (per `recent_plan_results` in strategy memory), the next
    poisson_solo is hard-capped to 1 leg regardless of how many +EV rows
    qualify. 5/11+5/12+5/13 cumulative 70 元 alpha 0 中. Plan description
    surfaces the cooling-off note for transparency.
20. **R25 — Per-league ttg/crs Poisson residual bias.** When a league has
    ≥ 5 ttg/crs `poisson_residuals` samples with average goal_residual > 0
    (model systematically under-prices goals), all subsequent ttg/crs
    Poisson edges in that league get a -0.10 shift. 5/13 法甲 (7 samples,
    all-miss across 5/10/5/12/5/13) was the canonical trigger.
21. **F2 — Empirical alpha decay (model-layer).** Per-(pool, pick) decay
    factor multiplied into Poisson edge. 10-day aggregate hit rate vs
    baseline implied probability: actual ≥ baseline × 0.95 → no decay;
    else `decay = max(0.5, actual/baseline)`. Baseline table: crs 0:0/1:0
    = 10%, crs 0:1 = 8%, ttg 0球 = 10%, ttg 1球 = 22%. 5/14 first day:
    crs 0:0 实测 1/16 = 6.25% → decay 0.625; +36.1% alpha → +22.6% raw,
    then R25 stacks → +12.6% effective. F2 + R25 联合让 5/14 C 票 (poisson_solo)
    整张消失（alpha 全部衰减到 < +15% / +25% 阈值）。
22. **F3 — Daily alpha concentration warning (meta-rule).** Detects on RAW
    alpha (pre-bias): when ≥ DAILY_CONCENTRATION_TRIGGER_COUNT (3) distinct
    matches show ≥ DAILY_CONCENTRATION_ALPHA_THRESHOLD (+15%) alpha all in
    LOW_GOALS_PICKS direction (crs 0:0/0:1/1:0 + ttg 0球/1球), apply
    DAILY_CONCENTRATION_DECAY (0.9) multiplier to all matching legs ON TOP
    of F2. Implementation requires 2-pass `compute_poisson_edges` call:
    raw → detect F3 → final with all biases. Brief renders 🟦 banner above
    Section 4 when triggered. 5/14 first day: 3 distinct low_goals matches
    (004/001/003) trigger; final stack 004 crs 0:0 +14.7%, 001 +10.5%, all
    < poisson_solo +15% threshold.
23. **F1 — Dixon-Coles low-score correction (model-layer, opt-in).** Adds
    `_dixon_coles_tau(h, a, lam_h, lam_a, rho)` correction to (0,0)/(0,1)/
    (1,0)/(1,1) entries in `build_score_grid`. `dc_rho > 0` deflates 0:0/1:1
    (JCZQ use case where 0:0 over-priced); `dc_rho < 0` inflates them
    (textbook D-C for European football); `dc_rho = 0.0` (default) = F1
    disabled. Read from `strategy_memory["dixon_coles_rho"]` via
    `get_dixon_coles_rho(memory)`; propagated through `fit_lambdas_from_market`
    / `fair_odds_hhad` / `edge_vs_market` / `compute_poisson_edges`. Grid
    renormalized after tau correction. 5/14 ships disabled — operator opts
    in after backtest validates rho value.
24. **F4 — ttg-over-crs same-match alpha preference (strategy-layer).** When
    same-match has both ttg and crs alpha candidates, `select_preferred_alpha_per_match`
    prefers ttg unless `crs.edge - ttg.edge >= F4_DOMINANCE_THRESHOLD (+0.10)`.
    Applied in `_build_poisson_solo_plan` after R22/R23/R13 filtering. Reduces
    crs 9-way fine-split exposure in favor of ttg's coarser-but-more-stable
    0/1/2/3+ buckets. Compatible with Rule O (one leg per match per ticket);
    F4 is the policy for *which* alpha row surfaces.
25. **R26 — crs pool blocked from poisson_solo (5/15).** 5/01-5/14 aggregate:
    crs leg-hit 1/30 (3.3%); 0:0 1/17, 1:0 0/6, 0:1 0/2. Even after R23 (+25%
    0:0 floor) the 5/14 case (004 crs 0:0 adjusted edge +36.1% λ=2.4) passed
    and missed (实际 1:1). Poisson 在 score-grid 单点上 systematically miscalibrated.
    poisson_solo 仅接受 ttg/had/hhad alpha；crs 仍可由 inspiration/extreme 通过
    `select_top_legs` 选用，其中 R22 (hi-vol)、R23 (+25% 0:0 floor) 仍生效。
    Implementation: `_build_poisson_solo_plan` eligibility filter excludes
    `pool == "crs"` when `RULE_R26_DROP_CRS_FROM_POISSON_SOLO = True`.
26. **R27 — hafu pool fully blocked (5/15).** Rule H 升级版。5/01-5/14: hafu
    legs 0/18 across all plan kinds (incl. 0/8 in extreme); every ticket
    containing any hafu leg failed integer-hit (0/18). Original Rule H
    quarantined hafu to extreme as "entertainment lottery still allowed" —
    data shows the carve-out is dead weight. `_apply_rule_h_hafu_block`
    now strips hafu unconditionally; non-extreme replaces with ttg/hhad,
    extreme drops the leg without replacement (ticket odds shrink but no
    bad legs). `_search_plan` hard-codes `allow_hafu = False` so the extreme
    path no longer emits hafu at all. 5/14 replay validation: extreme 03 crs
    2:0 × 05 crs 2:0 整票命中 52.56x (vs 老版含 003 hafu 平/平 0/1).
27. **R28 — poisson_solo ticket retired (5/16).** 5/01-5/15 aggregate:
    whole-ticket hit 1/11 days, leg-hit 2/16 (12.5%), realized -47.7% over
    the 11-day window. The ticket bets the single highest-Poisson-edge leg —
    but "highest model edge" is structurally the most over-concentrated bin
    on the score grid (always ttg 1球 or crs 0:0): adverse selection against
    the model's own worst-calibrated output. R17/R18/R22/R23/R24/R26 patched
    symptoms; the structure stayed -EV. `_build_poisson_solo_plan` is still
    invoked (keeps cooling-off + edge index warm, retains unit tests) but the
    plan is dropped from output when `RULE_R28_RETIRE_POISSON_SOLO = True`.
    Parallels R27 (hafu retired). A ≥30-day re-review may revive it.
12. **Fail loud if data gaps exist.** If brief Section 1 has 0 matches,
   `_resolve_drift_provider` errored, or all matches show role "未知",
   report the failure and stop instead of guessing.
10. **Cluster threshold respect.** `draw_cluster` only fires when comfort
    matches ≥ 3; `upset_cluster` only when strong bankers ≥ 3. If the brief
    shows the cluster ticket as 0 legs, it correctly didn't trigger — don't
    force-create one.

### Step 4 (next day): Run the review

```bash
uv run python -m nutmeg.interfaces.cli jczq-daily-review \
  --date yesterday --output-dir .nutmeg-data/jczq
```

This updates `.nutmeg-data/jczq/memory/strategy-memory.json`:
- `pattern_buckets` — league × role × pool EV-weighted scores
- `oracle_learnings` — actual winning picks per match
- `decision_policy` — auto-adjusted execution rules

The next day's generator reads these via `_active_bias_fn`, so the more
review history accumulates, the smarter the picks.

### Model limitations (state these to the user when relevant)

1. **Poisson covers had / ttg / crs / hafu only.** hhad (handicap) is priced
   separately; Poisson edge isn't computed for hhad legs.
2. **Edge ≤ -15% is not "opposed".** Sporttery's standard vig is 12-13%, so
   every favorite shows ~-11% by construction. Only edge ≤ -20% is real
   model opposition.
3. **`pattern_buckets` needs ~7-14 days of reviews** before its bias becomes
   reliable. Early on, the brief's value comes mainly from Poisson + EV gap.
4. **No cross-bookie cross-check yet.** Sporttery is the only source.

### Capabilities not yet wired into the generator

- Multi-time-of-day Sporttery snapshots → drift detection
  (`OddsDriftStore` exists; needs launchd schedule to actually fire)
- European-bookie reference odds (`EuropeanOddsReferenceProvider` needs
  credentials)
- LLM-augmented postmortem narratives (`Completer` interface exists; needs
  Portkey wiring)
- soccerdata Elo / form baseline (interface ready; populate
  `LeaguePriorBaseline.overrides` to override defaults)

### Reference artifacts

- Pipeline modules: `nutmeg/services/jczq_*.py` (intelligence / drift /
  baseline / poisson / review_explainer)
- Generator service: `nutmeg/services/jczq_daily.py`
- Strategy memory: `nutmeg/services/jczq_strategy_memory.py` (v2 schema)
- Brief command: `nutmeg jczq-daily-brief` (module `nutmeg/services/jczq_brief.py`)
- Replay command: `nutmeg jczq-replay` (module `nutmeg/services/jczq_replay.py`)
- Second-leg helper: `nutmeg jczq-second-leg` (module `nutmeg/services/jczq_second_leg.py`)
- Final-plan PDF dispatcher: `nutmeg jczq-final-plan-pdf` (module `nutmeg/services/jczq_final_plan_pdf.py`)
- Test coverage: 676 tests across `tests/test_jczq_*.py` (Rules A-J + R1-R27 + F1-F4
  regression in `tests/test_jczq_daily_iteration_rules.py` + `tests/test_jczq_poisson.py`)
- Rule constants live at the top of `nutmeg/services/jczq_daily.py`
  (`HAD_BANKER_FLOOR`, `STABLE_BASE_HAD_MIN_POISSON_EDGE` (R20),
  `MAIN_HAD_MIN_POISSON_EDGE` (R21), `POISSON_SOLO_EDGE_THRESHOLD`,
  `POISSON_SOLO_CRS_ZERO_ZERO_MIN_EDGE` (R23),
  `POISSON_SOLO_LOW_GOALS_LAMBDA_TRIGGER` (R17),
  `POISSON_SOLO_COOLING_OFF_LOOKBACK` (R24),
  `POISSON_SOLO_CRS_LOW_PICKS`, `EXTREME_CRS_LOW_PICKS` (R18),
  `POISSON_STRONG_OPPOSE_THRESHOLD`, `BURNED_TEAM_BIAS`,
  `RULE_H_NON_EXTREME_HAFU_BLOCKED`)
  and `nutmeg/services/jczq_strategy_memory.py`
  (`POISSON_LEAGUE_BIAS_MIN_SAMPLES`, `POISSON_LEAGUE_BIAS_DELTA` (R25),
  `RECENT_PLAN_RESULTS_LIMIT` (R24),
  `EMPIRICAL_DECAY_BASELINES`, `EMPIRICAL_DECAY_MIN_SAMPLES`,
  `EMPIRICAL_DECAY_FLOOR`, `EMPIRICAL_DECAY_TOLERANCE` (F2),
  `DAILY_CONCENTRATION_ALPHA_THRESHOLD`, `DAILY_CONCENTRATION_TRIGGER_COUNT`,
  `DAILY_CONCENTRATION_DECAY`, `LOW_GOALS_PICKS` (F3),
  `DIXON_COLES_RHO_KEY`, `DIXON_COLES_RHO_DEFAULT` (F1))
  and `nutmeg/services/jczq_daily.py` (`F4_DOMINANCE_THRESHOLD` (F4)) and
  `nutmeg/services/jczq_intelligence.py` (`COINFLIP_VIG_THRESHOLD`,
  `COINFLIP_IMPLIED_SPREAD_THRESHOLD`, `HIGH_VOLATILITY_TTG_MEDIAN`,
  `CRS_POISSON_EDGE_FLOOR`, `HIGH_ODDS_HAD_THRESHOLD`,
  `HIGH_ODDS_HAD_REQUIRED_EDGE`, `CONTRARIAN_POISSON_REJECT_BELOW`,
  `HHAD_POISSON_REJECT_BELOW`, `HHAD_DRAW_MIN_EDGE` (R19)).
