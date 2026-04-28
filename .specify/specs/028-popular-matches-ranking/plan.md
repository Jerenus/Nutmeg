# Implementation Plan: Popular Matches Ranking

**Branch**: `028-popular-matches-ranking` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/028-popular-matches-ranking/spec.md`

## Summary

Add a deterministic local-first match popularity ranker plus a `popular-matches` CLI. Reuse the same ranking metadata in `today-briefs --sort popularity` without changing the default kickoff-order behavior.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: stdlib dataclasses/datetime, existing fixture domain and CLI service builders  
**Storage**: no new storage; uses existing fixture repository/demo fixtures  
**Testing**: unit ranker tests plus CLI JSON contract tests  
**Constraints**: no network in tests, deterministic scoring, no secrets in output, no provider-specific calls

## Design

- `nutmeg.services.popularity.MatchPopularityRanker`: scores and ranks `Fixture` objects.
- `MatchPopularityScore`: score/tier/reasons value object for explainability.
- `RankedFixture`: fixture plus rank and popularity metadata.
- `popular-matches` CLI: lists ranked candidates with suggested `/brief` follow-up messages.
- `today-briefs --sort popularity`: applies the same ranker before optional brief fan-out.
