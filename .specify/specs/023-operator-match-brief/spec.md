# Feature Specification: Operator Match Brief

**Feature Branch**: `023-operator-match-brief`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: Continue unfinished product work by adding a single operator-facing pre-match brief command that packages fixture context, odds context, deterministic judgment, and optional agent synthesis.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Produce one pre-match operator brief (Priority: P1)

As the private operator, I want one command to return the match identity, agent execution status, deterministic judgment, confidence, key reasons, tactical evidence, market evidence, caveats, and generated synthesis when available.

**Independent Test**: Stub the existing agent workflow and verify JSON output includes `fixture_id`, `query`, `status`, `fixture`, `judgment`, `evidence`, `agent`, `generated_synthesis`, and `sections`.

### User Story 2 - Render a concise text brief (Priority: P1)

As the private operator, I want a readable text brief for terminal/IM use without opening raw JSON.

**Independent Test**: Stub the workflow and verify text output renders heading, verdict, confidence, reasons, market/tactical evidence, caveats, and synthesis.

### User Story 3 - Fail truthfully when evidence is insufficient (Priority: P1)

As the private operator, I need the command to preserve workflow failure semantics and not fabricate a brief when analysis fails.

**Independent Test**: Stub a failed workflow and verify the command exits non-zero with the workflow error in JSON/text.
