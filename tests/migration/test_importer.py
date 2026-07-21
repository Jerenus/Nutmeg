from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.migration.importer import HistoricalImporter
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

MATCHES = [
    {"match_id": "old-m1", "home": "Alpha FC", "away": "Beta FC", "home_team_id": "t-a",
     "away_team_id": "t-b", "competition": "Test League", "competition_id": "c1",
     "kickoff_at": "2026-07-19T19:00:00+08:00", "channel_refs": {}},
    {"match_id": "old-m2", "home": "Gamma FC", "away": "Delta FC", "home_team_id": "t-g",
     "away_team_id": "t-d", "competition": "Test League", "competition_id": "c1",
     "kickoff_at": "2026-07-19T21:00:00+08:00", "channel_refs": {}},
]


def _kernel(tmp_path: Path):
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    return kernel


def test_import_matches_maps_ids_and_is_idempotent(tmp_path: Path) -> None:
    kernel = _kernel(tmp_path)
    importer = HistoricalImporter(kernel)
    report = importer.import_matches(MATCHES)
    assert set(report.match_id_map) == {"old-m1", "old-m2"}
    assert len(report.team_id_map) == 4       # four distinct imported teams
    assert kernel.status().match_count == 2

    # second import is a no-op (idempotent by derived key)
    HistoricalImporter(kernel).import_matches(MATCHES)
    assert kernel.status().match_count == 2


SNAPSHOTS = [
    {"snapshot_id": "old-s1", "match_id": "old-m1", "kind": "closing",
     "fair": {"home": 0.5, "draw": 0.3, "away": 0.2}, "raw_odds": {}, "lines": {},
     "source": "test", "taken_at": "2026-07-19T18:00:00+08:00"},
    {"snapshot_id": "old-s2", "match_id": "does-not-exist", "kind": "open",
     "fair": {"home": 0.4, "draw": 0.3, "away": 0.3}, "raw_odds": {}, "lines": {},
     "source": "test", "taken_at": "2026-07-19T10:00:00+08:00"},
]


def test_import_snapshots_reproduces_fair_and_skips_unmapped(tmp_path: Path) -> None:
    kernel = _kernel(tmp_path)
    importer = HistoricalImporter(kernel)
    importer.import_matches(MATCHES)
    importer.import_snapshots(SNAPSHOTS)
    assert set(importer.report.snapshot_id_map) == {"old-s1"}
    assert "snapshot:old-s2:unmapped_match" in importer.report.skipped
    new_match = importer.report.match_id_map["old-m1"]
    with OntologyUnitOfWork(kernel.engine) as uow:
        fair = uow.market.closing_fair(new_match, "md-had")
    assert abs(fair["home"] - 0.5) < 1e-9    # de-vig of no-vig quotes reproduces the old fair
    assert abs(fair["draw"] - 0.3) < 1e-9
    assert abs(fair["away"] - 0.2) < 1e-9


READS = [
    {"read_id": "old-r1", "match_id": "old-m1", "snapshot_id": "old-s1", "market": "had",
     "prior": {"home": 0.5, "draw": 0.3, "away": 0.2},
     "belief": {"home": 0.6, "draw": 0.25, "away": 0.15},
     "factors": [{"factor_id": "lineup_news_gap", "direction": "home", "weight_pp": 3}],
     "confidence": 4, "made_at": "2026-07-19T15:00:00+08:00", "falsifier": None, "note": ""},
    {"read_id": "old-r2", "match_id": "old-m2", "snapshot_id": None, "market": "cricket",
     "prior": {"home": 0.4, "draw": 0.3, "away": 0.3},
     "belief": {"home": 0.4, "draw": 0.3, "away": 0.3},
     "factors": [], "confidence": 3, "made_at": "2026-07-19T15:00:00+08:00"},
]
SETTLEMENTS = [
    {"settlement_id": "st-1", "ref_type": "read", "ref_id": "old-r1", "outcome_90": "home",
     "brier": 0.2, "clv_pp": None, "hit": 1, "settled_at": "2026-07-20T10:00:00+08:00"},
]


def test_import_reads_drops_factors_and_records_outcomes(tmp_path: Path) -> None:
    kernel = _kernel(tmp_path)
    importer = HistoricalImporter(kernel)
    importer.import_matches(MATCHES)
    importer.import_snapshots(SNAPSHOTS)
    importer.import_reads(READS)
    assert kernel.status().forecast_count == 1                 # r2 market unmapped -> skipped
    assert "read:old-r2:unmapped_market" in importer.report.skipped
    assert importer.report.counts["factors_dropped"] == 1      # old factor cannot be replayed
    importer.import_outcomes(SETTLEMENTS)
    assert importer.report.counts["outcomes"] == 1
    with OntologyUnitOfWork(kernel.engine) as uow:
        new_match = importer.report.match_id_map["old-m1"]
        assert uow.finance.current_outcome(new_match).score_90 == "1-0"   # home result
