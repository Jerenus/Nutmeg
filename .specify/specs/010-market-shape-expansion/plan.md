# Implementation Plan: Market Shape Expansion

**Branch**: `010-market-shape-expansion` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/010-market-shape-expansion/spec.md`
**Input**: Feature specification from `.specify/specs/010-market-shape-expansion/spec.md`

## Summary

Extend `analyze-match` so it consumes multiple canonical odds markets and produces a richer market-shape view covering result lean, scoring environment, and missing-market truthfulness.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: existing odds snapshot service, deterministic analysis service, Typer  
**Storage**: no new persistence; reuse existing normalized odds snapshot contract  
**Testing**: pytest + ruff  
**Target Platform**: macOS / CLI-first local runtime  
**Constraints**: deterministic only; reuse canonical odds normalization; no new provider layer  
**Scale/Scope**: deepen analysis using existing markets `match_winner`, `btts`, and `totals_2_5`

## Constitution Check

- **Spec-first delivery**: PASS — this slice stays isolated in a new feature package.
- **CLI-first**: PASS — the work lands on the current `analyze-match` surface.
- **Shared facts, isolated user state**: PASS — no new user state is introduced.
- **Phase-1 simplicity**: PASS — reuse of normalized odds keeps complexity bounded.

## Structure Decision

Extend the analysis domain contract with a distinct market-shape evidence bucket and keep all market interpretation logic inside the deterministic analysis service.
