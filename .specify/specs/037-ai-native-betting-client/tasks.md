# Tasks: AI-Native Betting Client

**Input**: Design documents from `.specify/specs/037-ai-native-betting-client/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/client-api.yaml`, `quickstart.md`

**Tests**: Required. The spec and constitution require Superpowers/TDD; each user-visible behavior starts with a failing test task before implementation.

**Organization**: Tasks are grouped by user story so each story can be implemented and tested independently after the shared foundation is complete.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it touches different files and does not depend on incomplete tasks
- **[Story]**: Maps to the user story in `spec.md` as `[US1]`, `[US2]`, `[US3]`, `[US4]`, or `[US5]`
- Every task names exact file paths

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add the minimal web/PWA dependency and package structure without implementing feature behavior.

- [x] T001 Add FastAPI, Jinja2, and Uvicorn runtime dependencies to `pyproject.toml`
- [x] T002 Create browser client package markers in `nutmeg/interfaces/web/__init__.py` and `nutmeg/interfaces/web/templates/__init__.py`
- [x] T003 [P] Create client static asset placeholders in `nutmeg/interfaces/web/static/client/app.css`, `nutmeg/interfaces/web/static/client/app.js`, and `nutmeg/interfaces/web/static/client/manifest.webmanifest`
- [x] T004 [P] Create client template placeholders in `nutmeg/interfaces/web/templates/client/layout.html`, `nutmeg/interfaces/web/templates/client/feed.html`, `nutmeg/interfaces/web/templates/client/match.html`, and `nutmeg/interfaces/web/templates/client/status.html`
- [x] T005 [P] Create architecture documentation stub in `docs/architecture/ai-native-client.md`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish domain, storage, service, app factory, and CLI seams that all user stories depend on.

**CRITICAL**: No user story work begins until this phase is complete.

- [x] T006 [P] Write failing domain tests for actionability, freshness, evidence, entitlement, and responsible-use constants in `tests/test_client_domain.py`
- [x] T007 Implement client domain enums and dataclasses in `nutmeg/domain/client.py`
- [x] T008 [P] Write failing SQLite repository tests for user isolation, entitlement lookup, watchlist upsert, alert grouping, and audit insertion in `tests/test_client_state_repository.py`
- [x] T009 Implement client state repository schema and methods in `nutmeg/storage/client_state_repository.py`
- [x] T010 [P] Write failing service-factory tests for dependency injection and owner default identity in `tests/test_client_service.py`
- [x] T011 Implement `ClientService` constructor, dependency container, and owner defaults in `nutmeg/services/client.py`
- [x] T012 [P] Write failing web app factory smoke tests for `/client/api/status` and `/client/manifest.webmanifest` in `tests/test_client_web.py`
- [x] T013 Implement FastAPI app factory, static mounting, manifest route, and status route in `nutmeg/interfaces/client_web.py`
- [x] T014 Write failing CLI registration tests for `client-feed`, `client-match`, `client-question`, `client-status`, and `client-web` help in `tests/test_cli.py`
- [x] T015 Register client CLI command stubs and web server entrypoint in `nutmeg/interfaces/cli.py`

**Checkpoint**: Shared client domain, storage, service, web, and CLI seams exist and fail safely.

---

## Phase 3: User Story 1 - Triage today's betting opportunities (Priority: P1) MVP

**Goal**: A user can open or request the daily feed and see ranked betting-analysis match opportunities with actionability, freshness, missing-evidence labels, and responsible-use copy.

**Independent Test**: Seed demo data, request `client-feed` or `/client/api/feed`, and verify top match cards expose rank, actionability, confidence, edge status, freshness, caveats, and next action without unsupported value calls.

### Tests for User Story 1

- [x] T016 [P] [US1] Write failing service test for top-three ranked daily feed from seeded popular/value/brief data within the local performance target in `tests/test_client_service.py`
- [x] T017 [P] [US1] Write failing service test for missing odds, lineup, player, tactical, and information sections forcing unavailable/stale labels in `tests/test_client_service.py`
- [x] T018 [P] [US1] Write failing service test for live or near-kickoff fixture risk lowering actionability or suggested action in `tests/test_client_service.py`
- [x] T019 [P] [US1] Write failing contract test for `GET /client/api/feed` matching `contracts/client-api.yaml` required fields in `tests/test_client_web.py`
- [x] T020 [US1] Write failing CLI JSON contract test for `nutmeg client-feed --league epl --days 3 --demo --format json` in `tests/test_cli.py`
- [x] T021 [US1] Write failing Chinese-first responsive HTML smoke test for `/client?league=epl&days=3&demo=true` daily feed cards in `tests/test_client_web.py`

### Implementation for User Story 1

- [x] T022 [US1] Implement daily feed aggregation over existing popular matches, value board, match brief summaries, and freshness states in `nutmeg/services/client.py`
- [x] T023 [US1] Implement actionability classification for value, lean, watch, avoid, and no-bet feed cards in `nutmeg/services/client.py`
- [x] T024 [US1] Implement unavailable/stale evidence blocking rules and responsible-use copy in `nutmeg/services/client.py`
- [x] T025 [US1] Implement `client-feed` JSON/text command in `nutmeg/interfaces/cli.py`
- [x] T026 [US1] Implement `/client/api/feed` and `/client` daily feed routes in `nutmeg/interfaces/client_web.py`
- [x] T027 [US1] Implement Chinese-first daily feed HTML card rendering in `nutmeg/interfaces/web/templates/client/feed.html`
- [x] T028 [US1] Implement desktop and mobile-width responsive daily feed styling in `nutmeg/interfaces/web/static/client/app.css`
- [x] T029 [US1] Document daily feed behavior and unsupported-value-call guardrails in `docs/architecture/ai-native-client.md`

**Checkpoint**: User Story 1 is independently usable as the MVP daily triage client.

---

## Phase 4: User Story 2 - Inspect one match as an AI-native analysis workspace (Priority: P1)

**Goal**: A user can open one match and see the grounded judgment, value/market/tactical/player/information evidence, caveats, source ledger, freshness, and audit id.

**Independent Test**: Request one fixture through `client-match` or `/client/api/matches/{fixture_id}` and verify judgment, actionability, evidence, caveats, source attribution, and audit trail are present.

### Tests for User Story 2

- [x] T030 [P] [US2] Write failing service test for match workspace assembly from match brief, value board, odds, tactical visuals, player profile, and information placeholders in `tests/test_client_service.py`
- [x] T031 [P] [US2] Write failing service test for market-vs-tactical conflict lowering or qualifying actionability in `tests/test_client_service.py`
- [x] T032 [P] [US2] Write failing service test for source attribution and timestamps on externally derived evidence in `tests/test_client_service.py`
- [x] T033 [P] [US2] Write failing repository test for analysis audit record creation without secrets in `tests/test_client_state_repository.py`
- [x] T034 [P] [US2] Write failing contract test for `GET /client/api/matches/{fixture_id}` matching `contracts/client-api.yaml` in `tests/test_client_web.py`
- [x] T035 [US2] Write failing CLI JSON contract test for `nutmeg client-match --fixture-id epl-001 --format json` in `tests/test_cli.py`
- [x] T036 [US2] Write failing HTML smoke test for `/client/matches/epl-001` showing judgment, counterargument, caveats, and freshness ledger in `tests/test_client_web.py`

### Implementation for User Story 2

- [x] T037 [US2] Implement match workspace aggregation and deterministic-output precedence in `nutmeg/services/client.py`
- [x] T038 [US2] Implement evidence extraction and source ledger mapping in `nutmeg/services/client.py`
- [x] T039 [US2] Implement conflict detection and actionability qualification in `nutmeg/services/client.py`
- [x] T040 [US2] Implement audit record persistence and retrieval hooks in `nutmeg/storage/client_state_repository.py`
- [x] T041 [US2] Implement `client-match` JSON/text command in `nutmeg/interfaces/cli.py`
- [x] T042 [US2] Implement `/client/api/matches/{fixture_id}` and `/client/matches/{fixture_id}` routes in `nutmeg/interfaces/client_web.py`
- [x] T043 [US2] Implement Chinese-first match workspace rendering in `nutmeg/interfaces/web/templates/client/match.html`
- [x] T044 [US2] Add desktop and mobile-width match workspace source-ledger and caveat styling in `nutmeg/interfaces/web/static/client/app.css`
- [x] T045 [US2] Document match workspace, source attribution, and audit behavior in `docs/architecture/ai-native-client.md`

**Checkpoint**: User Story 2 is independently usable for one-match analysis and audit review.

---

## Phase 5: User Story 3 - Ask grounded follow-up questions (Priority: P1)

**Goal**: A user can ask match-specific follow-up questions and receive grounded answers or truthful refusals that cite available evidence and preserve deterministic Nutmeg outputs.

**Independent Test**: Ask supported, stale-data, missing-data, and out-of-scope questions through `client-question` and `/client/api/matches/{fixture_id}/questions`; verify answer, refusal, evidence, and confidence behavior.

### Tests for User Story 3

- [x] T046 [P] [US3] Write failing service test for grounded follow-up answer using match workspace evidence in `tests/test_client_service.py`
- [x] T047 [P] [US3] Write failing service test for unsupported, speculative, stale, or out-of-scope question refusal in `tests/test_client_service.py`
- [x] T048 [P] [US3] Write failing service test proving deterministic verdicts, probabilities, and caveats override generated wording in `tests/test_client_service.py`
- [x] T049 [P] [US3] Write failing contract test for `POST /client/api/matches/{fixture_id}/questions` in `tests/test_client_web.py`
- [x] T050 [US3] Write failing CLI JSON contract test for `nutmeg client-question --fixture-id epl-001 --question "What changed?" --format json` in `tests/test_cli.py`
- [x] T051 [US3] Write failing Chinese-first HTML interaction smoke test for the match question form in `tests/test_client_web.py`

### Implementation for User Story 3

- [x] T052 [US3] Implement grounded question classification and evidence selection in `nutmeg/services/client.py`
- [x] T053 [US3] Implement truthful refusal and qualification rules for unsupported questions in `nutmeg/services/client.py`
- [x] T054 [US3] Implement conversational session audit persistence in `nutmeg/storage/client_state_repository.py`
- [x] T055 [US3] Implement `client-question` JSON/text command in `nutmeg/interfaces/cli.py`
- [x] T056 [US3] Implement question endpoint in `nutmeg/interfaces/client_web.py`
- [x] T057 [US3] Implement match workspace question form and answer rendering in `nutmeg/interfaces/web/templates/client/match.html`
- [x] T058 [US3] Add client-side progressive enhancement for the question form in `nutmeg/interfaces/web/static/client/app.js`
- [x] T059 [US3] Document grounded follow-up behavior and refusal policy in `docs/architecture/ai-native-client.md`

**Checkpoint**: User Story 3 is independently usable for grounded AI-native follow-up.

---

## Phase 6: User Story 4 - Use subscription-ready access and personalization (Priority: P2)

**Goal**: Two users have isolated preferences, entitlements, watchlists, alerts, prediction history, and premium gates while owner-only Phase 1 still works.

**Independent Test**: Seed owner and basic users, request feed/workspace/status, and verify gated sections, owner fallback, and no cross-user leakage.

### Tests for User Story 4

- [x] T060 [P] [US4] Write failing repository test for entitlement lookup, expiration, and owner fallback in `tests/test_client_state_repository.py`
- [x] T061 [P] [US4] Write failing service test for premium section gating without leaking hidden facts in `tests/test_client_service.py`
- [x] T062 [P] [US4] Write failing service test proving two users' watchlists, alerts, prediction records, and audit history stay isolated in `tests/test_client_service.py`
- [x] T063 [P] [US4] Write failing web test for restriction messaging on gated premium sections in `tests/test_client_web.py`
- [x] T064 [US4] Write failing CLI JSON contract test for `nutmeg client-status --user-id owner --format json` entitlement fields in `tests/test_cli.py`

### Implementation for User Story 4

- [x] T065 [US4] Implement entitlement models and repository methods in `nutmeg/storage/client_state_repository.py`
- [x] T066 [US4] Implement entitlement checks and owner-only fallback in `nutmeg/services/client.py`
- [x] T067 [US4] Implement premium gating in feed and workspace payloads in `nutmeg/services/client.py`
- [x] T068 [US4] Implement `client-status` entitlement and data-health output in `nutmeg/interfaces/cli.py`
- [x] T069 [US4] Implement gated-section messaging in `nutmeg/interfaces/client_web.py`
- [x] T070 [US4] Render Chinese-first gated states and user status in `nutmeg/interfaces/web/templates/client/status.html`
- [x] T071 [US4] Document entitlement boundaries and user-state isolation in `docs/architecture/ai-native-client.md`

**Checkpoint**: User Story 4 is independently usable for private beta and subscription-readiness validation.

---

## Phase 7: User Story 5 - Track alerts and calibration outcomes (Priority: P2)

**Goal**: A user can save matches, receive grouped material-change alerts, record simulated picks, and review calibration/outcome context without encouraging impulsive betting.

**Independent Test**: Save a match, simulate odds/lineup/information/value-edge changes, record a prediction, add an outcome, and verify grouped alerts plus calibration review.

### Tests for User Story 5

- [x] T072 [P] [US5] Write failing repository test for watchlist upsert and duplicate preference update in `tests/test_client_state_repository.py`
- [x] T073 [P] [US5] Write failing service test for material odds, lineup, injury, fixture-status, information, and value-edge alert creation in `tests/test_client_service.py`
- [x] T074 [P] [US5] Write failing service test for alert grouping and spam prevention by group key in `tests/test_client_service.py`
- [x] T075 [P] [US5] Write failing service test for client prediction recording linked to analysis audit and calibration review in `tests/test_client_service.py`
- [x] T076 [P] [US5] Write failing contract tests for `POST /client/api/watchlist`, `GET /client/api/alerts`, and `POST /client/api/predictions` in `tests/test_client_web.py`
- [x] T077 [US5] Write failing CLI JSON contract tests for watchlist, alert, and client prediction flows in `tests/test_cli.py`

### Implementation for User Story 5

- [x] T078 [US5] Implement watchlist upsert and alert preference behavior in `nutmeg/storage/client_state_repository.py`
- [x] T079 [US5] Implement material-change detection for alerts in `nutmeg/services/client.py`
- [x] T080 [US5] Implement alert grouping and read-state behavior in `nutmeg/storage/client_state_repository.py`
- [x] T081 [US5] Implement prediction recording integration with existing prediction repository and audit ids in `nutmeg/services/client.py`
- [x] T082 [US5] Implement watchlist, alerts, and client prediction CLI commands in `nutmeg/interfaces/cli.py`
- [x] T083 [US5] Implement watchlist, alerts, and prediction HTTP routes in `nutmeg/interfaces/client_web.py`
- [x] T084 [US5] Render watchlist controls, grouped alerts, and calibration review snippets in `nutmeg/interfaces/web/templates/client/feed.html` and `nutmeg/interfaces/web/templates/client/match.html`
- [x] T085 [US5] Add alert grouping and responsible-use UI styling in `nutmeg/interfaces/web/static/client/app.css`
- [x] T086 [US5] Document alert thresholds, grouping policy, prediction review, and no-dark-pattern constraints in `docs/architecture/ai-native-client.md`

**Checkpoint**: User Story 5 is independently usable for saved opportunities, change alerts, and calibration review.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Finish documentation, registry, packaging, graph assets, and full verification.

- [x] T087 [P] Update README client usage examples including Chinese-first copy and mobile/PWA entrypoints in `README.md`
- [x] T088 [P] Add `ai-native-betting-client` entry to `feature-list.json`
- [x] T089 [P] Add completion notes to `.specify/specs/037-ai-native-betting-client/verification.md`
- [x] T090 Update package data inclusion for templates and static assets in `pyproject.toml`
- [x] T091 Run focused client tests and record evidence in `.specify/specs/037-ai-native-betting-client/verification.md`
- [x] T092 Run `uv run ruff check .`, `python3 -m compileall nutmeg`, and `bash scripts/verify.sh`, then record evidence in `.specify/specs/037-ai-native-betting-client/verification.md`
- [x] T093 Refresh graph assets with `python3 scripts/refresh_graph.py --project-root . --output-dir graphify-out` and review `graphify-out/GRAPH_REPORT.md`
- [x] T094 Update `memory/2026-04-26.md` and `agent-progress.md` with implementation rationale and verification evidence
- [x] T095 Mark `.specify/specs/037-ai-native-betting-client/spec.md` status according to final verification result

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 Setup**: No dependencies.
- **Phase 2 Foundational**: Depends on Phase 1; blocks all user stories.
- **Phase 3 US1**: Depends on Phase 2; MVP daily feed.
- **Phase 4 US2**: Depends on Phase 2; can run after or alongside US1, but benefits from US1 actionability helpers.
- **Phase 5 US3**: Depends on Phase 4 workspace evidence because follow-up questions use match workspace context.
- **Phase 6 US4**: Depends on Phase 2; can run in parallel with US1/US2 after foundation, but gating must be integrated before public demo.
- **Phase 7 US5**: Depends on Phase 2 and benefits from US2 audit records.
- **Phase 8 Polish**: Depends on all implemented user stories targeted for the release.

### User Story Dependencies

- **US1**: Independent MVP after foundation.
- **US2**: Independent match workspace after foundation, with optional reuse of US1 actionability helpers.
- **US3**: Requires US2 workspace evidence to answer grounded follow-ups.
- **US4**: Independent subscription-readiness layer after foundation; integrates with feed/workspace before release.
- **US5**: Requires foundation and audit hooks; integrates with feed/workspace for saved matches and alerts.

### Within Each User Story

- Write failing tests first.
- Implement only enough behavior to make the failing tests pass.
- Keep deterministic Nutmeg outputs as source of truth.
- Verify story independently before moving to the next story.
- Do not place bets, connect sportsbooks, or hide stale/missing evidence.

## Parallel Opportunities

- T003, T004, and T005 can run in parallel after T001.
- T006, T008, T010, and T012 can run in parallel because they create different test files.
- US1 test tasks T016 through T019 can run in parallel; T020 and T021 share CLI/web files and should be sequenced with related implementation.
- US2 service/repository/web test tasks T030 through T034 can run in parallel.
- US3 service and web test tasks T046 through T049 can run in parallel.
- US4 test tasks T060 through T063 can run in parallel.
- US5 test tasks T072 through T076 can run in parallel.
- Documentation and feature registry polish tasks T087 through T089 can run in parallel.

## Parallel Example: User Story 1

```bash
# Parallel test-writing candidates for US1:
Task: "T016 [US1] Write failing service test for ranked daily feed in tests/test_client_service.py"
Task: "T019 [US1] Write failing contract test for GET /client/api/feed in tests/test_client_web.py"

# Then sequence shared-file implementation:
Task: "T022 [US1] Implement daily feed aggregation in nutmeg/services/client.py"
Task: "T026 [US1] Implement /client/api/feed in nutmeg/interfaces/client_web.py"
```

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 setup.
2. Complete Phase 2 foundation.
3. Complete Phase 3 User Story 1.
4. Validate `client-feed` and `/client` with seeded data.
5. Stop for review before expanding to workspace, chat, subscriptions, or alerts.

### Incremental Delivery

1. Foundation: domain, repository, service, web, CLI seams.
2. US1: Daily feed MVP.
3. US2: Match workspace and audit trail.
4. US3: Grounded follow-up analyst.
5. US4: Entitlements and user isolation.
6. US5: Watchlists, alerts, and calibration review.
7. Polish: docs, feature registry, verification, graph refresh.

### TDD and Verification Gates

- Run `speckit.superb.review` after this task file is generated.
- Before implementation, run `speckit.superb.tdd` and preserve RED test evidence for each story.
- Before completion, run `speckit.superb.verify` plus focused client tests, ruff, compileall, and `bash scripts/verify.sh`.
