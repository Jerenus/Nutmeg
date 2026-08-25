from pathlib import Path

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.market import MarketRepository, QuoteRow, SnapshotRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _prepare(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")   # matches row only, for FK
    return engine


def test_insert_quote_and_snapshot_links(tmp_path: Path) -> None:
    engine = _prepare(tmp_path)
    with OntologyUnitOfWork(engine) as uow:
        repo: MarketRepository = uow.market
        repo.insert_quote(QuoteRow(
            quote_id="q1", match_id="match-1", market_definition_id="md-had",
            selection_id="sel-had-home", provider="sporttery", bookmaker=None,
            decimal_odds=2.1, captured_at="2026-07-19T15:00:00+08:00",
            artifact_retrieval_id=None, quote_status="active",
        ))
        repo.insert_snapshot(SnapshotRow(
            market_snapshot_id="s1", match_id="match-1", market_definition_id="md-had",
            snapshot_kind="read_time", as_of="2026-07-19T15:00:00+08:00",
            fair_distribution={"home": 0.5, "draw": 0.3, "away": 0.2},
            devig_method="proportional", method_version="1",
            source_coverage={"providers": 1}, freshness={"age_s": 0}, disagreement={},
        ), quote_ids=("q1",))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.market.count_quotes() == 1
        assert uow.market.count_snapshots() == 1
        assert uow.market.snapshot_quote_ids("s1") == ("q1",)
        assert uow.market.snapshot_exists_for("s1", "match-1", "md-had") is True
        assert uow.market.snapshot_id_for_source(
            "match-1", "md-had", "read_time", "sporttery"
        ) == "s1"
        assert uow.market.snapshot_id_for_source(
            "match-1", "md-had", "read_time", "intl"
        ) is None
