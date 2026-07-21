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
