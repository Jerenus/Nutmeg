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


def test_ai_read_v2_writes_a_draft_forecast(tmp_path: Path) -> None:
    kernel, match_id, output_dir = _kernel_with_match(tmp_path)
    reads = [{
        "read_id": "r-ai-draft", "match_id": match_id, "snapshot_id": None,
        "market": "had", "prior": {"home": 0.5, "draw": 0.3, "away": 0.2},
        "belief": {"home": 0.5, "draw": 0.3, "away": 0.2}, "factors": [],
        "made_at": "2026-07-19T15:00:00+08:00", "judge": "ai:jczq-analyst",
        "status": "draft",
    }]
    reads_file = output_dir / "reads-ai-draft.json"
    reads_file.write_text(json.dumps(reads), encoding="utf-8")

    msg = run_decision_read_v2(reads_file, output_dir, kernel=kernel)

    assert "摄取 1/1" in msg
    assert kernel.status().forecast_count == 0
    with OntologyUnitOfWork(kernel.engine) as uow:
        series_id = uow.decision.ensure_series(match_id, "md-had")
        assert uow.decision.current_committed_revision(series_id) is None
        assert uow.decision.max_revision_no(series_id) == 1


def test_market_anchor_draft_uses_ai_draft_forecast(tmp_path: Path) -> None:
    kernel, match_id, output_dir = _kernel_with_match(tmp_path)
    reads = [{
        "read_id": "r-market-anchor", "match_id": match_id, "snapshot_id": None,
        "market": "had", "prior": {"home": 0.5, "draw": 0.3, "away": 0.2},
        "belief": {"home": 0.5, "draw": 0.3, "away": 0.2}, "factors": [],
        "made_at": "2026-07-19T15:00:00+08:00", "judge": "market-anchor",
        "status": "draft",
    }]
    reads_file = output_dir / "reads-market-anchor.json"
    reads_file.write_text(json.dumps(reads), encoding="utf-8")

    msg = run_decision_read_v2(reads_file, output_dir, kernel=kernel)

    assert "摄取 1/1" in msg
    assert kernel.status().forecast_count == 0
    with OntologyUnitOfWork(kernel.engine) as uow:
        series_id = uow.decision.ensure_series(match_id, "md-had")
        assert uow.decision.current_committed_revision(series_id) is None
        assert uow.decision.max_revision_no(series_id) == 1


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


def test_read_v2_stores_the_whole_read_as_judgment_payload(tmp_path: Path) -> None:
    """判断唯一事实 P0：revision 装下整条 Read（kind/board_key/judgment_json）。"""
    kernel, match_id, output_dir = _kernel_with_match(tmp_path)
    read = {
        "read_id": "R-ai-jczq-2026-07-19-周日001-had-1500", "match_id": match_id,
        "snapshot_id": None, "market": "had", "prior": {"home": 0.5, "draw": 0.3, "away": 0.2},
        "belief": {"home": 0.55, "draw": 0.3, "away": 0.15}, "factors": [],
        "made_at": "2026-07-19T15:00:00+08:00", "judge": "ai:jczq-analyst", "status": "draft",
        "code": "周日001", "board_key": "jczq:2026-07-19", "kind": "research",
        "stance": {"face": "3", "structure": "single"},
        "note": "[周日001|哈马比-AIK|deep_research]",
    }
    reads_file = output_dir / "reads-payload.json"
    reads_file.write_text(json.dumps([read], ensure_ascii=False), encoding="utf-8")

    msg = run_decision_read_v2(reads_file, output_dir, kernel=kernel)

    assert "摄取 1/1" in msg
    with OntologyUnitOfWork(kernel.engine) as uow:
        [row] = list(uow.decision.iter_board_revisions("jczq:2026-07-19"))
    assert row.kind == "research" and row.judgment == read
    assert row.belief_distribution == read["belief"]


def test_read_v2_idempotency_prefix_lets_a_replay_resubmit_the_same_read(tmp_path: Path) -> None:
    """历史重放（判断唯一事实 P0 批量比对）用另一前缀重交同一条 Read，不撞生产的幂等键。"""
    kernel, match_id, output_dir = _kernel_with_match(tmp_path)
    read = {"read_id": "R-same", "match_id": match_id, "snapshot_id": None, "market": "had",
            "prior": {"home": 0.5, "draw": 0.3, "away": 0.2},
            "belief": {"home": 0.5, "draw": 0.3, "away": 0.2}, "factors": [],
            "made_at": "2026-07-19T15:00:00+08:00", "judge": "ai:jczq-analyst", "status": "draft",
            "board_key": "jczq:2026-07-19", "kind": "research", "code": "周日001"}
    reads_file = output_dir / "reads-prefix.json"
    reads_file.write_text(json.dumps([read]), encoding="utf-8")
    assert "摄取 1/1" in run_decision_read_v2(reads_file, output_dir, kernel=kernel)
    assert "摄取 1/1" in run_decision_read_v2(reads_file, output_dir, kernel=kernel,
                                             idempotency_prefix="replay")
    with OntologyUnitOfWork(kernel.engine) as uow:
        rows = list(uow.decision.iter_board_revisions("jczq:2026-07-19"))
    assert [r.revision_no for r in rows] == [1, 2]


def test_read_v2_absorbs_four_decimal_rounding_noise_but_not_real_errors(tmp_path: Path) -> None:
    # 26135 场11（2026-10-05）：18:30 新价 0.4586/0.2868/0.2545 合计 0.9999，整条被内核拒收
    kernel, match_id, output_dir = _kernel_with_match(tmp_path)
    reads = [
        {"read_id": "r-round", "match_id": match_id, "market": "had",
         "prior": {"home": 0.4586, "draw": 0.2868, "away": 0.2545},
         "belief": {"home": 0.4086, "draw": 0.3268, "away": 0.2645},
         "made_at": "2026-07-19T15:00:00+08:00"},
        {"read_id": "r-wrong", "match_id": match_id, "market": "had",
         "prior": {"home": 0.45, "draw": 0.28, "away": 0.25},
         "belief": {"home": 0.45, "draw": 0.28, "away": 0.25},
         "made_at": "2026-07-19T16:00:00+08:00"},
    ]
    reads_file = output_dir / "reads.json"
    reads_file.write_text(json.dumps(reads), encoding="utf-8")

    msg = run_decision_read_v2(reads_file, output_dir, kernel=kernel)
    assert "摄取 1/2" in msg and "r-wrong:distribution does not sum to 1" in msg
    assert kernel.status().forecast_count == 1
