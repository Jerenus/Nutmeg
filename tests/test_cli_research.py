import json

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app


def test_research_board_run_intake_build_reads_pipeline(tmp_path, monkeypatch):
    root = tmp_path / "jczq"
    day_dir = root / "daily" / "2026-09-19"
    day_dir.mkdir(parents=True)
    (day_dir / "bold_odds.json").write_text(
        json.dumps(
            {
                "周五001": {
                    "match_winner": {
                        "odds": {"home": 2.0, "draw": 3.5, "away": 4.0}
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    import nutmeg.interfaces.cli.research as mod

    monkeypatch.setattr(
        mod,
        "_board_matches",
        lambda day, data_dir: [
            {
                "match_id": "m-1",
                "home_team": "A",
                "away_team": "B",
                "competition": "x",
                "scheduled_at": "2099-01-01T19:00:00+00:00",
                "board_code": "周五001",
            }
        ],
    )
    good = json.dumps(
        {
            "name": "A-B",
            "summary": "s",
            "confidence": 3,
            "anchor_integrity": "pass",
            "license_questions": {
                "q1_spine": True,
                "q2_route": True,
                "q3a_opponent_scores": False,
                "q3b_opponent_takes_points": False,
                "q4_no_context_flag": True,
            },
            "death_three_proofs": {},
            "directional_flags": [],
            "nondirectional_flags": [],
            "crash_markers": [],
            "precedents": [],
        }
    )
    monkeypatch.setattr(mod, "_claude", lambda system, brief: (0, good))
    monkeypatch.setattr(mod, "_fulfill", lambda argv: (0, ""))
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "research",
            "board",
            "--day",
            "2026-09-19",
            "--jczq-dir",
            str(root),
            "--data-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        app,
        [
            "research",
            "run",
            "--day",
            "2026-09-19",
            "--jczq-dir",
            str(root),
            "--data-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0 and "done" in result.output
    result = runner.invoke(
        app,
        [
            "research",
            "intake",
            "--day",
            "2026-09-19",
            "--jczq-dir",
            str(root),
            "--write",
        ],
    )
    assert result.exit_code == 0 and "周五001" in result.output
    result = runner.invoke(
        app,
        [
            "jczq-build-reads",
            "--day",
            "2026-09-19",
            "--jczq-dir",
            str(root),
        ],
    )
    assert result.exit_code == 0
    assert (day_dir / "reads.json").exists()


def test_r0_registry_doc_declares_a_per_match_duty():
    from nutmeg.decision.rsi_prereg import load_registry_doc

    doc = load_registry_doc("experiments/registry/R0.json")
    assert doc["population"] == "jczq"
    assert doc["tier"] == "observation"
    assert doc["layer"] == "judgment"
    duty = doc["duties"][0]
    assert duty["scope"] == "match"
    assert duty["deadline_rule"] == "match_kickoff"
    assert "{day}" in " ".join(duty["instrument"])
