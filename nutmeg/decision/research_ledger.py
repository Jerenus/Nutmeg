"""Append-only run history for the JCZQ research runner."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path


def _atomic_json_write(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(document, handle, ensure_ascii=False, indent=1)
        temporary = Path(handle.name)
    os.replace(temporary, path)


class ResearchRunLedger:
    """Store one immutable JSON document for every research invocation."""

    def __init__(self, day_dir: Path) -> None:
        self._runs_dir = Path(day_dir) / "research-runs"

    def append(self, run: dict) -> dict:
        idempotency_key = str(run.get("idempotency_key", "")).strip()
        if not idempotency_key:
            raise ValueError("research run idempotency_key is required")
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        path = self._runs_dir / f"{digest}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        _atomic_json_write(path, run)
        return dict(run)

    def runs(self) -> list[dict]:
        if not self._runs_dir.exists():
            return []
        rows = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in self._runs_dir.glob("*.json")
        ]
        return sorted(rows, key=lambda row: (row["started_at"], row["run_id"]))

    def daily_projection(self) -> dict:
        runs = self.runs()
        matches = [
            {**match, "run_id": run["run_id"]}
            for run in runs
            for match in run["matches"]
        ]
        return {
            "day": runs[0]["day"] if runs else None,
            "run_count": len(runs),
            "runs": runs,
            "matches": matches,
        }

    def write_daily_projection(self, path: Path) -> dict:
        projection = self.daily_projection()
        _atomic_json_write(Path(path), projection)
        return projection
