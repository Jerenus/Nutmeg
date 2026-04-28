# Implementation Plan: LLM Provider Adapter

**Branch**: `018-llm-provider-adapter` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/018-llm-provider-adapter/spec.md`

## Summary

Introduce a default-off Portkey-compatible synthesis provider. The provider is injected into `MatchAnalysisAgentWorkflow` only when `NUTMEG_AGENT_SYNTHESIS_ENABLED=true` and `NUTMEG_PORTKEY_API_KEY` is configured.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: httpx, existing analysis domain and agent workflow  
**Storage**: none  
**Testing**: pytest + ruff with mock HTTP  
**Constraints**: no real network in tests; no key leakage; generated text remains guarded by workflow
