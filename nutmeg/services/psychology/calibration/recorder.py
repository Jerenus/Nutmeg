from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nutmeg.services.psychology.schemas import DualSchemeReport


@dataclass(slots=True)
class Recorder:
    base_dir: Path

    def _path(self, date: str) -> Path:
        return self.base_dir / date / "recorder.jsonl"

    def record(self, *, date: str, report: DualSchemeReport) -> None:
        path = self._path(date)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        for final_leg, dash in zip(report.final_scheme.legs, report.dashboard_rows, strict=False):
            rows.append({"date": date, "fixture_id": final_leg.fixture_id, "leg_id": final_leg.leg_id, "market": final_leg.market, "data_pick": dash.data_pick, "psych_pick": dash.psych_pick, "final_pick": final_leg.outcome, "provenance": final_leg.provenance, "conviction": dash.conviction, "hit": None})
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def update_outcome(self, *, date: str, fixture_id: str, market: str, actual_outcome: str) -> None:
        path = self._path(date)
        if not path.exists():
            return
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        for row in rows:
            if row["fixture_id"] == fixture_id and row["market"] == market:
                row["hit"] = row["final_pick"] == actual_outcome
        path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")

    def read(self, *, date: str) -> list[dict[str, Any]]:
        path = self._path(date)
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
