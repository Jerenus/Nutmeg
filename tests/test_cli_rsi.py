import json
import sqlite3
from hashlib import sha256
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app
from nutmeg.interfaces.cli import rsi as rsi_cli

DOC = {
    "exp_id": "F2", "claim": "c", "mechanism": "m", "tier": "observation", "layer": "judgment",
    "population": "zucai", "min_tier": "price_only",
    "window": {"issue_from": "26126", "issue_to": "26137"},
    "falsifier": {"metric": "home_resid_pp", "stratum": "zucai", "n_min": 140,
                  "bound": "ci_upper", "threshold_pp": 2.0, "direction": "lt_means_falsified"},
    "stop_rule": "n≥140", "quota_slot": False, "buckets": ["向主 ≥+0.5"], "rule_ids": [],
    "source_doc": "experiments/prereg-26126-F1c-F2.json", "registered_at": "2026-09-14",
    "duties": [{"name": "f2-observation", "scope": "day", "deadline_rule": "earliest_kickoff",
                "instrument": ["python", "scripts/zucai_f2_observe.py", "record",
                               "--issue", "{issue}"],
                "artifact_glob": ".nutmeg-data/zucai/{issue}-f2-observation.json"}],
}


def _data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    (d / "zucai").mkdir(parents=True)
    (d / "zucai" / "26129-issue.json").write_text(json.dumps({"issue_id": "26129", "matches": [
        {"match_no": 4, "kickoff_bj": "2026-09-19T00:30:00"},
        {"match_no": 1, "kickoff_bj": "2026-09-19T03:00:00"}]}), encoding="utf-8")
    (d / "zucai" / "26129-store-ids.json").write_text(
        json.dumps(
            {
                "4": {"match_no": 4, "match_id": "m-0"},
                "1": {"match_no": 1, "match_id": "m-1"},
            }
        ),
        encoding="utf-8",
    )
    day_dir = d / "jczq" / "daily" / "2026-09-19"
    day_dir.mkdir(parents=True)
    day_dir.joinpath("jczq-legs-base.json").write_text(
        json.dumps(
            {
                "legs": {
                    "周五001": {
                        "match_id": "m-0",
                        "kickoff_bj": "2026-09-19T00:30:00+08:00",
                    },
                    "周五002": {
                        "match_id": "m-1",
                        "kickoff_bj": "2026-09-19T03:00:00+08:00",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    return d


def test_register_schedule_due_status_round_trip(tmp_path):
    d = _data_dir(tmp_path)
    doc = tmp_path / "F2.json"
    doc.write_text(json.dumps(DOC), encoding="utf-8")
    r = CliRunner().invoke(app, ["rsi", "register", "--by", "Jun", str(doc), "--data-dir", str(d)])
    assert r.exit_code == 0, r.output
    assert "F2" in r.output and "frozen" in r.output
    r = CliRunner().invoke(app, ["rsi", "schedule", "--day", "2026-09-19", "--issue", "26129",
                                 "--data-dir", str(d)])
    assert r.exit_code == 0, r.output
    r = CliRunner().invoke(app, ["rsi", "due", "--day", "2026-09-19", "--data-dir", str(d),
                                 "--now", "2026-09-18T20:00:00+08:00"])
    assert "f2-observation" in r.output and "00:30" in r.output
    assert "scripts/zucai_f2_observe.py record --issue 26129" in r.output   # 占位已填
    r = CliRunner().invoke(app, ["rsi", "status", "--data-dir", str(d)])
    assert r.exit_code == 0 and "F2" in r.output and "registered" in r.output


def test_verdict_before_n_min_exits_nonzero_with_the_shortfall(tmp_path):
    d = _data_dir(tmp_path)
    doc = tmp_path / "F2.json"
    doc.write_text(json.dumps(DOC), encoding="utf-8")
    CliRunner().invoke(app, ["rsi", "register", "--by", "Jun", str(doc), "--data-dir", str(d)])
    r = CliRunner().invoke(app, ["rsi", "verdict", "--exp", "F2", "--data-dir", str(d)])
    assert r.exit_code == 1 and "prospective" in r.output


def test_register_twice_is_refused(tmp_path):
    d = _data_dir(tmp_path)
    doc = tmp_path / "F2.json"
    doc.write_text(json.dumps(DOC), encoding="utf-8")
    CliRunner().invoke(app, ["rsi", "register", "--by", "Jun", str(doc), "--data-dir", str(d)])
    r = CliRunner().invoke(app, ["rsi", "register", "--by", "Jun", str(doc), "--data-dir", str(d)])
    assert r.exit_code == 1 and "已登记" in r.output


def test_register_can_fork_a_new_population_into_a_new_registry_doc(tmp_path):
    data_dir = _data_dir(tmp_path)
    source = tmp_path / "F2.json"
    source.write_text(json.dumps(DOC), encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(
        app, ["rsi", "register", "--by", "Jun", str(source), "--data-dir", str(data_dir)]
    ).exit_code == 0
    target = tmp_path / "F2j.json"

    result = runner.invoke(
        app,
        [
            "rsi",
            "register", "--by", "Jun",
            str(target),
            "--fork-from",
            "F2",
            "--population",
            "jczq",
            "--window-from",
            "2026-09-20",
            "--data-dir",
            str(data_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    fork = json.loads(target.read_text(encoding="utf-8"))
    assert fork["exp_id"] == "F2j" and fork["forked_from"] == "F2"
    assert fork["claim"] == DOC["claim"] and fork["mechanism"] == DOC["mechanism"]
    assert fork["falsifier"] == {**DOC["falsifier"], "stratum": "jczq"}
    assert fork["window"] == {"date_from": "2026-09-20", "n_min": 140}
    status = runner.invoke(
        app, ["rsi", "status", "--exp", "F2j", "--data-dir", str(data_dir)]
    )
    assert status.exit_code == 0 and "F2j" in status.output


def test_register_refuses_to_fork_an_experiment_with_a_verdict(tmp_path):
    from nutmeg.config.settings import AppSettings
    from nutmeg.ontology import build_ontology_kernel
    from nutmeg.ontology.repository.rsi import GradeRow, VerdictRow
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

    data_dir = _data_dir(tmp_path)
    source = tmp_path / "F2.json"
    source.write_text(json.dumps(DOC), encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(
        app, ["rsi", "register", "--by", "Jun", str(source), "--data-dir", str(data_dir)]
    ).exit_code == 0
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir.resolve()))
    kernel.initialize()
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.rsi.insert_grade(
            GradeRow(
                grade_id="grade-settled",
                exp_id="F2",
                mode="prospective",
                stratum="zucai",
                n_cum=140,
                metric="home_resid_pp",
                metric_value_pp=0,
                ci_low_pp=-1,
                ci_high_pp=1,
                distance_to_falsifier_pp=0,
                cost_axis_pp=None,
                as_of_policy="test",
                computed_by="test",
                inputs_hash="test",
                graded_at="2026-09-20T12:00:00+08:00",
            )
        )
        uow.rsi.insert_verdict(
            VerdictRow(
                verdict_id="verdict-settled",
                exp_id="F2",
                verdict="inconclusive",
                grade_id="grade-settled",
                criterion_snapshot={},
                decided_at="2026-09-20T12:01:00+08:00",
            )
        )

    target = tmp_path / "F2j.json"
    result = runner.invoke(
        app,
        [
            "rsi",
            "register", "--by", "Jun",
            str(target),
            "--fork-from",
            "F2",
            "--population",
            "jczq",
            "--window-from",
            "2026-09-20",
            "--data-dir",
            str(data_dir),
        ],
    )

    assert result.exit_code == 1
    assert "已结账" in result.output
    assert not target.exists()


def test_schedule_normalises_space_form_kickoff_bj(tmp_path):
    """真 issue.json 的 kickoff_bj 是「2026-09-19 00:30」（空格、无秒）；due_at 必须落成 ISO，
    否则与 pending/gaps 里的 ISO now 字串字典序比较会错位。"""
    d = tmp_path / "data"
    (d / "zucai").mkdir(parents=True)
    (d / "zucai" / "26129-issue.json").write_text(json.dumps({"issue_id": "26129", "matches": [
        {"match_no": 4, "kickoff_bj": "2026-09-19 00:30"},
        {"match_no": 1, "kickoff_bj": "2026-09-19 03:00"}]}), encoding="utf-8")
    doc = tmp_path / "F2.json"
    doc.write_text(json.dumps(DOC), encoding="utf-8")
    CliRunner().invoke(app, ["rsi", "register", "--by", "Jun", str(doc), "--data-dir", str(d)])
    r = CliRunner().invoke(app, ["rsi", "schedule", "--day", "2026-09-19", "--issue", "26129",
                                 "--data-dir", str(d)])
    assert r.exit_code == 0, r.output
    assert "2026-09-19T00:30:00+08:00" in r.output
    r = CliRunner().invoke(app, ["rsi", "due", "--day", "2026-09-19", "--data-dir", str(d),
                                 "--now", "2026-09-18T20:00:00+08:00"])
    assert "f2-observation" in r.output and "00:30" in r.output, r.output


def test_schedule_and_fulfill_per_match_jczq_duty(tmp_path):
    data_dir = tmp_path / "data"
    day_dir = data_dir / "jczq" / "daily" / "2026-09-19"
    day_dir.mkdir(parents=True)
    day_dir.joinpath("jczq-legs-base.json").write_text(
        json.dumps(
            {
                "day": "2026-09-19",
                "legs": {
                    "周五001": {
                        "match_id": "match-1",
                        "kickoff_bj": "2099-01-01T20:00:00+08:00",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    doc = tmp_path / "R0.json"
    doc.write_text(
        Path("experiments/registry/R0.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    runner = CliRunner()
    registered = runner.invoke(
        app, ["rsi", "register", "--by", "Jun", str(doc), "--data-dir", str(data_dir)]
    )
    assert registered.exit_code == 0
    scheduled = runner.invoke(
        app, ["rsi", "schedule", "--day", "2026-09-19", "--data-dir", str(data_dir)]
    )
    assert scheduled.exit_code == 0, scheduled.output
    artifact = day_dir / "research-周五001.json"
    artifact.write_text("{}", encoding="utf-8")
    fulfilled = runner.invoke(
        app,
        [
            "rsi", "fulfill", "--exp", "R0", "--duty", "match-research",
            "--day", "2026-09-19", "--match", "match-1", "--artifact", str(artifact),
            "--n-rows", "1", "--stratum", "jczq", "--data-dir", str(data_dir),
        ],
    )
    assert fulfilled.exit_code == 0, fulfilled.output
    status = runner.invoke(
        app, ["rsi", "status", "--exp", "R0", "--data-dir", str(data_dir)]
    )
    assert status.exit_code == 0, status.output
    # R0's frozen window starts on 2026-09-20, so this older observation is
    # retained as evidence but cannot enter the prospective sample count.
    assert "n=   0/200" in status.output


def _prepare_f5_match_duty(tmp_path):
    data_dir = tmp_path / "data"
    day = "2026-09-20"
    day_dir = data_dir / "jczq" / "daily" / day
    day_dir.mkdir(parents=True)
    day_dir.joinpath("jczq-legs-base.json").write_text(
        json.dumps(
            {
                "legs": {
                    "周日001": {
                        "match_id": "match-f5",
                        "kickoff_bj": "2099-09-20T20:00:00+08:00",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    runner = CliRunner()
    registered = runner.invoke(
        app,
        [
            "rsi",
            "register",
            "--by",
            "Jun",
            "experiments/registry/F5.json",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert registered.exit_code == 0, registered.output
    scheduled = runner.invoke(
        app, ["rsi", "schedule", "--day", day, "--data-dir", str(data_dir)]
    )
    assert scheduled.exit_code == 0, scheduled.output
    artifact = day_dir / "price-band-match-f5.json"
    artifact.write_text("{}", encoding="utf-8")
    return data_dir, day, artifact, runner


def test_fulfill_uses_registered_falsifier_stratum_and_status_counts_it(tmp_path):
    data_dir, day, artifact, runner = _prepare_f5_match_duty(tmp_path)

    fulfilled = runner.invoke(
        app,
        [
            "rsi",
            "fulfill",
            "--exp",
            "F5",
            "--duty",
            "price-band-observation",
            "--day",
            day,
            "--match",
            "match-f5",
            "--artifact",
            str(artifact),
            "--n-rows",
            "1",
            "--data-dir",
            str(data_dir),
        ],
    )

    assert fulfilled.exit_code == 0, fulfilled.output
    with sqlite3.connect(data_dir / "ontology" / "ontology.db") as connection:
        assert connection.execute(
            "SELECT population_stratum FROM rsi_observations WHERE exp_id='F5'"
        ).fetchone() == ("pooled",)
    status = runner.invoke(
        app, ["rsi", "status", "--exp", "F5", "--data-dir", str(data_dir)]
    )
    assert status.exit_code == 0, status.output
    assert "n=   1/120" in status.output
    assert "orphan:" not in status.output


def test_fulfill_rejects_mismatched_stratum_without_writing_observation(tmp_path):
    data_dir, day, artifact, runner = _prepare_f5_match_duty(tmp_path)

    fulfilled = runner.invoke(
        app,
        [
            "rsi",
            "fulfill",
            "--exp",
            "F5",
            "--duty",
            "price-band-observation",
            "--day",
            day,
            "--match",
            "match-f5",
            "--artifact",
            str(artifact),
            "--n-rows",
            "1",
            "--stratum",
            "jczq",
            "--data-dir",
            str(data_dir),
        ],
    )

    assert fulfilled.exit_code == 1
    assert "--stratum jczq 与 F5 注册的 falsifier.stratum=pooled 不一致" in fulfilled.output
    with sqlite3.connect(data_dir / "ontology" / "ontology.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM rsi_observations WHERE exp_id='F5'"
        ).fetchone() == (0,)


def test_status_reports_observations_with_a_non_registered_stratum(tmp_path):
    data_dir, day, _artifact, runner = _prepare_f5_match_duty(tmp_path)
    with sqlite3.connect(data_dir / "ontology" / "ontology.db") as connection:
        connection.execute(
            "INSERT INTO rsi_observations "
            "(observation_id, exp_id, day, population_stratum, n_rows, captured_at, "
            "prospective, judgment_tier_hist_json, artifact_hash) "
            "VALUES ('orphan-f5', 'F5', ?, 'jczq', 1, ?, 1, '{}', ?)",
            (day, "2026-09-20T12:00:00+08:00", "a" * 64),
        )

    status = runner.invoke(
        app, ["rsi", "status", "--exp", "F5", "--data-dir", str(data_dir)]
    )

    assert status.exit_code == 0, status.output
    assert (
        "orphan: F5 1 条观测 stratum=jczq，而 falsifier.stratum=pooled（不计入 n）"
        in status.output
    )


def test_due_without_issue_lists_issue_bound_duties_instead_of_failing(tmp_path):
    data_dir = tmp_path / "data"
    day = "2026-09-19"
    day_dir = data_dir / "jczq" / "daily" / day
    day_dir.mkdir(parents=True)
    day_dir.joinpath("jczq-legs-base.json").write_text(
        json.dumps(
            {
                "legs": {
                    "周五001": {
                        "match_id": "match-1",
                        "kickoff_bj": "2099-09-19T20:00:00+08:00",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    doc = tmp_path / "F2.json"
    doc.write_text(json.dumps(DOC), encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(
        app, ["rsi", "register", "--by", "Jun", str(doc), "--data-dir", str(data_dir)]
    ).exit_code == 0
    scheduled = runner.invoke(
        app, ["rsi", "schedule", "--day", day, "--data-dir", str(data_dir)]
    )
    assert scheduled.exit_code == 0, scheduled.output

    result = runner.invoke(
        app,
        [
            "rsi",
            "due",
            "--day",
            day,
            "--data-dir",
            str(data_dir),
            "--now",
            "2026-09-18T20:00:00+08:00",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "F2:f2-observation" in result.output
    assert "<需 --issue>" in result.output


def test_schedule_expands_each_match_duty_by_its_population(tmp_path):
    data_dir = tmp_path / "data"
    day = "2026-09-19"
    day_dir = data_dir / "jczq" / "daily" / day
    zucai_dir = data_dir / "zucai"
    day_dir.mkdir(parents=True)
    zucai_dir.mkdir()
    day_dir.joinpath("jczq-legs-base.json").write_text(
        json.dumps(
            {
                "legs": {
                    "周五001": {
                        "match_id": "shared",
                        "kickoff_bj": "2026-09-19T20:00:00+08:00",
                    },
                    "周五002": {
                        "match_id": "jczq-only",
                        "kickoff_bj": "2026-09-19T21:00:00+08:00",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    zucai_dir.joinpath("26130-store-ids.json").write_text(
        json.dumps(
            {
                "1": {"match_id": "shared", "match_no": 1},
                "2": {"match_id": "zucai-only", "match_no": 2},
            }
        ),
        encoding="utf-8",
    )
    zucai_dir.joinpath("26130-issue.json").write_text(
        json.dumps(
            {
                "matches": [
                    {"match_no": 1, "kickoff_bj": "2026-09-19 20:00"},
                    {"match_no": 2, "kickoff_bj": "2026-09-19 22:00"},
                ]
            }
        ),
        encoding="utf-8",
    )
    r0_path = tmp_path / "R0.json"
    r0_doc = json.loads(Path("experiments/registry/R0.json").read_text("utf-8"))
    r0_path.write_text(json.dumps(r0_doc), encoding="utf-8")
    both_path = tmp_path / "BOTH.json"
    both_doc = {**r0_doc, "exp_id": "BOTH", "population": "both"}
    both_path.write_text(json.dumps(both_doc), encoding="utf-8")

    runner = CliRunner()
    registered = runner.invoke(
        app, ["rsi", "register", "--by", "Jun", str(r0_path), "--data-dir", str(data_dir)]
    )
    assert registered.exit_code == 0, registered.output
    first_schedule = runner.invoke(
        app,
        [
            "rsi",
            "schedule",
            "--day",
            day,
            "--issue",
            "26130",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert first_schedule.exit_code == 0, first_schedule.output
    registered = runner.invoke(
        app, ["rsi", "register", "--by", "Jun", str(both_path), "--data-dir", str(data_dir)]
    )
    assert registered.exit_code == 0, registered.output
    scheduled = runner.invoke(
        app,
        [
            "rsi",
            "schedule",
            "--day",
            day,
            "--issue",
            "26130",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert scheduled.exit_code == 0, scheduled.output

    with sqlite3.connect(data_dir / "ontology" / "ontology.db") as connection:
        rows = connection.execute(
            "SELECT duty_id, match_id, due_at FROM rsi_duty_instances "
            "ORDER BY duty_id, match_id"
        ).fetchall()
    assert rows == [
        ("BOTH:match-research", "jczq-only", "2026-09-19T21:00:00+08:00"),
        ("BOTH:match-research", "shared", "2026-09-19T20:00:00+08:00"),
        ("BOTH:match-research", "zucai-only", "2026-09-19T22:00:00+08:00"),
        ("R0:match-research", "jczq-only", "2026-09-19T21:00:00+08:00"),
        ("R0:match-research", "shared", "2026-09-19T20:00:00+08:00"),
    ]


def test_reschedule_rebuilds_unfulfilled_instances_and_preserves_fulfilled(
    tmp_path, monkeypatch
):
    data_dir = _data_dir(tmp_path)
    day = "2026-09-19"
    base = json.loads(Path("experiments/registry/R0.json").read_text("utf-8"))
    day_duty = {
        **base["duties"][0],
        "scope": "day",
        "deadline_rule": "earliest_kickoff",
    }
    runner = CliRunner()
    for exp_id in ("DROP", "KEEP"):
        doc_path = tmp_path / f"{exp_id}.json"
        doc_path.write_text(
            json.dumps({**base, "exp_id": exp_id, "duties": [day_duty]}),
            encoding="utf-8",
        )
        registered = runner.invoke(
            app, ["rsi", "register", "--by", "Jun", str(doc_path), "--data-dir", str(data_dir)]
        )
        assert registered.exit_code == 0, registered.output

    first = runner.invoke(
        app,
        [
            "rsi",
            "schedule",
            "--day",
            day,
            "--issue",
            "26129",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert first.exit_code == 0, first.output

    db_path = data_dir / "ontology" / "ontology.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE rsi_duty_instances SET fulfilled_at = ?, artifact_path = ?, "
            "artifact_hash = ? WHERE duty_id = ? AND day = ? AND match_id = ''",
            (
                "2026-09-18T12:00:00+08:00",
                "kept.json",
                "a" * 64,
                "KEEP:match-research",
                day,
            ),
        )
        connection.execute(
            "UPDATE rsi_duties SET scope = 'match', "
            "deadline_rule = 'match_kickoff' WHERE exp_id IN ('DROP', 'KEEP')"
        )

    monkeypatch.setattr(rsi_cli, "_SCHEDULE_SEMANTICS", "legacy", raising=False)
    second = runner.invoke(
        app,
        [
            "rsi",
            "schedule",
            "--day",
            day,
            "--issue",
            "26129",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert second.exit_code == 0, second.output

    # Simulate an already-committed schedule Action from before reconciliation
    # existed. A semantic revision must execute the handler again, not replay it.
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO rsi_duty_instances "
            "(duty_id, day, match_id, due_at, issue, fulfilled_at, artifact_path, "
            "artifact_hash) VALUES (?, ?, '', ?, ?, NULL, NULL, NULL)",
            (
                "DROP:match-research",
                day,
                "2026-09-19T00:30:00+08:00",
                "26129",
            ),
        )

    monkeypatch.setattr(
        rsi_cli, "_SCHEDULE_SEMANTICS", "reconcile-unfulfilled-v1", raising=False
    )
    third = runner.invoke(
        app,
        [
            "rsi",
            "schedule",
            "--day",
            day,
            "--issue",
            "26129",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert third.exit_code == 0, third.output

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT duty_id, match_id, fulfilled_at, artifact_path FROM "
            "rsi_duty_instances WHERE duty_id LIKE 'DROP:%' OR duty_id LIKE 'KEEP:%' "
            "ORDER BY duty_id, match_id"
        ).fetchall()
        observation_count = connection.execute(
            "SELECT COUNT(*) FROM rsi_observations"
        ).fetchone()[0]
    assert rows == [
        ("DROP:match-research", "m-0", None, None),
        ("DROP:match-research", "m-1", None, None),
        (
            "KEEP:match-research",
            "",
            "2026-09-18T12:00:00+08:00",
            "kept.json",
        ),
        ("KEEP:match-research", "m-0", None, None),
        ("KEEP:match-research", "m-1", None, None),
    ]
    assert observation_count == 0


def test_balance_writes_issue_ledger_and_fulfills_f9(tmp_path):
    data_dir = _data_dir(tmp_path)
    reads = [
        {
            "read_id": f"r-{index}",
            "match_id": f"m-{index}",
            "prior": {"home": 0.4, "draw": 0.3, "away": 0.3},
            "belief": {"home": 0.4, "draw": 0.3, "away": 0.3},
        }
        for index in range(2)
    ]
    (data_dir / "zucai" / "26129-reads.json").write_text(
        json.dumps(reads), encoding="utf-8"
    )
    runner = CliRunner()
    registered = runner.invoke(
        app,
        [
            "rsi",
            "register", "--by", "Jun",
            "experiments/registry/F9.json",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert registered.exit_code == 0, registered.output

    result = runner.invoke(
        app, ["rsi", "balance", "--issue", "26129", "--data-dir", str(data_dir)]
    )

    assert result.exit_code == 0, result.output
    assert "0/2 拨动" in result.output
    artifact = data_dir / "jczq" / "daily" / "2026-09-19" / "balance.json"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["issue"] == "26129"
    assert payload["n_matches"] == 2 and payload["n_moved"] == 0
    status = runner.invoke(app, ["rsi", "status", "--exp", "F9", "--data-dir", str(data_dir)])
    assert status.exit_code == 0
    assert "observing" in status.output


def test_balance_rerun_with_unchanged_ledger_is_a_no_op(tmp_path):
    data_dir = _data_dir(tmp_path)
    reads = [{"read_id": "r-1", "match_id": "m-1",
              "prior": {"home": 0.4, "draw": 0.3, "away": 0.3},
              "belief": {"home": 0.4, "draw": 0.3, "away": 0.3}}]
    (data_dir / "zucai" / "26129-reads.json").write_text(json.dumps(reads), encoding="utf-8")
    runner = CliRunner()
    registered = runner.invoke(app, ["rsi", "register", "--by", "Jun",
                                     "experiments/registry/F9.json", "--data-dir", str(data_dir)])
    assert registered.exit_code == 0, registered.output
    argv = ["rsi", "balance", "--issue", "26129", "--data-dir", str(data_dir)]

    first = runner.invoke(app, argv)
    again = runner.invoke(app, argv)

    assert first.exit_code == 0, first.output
    assert again.exit_code == 0, again.output
    assert "无变化" in again.output


def test_balance_can_be_rerun_after_results_arrive(tmp_path):
    data_dir = _data_dir(tmp_path)
    reads = [
        {
            "read_id": "r-1",
            "match_id": "m-1",
            "prior": {"home": 0.4, "draw": 0.3, "away": 0.3},
            "belief": {"home": 0.46, "draw": 0.27, "away": 0.27},
        }
    ]
    (data_dir / "zucai" / "26129-reads.json").write_text(
        json.dumps(reads), encoding="utf-8"
    )
    runner = CliRunner()
    registered = runner.invoke(
        app,
        [
            "rsi",
            "register", "--by", "Jun",
            "experiments/registry/F9.json",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert registered.exit_code == 0, registered.output

    before = runner.invoke(
        app, ["rsi", "balance", "--issue", "26129", "--data-dir", str(data_dir)]
    )
    assert before.exit_code == 0, before.output
    (data_dir / "zucai" / "official-results.json").write_text(
        json.dumps({"26129": "3"}), encoding="utf-8"
    )

    after = runner.invoke(
        app, ["rsi", "balance", "--issue", "26129", "--data-dir", str(data_dir)]
    )

    assert after.exit_code == 0, after.output
    payload = json.loads(
        (
            data_dir / "jczq" / "daily" / "2026-09-19" / "balance.json"
        ).read_text(encoding="utf-8")
    )
    assert payload["brier_vs_market_all"] is not None
    assert payload["direction_right_n"] == 1
    artifact_hash = sha256(
        (
            data_dir / "jczq" / "daily" / "2026-09-19" / "balance.json"
        ).read_bytes()
    ).hexdigest()
    with sqlite3.connect(data_dir / "ontology" / "ontology.db") as connection:
        hashes = connection.execute(
            "SELECT artifact_hash FROM rsi_observations WHERE exp_id = 'F9'"
        ).fetchall()
        n_rows = connection.execute(
            "SELECT SUM(n_rows) FROM rsi_observations WHERE exp_id = 'F9'"
        ).fetchone()[0]
        keys = connection.execute(
            "SELECT idempotency_key FROM actions "
            "WHERE idempotency_key LIKE 'rsi-ful:F9:balance-ledger:%'"
        ).fetchall()
    assert len(hashes) == 2
    assert n_rows == 1
    assert (artifact_hash,) in hashes
    assert any(":balance-ledger:v3:2026-09-19:" in key for (key,) in keys)


def test_balance_day_records_one_f9_observation_per_union_match(tmp_path):
    data_dir = tmp_path / "data"
    day = "2026-09-20"
    day_dir = data_dir / "jczq" / "daily" / day
    zucai_dir = data_dir / "zucai"
    day_dir.mkdir(parents=True)
    zucai_dir.mkdir()
    day_dir.joinpath("jczq-legs-base.json").write_text(
        json.dumps(
            {
                "legs": {
                    "周日001": {
                        "match_id": "shared",
                        "kickoff_bj": "2099-09-20T20:00:00+08:00",
                    },
                    "周日002": {
                        "match_id": "jczq-only",
                        "kickoff_bj": "2099-09-20T21:00:00+08:00",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    day_dir.joinpath("reads.json").write_text(
        json.dumps(
            [
                {
                    "match_id": "shared",
                    "prior": {"home": 0.4, "draw": 0.3, "away": 0.3},
                    "belief": {"home": 0.45, "draw": 0.28, "away": 0.27},
                },
                {
                    "match_id": "jczq-only",
                    "prior": {"home": 0.3, "draw": 0.3, "away": 0.4},
                    "belief": {"home": 0.3, "draw": 0.3, "away": 0.4},
                },
            ]
        ),
        encoding="utf-8",
    )
    zucai_dir.joinpath("26131-store-ids.json").write_text(
        json.dumps(
            {
                "1": {"match_id": "shared", "match_no": 1},
                "2": {"match_id": "zucai-only", "match_no": 2},
            }
        ),
        encoding="utf-8",
    )
    zucai_dir.joinpath("26131-issue.json").write_text(
        json.dumps(
            {
                "matches": [
                    {"match_no": 1, "kickoff_bj": "2099-09-20 20:00"},
                    {"match_no": 2, "kickoff_bj": "2099-09-20 22:00"},
                ]
            }
        ),
        encoding="utf-8",
    )
    zucai_dir.joinpath("26131-reads.json").write_text(
        json.dumps(
            [
                {
                    "match_id": "shared",
                    "prior": {"home": 0.1, "draw": 0.2, "away": 0.7},
                    "belief": {"home": 0.1, "draw": 0.2, "away": 0.7},
                },
                {
                    "match_id": "zucai-only",
                    "prior": {"home": 0.2, "draw": 0.3, "away": 0.5},
                    "belief": {"home": 0.18, "draw": 0.3, "away": 0.52},
                },
            ]
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    registered = runner.invoke(
        app,
        [
            "rsi",
            "register", "--by", "Jun",
            "experiments/registry/F9.json",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert registered.exit_code == 0, registered.output
    scheduled = runner.invoke(
        app,
        [
            "rsi",
            "schedule",
            "--day",
            day,
            "--issue",
            "26131",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert scheduled.exit_code == 0, scheduled.output

    result = runner.invoke(
        app, ["rsi", "balance", "--day", day, "--data-dir", str(data_dir)]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(day_dir.joinpath("balance.json").read_text("utf-8"))
    assert [row["match_id"] for row in payload["rows"]] == [
        "shared",
        "jczq-only",
        "zucai-only",
    ]
    assert payload["rows"][0]["prior"]["home"] == 0.4
    with sqlite3.connect(data_dir / "ontology" / "ontology.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*), SUM(n_rows) FROM rsi_observations WHERE exp_id = 'F9'"
        ).fetchone() == (3, 0)
        assert connection.execute(
            "SELECT COUNT(*) FROM rsi_duty_instances "
            "WHERE duty_id = 'F9:balance-ledger' AND fulfilled_at IS NOT NULL"
        ).fetchone() == (3,)
    status = runner.invoke(
        app, ["rsi", "status", "--exp", "F9", "--data-dir", str(data_dir)]
    )
    assert status.exit_code == 0
    assert "n=   0/60" in status.output


# ── 同日重做：再履行必须成功，不能被幂等键顶回去 ──────────────────────────


def _prepare_r0_match_duty(tmp_path, *, day="2026-09-20", matches=None):
    data_dir = tmp_path / "data"
    day_dir = data_dir / "jczq" / "daily" / day
    day_dir.mkdir(parents=True)
    matches = matches or {"周日001": ("match-r0", "2099-09-20T20:00:00+08:00")}
    day_dir.joinpath("jczq-legs-base.json").write_text(
        json.dumps(
            {
                "legs": {
                    code: {"match_id": match_id, "kickoff_bj": kickoff}
                    for code, (match_id, kickoff) in matches.items()
                }
            }
        ),
        encoding="utf-8",
    )
    runner = CliRunner()
    registered = runner.invoke(
        app,
        ["rsi", "register", "--by", "Jun", "experiments/registry/R0.json",
         "--data-dir", str(data_dir)],
    )
    assert registered.exit_code == 0, registered.output
    scheduled = runner.invoke(
        app, ["rsi", "schedule", "--day", day, "--data-dir", str(data_dir)]
    )
    assert scheduled.exit_code == 0, scheduled.output
    return data_dir, day_dir, runner


def _fulfill_r0(runner, data_dir, day, match_id, artifact):
    return runner.invoke(
        app,
        [
            "rsi", "fulfill", "--exp", "R0", "--duty", "match-research",
            "--day", day, "--match", match_id, "--artifact", str(artifact),
            "--n-rows", "1", "--stratum", "jczq", "--data-dir", str(data_dir),
        ],
    )


def test_fulfill_redone_artifact_supersedes_the_earlier_observation(tmp_path):
    """研究被驳回后重做：第二次履行必须登记，旧观测标记 superseded，n 不翻倍。"""
    data_dir, day_dir, runner = _prepare_r0_match_duty(tmp_path)
    artifact = day_dir / "research-周日001.json"
    artifact.write_text('{"stance": "first"}', encoding="utf-8")
    first = _fulfill_r0(runner, data_dir, "2026-09-20", "match-r0", artifact)
    assert first.exit_code == 0, first.output

    artifact.write_text('{"stance": "redone"}', encoding="utf-8")
    second = _fulfill_r0(runner, data_dir, "2026-09-20", "match-r0", artifact)
    assert second.exit_code == 0, second.output
    assert "已登记" in second.output

    redone_hash = sha256(artifact.read_bytes()).hexdigest()
    with sqlite3.connect(data_dir / "ontology" / "ontology.db") as connection:
        rows = connection.execute(
            "SELECT observation_id, artifact_hash, superseded_by FROM rsi_observations "
            "WHERE exp_id = 'R0' ORDER BY captured_at, observation_id"
        ).fetchall()
        instance = connection.execute(
            "SELECT artifact_hash FROM rsi_duty_instances "
            "WHERE duty_id = 'R0:match-research' AND match_id = 'match-r0'"
        ).fetchone()
    assert len(rows) == 2
    base, latest = rows
    assert base[0] == "R0:2026-09-20:match-r0"
    assert latest[1] == redone_hash and latest[2] is None
    assert base[2] == latest[0]            # 旧观测指向新观测
    assert instance == (redone_hash,)     # 义务实例指向最新产物

    status = runner.invoke(
        app, ["rsi", "status", "--exp", "R0", "--data-dir", str(data_dir)]
    )
    assert status.exit_code == 0, status.output
    assert "n=   1/200" in status.output   # 只数最新版本，不是 2


def test_fulfill_identical_artifact_twice_is_a_no_op(tmp_path):
    data_dir, day_dir, runner = _prepare_r0_match_duty(tmp_path)
    artifact = day_dir / "research-周日001.json"
    artifact.write_text('{"stance": "same"}', encoding="utf-8")
    first = _fulfill_r0(runner, data_dir, "2026-09-20", "match-r0", artifact)
    assert first.exit_code == 0, first.output
    second = _fulfill_r0(runner, data_dir, "2026-09-20", "match-r0", artifact)
    assert second.exit_code == 0, second.output

    with sqlite3.connect(data_dir / "ontology" / "ontology.db") as connection:
        observations = connection.execute(
            "SELECT COUNT(*) FROM rsi_observations WHERE exp_id = 'R0'"
        ).fetchone()[0]
        actions = connection.execute(
            "SELECT COUNT(*) FROM actions WHERE idempotency_key LIKE "
            "'rsi-ful:R0:match-research:2026-09-20:match-r0%'"
        ).fetchone()[0]
    assert observations == 1
    assert actions == 1


def test_schedule_twice_same_day_is_a_no_op_and_a_grown_board_reschedules(tmp_path):
    """同日重排不冲突；板面新增更早开球的场次后重排要把新场排进去，不重复旧场。"""
    day = "2026-09-20"
    data_dir, day_dir, runner = _prepare_r0_match_duty(tmp_path, day=day)
    again = runner.invoke(
        app, ["rsi", "schedule", "--day", day, "--data-dir", str(data_dir)]
    )
    assert again.exit_code == 0, again.output

    # 2026-09-22 的死法：板面后来加了周二001，最早开球变了 → 同键异请求 → 冲突
    day_dir.joinpath("jczq-legs-base.json").write_text(
        json.dumps(
            {
                "legs": {
                    "周日001": {"match_id": "match-r0",
                               "kickoff_bj": "2099-09-20T20:00:00+08:00"},
                    "周日002": {"match_id": "match-early",
                               "kickoff_bj": "2099-09-20T18:00:00+08:00"},
                }
            }
        ),
        encoding="utf-8",
    )
    grown = runner.invoke(
        app, ["rsi", "schedule", "--day", day, "--data-dir", str(data_dir)]
    )
    assert grown.exit_code == 0, grown.output
    with sqlite3.connect(data_dir / "ontology" / "ontology.db") as connection:
        rows = connection.execute(
            "SELECT match_id, due_at FROM rsi_duty_instances "
            "WHERE duty_id = 'R0:match-research' AND day = ? ORDER BY match_id",
            (day,),
        ).fetchall()
    assert rows == [
        ("match-early", "2099-09-20T18:00:00+08:00"),
        ("match-r0", "2099-09-20T20:00:00+08:00"),
    ]


def test_day_duty_fulfilled_with_kickoff_day_resolves_to_the_scheduled_business_day(tmp_path):
    """2026-09-28：义务按备料业务日（停售日）排，观察仪按最早开球日登记；26134 首场
    9/29 00:00 → F2/F1c 整天「命令成功但未登记」。按期号唯一对到的那天登记。"""
    d = _data_dir(tmp_path)
    doc = tmp_path / "F2.json"
    doc.write_text(json.dumps(DOC), encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(app, ["rsi", "register", "--by", "Jun", str(doc),
                               "--data-dir", str(d)]).exit_code == 0
    r = runner.invoke(app, ["rsi", "schedule", "--day", "2026-09-18", "--issue", "26129",
                            "--data-dir", str(d)])
    assert r.exit_code == 0, r.output
    artifact = d / "zucai" / "26129-f2-observation.json"
    artifact.write_text("{}", encoding="utf-8")
    import os
    from datetime import datetime

    before_kickoff = datetime.fromisoformat("2026-09-18T20:00:00+08:00").timestamp()
    os.utime(artifact, (before_kickoff, before_kickoff))   # 前瞻：采样早于首场开球

    r = runner.invoke(app, ["rsi", "fulfill", "--exp", "F2", "--duty", "f2-observation",
                            "--day", "2026-09-19", "--issue", "26129",
                            "--artifact", str(artifact), "--n-rows", "0",
                            "--data-dir", str(d)])

    assert r.exit_code == 0, r.output
    assert "业务日 2026-09-18" in r.output
    with sqlite3.connect(d / "ontology" / "ontology.db") as connection:
        assert connection.execute(
            "SELECT day FROM rsi_duty_instances WHERE duty_id='F2:f2-observation' "
            "AND fulfilled_at IS NOT NULL").fetchall() == [("2026-09-18",)]


def test_status_counts_pool_coverage_r1_by_prospective_observations(tmp_path):
    """R1（并集池覆盖率，没有结账适配器）按前瞻观测行数显示 n；09-27 登记后曾一直显示 0。"""
    data_dir = tmp_path / "data"
    day = "2026-09-28"
    day_dir = data_dir / "jczq" / "daily" / day
    day_dir.mkdir(parents=True)
    day_dir.joinpath("jczq-legs-base.json").write_text(json.dumps({"legs": {
        "周一001": {"match_id": "match-r1", "kickoff_bj": "2099-09-28T20:00:00+08:00"}}}),
        encoding="utf-8")
    runner = CliRunner()
    registered = runner.invoke(app, ["rsi", "register", "--by", "Jun",
                                     "experiments/registry/R1.json", "--data-dir", str(data_dir)])
    assert registered.exit_code == 0, registered.output
    assert runner.invoke(app, ["rsi", "schedule", "--day", day, "--data-dir",
                               str(data_dir)]).exit_code == 0
    artifact = day_dir / "research-周一001.json"
    artifact.write_text("{}", encoding="utf-8")
    fulfilled = runner.invoke(app, [
        "rsi", "fulfill", "--exp", "R1", "--duty", "match-research", "--day", day,
        "--match", "match-r1", "--artifact", str(artifact), "--n-rows", "1",
        "--stratum", "pooled", "--data-dir", str(data_dir)])
    assert fulfilled.exit_code == 0, fulfilled.output
    status = runner.invoke(app, ["rsi", "status", "--exp", "R1", "--data-dir", str(data_dir)])
    assert status.exit_code == 0, status.output
    assert "n=   1/200" in status.output


def test_retire_stops_the_experiments_duties(tmp_path):
    """退役＝不再观察：义务置 retired，排程/到期/巡检都不再列它（2026-10-02 F2/F1c 退役时补）。"""
    data_dir = tmp_path / "data"
    day = "2026-09-28"
    day_dir = data_dir / "jczq" / "daily" / day
    day_dir.mkdir(parents=True)
    day_dir.joinpath("jczq-legs-base.json").write_text(json.dumps({"legs": {
        "周一001": {"match_id": "match-r1", "kickoff_bj": "2099-09-28T20:00:00+08:00"}}}),
        encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(app, ["rsi", "register", "--by", "Jun", "experiments/registry/R1.json",
                               "--data-dir", str(data_dir)]).exit_code == 0
    retired = runner.invoke(app, ["rsi", "deploy", "--exp", "R1", "--retire", "--reason",
                                  "窗口内到不了 n_min", "--by", "Jun", "--data-dir", str(data_dir)])
    assert retired.exit_code == 0, retired.output
    with sqlite3.connect(data_dir / "ontology" / "ontology.db") as connection:
        assert connection.execute(
            "SELECT DISTINCT status FROM rsi_duties WHERE exp_id='R1'").fetchall() == [("retired",)]
    assert runner.invoke(app, ["rsi", "schedule", "--day", day, "--data-dir",
                               str(data_dir)]).exit_code == 0
    due = runner.invoke(app, ["rsi", "due", "--day", day, "--data-dir", str(data_dir)])
    assert "R1" not in due.output
    status = runner.invoke(app, ["rsi", "status", "--exp", "R1", "--data-dir", str(data_dir)])
    assert "retired" in status.output


def test_union_match_keeps_its_zucai_identity_after_the_channel_map_lands(tmp_path):
    # 10-05 R1：channel-map 18:30 才落地，之前按足彩侧 id 排过并已履约的场，对上竞彩后
    # 又按竞彩侧 id 排一条、永远空着。同一天已按足彩侧排过的，继续用足彩侧 id。
    data_dir = tmp_path / "data"
    day = "2026-09-19"
    day_dir = data_dir / "jczq" / "daily" / day
    zucai_dir = data_dir / "zucai"
    day_dir.mkdir(parents=True)
    zucai_dir.mkdir(parents=True)
    day_dir.joinpath("jczq-legs-base.json").write_text(json.dumps({"legs": {
        "周五001": {"match_id": "jc-shared", "kickoff_bj": "2026-09-19T20:00:00+08:00"}}}),
        encoding="utf-8")
    zucai_dir.joinpath("26130-store-ids.json").write_text(json.dumps({
        "1": {"match_id": "zc-shared", "match_no": 1},
        "2": {"match_id": "zucai-only", "match_no": 2}}), encoding="utf-8")
    zucai_dir.joinpath("26130-issue.json").write_text(json.dumps({"matches": [
        {"match_no": 1, "kickoff_bj": "2026-09-19 20:00"},
        {"match_no": 2, "kickoff_bj": "2026-09-19 22:00"}]}), encoding="utf-8")
    r0_doc = json.loads(Path("experiments/registry/R0.json").read_text("utf-8"))
    both_path = tmp_path / "BOTH.json"
    both_path.write_text(json.dumps({**r0_doc, "exp_id": "BOTH", "population": "both"}),
                         encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(app, ["rsi", "register", "--by", "Jun", str(both_path),
                               "--data-dir", str(data_dir)]).exit_code == 0
    schedule = ["rsi", "schedule", "--day", day, "--issue", "26130", "--data-dir", str(data_dir)]
    assert runner.invoke(app, schedule).exit_code == 0          # 还没有 channel-map
    db = data_dir / "ontology" / "ontology.db"
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE rsi_duty_instances "
                           "SET fulfilled_at='2026-09-19T12:15:00+08:00' "
                           "WHERE match_id='zc-shared'")
    zucai_dir.joinpath("26130-channel-map.auto.json").write_text(
        json.dumps({"jc-shared": 1}), encoding="utf-8")
    again = runner.invoke(app, schedule)
    assert again.exit_code == 0, again.output

    with sqlite3.connect(db) as connection:
        rows = connection.execute(
            "SELECT match_id, fulfilled_at IS NOT NULL FROM rsi_duty_instances "
            "WHERE duty_id='BOTH:match-research' ORDER BY match_id").fetchall()
    assert rows == [("zc-shared", 1), ("zucai-only", 0)]


# ── 并集重叠场双身份：义务按足彩侧 id 排、Read 在竞彩侧 id，也必须履行 ───────────


def test_balance_fulfills_f9_when_duty_was_scheduled_under_zucai_identity(tmp_path):
    """2026-10-12 死法：26139 先于周一板备料，F9 义务按足彩 store-ids 的 match_id 排；
    竞彩 08:00 入板后同一场在 legs-base 里是另一个 match_id，Read 落在竞彩侧 →
    `rsi balance` 找不到 Read，重叠 8 场永不履行，sweep 每小时 DUTY_NOT_FULFILLED。"""
    data_dir = tmp_path / "data"
    day = "2026-09-20"
    day_dir = data_dir / "jczq" / "daily" / day
    zucai_dir = data_dir / "zucai"
    day_dir.mkdir(parents=True)
    zucai_dir.mkdir()
    zucai_dir.joinpath("26131-store-ids.json").write_text(
        json.dumps({"1": {"match_id": "shared-zucai", "match_no": 1}}), encoding="utf-8"
    )
    zucai_dir.joinpath("26131-issue.json").write_text(
        json.dumps({"matches": [{"match_no": 1, "kickoff_bj": "2099-09-20 20:00"}]}),
        encoding="utf-8",
    )
    zucai_dir.joinpath("26131-reads.json").write_text(
        json.dumps([{"match_id": "shared-zucai",
                     "prior": {"home": 0.1, "draw": 0.2, "away": 0.7},
                     "belief": {"home": 0.1, "draw": 0.2, "away": 0.7}}]),
        encoding="utf-8",
    )

    runner = CliRunner()
    registered = runner.invoke(
        app, ["rsi", "register", "--by", "Jun", "experiments/registry/F9.json",
              "--data-dir", str(data_dir)],
    )
    assert registered.exit_code == 0, registered.output
    # 足彩先排义务（竞彩 legs-base 还没有）→ 义务行按足彩侧 id
    scheduled = runner.invoke(
        app, ["rsi", "schedule", "--day", day, "--issue", "26131", "--data-dir", str(data_dir)],
    )
    assert scheduled.exit_code == 0, scheduled.output

    # 竞彩入板：同一场另一个 match_id；Read 只落在竞彩侧；channel-map 对号
    day_dir.joinpath("jczq-legs-base.json").write_text(
        json.dumps({"legs": {"周日001": {"match_id": "shared-jczq",
                                         "kickoff_bj": "2099-09-20T20:00:00+08:00"}}}),
        encoding="utf-8",
    )
    day_dir.joinpath("reads.json").write_text(
        json.dumps([{"match_id": "shared-jczq",
                     "prior": {"home": 0.4, "draw": 0.3, "away": 0.3},
                     "belief": {"home": 0.45, "draw": 0.28, "away": 0.27}}]),
        encoding="utf-8",
    )
    zucai_dir.joinpath("26131-channel-map.auto.json").write_text(
        json.dumps({"shared-jczq": 1}), encoding="utf-8"
    )

    result = runner.invoke(
        app, ["rsi", "balance", "--day", day, "--data-dir", str(data_dir)]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(day_dir.joinpath("balance.json").read_text("utf-8"))
    assert [row["match_id"] for row in payload["rows"]] == ["shared-zucai"]
    assert payload["rows"][0]["prior"]["home"] == 0.4          # Read 用的是竞彩侧那份
    with sqlite3.connect(data_dir / "ontology" / "ontology.db") as connection:
        assert connection.execute(
            "SELECT match_id FROM rsi_duty_instances "
            "WHERE duty_id = 'F9:balance-ledger' AND fulfilled_at IS NOT NULL"
        ).fetchall() == [("shared-zucai",)]


def test_fulfill_accepts_the_jczq_identity_when_the_duty_was_scheduled_under_zucai_id(tmp_path):
    """2026-10-14：重叠场义务按足彩侧 id 排、研究按竞彩侧 id 履约 → 「没有排过」→ 足彩侧实例
    到开球即过期（R1 10-10 起每天假缺口）。履约时对上另一侧已排的 id 就用它。"""
    data_dir = tmp_path / "data"
    day = "2026-09-19"
    day_dir = data_dir / "jczq" / "daily" / day
    zucai_dir = data_dir / "zucai"
    day_dir.mkdir(parents=True)
    zucai_dir.mkdir(parents=True)
    day_dir.joinpath("jczq-legs-base.json").write_text(json.dumps({"legs": {
        "周五001": {"match_id": "jc-shared", "kickoff_bj": "2099-01-01T20:00:00+08:00"}}}),
        encoding="utf-8")
    zucai_dir.joinpath("26130-store-ids.json").write_text(json.dumps({
        "1": {"match_id": "zc-shared", "match_no": 1}}), encoding="utf-8")
    zucai_dir.joinpath("26130-issue.json").write_text(json.dumps({"matches": [
        {"match_no": 1, "kickoff_bj": "2099-01-01 20:00"}]}), encoding="utf-8")
    r0_doc = json.loads(Path("experiments/registry/R0.json").read_text("utf-8"))
    both_path = tmp_path / "BOTH.json"
    both_path.write_text(json.dumps({**r0_doc, "exp_id": "BOTH", "population": "both",
                                     "window": {"date_from": "2026-09-01", "n_min": 10}}),
                         encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(app, ["rsi", "register", "--by", "Jun", str(both_path),
                               "--data-dir", str(data_dir)]).exit_code == 0
    schedule = ["rsi", "schedule", "--day", day, "--issue", "26130", "--data-dir", str(data_dir)]
    assert runner.invoke(app, schedule).exit_code == 0          # 还没有 channel-map：两侧都排
    db = data_dir / "ontology" / "ontology.db"
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE rsi_duty_instances "
                           "SET fulfilled_at='2026-09-19T12:15:00+08:00' "
                           "WHERE match_id='zc-shared'")
    zucai_dir.joinpath("26130-channel-map.auto.json").write_text(
        json.dumps({"jc-shared": 1}), encoding="utf-8")
    assert runner.invoke(app, schedule).exit_code == 0          # 对号后只剩足彩侧 id
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE rsi_duty_instances SET fulfilled_at=NULL")
    artifact = day_dir / "research-周五001.json"
    artifact.write_text("{}", encoding="utf-8")
    cmd = ["rsi", "fulfill", "--exp", "BOTH", "--duty", "match-research", "--day", day,
           "--match", "jc-shared", "--artifact", str(artifact), "--n-rows", "1",
           "--stratum", "jczq", "--data-dir", str(data_dir)]
    fulfilled = runner.invoke(app, cmd)
    assert fulfilled.exit_code == 0, fulfilled.output
    query = ("SELECT match_id, fulfilled_at IS NOT NULL FROM rsi_duty_instances "
             "WHERE duty_id='BOTH:match-research' ORDER BY match_id")
    with sqlite3.connect(db) as connection:
        assert connection.execute(query).fetchall() == [("zc-shared", 1)]
    # 两侧各排一条（R1 26141 的实况）：竞彩侧履约时足彩侧那条也要落
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE rsi_duty_instances SET fulfilled_at=NULL")
        connection.execute(
            "INSERT INTO rsi_duty_instances (duty_id, day, match_id, due_at, issue) "
            "VALUES ('BOTH:match-research', ?, 'jc-shared', '2099-01-01T20:00:00+08:00', "
            "'26130')", (day,))
    artifact.write_text('{"v": 2}', encoding="utf-8")
    assert runner.invoke(app, cmd).exit_code == 0
    with sqlite3.connect(db) as connection:
        assert connection.execute(query).fetchall() == [("jc-shared", 1), ("zc-shared", 1)]


def test_columns_reports_the_evidence_status_of_packet_columns(tmp_path):
    """2026-10-19：分析包 §0 抄这一行——许可证、热门带这些列背后的实验走到哪一步了。"""
    d = _data_dir(tmp_path)
    reg = tmp_path / "registry"
    reg.mkdir()
    doc = {**DOC, "exp_id": "F18", "duties": [],
           "exits": {"on_survived": "packet_column:许可证", "on_falsified": "retire_rule:x",
                     "on_expired": "none"}}
    (reg / "F18.json").write_text(json.dumps(doc), encoding="utf-8")
    (reg / "F99.json").write_text(json.dumps({**DOC, "exp_id": "F99", "duties": []}),
                                  encoding="utf-8")
    for path in (reg / "F18.json", reg / "F99.json"):
        CliRunner().invoke(app, ["rsi", "register", "--by", "Jun", str(path), "--data-dir", str(d)])
    r = CliRunner().invoke(app, ["rsi", "columns", "--data-dir", str(d),
                                 "--registry-dir", str(reg)])
    assert r.exit_code == 0, r.output
    assert "许可证 F18 未证 0/140" in r.output and "F99" not in r.output
