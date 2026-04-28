# Feature Specification: Live Acceptance Scripts

**Feature Branch**: `020-live-acceptance-scripts`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: Script the current acceptance paths so local checks are repeatable and live provider checks are opt-in only.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run no-network acceptance by default (Priority: P1)

As the maintainer, I want an acceptance script that is safe to run locally without paid provider calls.

**Independent Test**: Execute `scripts/acceptance.sh --dry-run` and verify it prints the no-network command plan.

### User Story 2 - Gate live acceptance explicitly (Priority: P1)

As the operator, I want live provider acceptance to require `--live` and configured keys so accidental provider calls do not happen.

**Independent Test**: Run `scripts/acceptance.sh --live` without required key and verify it exits non-zero with a clear message before live commands.

### User Story 3 - Document acceptance workflow (Priority: P2)

As future agents, we need Makefile/docs entries so acceptance commands are discoverable.

**Independent Test**: Verify `make acceptance` target exists and script help mentions dry-run/live behavior.
