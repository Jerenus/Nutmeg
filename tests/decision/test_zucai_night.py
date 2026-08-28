import json
from hashlib import sha256

from typer.testing import CliRunner

from nutmeg.decision.zucai_night import (
    fetch_af_day,
    load_af_map,
    night_results,
    render_report,
    result_code,
    run_night_calibrate,
    ticket_partial_status,
)
from nutmeg.interfaces import cli as cli_module
from nutmeg.interfaces.cli import app


def test_result_code_home_win():
    assert result_code(4, 1) == "3"


def test_result_code_draw():
    assert result_code(1, 1) == "1"


def test_result_code_away_win():
    assert result_code(1, 2) == "0"


def test_load_af_map(tmp_path):
    (tmp_path / "26111-af-map.json").write_text(json.dumps(
        {"issue": "26111", "fixtures": {"3": 1234501, "4": 1234502}}), "utf-8")
    assert load_af_map(tmp_path, "26111") == {"3": 1234501, "4": 1234502}


def test_load_af_map_missing_file_is_empty(tmp_path):
    assert load_af_map(tmp_path, "26111") == {}


def _af_payload():
    return {"response": [
        {"fixture": {"id": 1234503, "status": {"short": "AET"}},
         "teams": {"home": {"name": "Celje"}, "away": {"name": "Slovan Bratislava"}},
         "score": {"fulltime": {"home": 1, "away": 1}}},
        {"fixture": {"id": 1234501, "status": {"short": "FT"}},
         "teams": {"home": {"name": "AEK Athens FC"}, "away": {"name": "Levski Sofia"}},
         "score": {"fulltime": {"home": 4, "away": 0}}},
    ]}


def test_fetch_af_day_uses_fulltime_and_status(monkeypatch):
    monkeypatch.setenv("NUTMEG_API_FOOTBALL_BASE_URL", "https://af.example")
    monkeypatch.setenv("NUTMEG_API_FOOTBALL_KEY", "k")
    seen = {}

    def fake_fetcher(url, headers):
        seen["url"], seen["headers"] = url, headers
        return _af_payload()

    fixtures = fetch_af_day("2026-08-26", fetcher=fake_fetcher)
    assert seen["url"] == "https://af.example/fixtures?date=2026-08-26"
    assert seen["headers"] == {"x-apisports-key": "k"}
    assert fixtures[1234503] == {"status": "AET", "ft_home": 1, "ft_away": 1,
                                 "home": "Celje", "away": "Slovan Bratislava"}
    assert fixtures[1234501]["ft_home"] == 4


_MATCHES = [
    {"match_no": 3, "home_team": "雅典", "away_team": "索斯基"},
    {"match_no": 5, "home_team": "采列", "away_team": "布拉迪"},
    {"match_no": 7, "home_team": "萨茨堡", "away_team": "米亚尔"},
    {"match_no": 8, "home_team": "比尔森", "away_team": "红星"},
]
_FIXTURES = {
    1234501: {"status": "FT", "ft_home": 4, "ft_away": 0,
              "home": "AEK Athens FC", "away": "Levski Sofia"},
    1234503: {"status": "AET", "ft_home": 1, "ft_away": 1,
              "home": "Celje", "away": "Slovan Bratislava"},
    1234507: {"status": "NS", "ft_home": None, "ft_away": None,
              "home": "Salzburg", "away": "Brann"},
}


def test_night_results_codes_and_skips():
    af_map = {"3": 1234501, "5": 1234503, "7": 1234507}
    results, skipped = night_results(_MATCHES, af_map, _FIXTURES)
    assert results["3"]["code"] == "3" and results["3"]["ft"] == "4-0"
    assert results["5"]["code"] == "1"          # AET 取 90' 1-1 = 平
    assert "7" not in results                    # 未完赛
    assert any("场7" in s and "NS" in s for s in skipped)
    assert any("场8" in s and "无映射" in s for s in skipped)


def test_ticket_partial_status_alive_and_dead():
    faces = {"3": "31", "4": "31", "5": "310", "7": "3"}
    codes = {"3": "3", "4": "0", "5": "1"}      # 场7 未赛
    st = ticket_partial_status(faces, codes)
    assert st["dead"] == ["4"]                   # 双31 漏客胜
    assert st["hit"] == ["3", "5"]
    assert st["undecided"] == ["7"]
    assert st["alive"] is False


def test_ticket_partial_status_all_alive():
    st = ticket_partial_status({"3": "31", "12": "31"}, {"3": "3", "12": "3"})
    assert st["alive"] is True and st["dead"] == [] and st["undecided"] == []


def test_render_report_lines():
    results = {"3": {"code": "3", "ft": "4-0", "home": "AEK Athens FC",
                     "away": "Levski Sofia", "status": "FT"},
               "5": {"code": "1", "ft": "1-1", "home": "Celje",
                     "away": "Slovan Bratislava", "status": "AET"}}
    tickets = [{"id": "R9", "faces": {"3": "31", "5": "310", "7": "3"}}]
    text = render_report("26111", "2026-08-26", results, ["场8: af-map 无映射"], tickets)
    assert "场3 AEK Athens FC vs Levski Sofia: 4-0(90') → 3" in text
    assert "AET" in text                        # 加时场标注口径来源
    assert "R9: 存活 | 已中 3,5 | 未决 7" in text
    assert "场8: af-map 无映射" in text


def test_run_night_calibrate_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("NUTMEG_API_FOOTBALL_BASE_URL", "https://af.example")
    monkeypatch.setenv("NUTMEG_API_FOOTBALL_KEY", "k")
    (tmp_path / "26111-issue.json").write_text(json.dumps({"issue_id": "26111", "matches": [
        {"match_no": 3, "home_team": "雅典", "away_team": "索斯基"},
        {"match_no": 5, "home_team": "采列", "away_team": "布拉迪"}]}), "utf-8")
    (tmp_path / "26111-af-map.json").write_text(json.dumps(
        {"issue": "26111", "fixtures": {"3": 1234501, "5": 1234503}}), "utf-8")
    (tmp_path / "26111-final-tickets.json").write_text(json.dumps({"issue": "26111", "tickets": [
        {"id": "R9", "kind": "任九", "faces": {"3": "31", "5": "310"}}]}), "utf-8")

    report = run_night_calibrate("26111", "2026-08-26", tmp_path,
                                 fetcher=lambda url, headers: _af_payload())
    assert "R9: 存活" in report
    snap = json.loads((tmp_path / "26111-night-2026-08-26-af.json").read_text("utf-8"))
    assert snap["results"]["3"]["code"] == "3"
    assert snap["source"].startswith("API-Football")


def test_run_night_calibrate_no_tickets_file(tmp_path, monkeypatch):
    monkeypatch.setenv("NUTMEG_API_FOOTBALL_BASE_URL", "https://af.example")
    monkeypatch.setenv("NUTMEG_API_FOOTBALL_KEY", "k")
    (tmp_path / "26111-issue.json").write_text(json.dumps({"issue_id": "26111", "matches": [
        {"match_no": 3, "home_team": "雅典", "away_team": "索斯基"}]}), "utf-8")
    (tmp_path / "26111-af-map.json").write_text(json.dumps(
        {"issue": "26111", "fixtures": {"3": 1234501}}), "utf-8")
    report = run_night_calibrate("26111", "2026-08-26", tmp_path,
                                 fetcher=lambda url, headers: _af_payload())
    assert "场3" in report            # 无票文件仍出彩果，不报错


class _NotificationOutcome:
    def __init__(self, status: str, *, success: bool) -> None:
        self.status = type("Status", (), {"value": status})()
        self.is_success = success


class _NotificationService:
    def __init__(self, outcome) -> None:
        self.outcome = outcome
        self.calls = []

    def publish(self, request, *, dry_run):
        self.calls.append((request, dry_run))
        return self.outcome


def test_night_cli_without_dispatch_preserves_stdout_and_builds_no_notifier(
    tmp_path, monkeypatch
):
    report = "fixed night report"
    monkeypatch.setattr(
        "nutmeg.interfaces.cli.decision.run_night_calibrate",
        lambda issue, date, zucai_dir: report,
    )
    monkeypatch.setattr(
        cli_module,
        "build_notification_service",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("notifier built")),
    )

    result = CliRunner().invoke(app, [
        "zucai-night-calibrate",
        "--issue", "26111",
        "--date", "2026-08-26",
        "--zucai-dir", str(tmp_path),
    ])

    assert result.exit_code == 0
    assert result.stdout == report + "\n"


def test_night_cli_dispatches_exact_report_as_dry_run(tmp_path, monkeypatch):
    report = "fixed night report"
    service = _NotificationService(_NotificationOutcome("dry_run", success=True))
    monkeypatch.setattr(
        "nutmeg.interfaces.cli.decision.run_night_calibrate",
        lambda issue, date, zucai_dir: report,
    )
    monkeypatch.setattr(
        cli_module, "build_notification_service", lambda **kwargs: service
    )

    result = CliRunner().invoke(app, [
        "zucai-night-calibrate",
        "--issue", "26111",
        "--date", "2026-08-26",
        "--zucai-dir", str(tmp_path),
        "--dispatch-telegram",
        "--dry-run",
    ])

    assert result.exit_code == 0
    request, dry_run = service.calls[0]
    assert dry_run is True
    assert request.kind == "zucai.night-calibration"
    assert request.business_key == "26111"
    assert request.stage == "2026-08-26"
    assert request.semantic_fingerprint == sha256(report.encode()).hexdigest()
    assert request.subject == "26111 夜间校准 2026-08-26"
    assert request.body == report
    assert "notification: dry_run" in result.stdout


def test_night_cli_failed_required_delivery_exits_one(tmp_path, monkeypatch):
    service = _NotificationService(_NotificationOutcome("failed", success=False))
    monkeypatch.setattr(
        "nutmeg.interfaces.cli.decision.run_night_calibrate",
        lambda issue, date, zucai_dir: "report",
    )
    monkeypatch.setattr(
        cli_module, "build_notification_service", lambda **kwargs: service
    )

    result = CliRunner().invoke(app, [
        "zucai-night-calibrate",
        "--issue", "26111",
        "--date", "2026-08-26",
        "--zucai-dir", str(tmp_path),
        "--dispatch-telegram",
    ])

    assert result.exit_code == 1
    assert "notification: failed" in result.stdout


def test_night_cli_no_dry_run_is_forwarded_explicitly(tmp_path, monkeypatch):
    service = _NotificationService(_NotificationOutcome("sent", success=True))
    monkeypatch.setattr(
        "nutmeg.interfaces.cli.decision.run_night_calibrate",
        lambda issue, date, zucai_dir: "report",
    )
    monkeypatch.setattr(
        cli_module, "build_notification_service", lambda **kwargs: service
    )

    result = CliRunner().invoke(app, [
        "zucai-night-calibrate",
        "--issue", "26111",
        "--date", "2026-08-26",
        "--zucai-dir", str(tmp_path),
        "--dispatch-telegram",
        "--no-dry-run",
    ])

    assert result.exit_code == 0
    assert service.calls[0][1] is False
