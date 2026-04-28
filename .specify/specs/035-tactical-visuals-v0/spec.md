# Feature Specification: Tactical Visuals v0

**Feature Branch**: `035-tactical-visuals-v0`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: Close the remaining Sprint 2 tactical visualization gap from `Nutmeg-DESIGN-v0.3.md` with local-first visual artifacts over existing fixture snapshots.

## User Scenarios & Testing

### User Story 1 - Generate tactical visual artifacts for a fixture (Priority: P1)

As the operator, I want `nutmeg tactical-visuals --fixture-id <id>` to generate readable shot-map, lineup-network, and xG-trend visual artifacts from the existing snapshot context.

**Independent Test**: Build visuals from a deterministic fake snapshot and verify SVG artifacts are returned and optionally written to disk.

### User Story 2 - Keep visual limitations explicit (Priority: P1)

As the operator, I want Nutmeg to label proxy visuals clearly when event-level data is not available so I do not mistake aggregate data for true tracking/event plots.

**Independent Test**: Build visuals from a snapshot without lineup or shot-summary sections and verify unavailable sections are reported.

### User Story 3 - Expose visual output from CLI (Priority: P2)

As the operator, I want text and JSON CLI output plus an optional `--output-dir` so the visual pack can be used in Telegram/Web attachments later.

**Independent Test**: Monkeypatch the CLI builder, run JSON output, and verify artifact metadata and paths are stable.

## Functional Requirements

- **FR-001**: Provide a `tactical-visuals` CLI command.
- **FR-002**: Generate local SVG artifacts without requiring live provider calls or heavy plotting dependencies.
- **FR-003**: Include a shot-map-style visual from available shot summary aggregates.
- **FR-004**: Include a lineup-network proxy visual from confirmed/probable lineups when available.
- **FR-005**: Include a recent xG trend visual from matchup trend context when available.
- **FR-006**: Mark missing visual sections explicitly in `unavailable_sections`.
- **FR-007**: Support optional writing of artifacts to `--output-dir`.
- **FR-008**: Tests MUST cover service artifact generation, unavailable sections, output-dir writes, and CLI JSON contract.

## Key Entities

- **TacticalVisualArtifact**: one SVG artifact with status, source, description, inline SVG, and optional file path.
- **TacticalVisualPack**: fixture-level pack containing artifacts, insights, unavailable sections, and generation metadata.

## Success Criteria

- **SC-001**: `uv run nutmeg tactical-visuals --fixture-id epl-001 --format json` returns a parseable visual pack when snapshot inputs are available.
- **SC-002**: Service tests produce at least three SVG artifacts for a complete snapshot.
- **SC-003**: Full verification passes after integration.

## Verification Evidence

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_tactics_visuals.py tests/test_snapshot_service.py tests/test_cli.py::test_tactical_visuals_command_returns_json_contract -q` -> 13 passed.
- `uv run nutmeg tactical-visuals --fixture-id epl-001 --format json` -> fixture `epl-001`, 3 artifacts, no unavailable sections.
- `uv run ruff check .` -> all checks passed.
- `bash scripts/verify.sh` -> 175 passed.
- `python3 scripts/refresh_graph.py --project-root . --output-dir graphify-out` -> 74 modules / 118 edges.
