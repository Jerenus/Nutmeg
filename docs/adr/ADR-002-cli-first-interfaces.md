# ADR-002: Keep interfaces CLI-first in Phase 1

- **Status**: Accepted
- **Date**: 2026-04-24

## Context

The design doc makes Phase 1 a private operator tool. The fastest path to useful feedback is a CLI plus a reusable service layer that can later power Telegram/Discord bots.

## Decision

Build the first runnable interface as a Typer CLI. Future IM bot and Web layers must reuse the same application services.

## Consequences

- The first verification target is a local CLI, not a web frontend.
- Service boundaries stay clean enough for later interface reuse.
- Frontend concerns are intentionally deferred until the data and agent core mature.
