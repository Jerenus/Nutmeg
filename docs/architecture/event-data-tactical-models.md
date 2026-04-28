# Event Data Tactical Models

Nutmeg's event-data tactical models add a local-first layer for true event-sequence analysis. This is separate from the existing `tactical-visuals` proxy layer: proxy visuals work from fixture snapshots, while event-data models work from normalized pass, carry, shot, and defensive events.

## Scope

Implemented v0 capabilities:

- Local JSON loader for StatsBomb-like or simplified event files.
- Normalized `FootballEvent` domain records with fixture, team, player, event type, time, coordinates, outcome, xG, and provider metadata.
- Fixture-level quality state with `complete`, `partial`, or `unavailable` status.
- Completed-pass network nodes and edges from actual event locations.
- `xT-lite-v0` deterministic 12x8 spatial value model for successful progressive passes and carries.
- `VAEP-lite-heuristic-v0` player contribution summary combining xT-lite, shot xG, and simple defensive action credit.
- Deterministic SVG artifacts for pass network, xT-lite heatmap, and contribution bars.
- CLI surface: `nutmeg event-tactical-models`.

## CLI Usage

```bash
uv run nutmeg event-tactical-models --fixture-id epl-001 --format json
uv run nutmeg event-tactical-models \
  --fixture-id epl-001 \
  --events-file nutmeg/event_data/samples/epl-001-events.json \
  --output-dir .nutmeg-data/event-models \
  --format json
```

Text mode prints quality status, model labels, unavailable sections, artifact paths, and warnings.

## Data Contract

The local provider accepts:

- StatsBomb-like records with `type.name`, `team.name`, `player.name`, `location`, `pass.end_location`, `pass.recipient.name`, `shot.statsbomb_xg`, and nested outcomes.
- Simplified records with `event_type`, `team`, `player`, `x`, `y`, `end_x`, `end_y`, `outcome`, and `xg`.

Unknown provider fields are retained in event metadata for audit/debug. Missing or malformed files return `quality.status=unavailable` and empty report sections instead of fabricated events.

## Model Limitations

`xT-lite-v0` is a deterministic heuristic over a 120x80 pitch grid. It is useful for directional spatial context but is not a trained expected-threat model.

`VAEP-lite-heuristic-v0` combines simple event credits. It is not trained VAEP and must not be presented as a calibrated player valuation model.

Future specs can replace these heuristics with trained models, provider downloads, and mplsoccer rendering once enough event history and validation data are available.
