from pathlib import Path

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.rsi import (
    DutyInstanceRow,
    DutyRow,
    ExperimentRow,
    ObservationRow,
)
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _exp(exp_id="F2", *, layer="judgment") -> ExperimentRow:
    return ExperimentRow(
        exp_id=exp_id,
        claim="c",
        mechanism="m",
        tier="observation",
        layer=layer,
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
        stop_rule="n≥140",
        quota_slot=False,
        buckets=["a", "b"],
        rule_ids=[],
        replay_spec=None,
        dream_ref=None,
        variants_tried=None,
        source_doc="experiments/prereg-26126-F1c-F2.json",
        registered_at="2026-09-14",
        frozen_hash="h" * 64,
        created_at="2026-09-18T20:00:00+08:00",
    )


def test_experiment_round_trip_and_duty_projection(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "o.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.rsi.insert_experiment(_exp())
        uow.rsi.insert_duty(
            DutyRow(
                duty_id="F2:f2-observation",
                exp_id="F2",
                recurrence="per_day",
                scope="day",
                deadline_rule="earliest_kickoff",
                instrument=[
                    "python",
                    "scripts/zucai_f2_observe.py",
                    "record",
                    "--issue",
                    "{issue}",
                ],
                artifact_glob=".nutmeg-data/zucai/{issue}-f2-observation.json",
                description="F2 观察单",
            )
        )
        uow.rsi.insert_duty_instance(
            DutyInstanceRow(
                duty_id="F2:f2-observation",
                day="2026-09-19",
                match_id="",
                issue="26129",
                due_at="2026-09-19T00:30:00+08:00",
                fulfilled_at=None,
                artifact_path=None,
                artifact_hash=None,
            )
        )
    with OntologyUnitOfWork(engine) as uow:
        got = uow.rsi.experiment("F2")
        assert got is not None
        assert got.falsifier["n_min"] == 140
        assert got.buckets == ["a", "b"]
        assert [d.duty_id for d in uow.rsi.duties("F2")] == ["F2:f2-observation"]
        pend = uow.rsi.pending_duty_instances(
            day="2026-09-19", now="2026-09-18T23:00:00+08:00"
        )
        assert [(p.duty_id, p.issue) for p in pend] == [("F2:f2-observation", "26129")]
        # 过了 due_at 仍未落 → gap（事实记录，不是罚分）
        gaps = uow.rsi.gaps("F2", now="2026-09-19T01:00:00+08:00")
        assert gaps == ["2026-09-19"]
        assert uow.rsi.experiment("nope") is None


def test_gap_projection_ignores_a_mis_scheduled_issue_outside_the_window(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "o.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.rsi.insert_experiment(_exp("F4", layer="structural"))
        uow.rsi.insert_duty(
            DutyRow(
                duty_id="F4:capital-plan",
                exp_id="F4",
                recurrence="per_day",
                scope="day",
                deadline_rule="earliest_kickoff",
                instrument=[],
                artifact_glob="x",
                description="x",
            )
        )
        uow.rsi.insert_duty_instance(
            DutyInstanceRow(
                duty_id="F4:capital-plan",
                day="2026-09-14",
                match_id="",
                issue="26125",
                due_at="2026-09-14T18:00:00+08:00",
                fulfilled_at=None,
                artifact_path=None,
                artifact_hash=None,
            )
        )
    with OntologyUnitOfWork(engine) as uow:
        assert uow.rsi.gaps("F4", now="2026-09-20T00:00:00+08:00") == []


def test_observation_insert_and_count(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "o.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.rsi.insert_experiment(_exp())
        uow.rsi.insert_observation(
            ObservationRow(
                observation_id="F2:2026-09-19",
                exp_id="F2",
                day="2026-09-19",
                population_stratum="zucai",
                n_rows=10,
                captured_at="2026-09-18T19:22:02+08:00",
                prospective=True,
                judgment_tier_hist={"price_only": 10},
                artifact_hash="a" * 64,
            )
        )
    with OntologyUnitOfWork(engine) as uow:
        assert uow.rsi.count_observations("F2") == 1
        assert uow.rsi.observation("F2:2026-09-19").n_rows == 10
