# Implementation Plan: Tactics Synthesis v0

**Branch**: `009-tactics-synthesis-v0` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/009-tactics-synthesis-v0/spec.md`
**Input**: Feature specification from `.specify/specs/009-tactics-synthesis-v0/spec.md`

## Summary

Deepen the first analysis workflow by extracting tactical evidence from the existing fixture snapshot, handling synthesis contradictions between football context and market context, and stabilizing the evidence contract for future orchestration.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: existing snapshot and odds services, Typer, dataclasses  
**Storage**: reuse the shared fixture cache and snapshot services; no new persistence required  
**Testing**: pytest + ruff  
**Target Platform**: macOS / CLI-first local runtime  
**Constraints**: deterministic only; truthful missing-data handling; no LangGraph requirement yet  
**Scale/Scope**: one deeper analysis slice over the existing `analyze-match` command

## Constitution Check

- **Spec-first delivery**: PASS — the richer synthesis contract is isolated in its own slice.
- **CLI-first**: PASS — the command surface remains `analyze-match`.
- **Shared facts, isolated user state**: PASS — no new user-scoped persistence is introduced.
- **Phase-1 simplicity**: PASS — this slice improves evidence quality before adding orchestration complexity.

## Structure Decision

Extend the analysis domain contract with tactical evidence and conflict state, keep extraction logic in the deterministic analysis service, and preserve the CLI as a thin rendering layer.
