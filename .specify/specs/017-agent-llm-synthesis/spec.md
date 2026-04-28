# Feature Specification: Agent LLM Synthesis Guard

**Feature Branch**: `017-agent-llm-synthesis`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: Add an optional guarded synthesis node to the agent workflow so future LLM narration can be attached without bypassing deterministic evidence.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Produce guarded synthesis when enabled (Priority: P1)

As the Nutmeg operator, I want the agent workflow to call a synthesis provider only after deterministic analysis succeeds, so generated text is grounded in existing evidence.

**Independent Test**: Inject a fake synthesis provider and verify the workflow calls it with analysis evidence and records the generated text plus node trace.

### User Story 2 - Skip synthesis safely when unavailable (Priority: P1)

As the operator, I want the workflow to succeed without generated text when no synthesis provider is configured.

**Independent Test**: Run workflow without provider and verify status remains succeeded, generated synthesis is `None`, and node trace marks `synthesis_skipped`.

### User Story 3 - Reject unsupported synthesis output truthfully (Priority: P1)

As the maintainer, I want the workflow to reject generated text that ignores the deterministic verdict or confidence so it cannot drift from evidence.

**Independent Test**: Fake provider returns text missing verdict/confidence, workflow fails with guard error and does not expose generated synthesis as trusted.
