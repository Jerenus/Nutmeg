from pathlib import Path

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.rsi import DutyInstanceRow, DutyRow, ExperimentRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.repository import ProductReadRepository


def test_experiments_timeline_and_duties_due(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "o.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.rsi.insert_experiment(
            ExperimentRow(
                exp_id="F2",
                claim="c",
                mechanism="m",
                tier="observation",
                layer="judgment",
                population="zucai",
                min_tier="price_only",
                window={"issue_from": "26126", "issue_to": "26137"},
                falsifier={
                    "metric": "home_resid_pp",
                    "stratum": "zucai",
                    "n_min": 140,
                    "bound": "ci_upper",
                    "threshold_pp": 2.0,
                    "direction": "lt_means_falsified",
                },
                stop_rule="s",
                quota_slot=False,
                buckets=[],
                rule_ids=[],
                replay_spec=None,
                dream_ref=None,
                variants_tried=None,
                source_doc="x",
                registered_at="2026-09-14",
                frozen_hash="h" * 64,
                created_at="2026-09-18T20:00:00+08:00",
            )
        )
        uow.rsi.insert_duty(
            DutyRow(
                duty_id="F2:obs",
                exp_id="F2",
                recurrence="per_day",
                scope="day",
                deadline_rule="earliest_kickoff",
                instrument=["x", "{issue}"],
                artifact_glob="y",
                description="",
            )
        )
        uow.rsi.insert_duty_instance(
            DutyInstanceRow(
                duty_id="F2:obs",
                day="2026-09-19",
                match_id="",
                issue="26129",
                due_at="2026-09-19T00:30:00+08:00",
                fulfilled_at=None,
                artifact_path=None,
                artifact_hash=None,
            )
        )
    repo = ProductReadRepository(engine)
    exps = repo.experiments(as_of="2026-09-18T21:00:00+08:00")
    assert [e["exp_id"] for e in exps] == ["F2"] and exps[0]["status"] == "registered"
    assert exps[0]["falsifier"]["threshold_pp"] == 2.0
    tl = repo.experiment_timeline("F2", as_of="2026-09-18T21:00:00+08:00")
    assert tl[0]["kind"] == "registered" and tl[0]["at"] == "2026-09-18T20:00:00+08:00"
    due = repo.duties_due("2026-09-19", now="2026-09-18T21:00:00+08:00")
    assert [d["duty_id"] for d in due] == ["F2:obs"]
    assert repo.experiments(as_of="2026-09-18T19:00:00+08:00") == []  # 登记之前看不见
