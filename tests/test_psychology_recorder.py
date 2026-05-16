from __future__ import annotations

import json
from pathlib import Path

from nutmeg.services.psychology.io import Recorder
from nutmeg.services.psychology.schemas import (
    DashboardRow,
    DataLeg,
    DualSchemeReport,
    FinalLeg,
    FinalScheme,
    GuardrailDecision,
    Scheme,
)


def _report() -> DualSchemeReport:
    return DualSchemeReport(
        Scheme("data", [DataLeg("L1", "f1", "HHAD", "home_win", 2.1)]),
        Scheme("psychology", [DataLeg("L1", "f1", "HHAD", "away_win", 2.45)]),
        FinalScheme([FinalLeg("L1", "f1", "HHAD", "away_win", 2.45, "psychology")], "medium", []),
        [DashboardRow("f1", "home_win", "away_win", True, "away_win", 0.8)],
        None,
        GuardrailDecision([], [], {"budget": "1/1"}),
    )


def test_record_writes_jsonl(tmp_path: Path) -> None:
    Recorder(base_dir=tmp_path).record(date="2026-04-29", report=_report())
    lines = (tmp_path / "2026-04-29" / "recorder.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["fixture_id"] == "f1"
    assert row["provenance"] == "psychology"
    assert row["hit"] is None


def test_update_outcome_marks_hits(tmp_path: Path) -> None:
    rec = Recorder(base_dir=tmp_path)
    rec.record(date="2026-04-29", report=_report())
    rec.update_outcome(date="2026-04-29", fixture_id="f1", market="HHAD", actual_outcome="away_win")
    assert rec.read(date="2026-04-29")[0]["hit"] is True


def test_update_outcome_marks_miss(tmp_path: Path) -> None:
    rec = Recorder(base_dir=tmp_path)
    rec.record(date="2026-04-29", report=_report())
    rec.update_outcome(date="2026-04-29", fixture_id="f1", market="HHAD", actual_outcome="home_win")
    assert rec.read(date="2026-04-29")[0]["hit"] is False
