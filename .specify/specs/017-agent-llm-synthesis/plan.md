# Implementation Plan: Agent LLM Synthesis Guard

**Branch**: `017-agent-llm-synthesis` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/017-agent-llm-synthesis/spec.md`

## Summary

Extend `MatchAnalysisAgentWorkflow` with an optional synthesis provider seam. Generated synthesis is only produced after deterministic analysis and must mention the deterministic verdict and confidence, otherwise the workflow fails truthfully.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: existing agent workflow and analysis domain  
**Storage**: none  
**Testing**: pytest + ruff  
**Constraints**: no live LLM calls in tests; provider injection only; generated synthesis cannot replace deterministic analysis payload
