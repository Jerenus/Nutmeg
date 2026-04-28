# Implementation Plan: Eval and Review Loop

**Branch**: `033-eval-and-review-loop` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/033-eval-and-review-loop/spec.md`

## Summary

Add local eval datasets and a prediction review loop so Nutmeg can measure
judgment quality instead of only producing unscored opinions.

## Architecture

- `nutmeg.domain.evals`: eval case and prediction review dataclasses.
- `nutmeg.models.scoring`: Brier Score helpers.
- `nutmeg.storage.prediction_repository`: SQLite-backed prediction review rows.
- `nutmeg.services.evals`: eval runner and review aggregation.
- `nutmeg.interfaces.cli`: `eval-run`, `prediction-record`, `prediction-review`.

## Testing

Cover Brier Score math, local eval case parsing, prediction storage, and CLI JSON
contracts with no live provider calls.

