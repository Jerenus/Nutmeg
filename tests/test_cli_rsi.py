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


def test_dream_ranks_variants_and_prints_variants_tried(tmp_path):
    corpus = tmp_path / "c.json"
    corpus.write_text(
        json.dumps(
            [{"fair": {"home": 0.7, "draw": 0.2, "away": 0.10}, "actual": "home"}]
            * 20
            + [{"fair": {"home": 0.7, "draw": 0.2, "away": 0.10}, "actual": "away"}]
            * 5
        ),
        encoding="utf-8",
    )
    family = tmp_path / "fam.json"
    family.write_text(
        json.dumps(
            {
                "harness": "nutmeg.decision.rsi_grading:c14_line_harness",
                "corpus": str(corpus),
                "variants": [{"line": 0.15}, {"line": 0.12}],
            }
        ),
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["rsi", "dream", "--family", str(family)])
    assert result.exit_code == 0
    assert "variants_tried=2" in result.output and "进不了判决" in result.output


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
