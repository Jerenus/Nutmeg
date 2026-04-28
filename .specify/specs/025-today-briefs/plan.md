# Implementation Plan: Today Briefs

**Branch**: `025-today-briefs` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/025-today-briefs/spec.md`

## Summary

Add `nutmeg today-briefs` to list local fixture candidates and optionally run the existing match brief workflow for each selected fixture.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: existing Typer CLI and FixtureService  
**Storage**: existing DuckDB fixture cache; demo mode uses sample fixtures  
**Testing**: CLI tests with demo fixtures and stubbed workflow  
**Constraints**: no network calls, do not require live provider keys, preserve per-fixture failures, avoid duplicating match analysis logic

## Design

- CLI: `today-briefs --league epl --days 1 --limit 5 --demo --briefs --format text|json`.
- Candidate source: `FixtureService.list_upcoming(league, days, demo=demo)`.
- List-only payload: fixture id, league, kickoff, home/away, venue, status, suggested `/brief` message.
- Brief mode: reuse `build_agent_workflow()` and `build_match_brief_payload()` per fixture.
- Per-fixture errors are captured in the item; command exits 0 if listing succeeds, even when individual briefs fail.
