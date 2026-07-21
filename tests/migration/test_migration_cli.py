import json
from pathlib import Path

from typer.testing import CliRunner

import nutmeg.interfaces.cli as cli

MATCH = {"match_id": "old-m1", "home": "Alpha", "away": "Beta", "home_team_id": "t-a",
         "away_team_id": "t-b", "competition": "L", "competition_id": "c1",
         "kickoff_at": "2026-07-19T19:00:00+08:00", "channel_refs": {}}
SNAPSHOT = {"snapshot_id": "old-s1", "match_id": "old-m1", "kind": "closing",
            "fair": {"had": {"home": 0.5, "draw": 0.3, "away": 0.2}}, "raw_odds": {}, "lines": {},
            "source": "t", "taken_at": "2026-07-19T18:00:00+08:00"}
READ = {"read_id": "old-r1", "match_id": "old-m1", "snapshot_id": "old-s1", "market": "had",
        "prior": {"home": 0.5, "draw": 0.3, "away": 0.2},
        "belief": {"home": 0.6, "draw": 0.25, "away": 0.15}, "factors": [],
        "made_at": "2026-07-19T15:00:00+08:00"}
SETTLEMENT = {"settlement_id": "s1", "ref_type": "read", "ref_id": "old-r1",
              "outcome_90": "home", "brier": 0.245, "settled_at": "2026-07-20T10:00:00+08:00"}


def _write_golden(root: Path) -> None:
    decision = root / "decision"
    decision.mkdir(parents=True)
    for name, rows in {"matches": [MATCH], "snapshots": [SNAPSHOT], "reads": [READ],
                       "settlements": [SETTLEMENT]}.items():
        (decision / f"{name}.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_migrate_decision_store_cli(tmp_path: Path) -> None:
    source = tmp_path / "old"
    _write_golden(source)
    target = tmp_path / "new"
    result = CliRunner().invoke(cli.app, [
        "migrate-decision-store", "--source", str(source), "--target", str(target)])
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["counts"]["matches"] == 1
    assert summary["counts"]["reads"] == 1
    assert summary["reconciliation"]["matched"] == 1

    # target store was created; the source dir is untouched
    assert (target / "ontology").exists()
    assert json.loads((source / "decision" / "matches.jsonl").read_text())["match_id"] == "old-m1"
