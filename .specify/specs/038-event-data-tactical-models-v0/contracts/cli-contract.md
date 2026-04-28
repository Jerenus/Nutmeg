# CLI Contract: event-tactical-models

## Command

```bash
uv run nutmeg event-tactical-models \
  --fixture-id epl-001 \
  [--events-file path/to/events.json] \
  [--output-dir .nutmeg-data/event-models] \
  [--format text|json]
```

## JSON Output Shape

```json
{
  "fixture_id": "epl-001",
  "quality": {
    "fixture_id": "epl-001",
    "provider": "statsbomb-open-local",
    "status": "complete",
    "event_count": 12,
    "teams": ["Arsenal", "Tottenham Hotspur"],
    "players": ["Arsenal 6"],
    "warnings": [],
    "generated_at": "2026-04-26T00:00:00+00:00"
  },
  "pass_network": {
    "model_label": "pass-network-from-events-v0",
    "nodes": [],
    "edges": [],
    "warnings": []
  },
  "spatial_value": {
    "model_label": "xT-lite-v0",
    "pitch": {"length": 120, "width": 80},
    "grid": [],
    "actions": [],
    "players": [],
    "warnings": []
  },
  "player_contributions": {
    "model_label": "VAEP-lite-heuristic-v0",
    "players": [],
    "warnings": []
  },
  "artifacts": [
    {
      "artifact_id": "epl-001-pass-network",
      "title": "Pass Network",
      "kind": "pass_network",
      "description": "Completed pass network from event data.",
      "svg": "<svg...",
      "file_path": ".nutmeg-data/event-models/epl-001-pass-network.svg"
    }
  ],
  "unavailable_sections": [],
  "warnings": ["xT-lite-v0 is deterministic heuristic, not trained xT."]
}
```

## Text Output

Text mode prints fixture id, quality status, event count, model labels, top pass links, top xT-lite players, top VAEP-lite players, unavailable sections, and artifact paths.

## Failure Semantics

- Missing or empty event data returns exit code 0 with `quality.status=unavailable`, empty report sections, and `unavailable_sections` populated.
- Malformed JSON returns exit code 0 with `quality.status=unavailable` and a warning.
- CLI JSON stdout must remain parseable; provider noise must not be printed to stdout.
