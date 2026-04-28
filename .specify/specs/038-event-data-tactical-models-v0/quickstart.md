# Quickstart: Event Data Tactical Models v0

Generate a report from the bundled deterministic sample:

```bash
uv run nutmeg event-tactical-models --fixture-id epl-001 --format json
```

Generate a report from an explicit local file and write SVGs:

```bash
uv run nutmeg event-tactical-models \
  --fixture-id epl-001 \
  --events-file nutmeg/event_data/samples/epl-001-events.json \
  --output-dir .nutmeg-data/event-models \
  --format json
```

Text mode:

```bash
uv run nutmeg event-tactical-models --fixture-id epl-001
```

Expected behavior:

- Complete sample data produces pass-network, xT-lite, and VAEP-lite sections.
- Missing data produces unavailable labels rather than fabricated charts.
- Model labels must say `xT-lite-v0` and `VAEP-lite-heuristic-v0`.
