# Tasks: Popular Matches Ranking

**Input**: `.specify/specs/028-popular-matches-ranking/`
**Prerequisites**: `025-today-briefs`, `027-telegram-bot-daemon`

## Phase 1: Spec and contract

- [x] T001 Create `028-popular-matches-ranking` spec + plan + tasks artifacts.
- [x] T002 Define ranking score/tier/reasons and CLI JSON contract.

## Phase 2: TDD

- [x] T003 [P] [US1] Add failing deterministic ranker unit test.
- [x] T004 [P] [US2] Add failing `popular-matches` JSON CLI test.
- [x] T005 [P] [US3] Add failing `today-briefs --sort popularity` JSON test.

## Phase 3: Implementation

- [x] T006 [US1] Implement `MatchPopularityRanker` service.
- [x] T007 [US2] Implement `popular-matches` CLI text/JSON output.
- [x] T008 [US3] Wire optional popularity sorting into `today-briefs`.

## Phase 4: Verification and continuity

- [x] T009 Run focused popularity verification.
- [x] T010 Update README/progress/memory/feature-list.
- [x] T011 Refresh graph assets after service addition.
