# Implementation Plan: Market Intelligence Signals

**Branch**: `013-market-intelligence-signals` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/013-market-intelligence-signals/spec.md`

## Summary

Reuse existing odds snapshot history and bookmaker quote summaries to add deterministic market intelligence to `AnalysisService`: result-market movement, bookmaker disagreement, and confidence calibration.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: existing odds domain models and analysis service  
**Storage**: no schema changes; consume existing `OddsSnapshot.history` and `OutcomeOddsSnapshot.bookmaker_quotes`/price summaries  
**Testing**: pytest + ruff  
**Constraints**: preserve `AnalysisEvidenceSummary` contract; deterministic only; do not introduce model orchestration

## Structure Decision

Keep signals as helper methods inside `AnalysisService` for now because this is a small deterministic evidence enrichment. Movement belongs in `odds_summary`; bookmaker disagreement belongs in `caveats` so confidence can use the same caveat budget.
