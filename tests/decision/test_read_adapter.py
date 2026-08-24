import json
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.decision.identity import canonical_match_id
from nutmeg.decision.ontology_adapter import run_decision_am_v2, run_decision_read_v2
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

DATE = "2026-07-19"
SPORTTERY = {"matchInfoList": [{"businessDate": DATE, "subMatchList": [
    {"matchStatus": "Selling", "businessDate": DATE, "matchNumStr": "周日001",
     "matchNum": 7001, "matchId": 2040001, "matchDate": DATE, "matchTime": "23:30:00",
     "homeTeamAbbName": "哈马比", "awayTeamAbbName": "AIK", "leagueAbbName": "瑞典超",
     "had": {"h": "2.10", "d": "3.30", "a": "3.10"}}]}]}
BOLD = {"周日001": {"match_winner": {"odds": {"home": 2.05, "draw": 3.40, "away": 3.20}}}}


def _kernel_with_match(tmp_path: Path):
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    output_dir = tmp_path / "jczq"
    day = output_dir / "daily" / DATE
    day.mkdir(parents=True)
    (day / "sporttery_markets.json").write_text(json.dumps(SPORTTERY), encoding="utf-8")
    (day / "bold_odds.json").write_text(json.dumps(BOLD), encoding="utf-8")
    run_decision_am_v2(DATE, output_dir, kernel=kernel, fetch=False)
    with OntologyUnitOfWork(kernel.engine) as uow:
        [match_id] = uow.identity.all_match_ids()
    return kernel, match_id, output_dir


def test_read_v2_commits_forecast(tmp_path: Path) -> None:
    kernel, match_id, output_dir = _kernel_with_match(tmp_path)
    reads = [{
        "read_id": "r1", "match_id": match_id, "snapshot_id": None, "market": "had",
        "prior": {"home": 0.5, "draw": 0.3, "away": 0.2},
        "belief": {"home": 0.6, "draw": 0.25, "away": 0.15},
        "factors": [{"factor_id": "lineup_gap", "direction": "home", "weight_pp": 3}],
        "made_at": "2026-07-19T15:00:00+08:00"}]
    reads_file = output_dir / "reads.json"
    reads_file.write_text(json.dumps(reads), encoding="utf-8")

    msg = run_decision_read_v2(reads_file, output_dir, kernel=kernel)
    assert "摄取 1/1" in msg
    assert "旧式因子丢弃 1" in msg          # old-style factor cannot be replayed
    assert kernel.status().forecast_count == 1


def test_read_v2_resolves_legacy_canonical_match_id(tmp_path: Path) -> None:
    kernel, match_id, output_dir = _kernel_with_match(tmp_path)
    legacy_match_id = canonical_match_id("哈马比", "AIK", DATE)
    reads = [{
        "read_id": "r-legacy", "match_id": legacy_match_id, "snapshot_id": None,
        "market": "had", "prior": {"home": 0.5, "draw": 0.3, "away": 0.2},
        "belief": {"home": 0.6, "draw": 0.25, "away": 0.15}, "factors": [],
        "made_at": "2026-07-19T15:00:00+08:00",
    }]
    reads_file = output_dir / "daily" / DATE / "reads-canonical.json"
    reads_file.write_text(json.dumps(reads), encoding="utf-8")

    msg = run_decision_read_v2(reads_file, output_dir, kernel=kernel)

    assert "摄取 1/1" in msg
    with OntologyUnitOfWork(kernel.engine) as uow:
        [revision] = uow.decision.iter_committed_revisions()
    assert revision.match_id == match_id


def test_read_v2_resolves_legacy_prior_snapshot_id(tmp_path: Path) -> None:
    kernel, match_id, output_dir = _kernel_with_match(tmp_path)
    reads = [{
        "read_id": "r-snapshot", "match_id": match_id,
        "snapshot_id": "S-read_time-sporttery-周日001-2026-07-19T15:00:00+08:00",
        "market": "had", "prior": {"home": 0.5, "draw": 0.3, "away": 0.2},
        "belief": {"home": 0.5, "draw": 0.3, "away": 0.2}, "factors": [],
        "made_at": "2026-07-19T15:00:00+08:00",
    }]
    reads_file = output_dir / "daily" / DATE / "reads-snapshot.json"
    reads_file.write_text(json.dumps(reads), encoding="utf-8")

    msg = run_decision_read_v2(reads_file, output_dir, kernel=kernel)

    assert "摄取 1/1" in msg
    with OntologyUnitOfWork(kernel.engine) as uow:
        series_id = uow.decision.ensure_series(match_id, "md-had")
        revision = uow.decision.current_committed_revision(series_id)
    assert revision is not None
    assert revision.prior_snapshot_id is not None
    assert revision.prior_snapshot_id.startswith("snapshot-")


def test_read_v2_rejects_unresolved_prior_snapshot_before_write(tmp_path: Path) -> None:
    kernel, match_id, output_dir = _kernel_with_match(tmp_path)
    reads = [{
        "read_id": "r-missing-snapshot", "match_id": match_id,
        "snapshot_id": "S-read_time-unknown-周日001-2026-07-19T15:00:00+08:00",
        "market": "had", "prior": {"home": 0.5, "draw": 0.3, "away": 0.2},
        "belief": {"home": 0.5, "draw": 0.3, "away": 0.2}, "factors": [],
        "made_at": "2026-07-19T15:00:00+08:00",
    }]
    reads_file = output_dir / "daily" / DATE / "reads-unresolved-snapshot.json"
    reads_file.write_text(json.dumps(reads), encoding="utf-8")

    msg = run_decision_read_v2(reads_file, output_dir, kernel=kernel)

    assert "摄取 0/1" in msg
    assert "r-missing-snapshot:unresolved_snapshot" in msg
    assert kernel.status().forecast_count == 0


def test_read_v2_rejects_unresolved_match_before_forecast_write(tmp_path: Path) -> None:
    kernel, _match_id, output_dir = _kernel_with_match(tmp_path)
    reads = [{
        "read_id": "r-missing", "match_id": "M-2026-07-19-不存在-也不存在",
        "market": "had", "prior": {"home": 0.5, "draw": 0.3, "away": 0.2},
        "belief": {"home": 0.5, "draw": 0.3, "away": 0.2}, "factors": [],
        "made_at": "2026-07-19T15:00:00+08:00",
    }]
    reads_file = output_dir / "daily" / DATE / "reads-unresolved.json"
    reads_file.write_text(json.dumps(reads), encoding="utf-8")

    msg = run_decision_read_v2(reads_file, output_dir, kernel=kernel)

    assert "摄取 0/1" in msg
    assert "r-missing:unresolved_match" in msg
    assert kernel.status().forecast_count == 0


def test_read_v2_rejects_unmapped_market(tmp_path: Path) -> None:
    kernel, match_id, output_dir = _kernel_with_match(tmp_path)
    reads = [{"read_id": "rX", "match_id": match_id, "market": "cricket",
              "prior": {"home": 0.4, "draw": 0.3, "away": 0.3},
              "belief": {"home": 0.4, "draw": 0.3, "away": 0.3}, "factors": [],
              "made_at": "2026-07-19T15:00:00+08:00"}]
    reads_file = output_dir / "reads.json"
    reads_file.write_text(json.dumps(reads), encoding="utf-8")

    msg = run_decision_read_v2(reads_file, output_dir, kernel=kernel)
    assert "摄取 0/1" in msg and "rX:unmapped_market" in msg
    assert kernel.status().forecast_count == 0
