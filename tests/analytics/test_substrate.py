from pathlib import Path

from nutmeg.analytics.substrate import PROVENANCE_COLUMNS, AnalyticsProjectionBuilder
from nutmeg.ontology.paths import OntologyPaths
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.storage.duckdb_utils import connect_analytics_db

BUILT_AT = "2026-07-19T00:00:00+00:00"


def _engine(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    return engine


def test_build_is_deterministic_and_replaces(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    path = OntologyPaths.from_data_dir(tmp_path).analytics
    builder = AnalyticsProjectionBuilder(engine, path)

    def demo(ctx):
        ctx.write("demo", [{"x": 1}, {"x": 2}])

    r1 = builder.build([("demo", "demo-v1", demo)], built_at=BUILT_AT, high_watermark=5)
    r2 = builder.build([("demo", "demo-v1", demo)], built_at=BUILT_AT, high_watermark=5)
    assert r1.status == "succeeded" and r2.status == "succeeded"
    with connect_analytics_db(path) as con:
        assert con.execute("SELECT x FROM demo ORDER BY x").fetchall() == [(1,), (2,)]
        succeeded = con.execute(
            "SELECT count(*) FROM projection_runs WHERE status='succeeded'").fetchone()
        assert succeeded[0] == 2
        columns = {d[0] for d in con.execute("SELECT * FROM demo LIMIT 0").description}
        assert set(PROVENANCE_COLUMNS) <= columns


def test_failed_build_keeps_last_good(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    path = OntologyPaths.from_data_dir(tmp_path).analytics
    builder = AnalyticsProjectionBuilder(engine, path)
    builder.build(
        [("demo", "demo-v1", lambda ctx: ctx.write("demo", [{"x": 7}]))],
        built_at=BUILT_AT, high_watermark=1)

    def boom(ctx):
        raise RuntimeError("projector failed")

    result = builder.build([("demo", "demo-v1", boom)], built_at="2026-07-19T01:00:00+00:00",
                           high_watermark=2)
    assert result.status == "failed"
    with connect_analytics_db(path) as con:
        assert con.execute("SELECT x FROM demo").fetchall() == [(7,)]   # last good intact
        failed = con.execute(
            "SELECT count(*) FROM projection_runs WHERE status='failed'").fetchone()
        assert failed[0] == 1
