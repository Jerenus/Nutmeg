import json
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.decision.ontology_adapter import (
    run_decision_am_v2,
    run_decision_read_v2,
)
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

DATE = "2026-07-19"
PRIOR = {"home": 0.5, "draw": 0.3, "away": 0.2}
SPORTTERY = {"matchInfoList": [{"businessDate": DATE, "subMatchList": [
    {"matchStatus": "Selling", "businessDate": DATE, "matchNumStr": "周日001",
     "matchNum": 7001, "matchId": 2040001, "matchDate": DATE, "matchTime": "23:30:00",
     "homeTeamAbbName": "哈马比", "awayTeamAbbName": "AIK", "leagueAbbName": "瑞典超",
     "had": {"h": "2.10", "d": "3.30", "a": "3.10"}}]}]}
BOLD = {"周日001": {"match_winner": {"odds": {"home": 2.05, "draw": 3.40, "away": 3.20}}}}


def _kernel_with_read(tmp_path: Path):
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
    reads = [{"read_id": "r1", "match_id": match_id, "market": "had",
              "prior": PRIOR, "belief": PRIOR, "factors": [],
              "made_at": "2026-07-19T15:00:00+08:00"}]
    (day / "reads.json").write_text(json.dumps(reads), encoding="utf-8")
    run_decision_read_v2(day / "reads.json", output_dir, kernel=kernel)
    return kernel, match_id, output_dir


def _write_legs(output_dir: Path, legs: list) -> Path:
    path = output_dir / "daily" / DATE / "legs.json"
    path.write_text(json.dumps(legs), encoding="utf-8")
    return path


