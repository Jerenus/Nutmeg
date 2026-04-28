# Implementation Plan: Player Profile v0

**Branch**: `032-player-profile-v0` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/032-player-profile-v0/spec.md`

## Summary

Add a first-class player intelligence surface over the existing player identity,
Transfermarkt cache, and soccerdata materialization work.

## Architecture

- `nutmeg.domain.players`: profile, metrics, injury, and similarity dataclasses.
- `nutmeg.services.players`: identity resolution, cache reads, similarity ranking.
- `nutmeg.storage.reference_repository`: add focused player lookup/read helpers if needed.
- `nutmeg.interfaces.cli`: `player-profile` text/JSON.
- `docs/architecture/player-profile.md`: data contract and limitations.

## Testing

Use no-network fake/materialized rows. Cover identity resolution, provider missing
sections, similar-player ranking, and CLI JSON contract.

