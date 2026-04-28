# Tasks: Agent Status CLI

**Input**: `.specify/specs/019-agent-status-cli/`
**Prerequisites**: `014-provider-health-metrics`, `018-llm-provider-adapter`

## Phase 1: Spec and contract

- [x] T001 Create `019-agent-status-cli` spec + plan + tasks artifacts.
- [x] T002 Define no-network agent status payload contract.

## Phase 2: TDD

- [x] T003 [P] [US1] Add failing JSON status test for executor/LangGraph readiness.
- [x] T004 [P] [US2] Add failing text/JSON tests for synthesis config without key leakage.
- [x] T005 [P] [US3] Add failing JSON test for odds provider health capability.

## Phase 3: Implementation

- [x] T006 [US1] Implement status payload builder and CLI command.
- [x] T007 [US2] Add synthesis readiness fields without exposing secrets.
- [x] T008 [US3] Add odds provider health capability fields without live calls.

## Phase 4: Verification and continuity

- [x] T009 Run focused CLI/status verification.
- [x] T010 Update docs, progress, and memory artifacts.
