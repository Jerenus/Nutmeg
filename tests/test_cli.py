from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.config.settings import clear_settings_cache
from nutmeg.domain.fixtures import sample_fixtures
from nutmeg.interfaces.cli import app

runner = CliRunner()


def test_odds_snapshot_command_returns_json(monkeypatch) -> None:
    from datetime import UTC, datetime

    from nutmeg.domain.odds import (
        BookmakerQuote,
        MarketOddsSnapshot,
        OddsProviderSnapshot,
        OddsSnapshot,
        OutcomeOddsSnapshot,
    )

    fixture = sample_fixtures("epl")[0]
    snapshot = OddsSnapshot(
        fixture=fixture,
        provider=OddsProviderSnapshot(
            name="api-football",
            updated_at=datetime(2026, 4, 24, 6, 16, 30, tzinfo=UTC),
            bookmaker_count=2,
        ),
        markets={
            "match_winner": MarketOddsSnapshot(
                market_key="match_winner",
                market_name="Match Winner",
                status="available",
                line=None,
                source_market_ids=[1],
                outcomes=[
                    OutcomeOddsSnapshot(
                        outcome_key="home",
                        outcome_name="Home",
                        bookmaker_quotes=[
                            BookmakerQuote(
                                bookmaker_id=1,
                                bookmaker_name="10Bet",
                                market_id=1,
                                market_name="Match Winner",
                                selection_value="Home",
                                decimal_odds=1.48,
                                source="api-football",
                            )
                        ],
                        best_odds=1.48,
                        average_odds=1.48,
                        fair_probability=0.63,
                        fair_odds=1.59,
                        bookmaker_count=1,
                    )
                ],
            )
        },
        deferred_sections=[],
    )

    monkeypatch.setattr(
        "nutmeg.interfaces.cli.build_odds_service",
        lambda: (
            type(
                "FakeOddsService",
                (),
                {"build_snapshot": lambda self, fixture_id: snapshot},
            )(),
            type("FakeSession", (), {"close": lambda self: None})(),
        ),
        raising=False,
    )

    result = runner.invoke(
        app,
        ["odds-snapshot", "--fixture-id", fixture.fixture_id, "--format", "json"],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["provider"]["name"] == "api-football"
    assert (
        payload["markets"]["match_winner"]["outcomes"][0]["bookmaker_quotes"][0]["bookmaker_name"]
        == "10Bet"
    )
    assert payload["markets"]["match_winner"]["outcomes"][0]["fair_probability"] == 0.63


def test_odds_snapshot_command_fails_cleanly_for_missing_fixture(monkeypatch) -> None:
    from nutmeg.services.odds import OddsFixtureNotFoundError

    monkeypatch.setattr(
        "nutmeg.interfaces.cli.build_odds_service",
        lambda: (
            type(
                "FakeOddsService",
                (),
                {
                    "build_snapshot": lambda self, fixture_id: (_ for _ in ()).throw(
                        OddsFixtureNotFoundError(
                            f"Fixture `{fixture_id}` was not found in the local cache."
                        )
                    )
                },
            )(),
            type("FakeSession", (), {"close": lambda self: None})(),
        ),
        raising=False,
    )

    result = runner.invoke(app, ["odds-snapshot", "--fixture-id", "missing-001"])

    assert result.exit_code == 2
    assert "missing-001" in result.stdout


def test_odds_snapshot_command_renders_text(monkeypatch) -> None:
    from datetime import UTC, datetime

    from nutmeg.domain.odds import (
        BookmakerQuote,
        HistoricalMarketPoint,
        HistoricalMarketSummary,
        MarketOddsSnapshot,
        OddsProviderSnapshot,
        OddsSnapshot,
        OutcomeOddsSnapshot,
    )

    fixture = sample_fixtures("epl")[0]
    snapshot = OddsSnapshot(
        fixture=fixture,
        provider=OddsProviderSnapshot(
            name="api-football",
            updated_at=datetime(2026, 4, 24, 6, 16, 30, tzinfo=UTC),
            bookmaker_count=2,
        ),
        markets={
            "match_winner": MarketOddsSnapshot(
                market_key="match_winner",
                market_name="Match Winner",
                status="available",
                line=None,
                source_market_ids=[1],
                outcomes=[
                    OutcomeOddsSnapshot(
                        outcome_key="home",
                        outcome_name="Home",
                        bookmaker_quotes=[
                            BookmakerQuote(
                                bookmaker_id=1,
                                bookmaker_name="10Bet",
                                market_id=1,
                                market_name="Match Winner",
                                selection_value="Home",
                                decimal_odds=1.48,
                                source="api-football",
                            )
                        ],
                        best_odds=1.48,
                        average_odds=1.48,
                        fair_probability=0.63,
                        fair_odds=1.59,
                        bookmaker_count=1,
                    )
                ],
            )
        },
        deferred_sections=[],
        history={
            "match_winner": HistoricalMarketSummary(
                market_key="match_winner",
                line=None,
                points=[
                    HistoricalMarketPoint(
                        captured_at=datetime(2026, 4, 24, 5, 16, 30, tzinfo=UTC),
                        provider="api-football",
                        market_key="match_winner",
                        line=None,
                        outcome_probabilities={"home": 0.63},
                        outcome_fair_odds={"home": 1.59},
                        outcome_best_odds={"home": 1.48},
                        bookmaker_count=1,
                    )
                ],
                drift_vs_current={"home": 0.0},
                movement="flat",
                movement_span=0.0,
            )
        },
    )

    monkeypatch.setattr(
        "nutmeg.interfaces.cli.build_odds_service",
        lambda: (
            type(
                "FakeOddsService",
                (),
                {"build_snapshot": lambda self, fixture_id: snapshot},
            )(),
            type("FakeSession", (), {"close": lambda self: None})(),
        ),
        raising=False,
    )

    result = runner.invoke(app, ["odds-snapshot", "--fixture-id", fixture.fixture_id])

    assert result.exit_code == 0
    assert (
        "provider name=api-football updated=2026-04-24T06:16:30+00:00 bookmakers=2" in result.stdout
    )
    assert "match_winner status=available source_ids=[1]" in result.stdout
    assert "home best=1.48 avg=1.48 fair_prob=0.6300 fair_odds=1.590 books=1" in result.stdout
    assert "history points=1 movement=flat span=0.0 drift={'home': 0.0}" in result.stdout


def test_odds_snapshot_command_fails_cleanly_without_api_key(monkeypatch) -> None:
    from nutmeg.config.settings import get_settings
    from nutmeg.storage.bootstrap import create_analytics_schema, ensure_storage_paths
    from nutmeg.storage.fixture_repository import DuckDbFixtureRepository

    monkeypatch.setenv("NUTMEG_API_FOOTBALL_KEY", "")
    clear_settings_cache()
    settings = get_settings()
    ensure_storage_paths(settings)
    create_analytics_schema(settings)
    DuckDbFixtureRepository(settings).upsert_many(fixtures=sample_fixtures("epl"))

    result = runner.invoke(app, ["odds-snapshot", "--fixture-id", "epl-001"])

    assert result.exit_code == 2
    assert "NUTMEG_API_FOOTBALL_KEY is not configured" in result.stdout


def test_value_board_command_returns_json_contract(monkeypatch) -> None:
    from datetime import UTC, datetime

    from nutmeg.domain.value import ValueBoard, ValueCandidate
    from nutmeg.interfaces import cli as cli_module

    class FakeSession:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class FakeValueBoardService:
        def build_board(self, *, league: str, days: int, limit: int, min_edge: float):
            assert league == "epl"
            assert days == 3
            assert limit == 5
            assert min_edge == 0.03
            return ValueBoard(
                league="epl",
                days=3,
                generated_at=datetime(2026, 4, 25, 10, 0, tzinfo=UTC),
                candidates=[
                    ValueCandidate(
                        fixture_id="fx-1",
                        kickoff_at=datetime(2026, 4, 25, 15, 0, tzinfo=UTC),
                        home_team="Arsenal",
                        away_team="Tottenham Hotspur",
                        outcome_key="home",
                        outcome_name="Home",
                        model_probability=0.56,
                        market_probability=0.45,
                        edge=0.11,
                        best_odds=2.2,
                        expected_value=0.232,
                        quarter_kelly_fraction=0.048,
                        rating="strong",
                        model_name="dixon-coles-lite-poisson",
                        source_notes=["model=recent-xg-matchup", "odds=test-odds"],
                    )
                ],
                skipped=[],
            )

    session = FakeSession()
    monkeypatch.setattr(
        cli_module,
        "build_value_board_service",
        lambda: (FakeValueBoardService(), session),
    )

    result = runner.invoke(
        app,
        [
            "value-board",
            "--league",
            "epl",
            "--days",
            "3",
            "--limit",
            "5",
            "--min-edge",
            "0.03",
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert session.closed is True
    assert payload["league"] == "epl"
    assert payload["candidates"][0]["fixture_id"] == "fx-1"
    assert payload["candidates"][0]["edge"] == 0.11
    assert payload["candidates"][0]["quarter_kelly_fraction"] == 0.048


def test_player_profile_command_returns_json_contract(monkeypatch) -> None:
    from datetime import UTC, datetime

    from nutmeg.domain.players import (
        PlayerAvailability,
        PlayerIdentityProfile,
        PlayerMarketProfile,
        PlayerProfile,
        PlayerSeasonMetrics,
        SimilarPlayer,
    )
    from nutmeg.interfaces import cli as cli_module

    class FakeSession:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class FakePlayerProfileService:
        def build_profile(
            self,
            *,
            league: str,
            season: int | None,
            team: str,
            player: str,
            similar_limit: int = 5,
        ):
            assert league == "epl"
            assert season == 2025
            assert team == "Arsenal"
            assert player == "Bukayo Saka"
            assert similar_limit == 3
            return PlayerProfile(
                query_player="Bukayo Saka",
                query_team="Arsenal",
                league="epl",
                season=2025,
                generated_at=datetime(2026, 4, 25, 10, 0, tzinfo=UTC),
                identity=PlayerIdentityProfile(
                    identity_id="epl:arsenal:bukayo-saka",
                    canonical_name="Bukayo Saka",
                    team_name="Arsenal",
                    match_confidence="catalog",
                ),
                market=PlayerMarketProfile(
                    provider_player_id="7",
                    position="Right Winger",
                    market_value_eur=140000000,
                    source="transfermarkt-datasets",
                ),
                season_metrics=PlayerSeasonMetrics(
                    source="soccerdata-cache",
                    minutes=2500,
                    goals_per90=0.42,
                    assists_per90=0.33,
                    xg_per90=0.48,
                    xa_per90=0.30,
                    key_passes_per90=2.4,
                    duels_won_per90=3.2,
                ),
                availability=PlayerAvailability(
                    status="available",
                    reason=None,
                    expected_return=None,
                    source="local-cache",
                ),
                similar_players=[
                    SimilarPlayer(
                        player_name="Phil Foden",
                        team_name="Manchester City",
                        position="Right Winger",
                        similarity_score=0.98,
                        source="soccerdata-cache",
                    )
                ],
                unavailable_sections=[],
            )

    session = FakeSession()
    monkeypatch.setattr(
        cli_module,
        "build_player_profile_service",
        lambda: (FakePlayerProfileService(), session),
    )

    result = runner.invoke(
        app,
        [
            "player-profile",
            "--league",
            "epl",
            "--season",
            "2025",
            "--team",
            "Arsenal",
            "--player",
            "Bukayo Saka",
            "--similar-limit",
            "3",
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert session.closed is True
    assert payload["identity"]["canonical_name"] == "Bukayo Saka"
    assert payload["market"]["market_value_eur"] == 140000000
    assert payload["season_metrics"]["xg_per90"] == 0.48
    assert payload["similar_players"][0]["player_name"] == "Phil Foden"


def test_eval_run_command_returns_json_contract(monkeypatch) -> None:
    from datetime import UTC, datetime

    from nutmeg.domain.evals import EvalCaseResult, EvalRunResult
    from nutmeg.interfaces import cli as cli_module

    class FakeEvalService:
        def run_dataset(self, dataset: str):
            assert dataset == "starter"
            return EvalRunResult(
                dataset="starter",
                generated_at=datetime(2026, 4, 25, 11, 0, tzinfo=UTC),
                total_cases=1,
                passed_cases=1,
                failed_cases=0,
                results=[
                    EvalCaseResult(
                        case_id="case-1",
                        category="odds",
                        passed=True,
                        missing_keywords=[],
                        output_text="判断：edge. 置信度：中。",
                    )
                ],
            )

    monkeypatch.setattr(cli_module, "build_eval_service", lambda: FakeEvalService())

    result = runner.invoke(app, ["eval-run", "--dataset", "starter", "--format", "json"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["dataset"] == "starter"
    assert payload["passed_cases"] == 1
    assert payload["results"][0]["passed"] is True


def test_prediction_review_command_returns_json_contract(monkeypatch) -> None:
    from nutmeg.domain.evals import PredictionReviewSummary
    from nutmeg.interfaces import cli as cli_module

    class FakeSession:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class FakePredictionRepository:
        def review(self, *, user_id: str):
            assert user_id == "owner"
            return PredictionReviewSummary(
                total_predictions=3,
                resolved_predictions=2,
                average_brier_score=0.31,
                pick_accuracy=0.5,
            )

    session = FakeSession()
    monkeypatch.setattr(
        cli_module,
        "build_prediction_repository",
        lambda: (FakePredictionRepository(), session),
    )

    result = runner.invoke(app, ["prediction-review", "--format", "json"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert session.closed is True
    assert payload["resolved_predictions"] == 2
    assert payload["average_brier_score"] == 0.31


def test_telegram_bot_status_reports_configuration_without_token(monkeypatch) -> None:
    monkeypatch.setenv("NUTMEG_TELEGRAM_BOT_TOKEN", "telegram-secret")
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "111,222")
    clear_settings_cache()

    result = runner.invoke(app, ["telegram-bot-status", "--format", "json"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["configured"] is True
    assert payload["allowed_chat_count"] == 2
    assert payload["allowed_chat_ids_configured"] is True
    assert "telegram-secret" not in result.stdout


def test_telegram_bot_poll_once_uses_runner_builder(monkeypatch) -> None:
    from nutmeg.interfaces import cli as cli_module

    class StubSummary:
        updates_seen = 2
        messages_handled = 1
        messages_denied = 1
        messages_ignored = 0
        next_offset = 12

    class StubRunner:
        def poll_once(self, *, offset: int | None, timeout: int):
            assert offset == 10
            assert timeout == 1
            return StubSummary()

    monkeypatch.setenv("NUTMEG_TELEGRAM_BOT_TOKEN", "telegram-secret")
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "111")
    clear_settings_cache()
    monkeypatch.setattr(cli_module, "build_telegram_bot_runner", lambda settings: StubRunner())

    result = runner.invoke(
        app,
        ["telegram-bot-poll-once", "--offset", "10", "--timeout", "1", "--format", "json"],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["updates_seen"] == 2
    assert payload["messages_handled"] == 1
    assert payload["messages_denied"] == 1
    assert payload["next_offset"] == 12
    assert "telegram-secret" not in result.stdout


def test_telegram_bot_run_uses_daemon_builder(monkeypatch) -> None:
    from nutmeg.interfaces import cli as cli_module

    class StubSummary:
        polls_run = 2
        updates_seen = 3
        messages_handled = 2
        messages_denied = 1
        messages_ignored = 0
        next_offset = 13
        stop_reason = "max_polls"

    class StubDaemon:
        def run(self, *, offset: int | None, timeout: int, max_polls: int | None):
            assert offset == 10
            assert timeout == 1
            assert max_polls == 2
            return StubSummary()

    monkeypatch.setenv("NUTMEG_TELEGRAM_BOT_TOKEN", "telegram-secret")
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "111")
    clear_settings_cache()
    monkeypatch.setattr(
        cli_module,
        "build_telegram_polling_daemon",
        lambda settings, poll_interval_seconds, offset_store=None: StubDaemon(),
    )

    result = runner.invoke(
        app,
        [
            "telegram-bot-run",
            "--offset",
            "10",
            "--timeout",
            "1",
            "--poll-interval",
            "0",
            "--max-polls",
            "2",
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["polls_run"] == 2
    assert payload["updates_seen"] == 3
    assert payload["messages_handled"] == 2
    assert payload["messages_denied"] == 1
    assert payload["next_offset"] == 13
    assert payload["stop_reason"] == "max_polls"
    assert "telegram-secret" not in result.stdout


def test_telegram_bot_run_uses_stored_offset_when_offset_omitted(monkeypatch, tmp_path) -> None:
    from nutmeg.interfaces import cli as cli_module

    class StubSummary:
        polls_run = 1
        updates_seen = 0
        messages_handled = 0
        messages_denied = 0
        messages_ignored = 0
        next_offset = 100
        stop_reason = "max_polls"

    class StubDaemon:
        def run(self, *, offset: int | None, timeout: int, max_polls: int | None):
            assert offset == 99
            assert timeout == 1
            assert max_polls == 1
            return StubSummary()

    offset_file = tmp_path / "telegram.offset"
    offset_file.write_text("99\n")
    monkeypatch.setenv("NUTMEG_TELEGRAM_BOT_TOKEN", "telegram-secret")
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "111")
    clear_settings_cache()
    monkeypatch.setattr(
        cli_module,
        "build_telegram_polling_daemon",
        lambda settings, poll_interval_seconds, offset_store=None: StubDaemon(),
    )

    result = runner.invoke(
        app,
        [
            "telegram-bot-run",
            "--timeout",
            "1",
            "--poll-interval",
            "0",
            "--max-polls",
            "1",
            "--offset-file",
            str(offset_file),
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["offset_source"] == "store"
    assert payload["offset_file"] == str(offset_file)
    assert payload["offset_persistence_enabled"] is True
    assert payload["next_offset"] == 100
    assert "telegram-secret" not in result.stdout


def test_telegram_bot_run_explicit_offset_overrides_stored_offset(monkeypatch, tmp_path) -> None:
    from nutmeg.interfaces import cli as cli_module

    class StubSummary:
        polls_run = 1
        updates_seen = 0
        messages_handled = 0
        messages_denied = 0
        messages_ignored = 0
        next_offset = 11
        stop_reason = "max_polls"

    class StubDaemon:
        def run(self, *, offset: int | None, timeout: int, max_polls: int | None):
            assert offset == 10
            return StubSummary()

    offset_file = tmp_path / "telegram.offset"
    offset_file.write_text("99\n")
    monkeypatch.setenv("NUTMEG_TELEGRAM_BOT_TOKEN", "telegram-secret")
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "111")
    clear_settings_cache()
    monkeypatch.setattr(
        cli_module,
        "build_telegram_polling_daemon",
        lambda settings, poll_interval_seconds, offset_store=None: StubDaemon(),
    )

    result = runner.invoke(
        app,
        [
            "telegram-bot-run",
            "--offset",
            "10",
            "--timeout",
            "1",
            "--poll-interval",
            "0",
            "--max-polls",
            "1",
            "--offset-file",
            str(offset_file),
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["offset_source"] == "explicit"
    assert payload["next_offset"] == 11


def test_zucai_report_command_generates_json_artifacts_and_dry_run_dispatch(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "1234")
    result = runner.invoke(
        app,
        [
            "zucai-report",
            "--issue-id",
            "26068",
            "--output-dir",
            str(tmp_path),
            "--pdf",
            "--dispatch-telegram",
            "--dry-run",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["issue"]["issue_id"] == "26068"
    assert len(payload["recommendations"]) == 14
    assert payload["recommendations"][0]["pick"] == "31"
    assert payload["artifacts"]["pdf_path"].endswith(".pdf")
    assert payload["dispatch"]["status"] == "dry_run"
    assert Path(payload["artifacts"]["pdf_path"]).read_bytes().startswith(b"%PDF")


def test_zucai_renjiu_daily_command_generates_three_tiers(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "zucai-renjiu-daily",
            "--date",
            "2026-04-26",
            "--issue-file",
            "nutmeg/zucai/samples/26068-issue.json",
            "--odds-file",
            "nutmeg/zucai/samples/26068-odds.json",
            "--output-dir",
            str(tmp_path),
            "--pdf",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["recommended_ticket_id"] == "main"
    assert [ticket["ticket_id"] for ticket in payload["tickets"]] == [
        "conservative",
        "main",
        "aggressive",
    ]
    assert payload["artifacts"]["pdf_path"].endswith("analysis.pdf")
    assert Path(payload["artifacts"]["pdf_path"]).read_bytes().startswith(b"%PDF")

def test_zucai_report_command_rejects_invalid_issue(tmp_path) -> None:
    issue_file = tmp_path / "bad-issue.json"
    issue_file.write_text(
        json.dumps(
            {"issue_id": "bad", "matches": [{"match_no": 1, "home_team": "A", "away_team": "B"}]}
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["zucai-report", "--issue-file", str(issue_file), "--format", "json"],
    )

    assert result.exit_code == 2
    assert "exactly 14" in result.stdout


def test_zucai_grade_command_returns_plan_coverage(tmp_path) -> None:
    report_result = runner.invoke(
        app,
        [
            "zucai-report",
            "--issue-id",
            "26068",
            "--output-dir",
            str(tmp_path),
            "--format",
            "json",
        ],
    )
    assert report_result.exit_code == 0
    report_payload = json.loads(report_result.stdout)

    grade_result = runner.invoke(
        app,
        [
            "zucai-grade",
            "--report-file",
            report_payload["artifacts"]["report_json_path"],
            "--outcomes-file",
            "nutmeg/zucai/samples/26068-outcomes.json",
            "--format",
            "json",
        ],
    )

    assert grade_result.exit_code == 0
    payload = json.loads(grade_result.stdout)
    assert payload["issue_id"] == "26068"
    assert len(payload["match_results"]) == 14
    assert any(plan["covered"] for plan in payload["plan_results"])


def test_zucai_auto_run_command_skips_no_issue(tmp_path) -> None:
    registry_file = tmp_path / "registry.json"
    registry_file.write_text(json.dumps({"entries": []}), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "zucai-auto-run",
            "--date",
            "2026-04-27",
            "--slot",
            "afternoon",
            "--registry-file",
            str(registry_file),
            "--output-dir",
            str(tmp_path / "scheduled"),
            "--run-record-file",
            str(tmp_path / "records.json"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "skipped_no_issue"
    assert payload["dispatch"]["status"] == "skipped"
    assert payload["artifacts"]["pdf_path"] is None
    assert not (tmp_path / "records.json").exists()


def test_zucai_auto_run_command_generates_afternoon_report(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "1234")
    result = runner.invoke(
        app,
        [
            "zucai-auto-run",
            "--date",
            "2026-04-26",
            "--slot",
            "afternoon",
            "--registry-file",
            "nutmeg/zucai/samples/scheduled-issues.json",
            "--output-dir",
            str(tmp_path / "scheduled"),
            "--run-record-file",
            str(tmp_path / "records.json"),
            "--dispatch-telegram",
            "--dry-run",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "dry_run"
    assert payload["issue_id"] == "26068"
    assert payload["slot_label"] == "16:00首版分析"
    assert payload["dispatch"]["status"] == "dry_run"
    assert "16:00首版分析" in payload["dispatch"]["caption"]
    assert payload["artifacts"]["pdf_path"].endswith(".pdf")
    assert Path(payload["artifacts"]["pdf_path"]).read_bytes().startswith(b"%PDF")
    records = json.loads((tmp_path / "records.json").read_text(encoding="utf-8"))["records"]
    assert records[0]["slot"] == "afternoon"


def test_zucai_auto_run_command_duplicate_and_force(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "1234")
    base_args = [
        "zucai-auto-run",
        "--date",
        "2026-04-26",
        "--slot",
        "revision",
        "--registry-file",
        "nutmeg/zucai/samples/scheduled-issues.json",
        "--output-dir",
        str(tmp_path / "scheduled"),
        "--run-record-file",
        str(tmp_path / "records.json"),
        "--dispatch-telegram",
        "--dry-run",
        "--format",
        "json",
    ]

    first = runner.invoke(app, base_args)
    duplicate = runner.invoke(app, base_args)
    forced = runner.invoke(app, [*base_args, "--force"])

    assert first.exit_code == 0
    assert duplicate.exit_code == 0
    assert forced.exit_code == 0
    assert json.loads(first.stdout)["status"] == "dry_run"
    assert json.loads(duplicate.stdout)["status"] == "skipped_duplicate"
    assert json.loads(forced.stdout)["status"] == "dry_run"
    records = json.loads((tmp_path / "records.json").read_text(encoding="utf-8"))["records"]
    assert len(records) == 2


def test_zucai_source_sync_command_generates_registry(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "zucai-source-sync",
            "--source-file",
            "nutmeg/zucai/samples/26068-source-notice.html",
            "--date",
            "2026-04-26",
            "--output-dir",
            str(tmp_path / "zucai"),
            "--registry-file",
            str(tmp_path / "zucai" / "issues.json"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["parsed_count"] == 1
    assert payload["active_issue_ids"] == ["26068"]
    assert Path(payload["written_issue_paths"]["26068"]).exists()
    registry = json.loads(Path(payload["registry_path"]).read_text(encoding="utf-8"))
    assert registry["entries"][0]["issue_id"] == "26068"


def test_zucai_source_sync_command_rejects_url_without_live_fetch(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "zucai-source-sync",
            "--source-url",
            "https://example.test/source.html",
            "--date",
            "2026-04-26",
            "--output-dir",
            str(tmp_path / "zucai"),
            "--registry-file",
            str(tmp_path / "zucai" / "issues.json"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 2
    assert "requires --live-fetch" in result.stdout
