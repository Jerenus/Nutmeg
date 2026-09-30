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
            "stance": {
                "face": "3", "structure": "double", "cover": "1", "confidence": 3,
                "falsifier": "客队首发若有主力门将则本判断作废",
                "why_not_market": "none", "tilt": None, "alt_face": "1", "market_read": "agree",
            },
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


def test_override_records_the_ruling_and_refreshes_immediately(tmp_path, monkeypatch):
    """判断唯一事实 P1：改判记账后立刻刷新，改判成为内核里的新 revision。"""
    import nutmeg.interfaces.cli.research as mod

    day_dir = tmp_path / "jczq" / "daily" / "2026-09-19"
    day_dir.mkdir(parents=True)
    (day_dir / "jczq-legs-base.json").write_text(json.dumps({"day": "2026-09-19", "legs": {
        "周五001": {"match_id": "m-1", "name": "A-B", "kickoff_bj": "2026-09-20T03:00:00+08:00",
                  "fair": {"home": 0.6, "draw": 0.25, "away": 0.15},
                  "judgment_tier": "deep_research", "faces": "310"}}}), encoding="utf-8")
    (day_dir / "research-周五001.json").write_text(json.dumps(
        {"name": "A-B", "stance": {"face": "3", "tilt": {"shift": {"3": 3, "1": 0, "0": -3}}}}),
        encoding="utf-8")
    refreshed = []
    monkeypatch.setattr(mod, "_refresh", lambda day, data_dir: refreshed.append((day, data_dir)))

    result = CliRunner().invoke(app, [
        "research", "override", "--day", "2026-09-19", "--code", "周五001", "--market",
        "--note", "锚方证据不足，回到市场", "--data-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    [row] = [json.loads(line) for line in
             (day_dir / "overrides.jsonl").read_text(encoding="utf-8").splitlines()]
    assert row["tilt"] is None and row["note"] == "锚方证据不足，回到市场"
    assert refreshed == [("2026-09-19", tmp_path)]
