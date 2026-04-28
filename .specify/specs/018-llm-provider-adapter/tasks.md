# Tasks: LLM Provider Adapter

**Input**: `.specify/specs/018-llm-provider-adapter/`
**Prerequisites**: `017-agent-llm-synthesis`

## Phase 1: Spec and contract

- [x] T001 Create `018-llm-provider-adapter` spec + plan + tasks artifacts.
- [x] T002 Add settings contract for default-off agent synthesis.

## Phase 2: TDD

- [x] T003 [P] [US1] Add failing tests for provider builder default-off behavior.
- [x] T004 [P] [US2] Add failing adapter tests for request/response handling.
- [x] T005 [P] [US3] Add failing doctor JSON test for synthesis provider flags.

## Phase 3: Implementation

- [x] T006 [US1] Implement settings and provider builder.
- [x] T007 [US2] Implement Portkey synthesis provider adapter.
- [x] T008 [US3] Wire provider into agent workflow builder and doctor output.

## Phase 4: Verification and continuity

- [x] T009 Run focused provider/agent/CLI verification.
- [x] T010 Update docs, progress, and memory artifacts.
