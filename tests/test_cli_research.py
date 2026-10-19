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
            "rubric": {"version": "r1", "items": {"S_anchor_side": {"answer": "home"}}},
        }
    )
    monkeypatch.setattr(mod, "_claude", lambda system, brief: (0, good))
    monkeypatch.setattr(mod, "_fulfill", lambda argv: (0, ""))
    pending_reads: list = []
    monkeypatch.setattr(mod, "_read_pending", lambda data_dir: pending_reads.append(data_dir))
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
    # 研究一落盘就让读者 B 趁开球前补读（2026-10-05）
    assert pending_reads == [tmp_path]
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


def test_override_on_rubric_research_lands_on_items_with_a_reason(tmp_path, monkeypatch):
    import nutmeg.interfaces.cli.research as mod

    day_dir = tmp_path / "jczq" / "daily" / "2026-10-03"
    day_dir.mkdir(parents=True)
    (day_dir / "jczq-legs-base.json").write_text(json.dumps({"day": "2026-10-03", "legs": {
        "周五001": {"match_id": "m-1", "name": "A-B", "kickoff_bj": "2026-10-03T22:00:00+08:00",
                  "fair": {"home": 0.5, "draw": 0.3, "away": 0.2},
                  "judgment_tier": "deep_research", "faces": "310"}}}), encoding="utf-8")
    (day_dir / "research-周五001.json").write_text(json.dumps({
        "name": "A-B", "stance": {"face": "3", "tilt": None, "why_not_market": "none"},
        "rubric": {"version": "r1", "items": {"S_anchor_side": {
            "answer": "home", "p": 1.0, "abstain": False, "coerced": False}}}}),
        encoding="utf-8")
    monkeypatch.setattr(mod, "_refresh", lambda day, data_dir: None)
    bad = CliRunner().invoke(app, [
        "research", "override", "--day", "2026-10-03", "--code", "周五001", "--tilt-json",
        '{"face": "3", "evidence": []}', "--note", "x", "--data-dir", str(tmp_path)])
    assert bad.exit_code == 2 and "rubric" in bad.output
    good = CliRunner().invoke(app, [
        "research", "override", "--day", "2026-10-03", "--code", "周五001", "--items-json",
        '{"F_suspension": {"answer": "away", "p": 1.0, "source": "https://club.example/x", '
        '"captured_at": "2026-10-03T09:00:00+08:00"}}', "--reason", "new_official_info",
        "--note", "官宣", "--data-dir", str(tmp_path)])
    assert good.exit_code == 0, good.output
    assert "［new_official_info］" in good.output
    [row] = [json.loads(line) for line in
             (day_dir / "overrides.jsonl").read_text(encoding="utf-8").splitlines()]
    assert row["items"]["F_suspension"]["p"] == 1.0 and row["tilt"]["shift"]["0"] < 0


def test_intake_and_build_reads_skip_an_empty_board_day(tmp_path, monkeypatch):
    import nutmeg.interfaces.cli.research as mod

    jczq = tmp_path / "jczq"
    (jczq / "daily" / "2026-10-02").mkdir(parents=True)
    refreshed = []
    monkeypatch.setattr(mod, "_refresh", lambda day, data_dir: refreshed.append(day))
    out = CliRunner().invoke(app, ["research", "intake", "--day", "2026-10-02",
                                   "--jczq-dir", str(jczq), "--write"])
    assert out.exit_code == 0 and "空盘" in out.output
    out = CliRunner().invoke(app, ["jczq-build-reads", "--day", "2026-10-02",
                                   "--jczq-dir", str(jczq)])
    assert out.exit_code == 0 and "空盘" in out.output and refreshed == ["2026-10-02"]


def test_read_pending_is_a_side_path_that_never_breaks_the_refresh(tmp_path, monkeypatch):
    import nutmeg.decision.rubric_reader as reader
    import nutmeg.interfaces.cli.research as mod

    seen: list = []
    monkeypatch.setattr(reader, "pending_research", lambda data_dir: [tmp_path / "research-x.json"])
    monkeypatch.setattr(reader, "read_many",
                        lambda paths, workers: seen.append(paths) or {"done": ["x"], "failed": []})
    mod._read_pending(tmp_path)
    assert seen == [[tmp_path / "research-x.json"]]

    def boom(data_dir):
        raise RuntimeError("claude missing")

    monkeypatch.setattr(reader, "pending_research", boom)
    mod._read_pending(tmp_path)  # 不抛


def test_research_run_exits_nonzero_and_says_so_when_claude_is_logged_out(tmp_path, monkeypatch):
    """认证失败必须让定时任务变红并说清楚要重新登录；exit 0 会被当成「今天没场次」。"""
    import nutmeg.decision.research_runner as runner_mod

    monkeypatch.setattr(runner_mod, "run_day", lambda **kw: {
        "matches": [{"code": "周二001", "status": "auth_failed", "seconds": 2.5},
                    {"code": "周二002", "status": "skipped_auth"}],
        "used_attempts": 0, "written": 0, "auth_failed": True})
    result = CliRunner().invoke(app, ["research", "run", "--day", "2026-10-06",
                                      "--jczq-dir", str(tmp_path), "--data-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "认证失败" in result.output and "claude" in result.output
