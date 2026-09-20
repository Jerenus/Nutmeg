from pathlib import Path

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import MIGRATIONS, migration_status, run_migrations
from nutmeg.ontology.repository.rsi import ExperimentRow, ObservationRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _experiment(exp_id: str, stratum: str) -> ExperimentRow:
    return ExperimentRow(
        exp_id=exp_id,
        claim="claim",
        mechanism="mechanism",
        tier="observation",
        layer="structural",
        population="both",
        min_tier="price_only",
        window={"date_from": "2026-09-20", "n_min": 120},
        falsifier={
            "metric": "metric",
            "stratum": stratum,
            "n_min": 120,
            "bound": "ci_upper",
            "threshold_pp": 2.0,
            "direction": "gt_means_falsified",
        },
        stop_rule="stop",
        quota_slot=False,
        buckets=[],
        rule_ids=[],
        replay_spec=None,
        dream_ref=None,
        variants_tried=None,
        source_doc="test",
        registered_at="2026-09-20",
        frozen_hash="f" * 64,
        created_at="2026-09-20T12:00:00+08:00",
    )


def test_migration_39_corrects_only_observation_stratum_labels(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine, MIGRATIONS[:38])
    with OntologyUnitOfWork(engine) as uow:
        uow.rsi.insert_experiment(_experiment("F5", "pooled"))
        uow.rsi.insert_experiment(_experiment("R0", "jczq"))
        uow.rsi.insert_observation(
            ObservationRow(
                observation_id="f5-wrong",
                exp_id="F5",
                day="2026-09-20",
                population_stratum="jczq",
                n_rows=1,
                captured_at="2026-09-20T12:00:00+08:00",
                prospective=False,
                judgment_tier_hist={"price_only": 1},
                artifact_hash="a" * 64,
            )
        )
        uow.rsi.insert_observation(
            ObservationRow(
                observation_id="r0-correct",
                exp_id="R0",
                day="2026-09-20",
                population_stratum="jczq",
                n_rows=2,
                captured_at="2026-09-20T13:00:00+08:00",
                prospective=True,
                judgment_tier_hist={"deep_research": 2},
                artifact_hash="b" * 64,
            )
        )
        observations = uow.rsi.observations("F5") + uow.rsi.observations("R0")
        before = {row.observation_id: row for row in observations}

    report = run_migrations(engine)

    assert report.applied_versions == (39,)
    assert migration_status(engine).current_version == 39
    with OntologyUnitOfWork(engine) as uow:
        observations = uow.rsi.observations("F5") + uow.rsi.observations("R0")
        after = {row.observation_id: row for row in observations}
    assert set(after) == set(before)
    assert after["f5-wrong"].population_stratum == "pooled"
    assert after["r0-correct"].population_stratum == "jczq"
    for observation_id in before:
        assert after[observation_id].n_rows == before[observation_id].n_rows
        assert after[observation_id].captured_at == before[observation_id].captured_at
        assert after[observation_id].prospective == before[observation_id].prospective
        assert after[observation_id].artifact_hash == before[observation_id].artifact_hash
