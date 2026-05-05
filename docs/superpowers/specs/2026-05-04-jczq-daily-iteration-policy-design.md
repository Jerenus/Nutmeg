# JCZQ Daily Iteration Policy Design

## Goal

Make the 08:00 JCZQ daily review produce a complete, executable strategy iteration, and make the next daily advisor consume that iteration when building plans.

## Current State

The existing 08:00 launchd job runs `jczq-daily-review --date yesterday --output-dir .nutmeg-data/jczq --dispatch-telegram --no-dry-run --format json`. That command already grades the saved context, writes review artifacts, records DuckDB review rows when configured, updates `memory/strategy-memory.json`, and sends a Telegram postmortem. The gap is that strategy memory currently stores only coarse pattern counters and short insights, so the next `jczq-daily-advisor` only reacts to a small subset of the postmortem lessons.

## Design

`JczqDailyReviewService` remains the single 08:00 entry point. It will keep the existing command and launchd contract, but `update_strategy_memory()` will also derive a `decision_policy` object from the postmortem. The policy is deliberately small and deterministic so it can be audited in JSON and safely used by `JczqDailyAdvisorService`.

The policy includes five rule groups:

1. `stable_base`: tracks strong-banker favorite reliability and marks low-price bankers for downgrade when misses outweigh hits.
2. `comfort_favorite`: keeps direction-aware 1.75-2.05 favorite risk handling. A home favorite misses on draw/away; an away favorite misses on draw/home. A favorite that wins is not counted as cold-risk success.
3. `total_goals`: tracks actual total-goals distribution and promotes 2-goal/small-score protection when 2-goal outcomes cluster.
4. `hafu`: tracks selected half-full legs and downgrades half-full selection when misses outweigh hits.
5. `reuse_guard`: records selected-match miss concentration and tells the advisor not to reuse the same match/error story across multiple plans when that pattern is hot.

`JczqDailyAdvisorService` will read `decision_policy` from `strategy-memory.json` and apply it during plan construction. The advisor will downgrade unstable strong bankers in the stable base, prefer total-goals 2-ball/small-score legs in contrarian or inspiration plans when the policy is active, reduce half-full use outside extreme tickets when half-full is cold, and append policy notes to the summary.

## Data Flow

1. 12:00 daily advisor writes the full pre-match context to `.nutmeg-data/jczq/daily/<date>/context.json`.
2. 08:00 daily review reads yesterday's context and fetches settled results.
3. The review grades saved legs and updates both pattern counters and `decision_policy` in `.nutmeg-data/jczq/memory/strategy-memory.json`.
4. The review message includes the active policy notes under strategy memory.
5. The next advisor reads the same memory file and applies active rules before writing today's context/report.

## Error Handling

If context is missing, the review keeps the existing skipped report behavior and does not mutate policy. If a result row lacks a pool, that pool is skipped for policy stats. Invalid or older memory files are normalized with defaults so existing installations continue working.

## Testing

Add focused TDD tests in `tests/test_jczq_review_service.py` to verify that the review writes policy rules for strong-banker downgrade, 2-goal promotion, half-full downgrade, and reuse guard. Add focused tests in `tests/test_jczq_daily_service.py` to verify the advisor consumes those policy rules in summary text and plan selection.

## Operational Answer

The launchd plist does not need a new command. After this change, the same 08:00 job executes the complete iteration process because `jczq-daily-review` performs grading, persistence, policy derivation, artifact writing, and dispatch in one run.
