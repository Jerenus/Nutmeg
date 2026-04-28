# Feature Specification: Agent Execution Path

**Feature Branch**: `016-agent-execution-path`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: Add the first LangGraph-backed agent execution path over the existing deterministic analysis workflow.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Execute analysis through an agent workflow (Priority: P1)

As the Nutmeg operator, I want a dedicated agent workflow to run match analysis so future LLM/tool nodes can be inserted without changing the CLI contract.

**Independent Test**: Run a workflow with stub analysis service and verify it returns fixture id, query, intent, judgment, evidence, and node trace.

### User Story 2 - Fail truthfully on insufficient evidence (Priority: P1)

As the Nutmeg operator, I want agent workflow failures to preserve the reason rather than hallucinating an answer.

**Independent Test**: Stub analysis failure and verify workflow status is `failed` with a clear error and no judgment payload.

### User Story 3 - Expose CLI surface (Priority: P2)

As the operator, I want `agent-analyze-match` text/JSON output so I can test the agent path separately from deterministic `analyze-match`.

**Independent Test**: CLI JSON/text tests verify the agent path renders status, nodes, and analysis payload while preserving clean failure behavior.
