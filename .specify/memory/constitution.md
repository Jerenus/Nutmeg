# Nutmeg Constitution

## Core Principles

### I. Spec-First Delivery
Every meaningful product or architectural change starts from the versioned design doc and a Spec Kit feature artifact. `Nutmeg-DESIGN-v0.3.md` defines product intent; `.specify/specs/*` defines executable delivery slices. Code that cannot be traced back to a spec is drift.

### II. CLI-First, Bot-Ready Interfaces
Phase 1 optimizes for a personal operator workflow. Every new workflow must be callable from the CLI first, and any IM bot surface must reuse the same service layer rather than duplicating logic.

### III. Shared Facts, Isolated User State
Objective football data is globally shared; preferences, history, quotas, and memory are always keyed by `user_id`. Any mutable state introduced in Phase 1 must remain migration-safe for Phase 2 and Phase 3.

### IV. Evidence-Backed Reliability
Superpowers Bridge is the operational quality gate. Implementation work follows: `specify -> plan -> tasks -> review -> implement -> verify`. No production behavior ships without a failing test first, and no completion claim is valid without fresh verification evidence.

### V. Phase-1 Simplicity, Phase-3 Readiness
Prefer the simplest Phase 1 implementation that preserves future seams: repository abstractions, configuration boundaries, and storage portability. Do not introduce cloud-native complexity before it is justified by real usage.

## Technical Constraints

- Python 3.12 is the baseline runtime.
- LLM traffic is Portkey-first; direct ad hoc provider coupling is forbidden.
- LangSmith traces are enabled only when configured, and sensitive per-user details must remain redactable.
- SQLite is the mutable state store for Phase 1; DuckDB is the analytical cache; PostgreSQL and Redis stay as planned migration targets.
- Mermaid diagrams are the preferred architecture notation for repo docs.

## Delivery and Review Workflow

- Product-wide changes must update both architecture docs and the relevant Spec Kit artifact.
- `speckit.superb.review` is the planning completeness gate after `tasks.md` changes.
- `speckit.superb.tdd` is the mandatory pre-implementation gate.
- `speckit.superb.verify` is the mandatory post-implementation gate.
- Any unresolved trade-off is recorded as an ADR before the implementation spreads across modules.

## Governance

This constitution overrides ad hoc local habits. Amendments require a documented reason, an updated ADR or design note, and an implementation migration plan when existing code is affected.

**Version**: 1.0.0 | **Ratified**: 2026-04-24 | **Last Amended**: 2026-04-24
