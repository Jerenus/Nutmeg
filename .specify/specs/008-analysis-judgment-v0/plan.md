# Implementation Plan: Analysis Judgment v0

**Branch**: `008-analysis-judgment-v0` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/008-analysis-judgment-v0/spec.md`
**Input**: Feature specification from `.specify/specs/008-analysis-judgment-v0/spec.md`

## Summary

Add the first agent-facing analysis slice: a deterministic analysis service plus CLI command that synthesizes existing fixture snapshot and odds snapshot context into Nutmeg's four-part judgment format.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: Typer, existing snapshot/odds services, dataclasses  
**Storage**: Reuse existing DuckDB fixture cache and on-demand snapshot services  
**Testing**: pytest  
**Target Platform**: macOS / CLI-first local runtime  
**Project Type**: single Python package  
**Performance Goals**: one bounded analysis call over an already-cached fixture  
**Constraints**: truthful missing-data handling; no fabricated evidence; no new provider calls beyond existing services  
**Scale/Scope**: one-fixture pre-match judgment for the owner-only CLI phase

## Constitution Check

- **Spec-first delivery**: PASS — the analysis path is isolated in a dedicated feature package.
- **CLI-first**: PASS — the first surface is a direct CLI command.
- **Shared facts, isolated user state**: PASS — the analysis reads shared facts and adds no new mutable user state.
- **Phase-1 simplicity**: PASS — deterministic synthesis is the smallest useful agent slice before LangGraph.

## Structure Decision

Keep judgment synthesis in a dedicated `nutmeg/services/analysis.py` module with explicit domain dataclasses, while the CLI remains a thin rendering layer and existing snapshot/odds services remain the only evidence builders.
