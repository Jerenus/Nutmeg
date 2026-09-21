from sqlalchemy import inspect

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import migration_status, run_migrations


def test_candidate_band_schema_is_additive_and_idempotent(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")

    first = run_migrations(engine)
    second = run_migrations(engine)

    assert 31 in first.applied_versions
    assert second.applied_versions == ()
    assert migration_status(engine).current_version == 40
    inspector = inspect(engine)
    columns = {
        column["name"] for column in inspector.get_columns("operator_candidates")
    }
    assert {
        "odds_band",
        "target_odds_min_decimal",
        "target_odds_max_decimal",
        "combined_decimal_odds",
        "parent_candidate_revision_id",
        "delta_reason",
    } <= columns
    set_columns = {
        column["name"]
        for column in inspector.get_columns("operator_candidate_set_revisions")
    }
    assert {"change_delta_json", "rationale"} <= set_columns
    assert "operator_candidate_band_outcomes" in inspector.get_table_names()
