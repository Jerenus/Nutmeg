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

The agent (you) handles the daily brief, workspace update, and ticket output;
the user only types one trigger phrase. Do not stop after Step 1 to ask
permission — keep going through the workspace write and ticket output unless
the brief reveals a fatal data gap.

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
uv run python scripts/jczq_suggest_second_leg.py --date today --auto --top 8
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

### Hard rules (Rules A-J encoded in the generator since 2026-05-05/06)

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
- Brief script: `scripts/jczq_daily_brief.py`
- Replay tool: `scripts/replay_jczq_with_new_generator.py`
- Test coverage: 633 tests across `tests/test_jczq_*.py` (Rules A-J + R1-R20
  regression in `tests/test_jczq_daily_iteration_rules.py`)
- Rule constants live at the top of `nutmeg/services/jczq_daily.py`
  (`HAD_BANKER_FLOOR`, `STABLE_BASE_HAD_MIN_POISSON_EDGE` (R20),
  `POISSON_SOLO_EDGE_THRESHOLD`, `POISSON_SOLO_LOW_GOALS_LAMBDA_TRIGGER`
  (R17), `POISSON_SOLO_CRS_LOW_PICKS`, `EXTREME_CRS_LOW_PICKS` (R18),
  `POISSON_STRONG_OPPOSE_THRESHOLD`, `BURNED_TEAM_BIAS`,
  `RULE_H_NON_EXTREME_HAFU_BLOCKED`) and
  `nutmeg/services/jczq_intelligence.py` (`COINFLIP_VIG_THRESHOLD`,
  `COINFLIP_IMPLIED_SPREAD_THRESHOLD`, `HIGH_VOLATILITY_TTG_MEDIAN`,
  `CRS_POISSON_EDGE_FLOOR`, `HIGH_ODDS_HAD_THRESHOLD`,
  `HIGH_ODDS_HAD_REQUIRED_EDGE`, `CONTRARIAN_POISSON_REJECT_BELOW`,
  `HHAD_POISSON_REJECT_BELOW`, `HHAD_DRAW_MIN_EDGE` (R19)).
