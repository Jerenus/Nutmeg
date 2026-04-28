# Feature Specification: Value Board v0

**Feature Branch**: `031-value-board-v0`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: Close the main Sprint 3 gap from `Nutmeg-DESIGN-v0.3.md`: compare an independent model probability against market fair probability and generate a usable value board with Kelly sizing.

## User Scenarios & Testing

### User Story 1 - Price match outcomes with an independent baseline model (Priority: P1)

As the operator, I want Nutmeg to estimate home/draw/away probabilities from cached pre-match context so that odds analysis is not only a restatement of bookmaker fair prices.

**Independent Test**: Build a fixture snapshot with asymmetric xG trends and verify the model probabilities sum to one and favor the stronger expected-goals side.

### User Story 2 - Compare model probability to market fair probability (Priority: P1)

As the operator, I want each candidate to show model probability, market fair probability, edge, best odds, and quarter-Kelly fraction so I can see why a match is on the board.

**Independent Test**: Run the value service against deterministic fixture, snapshot, and odds fakes where the home side has a positive model edge, then verify the candidate includes edge and Kelly sizing.

### User Story 3 - Rank a league-level value board from the CLI (Priority: P1)

As the operator, I want `nutmeg value-board --league epl --days 3` to rank upcoming fixtures by value edge so I can quickly inspect the most interesting matches.

**Independent Test**: Monkeypatch the CLI service builder, run JSON output, and verify the board includes league, days, generated time, candidates, skipped fixtures, and no secrets.

## Functional Requirements

- **FR-001**: Nutmeg MUST provide a deterministic baseline football pricing model for match-winner outcomes.
- **FR-002**: Model output MUST include home, draw, and away probabilities that normalize to one.
- **FR-003**: Value board generation MUST use locally cached upcoming fixtures and existing snapshot/odds services.
- **FR-004**: Value candidates MUST include fixture identity, outcome key/name, model probability, market fair probability, edge, best odds, expected value, quarter-Kelly fraction, rating, and source notes.
- **FR-005**: The board MUST skip fixtures with unavailable snapshot/odds/model inputs without aborting the whole league board.
- **FR-006**: Candidates MUST be ranked by edge first, then Kelly fraction, then kickoff time.
- **FR-007**: The CLI MUST expose text and JSON output through `value-board`.
- **FR-008**: Tests MUST cover model math, value candidate assembly, skipped-fixture behavior, and CLI JSON contract.
- **FR-009**: Documentation, feature registry, memory, and graph assets MUST be updated after implementation.

## Key Entities

- **ModelProbabilitySet**: Home/draw/away probability output from the baseline model.
- **ValueCandidate**: One potentially mispriced fixture outcome with model-vs-market comparison and Kelly sizing.
- **ValueBoard**: League-level ranked collection of value candidates plus skipped fixtures and generation metadata.

## Success Criteria

- **SC-001**: `uv run nutmeg value-board --league epl --days 3 --format json` returns a parseable board payload when upstream providers are configured.
- **SC-002**: A deterministic service test produces at least one positive-edge candidate with non-zero quarter Kelly.
- **SC-003**: Full verification passes after the feature is integrated.

## Verification Evidence

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_dixon_coles.py tests/test_value_service.py tests/test_cli.py::test_value_board_command_returns_json_contract -q` -> 5 passed.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_dixon_coles.py tests/test_value_service.py tests/test_cli.py -q` -> 50 passed.
- `uv run ruff check .` -> pass.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q` -> pass.
- `python3 -m compileall nutmeg` -> pass.
- `bash scripts/verify.sh` -> 160 passed.
- `python3 scripts/refresh_graph.py --project-root . --output-dir graphify-out` -> 64 modules, 100 edges.
