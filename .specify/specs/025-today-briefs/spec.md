# Feature Specification: Today Briefs

**Feature Branch**: `025-today-briefs`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: Continue practical usability work by adding a command that lists today's locally available fixtures and can generate match briefs without manually entering fixture ids.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - List today's available fixtures (Priority: P1)

As the private operator, I want one command to show the fixtures available for briefing today or in a short lookahead window.

**Independent Test**: Seed demo/cache fixtures, run the command, and verify fixture ids, teams, kickoff, and brief command hints are rendered.

### User Story 2 - Generate multiple briefs from the fixture list (Priority: P1)

As the private operator, I want to ask for today briefs and receive per-fixture brief results without manually typing each fixture id.

**Independent Test**: Stub the workflow, run `today-briefs --briefs`, and verify each fixture gets a brief payload/text entry and failures are recorded per fixture.

### User Story 3 - Keep command local-first and machine-parseable (Priority: P1)

As a maintainer, I need the command to work with local cache/demo data and provide JSON output for automation.

**Independent Test**: Run text and JSON modes with `--demo`, verify no provider credentials are needed, and verify empty lists are truthful.
