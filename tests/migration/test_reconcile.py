from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.migration.importer import HistoricalImporter
from nutmeg.migration.reconcile import Reconciler
from nutmeg.ontology.wiring import build_ontology_kernel

MATCHES = [{"match_id": "old-m1", "home": "Alpha", "away": "Beta", "home_team_id": "t-a",
            "away_team_id": "t-b", "competition": "L", "competition_id": "c1",
            "kickoff_at": "2026-07-19T19:00:00+08:00", "channel_refs": {}}]
READS = [{"read_id": "old-r1", "match_id": "old-m1", "snapshot_id": None, "market": "had",
          "prior": {"home": 0.5, "draw": 0.3, "away": 0.2},
          "belief": {"home": 0.6, "draw": 0.25, "away": 0.15}, "factors": [],
          "made_at": "2026-07-19T15:00:00+08:00"}]
# brier(belief, home one-hot) = (0.6-1)^2 + 0.25^2 + 0.15^2 = 0.245
SETTLEMENTS = [
    {"settlement_id": "s1", "ref_type": "read", "ref_id": "old-r1", "outcome_90": "home",
     "brier": 0.245, "settled_at": "2026-07-20T10:00:00+08:00"},
    {"settlement_id": "s2", "ref_type": "read", "ref_id": "old-r1", "outcome_90": "home",
     "brier": 0.900, "settled_at": "2026-07-20T10:00:00+08:00"},   # deliberately wrong baseline
]


def test_reconcile_matches_rebuilt_brier(tmp_path: Path) -> None:
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    importer = HistoricalImporter(kernel)
    importer.import_matches(MATCHES)
    importer.import_reads(READS)
    importer.import_outcomes([SETTLEMENTS[0]])   # records the home outcome

    report = Reconciler(kernel).reconcile(
        importer.report, READS, SETTLEMENTS, as_of="2026-07-20T00:00:00+00:00",
        built_at="2026-07-20T00:00:00+00:00")
    assert report.matched == 1        # 0.245 baseline matches the rebuilt Brier
    assert report.mismatched == 1     # 0.900 baseline does not — reported, not hidden
    assert report.coverage == 1.0
