# Feature Specification: Agent Status CLI

**Feature Branch**: `019-agent-status-cli`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: Add a dedicated status surface for agent execution, synthesis configuration, and provider-health readiness.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Inspect agent execution readiness (Priority: P1)

As the operator, I want a CLI command that reports whether the agent workflow is running through LangGraph or deterministic fallback.

**Independent Test**: Run `agent-status --format json` and verify executor and LangGraph availability fields exist.

### User Story 2 - Inspect synthesis configuration without leaking secrets (Priority: P1)

As the operator, I want the status command to show synthesis enabled/configured/model while never printing API keys.

**Independent Test**: Set synthesis env vars and verify JSON/text output reports configuration without exposing the key.

### User Story 3 - Inspect provider health readiness (Priority: P2)

As the operator, I want the same status command to report configured odds provider and whether The Odds API health metrics are available.

**Independent Test**: Set odds provider to The Odds API and verify status includes health capability fields without making live provider calls.
