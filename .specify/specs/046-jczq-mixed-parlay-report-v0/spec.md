# Feature Specification: JCZQ Mixed Parlay Report v0

**Status**: Superseded for live use (2026-05-18); sample smoke retained  
**Created**: 2026-04-26

## Summary

Nutmeg originally generated two official-odds竞彩足球 4-leg high-odds mixed-parlay
reports, wrote JSON/Markdown/PDF artifacts, and exposed the workflow through
CLI and the OpenClaw Nutmeg bot router.

As of 2026-05-18 the live `jczq-mixed-report` selector is retired because the
hard-coded high-odds slate no longer matches the dynamic JCZQ daily workflow.
Live operation is now handled by `jczq-daily-brief`, debate workspace files,
`jczq-second-leg`, `jczq-debate-finalize`, and `jczq-final-plan-pdf`.
`jczq-mixed-report --provider sample` remains available for historical smoke
coverage only; `--provider live` fails loudly with guidance to the new path.

## Requirements

- Load sample Sporttery calculator-style竞彩足球 odds data for smoke tests.
- Reject live mixed-report execution with clear current-workflow guidance.
- Keep historical JSON/Markdown/PDF artifact tests deterministic.
- Keep OpenClaw routing honest: sample commands may be built, but retired live
  usage must not be described as the daily production path.
- Include pool, pick, odds, match metadata, explanation, official source URL, update times, total odds, and 2元 theoretical return.
- Render optional PDF with Chinese text.
- Support dry-run and real Telegram document dispatch through existing confirmation gates.
- Avoid wager execution, profit guarantees, and sportsbook integration.

## Success Criteria

- Focused service tests pass with no network.
- CLI sample-mode JSON contract returns artifacts and two combinations.
- CLI live mode exits non-zero and mentions `jczq-daily-brief`.
- Router action builds an allowlisted command and rejects unconfirmed dispatch.
