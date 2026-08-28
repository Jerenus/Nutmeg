# Scoreboard Projection Rebuild Design

Date: 2026-08-28  
Status: Approved for implementation  
Scope: T1 - expose the existing ontology analytics projection build as an explicit CLI

## 1. Problem and verified root cause

`scoreboard shadow` rejects a projection when a committed operational Action exists after
the projection's frozen SQLite high-watermark. This is correct: a shadow review must not
compare the legacy scoreboard against a projection that predates operational truth.

The current `decision-calibrate` command is not the ontology projection builder. It reads
and writes the legacy JSONL `DecisionStore`, producing `FactorVerdict` rows and a markdown
panel. It neither calls `CalibrateService.build` nor advances the SQLite Action log.
Production evidence on 2026-08-28 showed a scoreboard projection at Action watermark 5556
and the operational store at watermark 5636. The intervening rows were committed prediction,
scoreboard-observation, ingestion, identity, match, and adjudication Actions. The stale
failure was therefore caused by not rebuilding after legitimate writes, not by the legacy
FactorVerdict writes described in the handoff.

## 2. Approaches considered

### A. Add `scoreboard rebuild-projection` (selected)

Expose the existing read-only `CalibrateService.build` through the governed scoreboard CLI.
The operator runs it after all operational writes and before `scoreboard shadow`. This keeps
the M5 projection boundary explicit and agrees with the existing M5 operations contract,
which says legacy `decision-calibrate` must not substitute for ontology calibration.

### B. Make `decision-calibrate` write verdicts and then build the ontology projection

This would make the short sequence in the handoff work, but it would combine two persistence
systems with different roots and lifecycle semantics. It would also make a legacy JSONL
command an implicit M5 authority operation. This approach is rejected.

### C. Rebuild automatically inside `scoreboard shadow`

This would hide the frozen input boundary and make a review command mutate its analytical
inputs. It would also weaken the operator's ability to archive and inspect the exact
projection identity before shadowing. This approach is rejected.

## 3. Command contract

Add:

```text
nutmeg scoreboard rebuild-projection \
  --data-dir <ontology data root> \
  --as-of <aware ISO-8601 timestamp> \
  --built-at <aware ISO-8601 timestamp>
```

`--data-dir` uses the existing scoreboard kernel guard: the ontology must be initialized,
healthy, and have no pending migrations. `--as-of` controls the effective-time view used by
the scoreboard projector. `--built-at` is explicit provenance and must be timezone-aware.

On success the command emits the existing canonical one-line JSON format with:

- `status`, `run_id`, `projection_version`, and `source_high_watermark`;
- scorecard/factor/lifecycle/regime counts already returned by `CalibrateResult`;
- resolved `data_dir`, ontology database, and analytics database targets.

The projection version is `sb-v1`, the registered version of the scoreboard projector. The
CLI must not infer it by querying arbitrary rows or accept a caller-supplied version.

On invalid timestamps, unhealthy ontology state, or a failed projection run, the command
emits `scoreboard_operation_blocked` and exits 1. A failed build preserves the last good
projection under the existing keep-last-good contract.

## 4. Data flow and authority boundary

```text
operational typed Actions
  -> explicit rebuild-projection
  -> CalibrateService.build at max(actions.rowid)
  -> DuckDB sb-v1 rows stamped with that watermark
  -> operator supplies returned watermark to scoreboard shadow
```

The command writes only recomputable DuckDB projection state. It does not create an Action,
change a Factor lifecycle, modify `scoreboard.json`, create a shadow review, or perform a
cutover. It never touches production unless the operator explicitly points `--data-dir` at
production; tests and verification use isolated temporary roots.

The corrected operational sequence is:

```text
decision-calibrate (only when the legacy panel is still wanted)
  -> scoreboard rebuild-projection
  -> scoreboard shadow
```

## 5. Test design

Focused CLI tests will prove:

1. A build-only invocation emits `sb-v1` and the current Action watermark.
2. An operational Action recorded after an earlier build makes shadow stale.
3. Running `rebuild-projection` after that Action, then shadowing with the returned watermark,
   commits a shadow review without a stale error.
4. Naive timestamps and unhealthy/uninitialized roots fail with exit code 1.
5. The command creates no new SQLite Action row.

The acceptance chain uses only temporary SQLite/DuckDB data, fixture `scoreboard.json`, and
fixture classification JSON. It performs no authority cutover or compatibility export.

## 6. Explicit exclusions

- No change to legacy `decision-calibrate` behavior.
- No implicit rebuild in `scoreboard shadow`.
- No `scoreboard cutover`, SOP authority change, production data mutation, or launchd change.
- No automatic lifecycle decision or other business write.
