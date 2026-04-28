# Implementation Plan: Daily Operator Schedule

**Branch**: `034-daily-operator-schedule` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/034-daily-operator-schedule/spec.md`

## Summary

Build an operator command for repeatable daily use. This is an orchestration
layer over existing services, not a new scheduler daemon or cron installer.

## Architecture

- `nutmeg.domain.operations`: daily cycle summary dataclasses.
- `nutmeg.services.operations`: orchestrates sync, ranking, value board, briefs, and optional Telegram send.
- `nutmeg.interfaces.cli`: `daily-run`.
- `docs/architecture/daily-operator.md`: dry-run and deployment notes.

## Testing

Use fake services to cover partial failures, dry-run output, explicit dispatch,
and CLI JSON contract.

