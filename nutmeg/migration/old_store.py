"""Read-only reader for the old append-only JSONL decision store.

The legacy ``DecisionStore`` kept one JSONL file per object type
(matches/snapshots/reads/tickets/settlements/factors/teams/leagues/verdicts). This
reader is strictly read-only — it never writes the source — and tolerates blank
lines. A missing file yields an empty list so a partial store imports cleanly.
"""
from __future__ import annotations

import json
from pathlib import Path

_FILES = {
    'matches': 'matches.jsonl',
    'snapshots': 'snapshots.jsonl',
    'reads': 'reads.jsonl',
    'factors': 'factors.jsonl',
    'tickets': 'tickets.jsonl',
    'settlements': 'settlements.jsonl',
    'verdicts': 'verdicts.jsonl',
    'teams': 'teams.jsonl',
    'leagues': 'leagues.jsonl',
}


def read_objects(decision_dir: Path, name: str) -> list[dict[str, object]]:
    filename = _FILES.get(name, f'{name}.jsonl')
    path = Path(decision_dir) / filename
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding='utf-8').splitlines():
        stripped = line.strip()
        if stripped:
            rows.append(json.loads(stripped))
    return rows
