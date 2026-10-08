"""内核结算的赛果来源（2026-10-08 B1）：jc-results 为主，okooo 只补 jc-results 缺的场。"""
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from nutmeg.config.settings import AppSettings
from nutmeg.decision.ontology_adapter import (
    _normalize_score,
    _reconcile_v2,
    run_decision_am_v2,
)
from nutmeg.ontology.repository import schema_finance as sf
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

DATE = "2026-07-19"
AT = datetime(2026, 7, 20, 1, 0, tzinfo=UTC)


def _sub(code: str, mid: int, home: str, away: str) -> dict:
    return {"matchStatus": "Selling", "businessDate": DATE, "matchNumStr": code,
            "matchNum": 7000 + mid, "matchId": mid, "matchDate": DATE, "matchTime": "19:30:00",
            "homeTeamAbbName": home, "awayTeamAbbName": away, "leagueAbbName": "K联赛",
            "had": {"h": "3.60", "d": "3.20", "a": "1.85"}}


SPORTTERY = {"matchInfoList": [{"businessDate": DATE, "subMatchList": [
    _sub("周日001", 2050001, "光州FC", "金泉尚武"), _sub("周日002", 2050002, "大邱FC", "水原FC")]}]}


def _setup(tmp_path: Path):
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    output_dir = tmp_path / "jczq"
    day = output_dir / "daily" / DATE
    day.mkdir(parents=True)
    (day / "sporttery_markets.json").write_text(json.dumps(SPORTTERY), encoding="utf-8")
    run_decision_am_v2(DATE, output_dir, kernel=kernel, fetch=False)
    return kernel, output_dir


def _jc_results(output_dir: Path, rows: dict) -> None:
    (output_dir / "jc-results.json").write_text(json.dumps({DATE: rows}), encoding="utf-8")


def _outcomes(kernel) -> list[tuple[str, int, str]]:
    with kernel.engine.connect() as connection:
        rows = connection.execute(select(sf.match_outcomes.c.match_id, sf.match_outcomes.c.version,
                                         sf.match_outcomes.c.score_90)).all()
    return sorted(tuple(r) for r in rows)


def _kernel_ids(kernel) -> dict[str, str]:
    from nutmeg.ontology.identity.models import EntityType

    with OntologyUnitOfWork(kernel.engine) as uow:
        return {code: uow.identity.entity_by_external_id(
            EntityType.MATCH, provider="sporttery", external_id=str(mid))
            for code, mid in (("周日001", 2050001), ("周日002", 2050002))}


def _no_okooo(_run_date):
    raise AssertionError("okooo must not be called when jc-results covers the board")


def test_normalize_score_variants() -> None:
    assert _normalize_score("2-1") == "2-1"
    assert _normalize_score("2:1") == "2-1"
    assert _normalize_score("2：1") == "2-1"
    assert _normalize_score("home") == "1-0"
    assert _normalize_score("") is None
    assert _normalize_score(None) is None
    assert _normalize_score("abandoned") is None


def test_settle_takes_jc_results_and_never_calls_okooo_when_the_board_is_sealed(tmp_path):
    kernel, output_dir = _setup(tmp_path)
    _jc_results(output_dir, {"周日001": {"ft_home": 2, "ft_away": 1},
                             "周日002": {"ft_home": 0, "ft_away": 0}})
    msg = _reconcile_v2(kernel, DATE, output_dir, AT, live_fetcher=_no_okooo)
    ids = _kernel_ids(kernel)
    assert _outcomes(kernel) == sorted([(ids["周日001"], 1, "2-1"), (ids["周日002"], 1, "0-0")])
    assert "结算 2 场结果" in msg and "来源 jc-results 2" in msg


def test_okooo_only_fills_codes_jc_results_lacks(tmp_path):
    kernel, output_dir = _setup(tmp_path)
    _jc_results(output_dir, {"周日001": {"ft_home": 2, "ft_away": 1}})
    okooo = {"周日001": {"score": "9:9"}, "周日002": {"score": "1:3"}}   # 001 的 okooo 比分不被采用
    msg = _reconcile_v2(kernel, DATE, output_dir, AT, live_fetcher=lambda _d: okooo)
    ids = _kernel_ids(kernel)
    assert _outcomes(kernel) == sorted([(ids["周日001"], 1, "2-1"), (ids["周日002"], 1, "1-3")])
    assert "来源 jc-results 1 · okooo 1" in msg


def test_legs_base_identity_settles_matches_the_snapshot_dropped(tmp_path):
    kernel, output_dir = _setup(tmp_path)
    ids = _kernel_ids(kernel)
    day = output_dir / "daily" / DATE
    # 体彩实时快照会丢掉已完场的场次；legs-base 保留全板身份
    (day / "sporttery_markets.json").write_text(json.dumps({"matchInfoList": []}),
                                                encoding="utf-8")
    (day / "jczq-legs-base.json").write_text(json.dumps({"legs": {
        "周日001": {"match_id": ids["周日001"]}, "周日002": {"match_id": ids["周日002"]},
        "周日003": {"match_id": "match-not-in-kernel"}}}), encoding="utf-8")
    _jc_results(output_dir, {"周日001": {"ft_home": 1, "ft_away": 0},
                             "周日002": {"ft_home": 1, "ft_away": 2},
                             "周日003": {"ft_home": 0, "ft_away": 0}})
    _reconcile_v2(kernel, DATE, output_dir, AT, live_fetcher=_no_okooo)
    assert _outcomes(kernel) == sorted([(ids["周日001"], 1, "1-0"), (ids["周日002"], 1, "1-2")])


def test_rerun_and_disagreement_never_add_versions(tmp_path):
    kernel, output_dir = _setup(tmp_path)
    _jc_results(output_dir, {"周日001": {"ft_home": 2, "ft_away": 1},
                             "周日002": {"ft_home": 0, "ft_away": 0}})
    _reconcile_v2(kernel, DATE, output_dir, AT, live_fetcher=_no_okooo)
    before = _outcomes(kernel)
    again = _reconcile_v2(kernel, DATE, output_dir, AT, live_fetcher=_no_okooo)
    assert _outcomes(kernel) == before and "结算 0 场结果" in again
    assert "内核已有同比分 2 场" in again
    _jc_results(output_dir, {"周日001": {"ft_home": 3, "ft_away": 1},
                             "周日002": {"ft_home": 0, "ft_away": 0}})
    changed = _reconcile_v2(kernel, DATE, output_dir, AT, live_fetcher=_no_okooo)
    assert _outcomes(kernel) == before
    assert "比分与内核已记不一致 1 场" in changed and "内核 2-1 vs jc-results 3-1" in changed
