# Feature Specification: Graph Refresh Assets

**Feature Branch**: `021-graph-refresh`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: Generate local graph assets so future sessions can follow the graph-native workflow required by AGENTS.md.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Generate graph report locally (Priority: P1)

As future agents, we need `graphify-out/GRAPH_REPORT.md` to exist and summarize module structure before architecture/debugging work.

**Independent Test**: Run the graph refresh script against the repository and verify the report exists with module/edge/community sections.

### User Story 2 - Keep graph refresh deterministic and no-network (Priority: P1)

As the maintainer, I want graph generation to use only local source files and stable AST parsing.

**Independent Test**: Run script in tests and verify JSON edges are stable and contain known dependencies such as CLI to services.

### User Story 3 - Make graph refresh discoverable (Priority: P2)

As future sessions, we need Makefile/docs references for refreshing graph assets after structural changes.

**Independent Test**: Verify `make graph` exists and docs mention graph refresh.
