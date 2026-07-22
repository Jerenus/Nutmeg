import json
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.decision.ontology_adapter import (
    _capture_closing_v2,
    _report_v2,
    run_decision_am_v2,
)
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

DATE = "2026-07-19"
SPORTTERY = {"matchInfoList": [{"businessDate": DATE, "subMatchList": [
    {"matchStatus": "Selling", "businessDate": DATE, "matchNumStr": "周日001",
     "matchNum": 7001, "matchId": 2040001, "matchDate": DATE, "matchTime": "23:30:00",
     "homeTeamAbbName": "哈马比", "awayTeamAbbName": "AIK", "leagueAbbName": "瑞典超",
     "had": {"h": "2.10", "d": "3.30", "a": "3.10"}}]}]}
CLOSING = {"周日001": {"match_winner": {"odds": {"home": 1.95, "draw": 3.50, "away": 3.40}}}}


class _FakeOutcome:
    class _Status:
        value = "dry_run"

    status = _Status()


class _FakeNotifier:
    def __init__(self) -> None:
        self.calls: list[bool] = []

    def publish(self, request, *, dry_run=False):
        self.calls.append(dry_run)
        return _FakeOutcome()


def _kernel(tmp_path: Path):
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    output_dir = tmp_path / "jczq"
    (output_dir / "daily" / DATE).mkdir(parents=True)
    (output_dir / "daily" / DATE / "sporttery_markets.json").write_text(
        json.dumps(SPORTTERY), encoding="utf-8")
    run_decision_am_v2(DATE, output_dir, kernel=kernel, fetch=False)
    with OntologyUnitOfWork(kernel.engine) as uow:
        [match_id] = uow.identity.all_match_ids()
    return kernel, match_id, output_dir


def test_capture_closing_v2_ingests_closing_snapshot(tmp_path: Path) -> None:
    kernel, match_id, output_dir = _kernel(tmp_path)
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.market.closing_fair(match_id, "md-had") is None   # none before capture
    (output_dir / "daily" / DATE / "bold_odds_closing.json").write_text(
        json.dumps(CLOSING), encoding="utf-8")
    from datetime import UTC, datetime
    msg = _capture_closing_v2(kernel, DATE, output_dir,
                              datetime(2026, 7, 19, 22, tzinfo=UTC))
    assert "收盘快照" in msg
    with OntologyUnitOfWork(kernel.engine) as uow:
        closing = uow.market.closing_fair(match_id, "md-had")
    assert closing is not None and abs(sum(closing.values()) - 1.0) < 1e-9


def test_capture_closing_v2_skips_without_file(tmp_path: Path) -> None:
    kernel, _match_id, output_dir = _kernel(tmp_path)
    from datetime import UTC, datetime
    msg = _capture_closing_v2(kernel, DATE, output_dir, datetime(2026, 7, 19, 22, tzinfo=UTC))
    assert "跳过" in msg and "CLV 空" in msg


def test_report_v2_writes_markdown_and_pushes_dry(tmp_path: Path) -> None:
    kernel, _match_id, output_dir = _kernel(tmp_path)
    notifier = _FakeNotifier()
    msg = _report_v2(kernel, DATE, output_dir, "close", dispatch=True, dry_run=True,
                     notification_service=notifier)
    report_path = output_dir / "daily" / DATE / f"decision-report-v2-{DATE}.md"
    assert report_path.exists()
    assert "决策日报 v2" in report_path.read_text(encoding="utf-8")
    assert notifier.calls == [True]        # published in DRY-RUN only — never a real send
    assert "推送 dry_run" in msg


def test_report_v2_no_dispatch_writes_but_never_pushes(tmp_path: Path) -> None:
    kernel, _match_id, output_dir = _kernel(tmp_path)
    notifier = _FakeNotifier()
    msg = _report_v2(kernel, DATE, output_dir, "settle", dispatch=False, dry_run=True,
                     notification_service=notifier)
    assert (output_dir / "daily" / DATE / f"decision-report-v2-{DATE}.md").exists()
    assert notifier.calls == []            # dispatch off -> publish never called
    assert "推送" not in msg
