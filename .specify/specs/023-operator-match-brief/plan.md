# Implementation Plan: Operator Match Brief

**Branch**: `023-operator-match-brief` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/023-operator-match-brief/spec.md`

## Summary

Add an operator-facing `match-brief` CLI that wraps the existing `MatchAnalysisAgentWorkflow` and formats a stable brief payload. This avoids another provider integration while improving the Phase 1 private-operator loop.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: existing Typer CLI, dataclasses  
**Storage**: no new storage  
**Testing**: Typer CLI tests with stubbed workflow  
**Constraints**: no new live provider calls in tests, preserve failure semantics, no secret leakage, do not duplicate analysis logic

## Design

- Build a small payload assembler in `nutmeg.interfaces.cli` using `MatchAnalysisAgentResult`.
- Reuse `build_agent_workflow()` so optional LLM synthesis remains default-off and guarded.
- JSON payload shape:
  - `fixture_id`, `query`, `status`, `fixture`, `judgment`, `evidence`, `agent`, `generated_synthesis`, `sections`, `error`
- Text output shape:
  - `Match Brief: Home vs Away`
  - verdict/confidence/conflict
  - reasons/evidence/caveats/synthesis sections
- Failed workflows return exit code 2 and include error without fabricated sections.
