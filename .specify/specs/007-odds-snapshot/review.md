# Coverage Review: Odds Snapshot and Fair Probability

## Requirements Extracted

- R01 [TESTABLE][OBSERVABLE]: Build an odds snapshot only for a fixture already present in the shared local fixture cache.
- R02 [TESTABLE][OBSERVABLE]: Expose source name, provider update time, and bookmaker coverage count.
- R03 [TESTABLE][OBSERVABLE]: Normalize stable supported markets including match winner, both teams to score, and at least one standard totals line.
- R04 [TESTABLE][OBSERVABLE]: Preserve available bookmaker quotes and keep incomplete or unavailable markets explicit.
- R05 [TESTABLE][OBSERVABLE]: Derive no-vig fair probabilities and fair odds only for complete two-way or three-way markets.
- R06 [TESTABLE][OBSERVABLE]: Expose consensus fair probability, average price, best price, and bookmaker coverage count per outcome.
- R07 [TESTABLE][OBSERVABLE]: Render the odds snapshot through a dedicated CLI workflow in text and JSON forms.
- R08 [TESTABLE][OBSERVABLE]: Fail cleanly for unknown fixture or missing provider config, while staying truthful when odds are unavailable.
- R09 [TESTABLE][STRUCTURAL]: Retain source attribution and keep raw bookmaker prices distinct from derived fair probabilities.
- R10 [STRUCTURAL]: Keep the provider boundary replaceable so a second provider can be added without changing the consumer-facing contract.
- R11 [TESTABLE][OBSERVABLE]: Persist and expose historical market summaries with movement and fair-vs-current drift signals.
- R12 [TESTABLE][STRUCTURAL]: Cover normalization, duplicate handling, fair-probability derivation, CLI rendering, history rendering, provider-selection behavior, and unavailable-provider behavior with tests.
- R13 [STRUCTURAL][OBSERVABLE]: Update architecture and continuity artifacts for the odds slice, provider choice, and historical-odds behavior.

## Coverage Matrix

| Req | Requirement | Tasks | Coverage |
|-----|-------------|-------|----------|
| R01 | Cached fixture is required | T002, T005, T007 | ✓ Covered |
| R02 | Source/update/bookmaker metadata | T003, T006, T008 | ✓ Covered |
| R03 | Stable supported markets | T003, T006 | ✓ Covered |
| R04 | Explicit incomplete/unavailable markets | T003, T004, T005, T007 | ✓ Covered |
| R05 | No-vig fair probabilities and fair odds | T004, T007 | ✓ Covered |
| R06 | Consensus, average, best price, coverage counts | T004, T007 | ✓ Covered |
| R07 | Dedicated CLI text and JSON | T002, T005, T008 | ✓ Covered |
| R08 | Unknown fixture / missing provider / no odds behavior | T005, T007, T008 | ✓ Covered |
| R09 | Source attribution and raw-vs-derived separation | T004, T007, T008 | ✓ Covered |
| R10 | Replaceable provider seam | T002, T006, T011 | ✓ Covered |
| R11 | Historical market summaries with movement/drift | T007, T011 | ✓ Covered |
| R12 | Required test coverage | T003, T004, T005, T011 | ✓ Covered |
| R13 | Docs and continuity updates | T008, T009, T010, T012 | ✓ Covered |

## Task Quality And TDD Readiness

- No uncovered requirements were found.
- Tasks T003-T005 explicitly establish RED-phase coverage before implementation tasks T006-T008.
- File paths are concrete after tightening T009 and T010.
- Tasks remain intentionally coarse at the feature-slice level, but still map cleanly to independent user-story outcomes.

## Coverage Review Summary

**Requirements extracted:** 13  
**Fully covered:** 13 (100%)  
**Partially covered:** 0  
**Gaps identified:** 0  
**Task quality issues:** 0  
**TDD readiness:** READY

**Decision:**

✓ COVERAGE COMPLETE — All current feature requirements have corresponding tasks, and `tasks.md` is ready for implementation.
