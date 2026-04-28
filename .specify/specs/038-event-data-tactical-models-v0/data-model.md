# Data Model: Event Data Tactical Models v0

## FootballEvent

- `event_id`: stable source or generated id.
- `fixture_id`: Nutmeg fixture id.
- `provider`: source provider label, e.g. `statsbomb-open-local`.
- `team`: team name.
- `player`: player name when available.
- `event_type`: normalized type such as `pass`, `shot`, `carry`, `duel`, `interception`, `tackle`.
- `period`, `minute`, `second`: match clock values.
- `x`, `y`: start location on a 120x80 pitch when available.
- `end_x`, `end_y`: end location for passes/carries when available.
- `outcome`: normalized outcome such as `complete`, `incomplete`, `goal`, `saved`, `won`, `lost`, or `unknown`.
- `xg`: shot expected-goals value when provided.
- `metadata`: provider-specific details retained for audit/debug.

Validation:

- Coordinates are clamped to 120x80 and warnings are emitted if raw coordinates were out of range.
- Missing team, player, location, or outcome does not crash normalization.
- Unknown event types are retained as lowercased provider type labels.

## EventDataQuality

- `fixture_id`
- `provider`
- `status`: `complete`, `partial`, or `unavailable`
- `event_count`
- `teams`
- `players`
- `warnings`
- `generated_at`

## PassNetwork

- `model_label`: always `pass-network-from-events-v0`.
- `nodes`: player/team node summaries with average location, event count, and pass count.
- `edges`: passer-to-recipient completed-pass counts with average start/end locations.
- `warnings`: sparse-data or missing-recipient notices.

## SpatialValueSummary

- `model_label`: always `xT-lite-v0`.
- `pitch`: 120x80.
- `grid`: zone values for a deterministic 12x8 grid.
- `actions`: successful pass/carry deltas with event id, player, team, start/end zones, and value_delta.
- `players`: aggregated xT-lite value by player.
- `warnings`: model limitations and sparse-data notices.

## PlayerContributionSummary

- `model_label`: always `VAEP-lite-heuristic-v0`.
- `players`: offensive, defensive, xg, xt, and total contribution by player.
- `warnings`: explicitly says this is not trained VAEP.

## EventVisualArtifact

- `artifact_id`: stable identifier.
- `title`
- `kind`: `pass_network`, `xt_heatmap`, or `contribution_bars`.
- `description`
- `svg`
- `file_path`: optional path when written to disk.

## EventTacticalReport

- `fixture_id`
- `quality`
- `pass_network`
- `spatial_value`
- `player_contributions`
- `artifacts`
- `unavailable_sections`
- `warnings`
- `generated_at`
