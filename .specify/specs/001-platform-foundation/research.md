# Research: Nutmeg Platform Foundation

## Decision 1: Spec Kit over OpenSpec

- **Chosen**: Spec Kit
- **Why**: Nutmeg needs a strong constitution/spec/plan/tasks workflow for a long-running product, and there is existing local precedent for Spec Kit style work.
- **Trade-off**: More structure up front than OpenSpec, but better alignment with the project's architecture-first and sprint-driven planning style.

## Decision 2: Superpowers Bridge as execution reliability layer

- **Chosen**: Install `superpowers-bridge` plus the required Superpowers skills.
- **Why**: The bridge adds TDD and verification gates exactly where a Codex/Spec Kit workflow tends to drift: before implementation and before completion claims.
- **Trade-off**: Adds process overhead, but the cost is acceptable for an analytical product that mixes data, prompts, and probabilistic outputs.

## Decision 3: Modular monolith for Phase 1

- **Chosen**: Single Python package with clear domains, repositories, and interfaces.
- **Why**: Phase 1 is single-user and CLI-first; operational simplicity matters more than distributed decomposition.
- **Trade-off**: Some future extraction work may be required, but repository and service seams keep that migration affordable.

## Decision 4: SQLite + DuckDB split

- **Chosen**: SQLite for mutable state, DuckDB as analytics cache later.
- **Why**: This matches the design doc's Phase 1 storage model while preserving a credible path to PostgreSQL and Redis.
- **Trade-off**: Two storage concepts exist early, but only SQLite is exercised directly in the first skeleton.

## Decision 5: Portkey-first, LangSmith-ready

- **Chosen**: Portkey configuration lives in settings; LangSmith remains opt-in and documentation-first in the initial slice.
- **Why**: This keeps the skeleton aligned with the user's established preference and avoids adding live LLM coupling before the surrounding service layer exists.
