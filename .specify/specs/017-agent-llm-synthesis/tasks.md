# Tasks: Agent LLM Synthesis Guard

**Input**: `.specify/specs/017-agent-llm-synthesis/`
**Prerequisites**: `016-agent-execution-path`

## Phase 1: Spec and contract

- [x] T001 Create `017-agent-llm-synthesis` spec + plan + tasks artifacts.
- [x] T002 Extend agent workflow result contract with optional generated synthesis.

## Phase 2: TDD

- [x] T003 [P] [US1] Add failing workflow test for provider-generated guarded synthesis.
- [x] T004 [P] [US2] Add failing workflow test for skipped synthesis without provider.
- [x] T005 [P] [US3] Add failing workflow/CLI tests for guard rejection.

## Phase 3: Implementation

- [x] T006 [US1] Implement synthesis provider protocol and guarded provider node.
- [x] T007 [US2] Keep no-provider path successful and explicit.
- [x] T008 [US3] Reject drifted synthesis and expose failure truthfully.

## Phase 4: Verification and continuity

- [x] T009 Run focused workflow/CLI verification.
- [x] T010 Update architecture, progress, and memory artifacts.
