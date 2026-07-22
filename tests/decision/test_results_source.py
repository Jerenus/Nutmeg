import json
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.decision.ontology_adapter import (
    _normalize_score,
    _results_v2,
    run_decision_am_v2,
    run_decision_express_v2,
    run_decision_read_v2,
    run_decision_settle_v2,
)
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

DATE = "2026-07-19"
PRIOR = {"home": 0.5, "draw": 0.3, "away": 0.2}
SPORTTERY = {"matchInfoList": [{"businessDate": DATE, "subMatchList": [
    {"matchStatus": "Selling", "businessDate": DATE, "matchNumStr": "周三001",
     "matchNum": 7001, "matchId": 2050001, "matchDate": DATE, "matchTime": "19:30:00",
     "homeTeamAbbName": "光州FC", "awayTeamAbbName": "金泉尚武", "leagueAbbName": "K联赛",
     "had": {"h": "3.60", "d": "3.20", "a": "1.85"}}]}]}


def test_normalize_score_variants() -> None:
    assert _normalize_score("2-1") == "2-1"
    assert _normalize_score("2:1") == "2-1"
    assert _normalize_score("2：1") == "2-1"
    assert _normalize_score("home") == "1-0"
    assert _normalize_score("") is None
    assert _normalize_score(None) is None
    assert _normalize_score("abandoned") is None


def _kernel_with_ticket(tmp_path: Path):
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    output_dir = tmp_path / "jczq"
    day = output_dir / "daily" / DATE
    day.mkdir(parents=True)
    (day / "sporttery_markets.json").write_text(json.dumps(SPORTTERY), encoding="utf-8")
    run_decision_am_v2(DATE, output_dir, kernel=kernel, fetch=False)
    with OntologyUnitOfWork(kernel.engine) as uow:
        [match_id] = uow.identity.all_match_ids()
    reads = [{"read_id": "r1", "match_id": match_id, "market": "had",
              "prior": PRIOR, "belief": PRIOR, "factors": [],
              "made_at": f"{DATE}T15:00:00+08:00"}]
    (day / "reads.json").write_text(json.dumps(reads), encoding="utf-8")
    run_decision_read_v2(day / "reads.json", output_dir, kernel=kernel)
    legs = [{"match_id": match_id, "market": "had", "selection": "away",
             "odds": 1.85, "bucket": "main"}]
    (day / "legs.json").write_text(json.dumps(legs), encoding="utf-8")
    run_decision_express_v2(day / "legs.json", output_dir, kernel=kernel)
    return kernel, match_id, output_dir


def test_okooo_results_map_to_kernel_and_settle(tmp_path: Path) -> None:
    kernel, match_id, output_dir = _kernel_with_ticket(tmp_path)

    def fake_okooo(run_date):
        assert run_date == DATE
        return {"周三001": {"score": "0:2", "had": "客胜"},      # away wins → leg wins
                "周三002": {"score": None}}                      # 未终局 → skipped

    results = _results_v2(kernel, DATE, output_dir, live_fetcher=fake_okooo)
    assert results == {match_id: "0-2"}

    outcome = run_decision_settle_v2(DATE, output_dir, kernel=kernel,
                                     results_fetcher=fake_okooo)
    assert outcome.succeeded
    with OntologyUnitOfWork(kernel.engine) as uow:
        # 主注 ¥100 @1.85 中 → -100 + 185 = +85 (odds-faithful)
        assert uow.finance.ledger_balance("acct-jczq") == 85.0


def test_manual_results_json_overrides_and_accepts_real_scores(tmp_path: Path) -> None:
    kernel, match_id, output_dir = _kernel_with_ticket(tmp_path)
    (output_dir / "daily" / DATE / "results.json").write_text(
        json.dumps({match_id: "1:3"}), encoding="utf-8")

    def exploding_fetcher(run_date):   # manual override must win — never called
        raise AssertionError("okooo fetcher must not be called when results.json exists")

    results = _results_v2(kernel, DATE, output_dir, live_fetcher=exploding_fetcher)
    assert results == {match_id: "1-3"}


def test_fetch_failure_settles_nothing(tmp_path: Path) -> None:
    kernel, _match_id, output_dir = _kernel_with_ticket(tmp_path)

    def broken_fetcher(run_date):
        raise RuntimeError("okooo down")

    outcome = run_decision_settle_v2(DATE, output_dir, kernel=kernel,
                                     results_fetcher=broken_fetcher)
    assert outcome.succeeded                            # 抓不到 → 跳过,不产 pending
    assert kernel.status().settlement_count == 0


def test_partial_day_settles_rest_on_rerun(tmp_path: Path) -> None:
    kernel, match_id, output_dir = _kernel_with_ticket(tmp_path)

    def first_run(run_date):
        return {}                                       # 当晚: 本场未终局

    def second_run(run_date):
        return {"周三001": {"score": "0:2"}}            # 次日: 终局

    run_decision_settle_v2(DATE, output_dir, kernel=kernel, results_fetcher=first_run)
    assert kernel.status().settlement_count == 0        # 未终局 → 无 pending
    run_decision_settle_v2(DATE, output_dir, kernel=kernel, results_fetcher=second_run)
    assert kernel.status().settlement_count == 1        # 次日补结,同 key 幂等不冲突
    run_decision_settle_v2(DATE, output_dir, kernel=kernel, results_fetcher=second_run)
    assert kernel.status().settlement_count == 1        # 三跑 replay,不重复结算


def test_kickoff_guard_rejects_results_for_unplayed_matches(tmp_path: Path) -> None:
    from datetime import UTC, datetime
    kernel, match_id, output_dir = _kernel_with_ticket(tmp_path)

    def poison_okooo(run_date):
        # okooo 开奖页回退:未开奖日返回别的开奖日的行(2026-07-22 真实事故)
        return {"周三001": {"score": "1:1"}}

    kickoff = datetime.fromisoformat(f"{DATE}T19:30:00+08:00")
    before = kickoff.astimezone(UTC).replace(hour=5)               # 开球前
    just_under = kickoff + __import__("datetime").timedelta(minutes=100)   # 开球后100min<110
    after = kickoff + __import__("datetime").timedelta(minutes=115)        # 可能终局

    assert _results_v2(kernel, DATE, output_dir, live_fetcher=poison_okooo,
                       now=before) == {}
    assert _results_v2(kernel, DATE, output_dir, live_fetcher=poison_okooo,
                       now=just_under) == {}
    assert _results_v2(kernel, DATE, output_dir, live_fetcher=poison_okooo,
                       now=after) == {match_id: "1-1"}


def test_manual_override_bypasses_kickoff_guard(tmp_path: Path) -> None:
    # 人工 results.json 是显式动作(改期/腰斩等特殊场景的出口),不受 guard 限制
    from datetime import UTC, datetime
    kernel, match_id, output_dir = _kernel_with_ticket(tmp_path)
    (output_dir / "daily" / DATE / "results.json").write_text(
        json.dumps({match_id: "2-0"}), encoding="utf-8")
    early = datetime(2026, 7, 19, 1, 0, tzinfo=UTC)   # 远早于开球
    assert _results_v2(kernel, DATE, output_dir, now=early) == {match_id: "2-0"}
