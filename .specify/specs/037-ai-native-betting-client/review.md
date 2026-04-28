# Superpowers Task Coverage Review: AI-Native Betting Client

Date: 2026-04-26  
Feature directory: `.specify/specs/037-ai-native-betting-client`

## Loaded Artifacts

- `spec.md`
- `plan.md`
- `tasks.md`
- `data-model.md`
- `contracts/client-api.yaml`
- `research.md`
- `quickstart.md`

## Extracted Requirements

- **R01 [OBSERVABLE]**: Daily view shows ranked match cards with kickoff, league, verdict class, confidence, edge/value status, freshness, and suggested next action.
- **R02 [TESTABLE]**: Missing odds, lineup, player, tactical, or information inputs remain visible and avoid false value calls.
- **R03 [TESTABLE]**: Live or near-kickoff fixtures highlight late-data risk before betting-analysis conclusions.
- **R04 [OBSERVABLE]**: Match workspace presents core judgment, reasons, counterargument, confidence, and caveats before secondary detail.
- **R05 [TESTABLE]**: Market-vs-tactical/team conflict is displayed and lowers or qualifies actionability.
- **R06 [TESTABLE]**: Latest injuries, lineup changes, and information claims include source and timestamp attribution.
- **R07 [TESTABLE]**: Follow-up questions with evidence receive grounded answers with facts, counterpoint, confidence, and freshness/source references.
- **R08 [TESTABLE]**: Missing, speculative, stale, or out-of-scope follow-ups receive truthful refusal or qualification.
- **R09 [TESTABLE]**: Deterministic Nutmeg verdicts, probabilities, and caveats take precedence over generated wording.
- **R10 [TESTABLE]**: Non-entitled users see restriction messaging without hidden premium facts.
- **R11 [TESTABLE]**: Two users' watchlists, alerts, preferences, prediction history, and audit state remain isolated.
- **R12 [OBSERVABLE]**: Owner-only Phase 1 mode works without public billing.
- **R13 [TESTABLE]**: Watched matches create concise material-change alerts with before/after and actionability context.
- **R14 [TESTABLE]**: Prediction or simulated-pick outcomes can be reviewed with calibration feedback.
- **R15 [TESTABLE]**: Repeated alerts for the same match are grouped to avoid spam.
- **R16 [TESTABLE]**: Provider down, quota exhausted, or unsynced fixture states are shown as unavailable or stale.
- **R17 [TESTABLE]**: Stale, suspended, removed, or materially divergent odds are not hidden behind confident value calls.
- **R18 [TESTABLE]**: Unverified, duplicate, or conflicting news/information is not promoted to actionable evidence.
- **R19 [TESTABLE]**: Postponed, abandoned, rescheduled, finished, or ambiguous fixtures are handled truthfully.
- **R20 [TESTABLE]**: Guaranteed profit, bet placement, sportsbook connection, and legal/financial advice requests are refused.
- **R21 [TESTABLE]**: Expired, non-entitled, or cross-user access attempts do not leak protected state.
- **R22 [TESTABLE]**: AI wording cannot exceed deterministic evidence confidence.
- **R23 [OBSERVABLE]**: Missing true event-data visuals are labeled as proxy or unavailable.
- **R24 [OBSERVABLE]**: Client provides an AI-native daily match feed ranked by betting-analysis interest.
- **R25 [TESTABLE]**: Match cards include fixture identity, competition, kickoff, state, verdict, confidence, value/edge, and next action.
- **R26 [TESTABLE]**: Data freshness is visible on every card and workspace for fixture, odds, team/player, tactical, and information sections.
- **R27 [TESTABLE]**: Unavailable/stale evidence is explicit and blocks value, stake, or confidence claims when minimum evidence is unmet.
- **R28 [OBSERVABLE]**: Workspace combines brief, value, odds, movement, tactics, player availability, information, caveats, and source attribution.
- **R29 [TESTABLE]**: Every match analysis has one actionability class: value, lean, watch, avoid, or no-bet.
- **R30 [TESTABLE]**: Every actionable analysis includes a counterargument or risk note.
- **R31 [TESTABLE]**: Conversational analyst answers only from available match, market, player, tactical, and information evidence.
- **R32 [TESTABLE]**: Conversational analyst refuses or qualifies unsupported, speculative, stale, or out-of-scope requests.
- **R33 [TESTABLE]**: Deterministic outputs override generated prose on disagreement.
- **R34 [TESTABLE]**: External facts include source name, retrieval/publication time where known, and related match/entity.
- **R35 [TESTABLE]**: Users can create watchlist entries for matches and competitions.
- **R36 [TESTABLE]**: Alerts cover odds, line movement, value edge, lineup, injury, fixture status, and information changes.
- **R37 [TESTABLE]**: Alerts summarize what changed, why it matters, and whether actionability changed.
- **R38 [TESTABLE]**: Users can record predictions or simulated picks and review outcomes with calibration metrics.
- **R39 [STRUCTURAL]**: Product never places bets, connects sportsbooks, automates wagering, promises profit, or presents financial advice.
- **R40 [OBSERVABLE]**: Responsible-gambling and risk-disclosure language appears in betting-analysis contexts.
- **R41 [TESTABLE]**: User state is isolated by user identity across preferences, watchlists, alerts, prediction history, and entitlements.
- **R42 [OBSERVABLE]**: Owner-only use works while preserving future subscriber entitlement boundaries.
- **R43 [TESTABLE]**: Subscription gating prevents non-entitled access to premium detail, alerts, history, and advanced analysis sections.
- **R44 [OBSERVABLE]**: Client exposes data-health status for fixture, odds, information, and analysis freshness.
- **R45 [OBSERVABLE]**: User-facing copy is Chinese-first while preserving accurate English names and market labels.
- **R46 [OBSERVABLE]**: Daily triage, match inspection, and follow-up questions work on desktop and mobile-width screens.
- **R47 [TESTABLE]**: Generated betting-analysis outputs preserve an audit trail of decision-time evidence.
- **R48 [STRUCTURAL]**: First release reuses existing Nutmeg outputs and does not introduce a separate client-side model or odds-pricing logic.
- **R49 [STRUCTURAL]**: Primary screens help decide whether a market is interesting, risky, stale, or not worth action.
- **R50 [TESTABLE]**: Truthfulness outranks engagement; no-opinion/wait-for-data is preferred over weak confident analysis.
- **R51 [STRUCTURAL]**: AI-native behavior means orchestration, prioritization, explanation, memory, and follow-up over grounded evidence.
- **R52 [TESTABLE]**: Client avoids dark patterns, compulsive-gambling cues, alert spam, and unsupported urgency.
- **R53 [STRUCTURAL]**: Subscription design separates account entitlement from shared objective football data.
- **R54 [STRUCTURAL]**: Work follows Spec Kit and Superpowers gates before implementation and completion claims.
- **R55 [STRUCTURAL]**: Client preserves existing Nutmeg service boundaries and does not duplicate CLI internals.
- **R56 [OBSERVABLE]**: Seeded users can identify top three opportunities, actionability, and caveats in under 2 minutes.
- **R57 [TESTABLE]**: 100% of acceptance cards/workspaces show freshness or unavailable indicators for required sections.
- **R58 [TESTABLE]**: 100% of stale, missing, and conflicting-data scenarios avoid unsupported value calls and display blockers.
- **R59 [TESTABLE]**: Follow-up answer/refusal completes within 10 seconds in 95% of local test runs.
- **R60 [TESTABLE]**: Entitlement tests show 100% user isolation across protected state and gated sections.
- **R61 [OBSERVABLE]**: User can save a match, receive a simulated material-change alert, and review before/after in under 1 minute.
- **R62 [OBSERVABLE]**: User can record a prediction and later review outcome/calibration feedback in the client.
- **R63 [STRUCTURAL]**: Audit review confirms no workflow places wagers, connects sportsbooks, promises profit, or hides responsible-use disclosures.
- **R64 [OBSERVABLE]**: Daily feed, match workspace, and follow-up analyst are usable on desktop and mobile-width screens.

## Coverage Matrix

| Req | Coverage Tasks | Status |
|-----|----------------|--------|
| R01 | T016, T020, T021, T022, T025, T026, T027 | Covered |
| R02 | T017, T024, T027, T028 | Covered |
| R03 | T018, T023, T024 | Covered |
| R04 | T030, T036, T037, T043 | Covered |
| R05 | T031, T039 | Covered |
| R06 | T032, T038, T045 | Covered |
| R07 | T046, T052, T056, T057 | Covered |
| R08 | T047, T053, T055, T059 | Covered |
| R09 | T048, T037, T052 | Covered |
| R10 | T061, T063, T067, T069, T070 | Covered |
| R11 | T008, T009, T062, T065, T066 | Covered |
| R12 | T060, T064, T066, T068 | Covered |
| R13 | T073, T079, T083, T084 | Covered |
| R14 | T075, T081, T084, T086 | Covered |
| R15 | T074, T080, T085, T086 | Covered |
| R16 | T017, T024, T068, T092 | Covered |
| R17 | T017, T031, T039, T079 | Covered |
| R18 | T030, T032, T038, T047, T053 | Covered |
| R19 | T017, T024, T037 | Covered |
| R20 | T047, T053, T059, T086, T092 | Covered |
| R21 | T060, T061, T062, T065, T067, T069 | Covered |
| R22 | T048, T037, T052 | Covered |
| R23 | T017, T024, T030, T043 | Covered |
| R24 | T016, T022, T026, T027 | Covered |
| R25 | T016, T020, T022, T025, T027 | Covered |
| R26 | T017, T024, T030, T037, T043 | Covered |
| R27 | T017, T024, T047, T053 | Covered |
| R28 | T030, T037, T038, T043 | Covered |
| R29 | T006, T007, T023, T037 | Covered |
| R30 | T030, T036, T037, T043 | Covered |
| R31 | T046, T052 | Covered |
| R32 | T047, T053 | Covered |
| R33 | T048, T037, T052 | Covered |
| R34 | T032, T038, T045 | Covered |
| R35 | T072, T078, T082, T083, T084 | Covered |
| R36 | T073, T079, T083, T084 | Covered |
| R37 | T073, T079, T080, T084 | Covered |
| R38 | T075, T081, T082, T083, T084 | Covered |
| R39 | T047, T053, T086, T092 | Covered |
| R40 | T024, T027, T043, T085, T086 | Covered |
| R41 | T008, T009, T062, T065, T066 | Covered |
| R42 | T060, T064, T066, T068, T070 | Covered |
| R43 | T061, T063, T067, T069, T070 | Covered |
| R44 | T012, T013, T064, T068, T070 | Covered |
| R45 | T021, T027, T043, T051, T070, T087 | Covered |
| R46 | T021, T028, T036, T044, T051, T064 | Covered |
| R47 | T033, T040, T054, T075, T081 | Covered |
| R48 | T022, T030, T037, T048, T055 | Covered |
| R49 | T016, T022, T023, T024, T029, T045 | Covered |
| R50 | T017, T024, T047, T053 | Covered |
| R51 | T046, T052, T057, T058, T059 | Covered |
| R52 | T074, T080, T085, T086 | Covered |
| R53 | T008, T009, T060, T065, T066, T071 | Covered |
| R54 | T091, T092, T095 | Covered |
| R55 | T011, T022, T030, T037, T045 | Covered |
| R56 | T016, T021, T022, T025, T026 | Covered |
| R57 | T017, T024, T030, T037, T043 | Covered |
| R58 | T017, T024, T031, T039, T047, T053 | Covered |
| R59 | T046, T047, T052, T053, T056 | Covered |
| R60 | T060, T061, T062, T065, T067 | Covered |
| R61 | T072, T073, T078, T079, T083, T084 | Covered |
| R62 | T075, T081, T082, T083, T084 | Covered |
| R63 | T047, T053, T086, T092 | Covered |
| R64 | T021, T028, T036, T044, T051, T058 | Covered |

## Coverage Gaps

No coverage gaps detected.

## Task Quality and TDD Readiness

- **Format**: PASS. 95/95 implementation tasks use strict Spec Kit checkbox format with sequential IDs and exact file paths.
- **User-story organization**: PASS. Tasks are grouped by US1 through US5 with independent tests and checkpoints.
- **Test-first coverage**: PASS. Each user story starts with failing test tasks before implementation tasks.
- **File specificity**: PASS. Every task names exact target files.
- **Broad-task risk**: LOW. Some service tasks aggregate multiple existing Nutmeg capabilities, but each is preceded by focused tests that constrain behavior.
- **Parallel safety**: PASS. Parallel markers are limited to tasks touching different files or test-only setup.
- **Superpowers readiness**: READY. `speckit.superb.tdd` can enforce RED/GREEN per story because test tasks precede implementation tasks.

## Status Synchronization

The Superpowers review workflow asks for `.specify/scripts/bash/sync-spec-status.sh --status "Tasked"`, but this repository currently does not contain `sync-spec-status.sh`. I did not invent a replacement script. The feature path is resolved through `.specify/feature.json`, and the review result is recorded here.

## Coverage Review Summary

**Requirements extracted**: 64  
**Fully covered**: 64 (100%)  
**Partially covered**: 0  
**Gaps identified**: 0  
**Task quality issues**: 0 blocking issues  
**TDD readiness**: READY

**Decision**: Coverage complete. `tasks.md` is ready for the mandatory TDD gate before implementation.
