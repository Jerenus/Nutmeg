> ⚠️ **M2 已删（2026-07-07）**：本文描述的引擎已随 M2 切换整体下葬，仅存历史参考；现行系统见 `docs/superpowers/specs/2026-07-06-decision-ontology-design.md` 与 CLAUDE.md SOP。

# JCZQ Bold Judgment Mode Design

**Date**: 2026-06-04  
**Status**: design approved for discussion  
**Scope**: JCZQ daily decision workflow, GPT/Claude debate alignment, bold match-judgment output, review loop  
**Non-scope**: real betting execution, bankroll automation, sportsbook integration, guaranteed-profit claims

## 1. Problem Statement

The JCZQ workflow currently has multiple partially overlapping decision systems:

1. `jczq-daily-brief` / debate / final-plan: Poisson-led evidence, diagnostics, and human adjudication.
2. Deprecated `jczq-daily-advisor`: old v1 generator still used by some bot/router paths and by brief construction.
3. `jczq-tiered`: current 4-tier entertainment plan, explicitly non-edge and long-term negative expectation.
4. GPT/Claude free-form analysis: richer match judgment, but not guaranteed to follow the same input path or schema.
5. Human final notes: often the real final decision, but not yet treated as the canonical object for review and calibration.

The result is system drift. Different agents can start the same nominal task and follow different decision chains. GPT may read repo state, AGENTS.md, brief, tiered output, and local debate files. Claude may receive only copied brief sections and a prompt. Telegram/OpenClaw may still route to deprecated v1 paths. The system then compares outputs as if they were independent judgments on the same frozen input, but they are not.

This design creates a dedicated **Bold Judgment Mode** so bold match judgment becomes a structured system mode rather than an ad hoc escape from the system.

## 2. Goal

When the user asks for bold match judgment, the system should produce:

- clear match-by-match positions;
- an explicit top-level story for the day;
- legal market expressions for those positions;
- entertainment tickets built around the strongest judgments;
- explicit downside/反面风险 for every key call;
- a reviewable record of whether the judgment, the market expression, and the parlay construction were correct.

The mode must preserve the project's safety boundary: it is entertainment analysis, not investment advice, not guaranteed profit, and not a claim of positive EV.

## 3. Non-Goals

- Do not revive `poisson_solo` or hafu.
- Do not claim edge or positive expected value for bold tickets.
- Do not force A/B/D/E tickets when the bold structure does not support them.
- Do not add another pile of unscoped if-then rules after each single-day result.
- Do not use one-day outcomes to mutate model policy.
- Do not treat soft-chalk reverse picks as a mechanical strategy.

## 4. Core Design Principle

Bold mode is:

> match story first, market expression second, ticket construction third, review loop last.

The current system often starts from available legs and odds bands. Bold mode should start from football/market judgment:

1. What is today's slate story?
2. What is each match's likely script or trap?
3. Which market expresses that script most cleanly?
4. Which 1-3 judgments are worth turning into tickets?
5. Which parts failed tomorrow: the judgment, the expression, or the ticket packaging?

## 5. Mode Definition

Introduce a named operating mode:

```text
bold_judgment
```

### 5.1 Trigger

The mode is active when the user explicitly asks for any of:

- 大胆比赛判断
- 大胆选择
- 不要只空仓
- 给明确立场
- 比赛判断比投资建议重要
- bold judgment
- bold entertainment picks

The existing daily-plan SOP may still run the brief/debate setup, but the output template and review target switch to bold judgment mode.

### 5.2 Output Contract

Every bold-mode answer must contain these sections:

1. 今日总剧本
2. 逐场比赛判断
3. 市场读法
4. 大胆方向
5. 反面风险
6. 跳过理由
7. 主打判断票
8. 低波动表达
9. 剧本放大票
10. 极限想象票
11. 明日复盘标签

The system may return fewer than four tickets. It must not fabricate a stable base if the slate has no stable anchor.

### 5.3 Ticket Types

Replace the old A/B/D/E language in bold mode with more honest labels:

| Ticket | Role | Typical Structure | Notes |
|---|---|---|---|
| 主打判断票 | Core bold thesis | 1-2 legs or 2-string | Carries the day's strongest match view |
| 低波动表达 | Lower-variance expression | Single or 2-string | Uses cheaper leg to express same view, not called safe |
| 剧本放大票 | Narrative amplifier | 2-4 legs | Higher odds, same thesis, modest stake |
| 极限想象票 | Lottery tail | 3-5 legs | Tiny stake, explicitly entertainment |

The old terms `稳健底仓`, `主方案`, `反大众`, and `极限娱乐` can remain in tiered-engine artifacts, but bold-mode human-facing output should prefer the labels above.

## 6. Match Judgment Schema

Each match should be represented with a structured row/object:

```json
{
  "match_no": "周四205",
  "home": "墨西哥",
  "away": "塞尔维亚",
  "market_read": "体彩把墨西哥压成强热门",
  "judgment": "墨西哥热度偏虚，塞尔维亚不应被打成弱旅",
  "bold_direction": "墨西哥不穿盘 / 让负",
  "preferred_expression": {"pool": "hhad", "pick": "让负", "odds": 3.42},
  "lower_variance_expression": {"pool": "hhad", "pick": "让负", "odds": 3.42},
  "avoid": ["墨西哥让胜"],
  "downside": "如果墨西哥主场强势且塞尔维亚轮换，可能直接打穿",
  "tags": ["soft_hot", "not_cover", "friendlies"]
}
```

Important: a bold direction is not automatically a ticket leg. Ticket construction chooses a small subset of the strongest match judgments.

## 7. Handicap Semantics Fix

The system must stop using the word `cover` ambiguously for hhad legs.

For a home favorite with goal line `-1`:

| Expression | Meaning |
|---|---|
| had 胜 | Home wins the match |
| hhad 让胜 | Home wins by 2+ goals; favorite打穿 |
| hhad 让平 | Home wins by exactly 1; favorite小胜卡盘 |
| hhad 让负 | Home fails to cover: draw/loss or wins by 0-1 depending line semantics |

For an away favorite, mirror the direction. The rendered explanation must say `打穿`, `赢一球`, or `不穿盘`; it must not call `让胜` a wider or safer cover when the favorite is laying a handicap.

This is the most urgent conceptual correction because the tiered A output can currently treat `had <= 1.50 -> hhad same direction` as a safer anchor. In many cases that is actually a more aggressive margin bet.

## 8. F3 / Anomaly Semantics

F3 low-goals concentration should not be freely interpreted by each model.

When F3 triggers:

1. Low-score Poisson legs cannot be the main anchor.
2. Low-score legs may remain as small evidence only after adjusted edge and rule gates.
3. The system should generate a `counter_hypothesis` field, not an automatic bet:
   - possible values: `medium_goals`, `open_game`, `skip_low_score`, `no_counter`.
4. The counter-hypothesis requires contextual support, such as friendlies, rotation, attacking mismatch, defensive instability, or a mismatch between handicap line and low-goal model output.
5. GPT/Claude must state whether they accept, de-weight, reject, or reverse the F3-affected signal.

This converts anomaly handling from free-form opinion into a reviewable decision.

## 9. GPT / Claude Alignment

GPT and Claude must read the same frozen input bundle. The current brief instruction that suggests copying only Sections 1-5 to Claude is insufficient.

### 9.1 Required Shared Input

A bold-mode debate run should freeze:

- `brief.md` full text, including diagnostics and conflict sections;
- Sporttery odds snapshot timestamp;
- tiered-plan output, if generated;
- strategy-memory summary relevant to the day;
- F3/anomaly flags;
- value/conflict report availability status;
- mode: `bold_judgment`;
- user preference: e.g. `must_provide_bold_match_view = true`;
- safety boundary text.

### 9.2 Required Shared Output Schema

Both GPT and Claude should output:

- `daily_story`;
- `match_judgments[]`;
- `tickets[]`;
- `avoid_legs[]`;
- `anomaly_handling[]`;
- `review_tags[]`;
- `budget`.

Markdown can remain for readability, but the durable record should be parseable.

### 9.3 Compare Upgrade

The compare step should compare more than `match_no/pool/pick`:

- same match, different story;
- same story, different market expression;
- same leg, different risk framing;
- one model says empty/skip while another outputs tickets;
- budget and exposure difference;
- anomaly treatment difference.

Example: `周四204` can be compared as `low_score` vs `open_goals`, even if the final legs are different pools.

## 10. Final Decision Object

The final human decision should become the canonical review target.

Introduce a `final-decision.json` shape, even if implemented first as an enriched `final-plan.json`:

```json
{
  "run_date": "2026-06-04",
  "mode": "bold_judgment",
  "daily_story": "不信强队全打穿；信友谊赛开放进球 + 强队小胜卡盘",
  "tickets": [],
  "match_judgments": [],
  "review_tags": [
    "friendlies_open_goals",
    "soft_hot_not_cover",
    "counter_f3_low_goals"
  ],
  "source_artifacts": {
    "brief": "brief.md",
    "gpt_analysis": "debate/gpt-analysis.md",
    "claude_analysis": "debate/claude-analysis.md",
    "human_notes": "debate/human-notes.md"
  }
}
```

The review service should grade this object, not only auto-generated tiered or deprecated v1 plans.

## 11. Review Schema

Bold-mode review must grade three layers:

### 11.1 Judgment Result

Did the match story happen?

Examples:

- `favorite_not_cover`: favorite won but failed to cover, or failed to win.
- `favorite_cover`: favorite won by required margin.
- `medium_goals`: total goals landed in 2-4 range.
- `open_goals`: game produced 3+ or 4+ depending the declared threshold.
- `soft_hot_failed`: soft favorite did not win.

### 11.2 Market Expression Result

Was the chosen pool/pick the right expression?

A judgment can be directionally right while the market expression loses. Example: a match is open and has goals, but exact `ttg 3球` loses because it landed 4.

### 11.3 Ticket Packaging Result

Did parlay construction over-couple judgments? Did a good match call get buried inside too many related legs?

This prevents the system from marking a day as totally wrong when the football read was useful but the parlay packaging was too narrow.

## 12. Entry-Point Consolidation

The system should converge to one orchestration entry for daily JCZQ decisions.

Preferred future command:

```bash
uv run nutmeg jczq-decision-run --date today --mode bold_judgment
```

Minimum first step without a new command:

1. Update `AGENTS.md` to recognize bold judgment trigger phrases and require the bold-mode template.
2. Update debate templates to include bold judgment sections.
3. Update brief's Claude instruction to reference the full shared brief and mode, not only Sections 1-5.
4. Update bot/router docs so `/jczq` no longer points to deprecated `jczq-daily-advisor` for current workflows.
5. Keep `jczq-tiered` as one signal provider, not the final decision authority.

## 13. Safety and Language Rules

Bold mode should use language like:

- `大胆方向`
- `比赛判断`
- `娱乐预算`
- `反面风险`
- `如果只玩一张，我会选...`
- `这不是正 EV 断言`

Avoid language like:

- `投资建议`
- `重仓`
- `稳胆`
- `铁胆`
- `稳赚`
- `正期望`
- `必打`

If the user says `投资建议`, the assistant should translate the framing to `娱乐预算下的比赛判断` unless the user explicitly requests financial analysis, in which case the system should state that it cannot provide guaranteed or personalized financial/betting advice.

## 14. Migration Plan

### Phase 1: Documentation and Templates

- Write this design.
- Update `AGENTS.md` with bold judgment trigger and output contract.
- Update `JczqDebateWorkspaceService._analysis_template` for bold mode or add a mode-specific template.
- Update `jczq_brief.py` Claude instruction block to reference full shared brief and mode.

### Phase 2: Structured Artifacts

- Add optional `mode` to debate workspace initialization.
- Add `bold-decision-input.json` or extend `final-plan-input.json` with match judgments and review tags.
- Emit `final-decision.json` alongside `final-plan.json`.

### Phase 3: Review Loop

- Add a bold judgment review service or extend final-plan review to grade judgment/expression/packaging separately.
- Keep single-day results append-only; do not mutate selection rules until sample thresholds are reached.

### Phase 4: Entry-Point Cleanup

- Update OpenClaw router and Telegram bot to route current JCZQ daily requests to the canonical decision workflow.
- Leave deprecated v1 service available only for replay/tests or internal signal generation.
- Decide whether `jczq-tiered` remains a standalone command or becomes a sub-step in `jczq-decision-run`.

## 15. Acceptance Criteria

- A user asking for bold judgment receives match-by-match positions before tickets.
- GPT and Claude receive the same frozen input bundle and produce comparable schemas.
- F3 and similar anomalies have explicit treatment: accept, de-weight, reject, or counter-hypothesis.
- hhad rendered language correctly distinguishes `打穿`, `赢一球`, and `不穿盘`.
- The final human decision can be reviewed as the canonical object.
- Review can say: judgment right / expression wrong / packaging too narrow.
- No component claims positive EV or guaranteed returns.

## 16. Open Questions for Discussion

1. Should bold mode become the default for all `今天的方案` requests, or only when the user asks for bold judgment?
2. Should the system still generate a tiered-plan artifact every day, or only as one candidate signal inside the debate bundle?
3. Should `final-plan.json` be extended, or should a new `final-decision.json` be introduced to avoid breaking the PDF renderer?
4. How strict should the output be about giving at least one bold judgment on very poor slates?
5. Should bot/router changes wait until the new structured artifact exists, or should routing away from deprecated v1 happen immediately?

## 17. Recommended First Implementation Slice

The smallest useful slice is:

1. Add bold-mode text to `AGENTS.md`.
2. Add a bold-mode debate template.
3. Update brief's Claude instruction to point at the full shared brief and selected mode.
4. Fix hhad wording in tiered rendering so `让胜` is not called a wider cover.
5. Add a review tag section to `human-notes.md` / final-plan skeleton.

This slice does not require a new CLI command yet, but it makes future GPT/Claude outputs more systematic immediately.