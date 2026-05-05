<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan:
`.specify/specs/046-jczq-mixed-parlay-report-v0/plan.md`
<!-- SPECKIT END -->

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

The agent (you) handles all three steps; the user only types one trigger
phrase. Do not stop after Step 1 to ask permission — keep going to Step 3
unless the brief reveals a fatal data gap.

#### Step 1: Generate the daily brief

```bash
uv run python scripts/jczq_daily_brief.py \
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

#### Step 3: Output 5-6 tickets in this exact format

Tickets, ordered safest → wildest. All numeric odds come from the brief
or the generator output — never invent odds.

- **A 稳健底仓 (~2-4x)** — 2-3 had/hhad legs priced **strictly above 1.40**
  (Rule B). No 1.24/1.34 chalk dumps as bankers anymore.
- **B 主方案 (~30-150x)** — mix of mid-priced had legs (>1.40), 让球 covers,
  and ttg medium-line picks. Avoid hafu (decision_policy rule). Skip any
  match flagged ⚠coinflip from had pool (Rule E).
- **C Poisson 单核灵感票 (~50-300x)** — Rule A ticket: 1-2 legs straight
  from brief Section 4 with edge ≥ +15%. Do **not** dilute with chalk legs.
- **D 反大众盘口 (~80-200x)** — total goals + 让平 across draw_friendly /
  contrarian matches.
- **E 极限娱乐 (~1000-100000x)** — score-line lottery, tiny stake.

Stake allocation against a 100¥ entertainment budget:
**25 / 30 / 20 / 15 / 10** (A/B/C/D/E). The Poisson 单核 line gets a real
allocation now because it carries the strongest signal-to-noise ratio.

Always mark which ticket the agent itself would back hardest, and why.

### Hard rules (Rules A-F encoded in the generator since 2026-05-05)

1. **Rule A — Poisson +EV ≥ +15% becomes its own ticket.** When brief
   Section 4 has any leg edge ≥ +15%, the generator auto-emits a
   `poisson_solo` plan (1-2 legs, no chalk dilution). Treat this as the
   "model has high conviction" signal — never bury it inside a 4-leg combo.
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
8. **No hafu legs in tickets A-D.** `decision_policy.hafu.action =
   downgrade_half_full_non_extreme` is active. Hafu only allowed in E.
9. **Fail loud if data gaps exist.** If brief Section 1 has 0 matches,
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
- Brief script: `scripts/jczq_daily_brief.py`
- Replay tool: `scripts/replay_jczq_with_new_generator.py`
- Test coverage: 521 tests across `tests/test_jczq_*.py` (Rules A-F regression
  in `tests/test_jczq_daily_iteration_rules.py`)
- Rule constants live at the top of `nutmeg/services/jczq_daily.py`
  (`HAD_BANKER_FLOOR`, `POISSON_SOLO_EDGE_THRESHOLD`,
  `POISSON_STRONG_OPPOSE_THRESHOLD`, `BURNED_TEAM_BIAS`) and
  `nutmeg/services/jczq_intelligence.py` (`COINFLIP_VIG_THRESHOLD`,
  `COINFLIP_IMPLIED_SPREAD_THRESHOLD`, `HIGH_VOLATILITY_TTG_MEDIAN`).
