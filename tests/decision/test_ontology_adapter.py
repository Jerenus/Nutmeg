import json
import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from typer.testing import CliRunner

import nutmeg.config.settings as settings_module
from nutmeg.config.settings import AppSettings
from nutmeg.decision.ontology_adapter import run_decision_am_v2
from nutmeg.ontology.repository import schema, schema_market
from nutmeg.ontology.wiring import build_ontology_kernel

DATE = "2026-07-19"
SPORTTERY = {"matchInfoList": [{"businessDate": DATE, "subMatchList": [
    {"matchStatus": "Selling", "businessDate": DATE, "matchNumStr": "周日001",
     "matchNum": 7001, "matchId": 2040001, "matchDate": DATE, "matchTime": "23:30:00",
     "homeTeamAbbName": "哈马比", "awayTeamAbbName": "AIK", "leagueAbbName": "瑞典超",
     "had": {"h": "2.10", "d": "3.30", "a": "3.10"}}]}]}
BOLD = {"周日001": {"match_winner": {"odds": {"home": 2.05, "draw": 3.40, "away": 3.20}}}}


def _write_snapshots(output_dir: Path) -> None:
    day = output_dir / "daily" / DATE
    day.mkdir(parents=True)
    (day / "sporttery_markets.json").write_text(json.dumps(SPORTTERY), encoding="utf-8")
    (day / "bold_odds.json").write_text(json.dumps(BOLD), encoding="utf-8")


def test_am_v2_ingests_into_kernel(tmp_path: Path) -> None:
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    output_dir = tmp_path / "jczq"
    _write_snapshots(output_dir)
    result = run_decision_am_v2(DATE, output_dir, kernel=kernel, fetch=False)
    assert result.succeeded
    assert "入库 1 场" in str(result)
    assert kernel.status().match_count == 1


def test_am_v2_replay_uses_source_file_capture_times(tmp_path: Path) -> None:
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    output_dir = tmp_path / "jczq"
    _write_snapshots(output_dir)
    day = output_dir / "daily" / DATE
    sporttery_at = datetime(2026, 7, 19, 7, 55, tzinfo=UTC)
    intl_at = datetime(2026, 7, 19, 7, 57, tzinfo=UTC)
    for path, captured_at in (
        (day / "sporttery_markets.json", sporttery_at),
        (day / "bold_odds.json", intl_at),
    ):
        path.touch()
        timestamp = captured_at.timestamp()
        os.utime(path, (timestamp, timestamp))

    result = run_decision_am_v2(DATE, output_dir, kernel=kernel, fetch=False)

    assert result.succeeded
    with kernel.engine.connect() as connection:
        source_times = connection.execute(
            select(
                schema_market.market_quotes.c.provider,
                schema_market.market_quotes.c.captured_at,
                schema.artifact_retrievals.c.retrieved_at,
            )
            .select_from(
                schema_market.market_quotes.join(
                    schema.artifact_retrievals,
                    schema_market.market_quotes.c.artifact_retrieval_id
                    == schema.artifact_retrievals.c.artifact_retrieval_id,
                )
            )
            .where(schema_market.market_quotes.c.provider.in_(("sporttery", "intl")))
        ).all()
    assert {
        (provider, captured_at, retrieved_at)
        for provider, captured_at, retrieved_at in source_times
    } == {
        ("sporttery", sporttery_at.isoformat(), sporttery_at.isoformat()),
        ("intl", intl_at.isoformat(), intl_at.isoformat()),
    }


def test_am_v2_empty_board_is_legal(tmp_path: Path) -> None:
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    result = run_decision_am_v2(DATE, tmp_path / "jczq", kernel=kernel, fetch=False)
    assert result.succeeded and "空盘" in str(result)
    assert kernel.status().match_count == 0


def test_flag_routes_am_to_v2(tmp_path: Path, monkeypatch) -> None:
    import nutmeg.interfaces.cli as cli

    calls = {"v2": 0, "old": 0}

    def fake_v2(run_date, output_dir, **kwargs):
        calls["v2"] += 1
        from nutmeg.decision.verbs import DecisionWorkflowResult
        return DecisionWorkflowResult("decision-am", run_date, (), "v2")

    monkeypatch.setattr("nutmeg.decision.ontology_adapter.run_decision_am_v2", fake_v2)
    monkeypatch.setenv("NUTMEG_ONTOLOGY_V2", "1")
    settings_module.get_settings.cache_clear()
    try:
        result = CliRunner().invoke(cli.app, [
            "decision-am", "--run-date", DATE, "--output-dir", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert calls["v2"] == 1               # flag on -> routed to the kernel adapter
    finally:
        settings_module.get_settings.cache_clear()


def test_unset_flag_keeps_old_path(tmp_path: Path, monkeypatch) -> None:
    import nutmeg.interfaces.cli as cli

    seen = {"old": 0}

    def fake_old(run_date, output_dir, **kwargs):
        seen["old"] += 1
        from nutmeg.decision.verbs import DecisionWorkflowResult
        return DecisionWorkflowResult("decision-am", run_date, (), "old")

    monkeypatch.setattr("nutmeg.decision.verbs.run_decision_am", fake_old)
    # 显式 =0(而非 delenv):生产 .env 已携带 NUTMEG_ONTOLOGY_V2=1,env var 优先级盖过 env_file
    monkeypatch.setenv("NUTMEG_ONTOLOGY_V2", "0")
    settings_module.get_settings.cache_clear()
    try:
        result = CliRunner().invoke(cli.app, [
            "decision-am", "--run-date", DATE, "--output-dir", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert seen["old"] == 1                # flag off -> old JSONL path unchanged
    finally:
        settings_module.get_settings.cache_clear()


# ── zucai 泳道穿透(2026-08-24 cutover 缺口修复) ──────────────────────────

ZUCAI_ISSUE = {"issue": "26110", "matches": [
    {"match_no": 1, "competition": "英超", "home_team": "曼城",
     "away_team": "伯恩茅斯", "match_date": "2026-08-23"}]}
ZUCAI_ODDS = {"issue_id": "26110", "captured_at": "2026-07-19T08:00:00+00:00", "matches": [
    {"match_no": 1, "home": 1.30, "draw": 5.50, "away": 9.00}]}


def _write_zucai(zucai_dir: Path) -> None:
    zucai_dir.mkdir(parents=True)
    (zucai_dir / "26110-issue.json").write_text(json.dumps(ZUCAI_ISSUE), encoding="utf-8")
    (zucai_dir / "26110-odds.json").write_text(json.dumps(ZUCAI_ODDS), encoding="utf-8")


def test_am_v2_with_issue_ingests_zucai(tmp_path: Path) -> None:
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    output_dir = tmp_path / "jczq"
    _write_snapshots(output_dir)
    zucai_dir = tmp_path / "zucai"
    _write_zucai(zucai_dir)
    result = run_decision_am_v2(DATE, output_dir, kernel=kernel, fetch=False,
                                issue="26110", zucai_dir=zucai_dir)
    assert result.succeeded
    assert "decision-sense-zucai-v2 26110: 入库 1 场" in str(result)
    assert (
        "kernel对账 Snapshot: actions落库 1 / prep报告 1 / service本次 1"
        in str(result)
    )
    assert kernel.status().match_count == 2   # jczq 1 + zucai 1
    with kernel.engine.connect() as connection:
        lineage = connection.execute(
            select(
                schema_market.market_quotes.c.provider,
                schema_market.market_quotes.c.captured_at,
                schema.artifact_retrievals.c.source_name,
                schema.artifact_retrievals.c.retrieved_at,
            )
            .select_from(
                schema_market.market_quotes.join(
                    schema.artifact_retrievals,
                    schema_market.market_quotes.c.artifact_retrieval_id
                    == schema.artifact_retrievals.c.artifact_retrieval_id,
                )
            )
            .where(schema_market.market_quotes.c.provider == "zucai")
        ).all()
    assert lineage
    assert {
        (provider, captured_at, source_name, retrieved_at)
        for provider, captured_at, source_name, retrieved_at in lineage
    } == {
        (
            "zucai",
            datetime(2026, 7, 19, 8, tzinfo=UTC).isoformat(),
            "zucai",
            datetime(2026, 7, 19, 8, tzinfo=UTC).isoformat(),
        )
    }


def test_am_v2_zucai_rerun_reconciles_cumulative_action_truth(tmp_path: Path) -> None:
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    output_dir = tmp_path / "jczq"
    _write_snapshots(output_dir)
    zucai_dir = tmp_path / "zucai"
    _write_zucai(zucai_dir)

    first = run_decision_am_v2(
        DATE, output_dir, kernel=kernel, fetch=False,
        issue="26110", zucai_dir=zucai_dir,
    )
    second = run_decision_am_v2(
        DATE, output_dir, kernel=kernel, fetch=False,
        issue="26110", zucai_dir=zucai_dir,
    )

    assert first.succeeded and second.succeeded
    assert (
        "kernel对账 Snapshot: actions落库 1 / prep报告 1 / service本次 0"
        in str(second)
    )


def test_am_v2_cross_issue_anchor_reuse_reconciles_original_action_truth(
    tmp_path: Path,
) -> None:
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    output_dir = tmp_path / "jczq"
    _write_snapshots(output_dir)
    zucai_dir = tmp_path / "zucai"
    _write_zucai(zucai_dir)
    first = run_decision_am_v2(
        DATE, output_dir, kernel=kernel, fetch=False,
        issue="26110", zucai_dir=zucai_dir,
    )
    (zucai_dir / "26111-issue.json").write_text(
        json.dumps({**ZUCAI_ISSUE, "issue": "26111"}), encoding="utf-8"
    )
    (zucai_dir / "26111-odds.json").write_text(
        json.dumps({**ZUCAI_ODDS, "issue_id": "26111"}),
        encoding="utf-8",
    )

    second = run_decision_am_v2(
        DATE, output_dir, kernel=kernel, fetch=False,
        issue="26111", zucai_dir=zucai_dir,
    )

    assert first.succeeded and second.succeeded
    assert (
        "kernel对账 Snapshot: actions落库 1 / prep报告 1 / service本次 0"
        in str(second)
    )


def test_am_v2_rejected_snapshot_fails_kernel_count_assertion(
    tmp_path: Path, monkeypatch,
) -> None:
    from nutmeg.ontology.actions.market_actions import MarketActions
    from nutmeg.ontology.actions.models import ActionOutcome, ActionStatus

    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    output_dir = tmp_path / "jczq"
    _write_snapshots(output_dir)
    zucai_dir = tmp_path / "zucai"
    _write_zucai(zucai_dir)

    def rejected(_self, _request) -> ActionOutcome:
        return ActionOutcome(
            action_id="ACT-denied",
            action_type="build_market_snapshot",
            status=ActionStatus.REJECTED,
            error_code="permission_denied",
        )

    monkeypatch.setattr(MarketActions, "build_snapshot", rejected)
    result = run_decision_am_v2(
        DATE, output_dir, kernel=kernel, fetch=False,
        issue="26110", zucai_dir=zucai_dir,
    )

    assert not result.succeeded
    assert "kernel_snapshot_count_mismatch" in str(result)
    assert "actions=0 prep=1 service=0" in str(result)


def test_am_v2_issue_missing_snapshot_degrades_visibly(tmp_path: Path) -> None:
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    output_dir = tmp_path / "jczq"
    _write_snapshots(output_dir)
    result = run_decision_am_v2(DATE, output_dir, kernel=kernel, fetch=False,
                                issue="26999", zucai_dir=tmp_path / "zucai-none")
    assert result.succeeded
    assert "源快照缺失" in str(result)
