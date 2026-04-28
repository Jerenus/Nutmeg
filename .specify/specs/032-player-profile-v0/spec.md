# Feature Specification: Player Profile v0

**Feature Branch**: `032-player-profile-v0`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: Close the Sprint 4 player-module gap from `Nutmeg-DESIGN-v0.3.md`.

## User Scenarios & Testing

### User Story 1 - Inspect one player profile (Priority: P1)

As the operator, I want `nutmeg player-profile --player "Bukayo Saka" --team Arsenal`
to return identity, team, position, market value, injury state, and season metrics.

### User Story 2 - Compare similar players (Priority: P1)

As the operator, I want the profile to include similar-player candidates from
available per-90 metrics so I can reason about style and replacement options.

### User Story 3 - Keep missing provider data truthful (Priority: P2)

As the operator, I want missing Transfermarkt, soccerdata, or injury history
sections to be explicit rather than silently fabricated.

## Functional Requirements

- **FR-001**: Provide `player-profile` text/JSON CLI.
- **FR-002**: Resolve player identity through the existing alias/materialization layer.
- **FR-003**: Include Transfermarkt identity, team, position, current market value, and injury status when available.
- **FR-004**: Include soccerdata/FBref season metrics when available.
- **FR-005**: Include at least one deterministic similar-player score when enough metrics exist.
- **FR-006**: Return section-level unavailable reasons for missing provider data.
- **FR-007**: Keep the service no-network in tests with fixture-backed materialized data.

## Verification Evidence

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_player_profile_service.py tests/test_cli.py::test_player_profile_command_returns_json_contract -q` -> 3 passed.
- Focused new-feature suite with `tests/test_cli.py` -> 57 passed.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q` -> pass.
- `uv run ruff check .` -> pass.
- `python3 -m compileall nutmeg` -> pass.
- `bash scripts/verify.sh` -> 171 passed.
- `uv run nutmeg player-profile --league epl --season 2025 --team Arsenal --player "Bukayo Saka" --format json` -> JSON smoke pass when run serially.
