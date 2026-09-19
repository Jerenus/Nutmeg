import json

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app

LQ4 = {
    "q1_spine": True,
    "q2_route": True,
    "q3a_opponent_scores": False,
    "q4_no_context_flag": True,
}


def _data_dir(tmp_path):
    zucai = tmp_path / "zucai"
    zucai.mkdir()
    (tmp_path / "jczq").mkdir()
    legs = {
        str(i): {
            "name": f"m{i}",
            "license_questions": LQ4,
            "anchor_integrity": "pass",
            "crash_markers": [],
            "fair": {"home": 0.6, "draw": 0.25, "away": 0.15},
            "_d3": {"away": {"a": True, "b": True, "c": False}},
            "face_status": {
                face: {
                    "state": "alive" if face == "home" else "dead",
                    "proofs": {},
                    "precedent": "none",
                    "source": "x",
                }
                for face in ("home", "draw", "away")
            },
        }
        for i in range(1, 15)
    }
    (zucai / "26130-legs-base.json").write_text(
        json.dumps({"issue": "26130", "legs": legs}), encoding="utf-8"
    )
    (zucai / "26130-issue.json").write_text(
        json.dumps(
            {
                "issue_id": "26130",
                "matches": [
                    {"match_no": i, "kickoff_bj": "2026-09-26 02:00"}
                    for i in range(1, 15)
                ],
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_tiers_frontier_choose_round_trip(tmp_path):
    data_dir = _data_dir(tmp_path)
    runner = CliRunner()
    out = runner.invoke(
        app, ["plan", "tiers", "--issue", "26130", "--data-dir", str(data_dir)]
    )
    assert out.exit_code == 0 and "风向" in out.output and "T1" in out.output
    out = runner.invoke(
        app,
        [
            "plan",
            "frontier",
            "--issue",
            "26130",
            "--channel",
            "renjiu",
            "--cap",
            "400",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert out.exit_code == 0 and "max P" in out.output and "strict" in out.output
    out = runner.invoke(
        app,
        [
            "plan",
            "choose",
            "--issue",
            "26130",
            "--channel",
            "renjiu",
            "--point",
            "0",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert out.exit_code == 0 and "26130-legs-renjiu.json" in out.output


def test_frontier_without_tiers_exits_one(tmp_path):
    data_dir = _data_dir(tmp_path)
    out = CliRunner().invoke(
        app,
        [
            "plan",
            "frontier",
            "--issue",
            "26130",
            "--channel",
            "renjiu",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert out.exit_code == 1 and "tiers" in out.output


def test_frontier_refuses_legs_without_face_status(tmp_path):
    data_dir = _data_dir(tmp_path)
    path = data_dir / "zucai" / "26130-legs-base.json"
    doc = json.loads(path.read_text("utf-8"))
    for leg in doc["legs"].values():
        leg.pop("face_status")
    path.write_text(json.dumps(doc), encoding="utf-8")
    runner = CliRunner()
    runner.invoke(
        app, ["plan", "tiers", "--issue", "26130", "--data-dir", str(data_dir)]
    )
    out = runner.invoke(
        app,
        [
            "plan",
            "frontier",
            "--issue",
            "26130",
            "--channel",
            "renjiu",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert out.exit_code == 1 and "face_status" in out.output


def _slips(tmp_path, rows):
    (tmp_path / "betslips.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_commit_baseline_then_status_shows_unregistered_ticket(tmp_path):
    data_dir = _data_dir(tmp_path)
    runner = CliRunner()
    runner.invoke(
        app, ["plan", "tiers", "--issue", "26130", "--data-dir", str(data_dir)]
    )
    runner.invoke(
        app,
        [
            "plan",
            "frontier",
            "--issue",
            "26130",
            "--channel",
            "renjiu",
            "--cap",
            "400",
            "--data-dir",
            str(data_dir),
        ],
    )
    runner.invoke(
        app,
        [
            "plan",
            "choose",
            "--issue",
            "26130",
            "--channel",
            "renjiu",
            "--point",
            "0",
            "--data-dir",
            str(data_dir),
        ],
    )
    _slips(
        data_dir,
        [{"slip_id": "26130-JC-A", "channel": "jczq", "stake_yuan": 100, "issue": None}],
    )
    out = runner.invoke(
        app,
        [
            "plan",
            "commit",
            "--issue",
            "26130",
            "--cap-source",
            "baseline",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert out.exit_code == 0, out.output
    assert "gate_cost" in out.output and "竞彩已登记 ¥100" in out.output
    out = runner.invoke(
        app, ["plan", "status", "--issue", "26130", "--data-dir", str(data_dir)]
    )
    assert out.exit_code == 0 and "没入账=没打" in out.output


def test_commit_override_without_adjudication_exits_one(tmp_path):
    data_dir = _data_dir(tmp_path)
    runner = CliRunner()
    runner.invoke(
        app, ["plan", "tiers", "--issue", "26130", "--data-dir", str(data_dir)]
    )
    runner.invoke(
        app,
        [
            "plan",
            "frontier",
            "--issue",
            "26130",
            "--channel",
            "renjiu",
            "--cap",
            "1200",
            "--data-dir",
            str(data_dir),
        ],
    )
    runner.invoke(
        app,
        [
            "plan",
            "choose",
            "--issue",
            "26130",
            "--channel",
            "renjiu",
            "--point",
            "0",
            "--data-dir",
            str(data_dir),
        ],
    )
    out = runner.invoke(
        app,
        [
            "plan",
            "commit",
            "--issue",
            "26130",
            "--cap-source",
            "override",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert out.exit_code == 1 and "adjudication" in out.output
