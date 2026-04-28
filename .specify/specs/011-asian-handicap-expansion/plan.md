# Implementation Plan: Asian Handicap Expansion

**Branch**: `011-asian-handicap-expansion` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/011-asian-handicap-expansion/spec.md`
**Input**: Feature specification from `.specify/specs/011-asian-handicap-expansion/spec.md`

## Summary

Expand canonical Asian handicap coverage in the odds layer and allow the deterministic analysis workflow to mention stronger handicap pressure when available.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: existing odds provider clients, odds snapshot service, analysis service  
**Storage**: no new storage model; reuse canonical odds snapshots and history path  
**Testing**: pytest + ruff  
**Target Platform**: macOS / CLI-first local runtime  
**Constraints**: preserve existing canonical contract; keep provider parsing shared; deterministic analysis only  
**Scale/Scope**: broaden handicap coverage and consume the new signal in analysis

## Constitution Check

- **Spec-first delivery**: PASS — this is an isolated continuation of the odds roadmap.
- **CLI-first**: PASS — `odds-snapshot` and `analyze-match` remain the visible surfaces.
- **Shared facts, isolated user state**: PASS — no new user-state concerns are introduced.
- **Phase-1 simplicity**: PASS — this is coverage growth over existing deterministic services, not a new orchestration layer.

## Structure Decision

Keep provider normalization inside the odds clients/services, expose more canonical handicap keys, and let analysis consume a summarized handicap-pressure signal instead of raw provider details.
