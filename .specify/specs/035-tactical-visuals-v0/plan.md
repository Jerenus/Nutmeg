# Implementation Plan: Tactical Visuals v0

**Branch**: `035-tactical-visuals-v0` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/035-tactical-visuals-v0/spec.md`

## Summary

Add deterministic SVG tactical artifacts over existing fixture snapshot data. This
is a local-first v0 visualization layer, not a claim of event-level mplsoccer
parity. It creates usable visual attachments now while preserving a future path
to true event-data plots.

## Architecture

- `nutmeg.domain.tactics`: visual artifact and pack dataclasses.
- `nutmeg.services.tactics`: tactical visual pack builder and pure-SVG renderers.
- `nutmeg.interfaces.cli`: `tactical-visuals` text/JSON command.
- `docs/architecture/tactical-visuals.md`: scope, limitations, and CLI examples.

## Testing

Use fake snapshot service objects. Cover full visual generation, unavailable
section reporting, output-dir writes, and CLI JSON contract. No network calls.

## Constraints

- Do not add heavyweight plotting dependencies in this slice.
- Label lineup/pass-network artifacts as proxies unless true event/pass data is available.
- Keep SVG generation deterministic for tests and reproducibility.

