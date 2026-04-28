# Implementation Plan: Value Board v0

**Branch**: `031-value-board-v0` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/031-value-board-v0/spec.md`

## Summary

Add the first true model-vs-market decision surface. The implementation uses a
deterministic Dixon-Coles-lite Poisson model over existing richer fixture
snapshots, compares model probabilities against the normalized match-winner
market from odds snapshots, and ranks value candidates with quarter-Kelly sizing.

## Technical Context

**Language/Runtime**: Python 3.12  
**Primary Dependencies**: stdlib dataclasses/datetime/math, existing Typer CLI, existing snapshot and odds services  
**Storage**: no new persistence; read from existing DuckDB fixture/snapshot/odds paths  
**Testing**: pytest with fake services and CLI monkeypatching; no network required  
**Constraints**: deterministic, source-attributed, truthful skips for missing data, no betting recommendation language beyond value diagnostics  

## Architecture

- `nutmeg.models.dixon_coles`: deterministic baseline pricing model and expected-goals extraction helpers.
- `nutmeg.domain.value`: value-board dataclasses for stable service/CLI contract.
- `nutmeg.services.value`: fixture iteration, snapshot/odds orchestration, model-vs-market comparison, ranking, skipped fixture capture.
- `nutmeg.interfaces.cli`: `value-board` command and builder wiring.
- `docs/architecture/value-board.md`: operator-facing architecture and limitations.

## Constitution Check

- **Spec-first**: PASS — this spec/plan/tasks package defines behavior before implementation.
- **CLI-first**: PASS — primary surface is `nutmeg value-board`.
- **Truthful data**: PASS — missing odds/snapshot/model inputs skip fixtures explicitly.
- **Local-first Phase 1**: PASS — no new remote dependency and no new state service.
- **TDD**: PASS — tests are written and watched fail before production code changes.

## Risks

- A Poisson/Dixon-Coles-lite baseline is not a fully trained Dixon-Coles model.
  The output must label itself as a baseline model and avoid overclaiming.
- Building snapshots for many fixtures can be slow with live providers. Limit
  defaults stay small and skipped fixtures are reported.
- Market value is only meaningful when match-winner odds are available. Other
  markets can be added later as separate specs.

