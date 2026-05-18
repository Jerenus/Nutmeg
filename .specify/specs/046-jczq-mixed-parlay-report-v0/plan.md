# Implementation Plan: JCZQ Mixed Parlay Report v0

**Branch**: `046-jczq-mixed-parlay-report-v0` | **Date**: 2026-04-26 | **Spec**: `.specify/specs/046-jczq-mixed-parlay-report-v0/spec.md`

## Summary

This historical plan added a reusable竞彩足球 mixed-parlay report workflow that
fetches Sporttery calculator-style odds, validates sellable pools, emits two
high-odds 4-leg combinations, renders JSON/Markdown/PDF artifacts, and exposes
the command through the OpenClaw safe router.

2026-05-18 update: the live surface is retired. The command now keeps
`--provider sample` for deterministic smoke coverage and rejects
`--provider live` with guidance to the current daily brief/debate/final-plan
workflow. See `docs/superpowers/specs/2026-05-18-project-repair-design.md`.

## Technical Context

**Language/Version**: Python 3.12 baseline  
**Dependencies**: Typer, httpx, reportlab, existing TelegramBotClient and OpenClaw router  
**Storage**: Local artifacts under `.nutmeg-data/jczq` by default  
**Testing**: pytest service/CLI/router tests, ruff, compileall, `scripts/verify.sh`  
**Constraints**: No wager execution, sportsbook integration, guaranteed-profit claims, or surprise network in tests

## Structure

```text
nutmeg/domain/jczq.py
nutmeg/services/jczq.py
nutmeg/jczq/samples/mixed-calculator-20260426.json
nutmeg/interfaces/cli.py
scripts/openclaw/nutmeg_command_router.py
tests/test_jczq_service.py
tests/test_cli.py
tests/test_openclaw_router.py
```

## Supersession Notes

- Live execution: `uv run nutmeg jczq-mixed-report --provider live` exits 2 and
  points operators to `jczq-daily-brief`.
- Smoke execution: `uv run nutmeg jczq-mixed-report --provider sample --format json`
  remains valid for historical contract tests.
- OpenClaw: the router may still build sample mixed-report commands, but the
  current cooperation path is `jczq-daily-advisor` plus the daily
  brief/debate/final-plan commands exposed directly in the CLI.
