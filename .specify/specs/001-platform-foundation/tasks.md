# Tasks: Nutmeg Platform Foundation

**Input**: Design documents from `.specify/specs/001-platform-foundation/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md

**Tests**: Included because the foundation must prove CLI readiness and workflow reliability.

## Phase 1: Setup (Shared Infrastructure)

- [x] T001 Create the repository delivery framework: Spec Kit bootstrap, constitution, and foundation feature package.
- [x] T002 Install Superpowers Bridge and the required local skills for TDD and verification gates.
- [x] T003 Add root project files: `README.md`, `pyproject.toml`, `.env.example`, `.gitignore`, `Makefile`.

## Phase 2: Foundational (Blocking Prerequisites)

- [x] T004 Create the package layout under `nutmeg/` for config, core, process, storage, agents, services, and interfaces.
- [x] T005 Add the core domain models for identity, quota placeholders, fixtures, and odds utilities.
- [x] T006 Add storage bootstrapping and a SQLite-backed fixture repository with `user_id`-aware state APIs.
- [x] T007 Add Superpowers Bridge inspection logic and expose it through the CLI doctor path.
- [x] T008 Add architecture docs and ADRs aligned with `Nutmeg-DESIGN-v0.3.md`.

## Phase 3: User Story 1 - Operate the Phase 1 CLI shell (Priority: P1)

**Goal**: deliver a runnable local CLI for environment readiness and demo fixtures.

**Independent Test**: `uv run nutmeg doctor` and `uv run nutmeg fixtures --league epl --demo`

- [x] T009 [US1] Write CLI tests for `doctor` and `fixtures --demo`.
- [x] T010 [US1] Implement `nutmeg.interfaces.cli` with `doctor`, `fixtures`, and `seed-demo` commands.
- [x] T011 [US1] Render human-readable fixture output and JSON doctor output.

## Phase 4: User Story 2 - Preserve multi-tenant-ready boundaries (Priority: P2)

**Goal**: keep Phase 1 simple without losing future storage and identity seams.

**Independent Test**: inspect repository signatures and identity tests.

- [x] T012 [US2] Write tests for owner identity defaults and fixture repository behavior.
- [x] T013 [US2] Implement identity, quota, repository protocols, and SQLite repository plumbing.
- [x] T014 [US2] Add configuration defaults, per-user preferences, and seed fixture helpers.

## Phase 5: User Story 3 - Enforce specification and reliability workflow (Priority: P3)

**Goal**: make the repo self-describing and verification-aware.

**Independent Test**: inspect docs and run Superpowers bridge readiness tests.

- [x] T015 [US3] Write tests for bridge readiness inspection and router intent classification.
- [x] T016 [US3] Implement bridge inspection module and architecture/reference docs.
- [x] T017 [US3] Document reliability gates and ADR decisions.

## Phase 6: Polish & Cross-Cutting Concerns

- [x] T018 Run local verification for tests and doctor command.
- [x] T019 Add live provider integration slices in future sprint-specific specs.
- [x] T020 Track graph refresh readiness once the code graph is large enough to justify it.
