# Implementation Plan: Live Acceptance Scripts

**Branch**: `020-live-acceptance-scripts` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/020-live-acceptance-scripts/spec.md`

## Summary

Add `scripts/acceptance.sh` with safe default dry-run/no-network acceptance commands and explicit `--live` mode for provider-backed checks.

## Technical Context

**Language/Version**: bash + Python test harness  
**Primary Dependencies**: existing CLI commands  
**Storage**: no schema changes  
**Testing**: pytest subprocess tests  
**Constraints**: default must not call live providers; live mode must fail fast without keys
