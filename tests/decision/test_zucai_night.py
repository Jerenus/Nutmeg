import json
from hashlib import sha256

from typer.testing import CliRunner

from nutmeg.decision.zucai_night import (
    board_results,
    load_channel_map,
    night_results,
    render_report,
    result_code,
    run_night_calibrate,
    ticket_partial_status,
)
from nutmeg.interfaces.cli import app
from nutmeg.notifications.notify import NotifyResult


def test_result_code_home_win():
    assert result_code(2, 1) == "3"


def test_result_code_draw():
    assert result_code(0, 0) == "1"


def test_result_code_away_win():
    assert result_code(0, 3) == "0"


_MID = {"3": "match-aaa", "5": "match-bbb", "7": "match-ccc"}


def test_load_channel_map_prefers_manual_table_and_inverts(tmp_path):
    (tmp_path / "26111-channel-map.auto.json").write_text(json.dumps(
        {"match-aaa": "3", "match-zzz": "9"}), "utf-8")
    (tmp_path / "26111-channel-map.json").write_text(json.dumps(
        {"match-aaa": 3, "match-bbb": "5"}), "utf-8")
    assert load_channel_map(tmp_path, "26111") == {"3": "match-aaa", "5": "match-bbb"}


def test_load_channel_map_falls_back_to_auto_then_empty(tmp_path):
    assert load_channel_map(tmp_path, "26111") == {}
    (tmp_path / "26111-channel-map.auto.json").write_text(json.dumps({"match-aaa": "3"}), "utf-8")
    assert load_channel_map(tmp_path, "26111") == {"3": "match-aaa"}


def _data_dir(tmp_path):
    data = tmp_path / "data"
    day = data / "jczq" / "daily" / "2026-08-26"
    day.mkdir(parents=True)
    (data / "zucai").mkdir()
    day.joinpath("jczq-legs-base.json").write_text(json.dumps({"legs": {
        "周三001": {"match_id": "match-aaa", "home_team": "雅典", "away_team": "索斯基"},
        "周三002": {"match_id": "match-bbb", "home_team": "采列", "away_team": "布拉迪"},
        "周三003": {"match_id": "match-ccc", "home_team": "萨茨堡", "away_team": "布兰"},
        "周三004": {"home_team": "无身份", "away_team": "队"},
    }}), "utf-8")
    (data / "jczq" / "jc-results.json").write_text(json.dumps({"2026-08-26": {
        "周三001": {"ft_home": 4, "ft_away": 0},
        "周三002": {"ft_home": 1, "ft_away": 1},          # 加时 2-1 不在 90' 口径里
        "周三003": {"ft_home": None, "ft_away": None},    # 未完赛
        "周三004": {"ft_home": 2, "ft_away": 0},
    }}), "utf-8")
    return data


def test_board_results_joins_legs_base_identity_with_jc_results(tmp_path):
    data = _data_dir(tmp_path)
    board = board_results(data, "2026-08-26")
    assert board["match-aaa"] == {"code": "3", "ft": "4-0", "jc_code": "周三001",
                                  "home": "雅典", "away": "索斯基"}
    assert board["match-bbb"]["code"] == "1"
    assert "match-ccc" not in board                       # 缺终场不进表
    assert len(board) == 2                                # 无 match_id 的腿不猜身份
    assert board_results(data, "2026-08-27") == {}


_MATCHES = [
    {"match_no": 3, "home_team": "雅典", "away_team": "索斯基"},
    {"match_no": 5, "home_team": "采列", "away_team": "布拉迪"},
    {"match_no": 7, "home_team": "萨茨堡", "away_team": "米亚尔"},
    {"match_no": 8, "home_team": "比尔森", "away_team": "红星"},
]
_BOARD = {
    "match-aaa": {"code": "3", "ft": "4-0", "jc_code": "周三001", "home": "雅典", "away": "索斯基"},
    "match-bbb": {"code": "1", "ft": "1-1", "jc_code": "周三002", "home": "采列", "away": "布拉迪"},
}


def test_night_results_codes_and_skips():
    results, skipped = night_results(_MATCHES, _MID, _BOARD)
    assert results["3"]["code"] == "3" and results["3"]["ft"] == "4-0"
    assert results["3"]["match_id"] == "match-aaa"
    assert results["5"]["code"] == "1"
    assert "7" not in results                    # 有身份、板面日无终场
    assert any("场7" in s and "无终场" in s for s in skipped)
    assert any("场8" in s and "无映射" in s for s in skipped)


def test_ticket_partial_status_alive_and_dead():
    codes = {"3": "3", "5": "1"}
    alive = ticket_partial_status({"3": "31", "5": "310", "7": "3"}, codes)
    assert alive == {"alive": True, "hit": ["3", "5"], "dead": [], "undecided": ["7"]}
    dead = ticket_partial_status({"3": "0", "5": "1"}, codes)
    assert dead["alive"] is False and dead["dead"] == ["3"] and dead["hit"] == ["5"]


def test_ticket_partial_status_all_alive():
    st = ticket_partial_status({"3": "3"}, {"3": "3"})
    assert st["alive"] and st["undecided"] == []


def test_render_report_lines():
    results = {"3": {**_BOARD["match-aaa"], "match_id": "match-aaa"}}
    report = render_report("26111", "2026-08-26", results, ["场8: channel-map 无映射"],
                           [{"id": "R9", "faces": {"3": "31", "8": "3"}}])
    assert report.splitlines()[0].startswith("== 26111 夜间校准 2026-08-26 (jc-results")
    assert "场3 雅典 vs 索斯基: 4-0(90') → 3 [周三001]" in report
    assert "R9: 存活 | 已中 3 | 未决 8" in report
    assert report.splitlines()[-1] == "场8: channel-map 无映射"


def test_run_night_calibrate_end_to_end(tmp_path):
    data = _data_dir(tmp_path)
    zucai = data / "zucai"
    (zucai / "26111-issue.json").write_text(json.dumps({"issue_id": "26111", "matches": [
        {"match_no": 3, "home_team": "雅典", "away_team": "索斯基"},
        {"match_no": 5, "home_team": "采列", "away_team": "布拉迪"},
        {"match_no": 7, "home_team": "萨茨堡", "away_team": "米亚尔"}]}), "utf-8")
    (zucai / "26111-channel-map.json").write_text(json.dumps(
        {"match-aaa": "3", "match-bbb": "5", "match-ccc": "7"}), "utf-8")
    (zucai / "26111-final-tickets.json").write_text(json.dumps({"issue": "26111", "tickets": [
        {"id": "R9", "kind": "任九", "faces": {"3": "31", "5": "310", "7": "3"}}]}), "utf-8")

    report = run_night_calibrate("26111", "2026-08-26", zucai)   # data_dir 默认 = zucai 的父目录
    assert "R9: 存活 | 已中 3,5 | 未决 7" in report
    assert "场7" in report and "无终场" in report
    snap = json.loads((zucai / "26111-night-2026-08-26-jc.json").read_text("utf-8"))
    assert snap["results"]["3"]["code"] == "3" and snap["results"]["5"]["jc_code"] == "周三002"
    assert snap["source"].startswith("jczq/jc-results.json[2026-08-26]")
    assert not list(zucai.glob("*-af.json"))


def test_run_night_calibrate_no_tickets_file(tmp_path):
    data = _data_dir(tmp_path)
    zucai = data / "zucai"
    (zucai / "26111-issue.json").write_text(json.dumps({"issue_id": "26111", "matches": [
        {"match_no": 3, "home_team": "雅典", "away_team": "索斯基"}]}), "utf-8")
    (zucai / "26111-channel-map.auto.json").write_text(json.dumps({"match-aaa": "3"}), "utf-8")
    report = run_night_calibrate("26111", "2026-08-26", zucai, data_dir=data)
    assert "场3" in report and "→ 3" in report      # 无票文件仍出彩果，不报错


class _Notify:
    """Fake ``nutmeg.notifications.notify.notify``: records calls, returns a fixed result."""

    def __init__(self, status: str) -> None:
        self.result = NotifyResult(status)
        self.calls = []

    def __call__(self, kind, key, fingerprint, text, **kwargs):
        self.calls.append(((kind, key, fingerprint, text), kwargs))
        return self.result


def test_night_cli_without_dispatch_preserves_stdout_and_builds_no_notifier(
    tmp_path, monkeypatch
):
    report = "fixed night report"
    monkeypatch.setattr(
        "nutmeg.interfaces.cli.decision.run_night_calibrate",
        lambda issue, date, zucai_dir: report,
    )
    monkeypatch.setattr(
        "nutmeg.notifications.notify.notify",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("notify called")),
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
    service = _Notify("dry_run")
    monkeypatch.setattr(
        "nutmeg.interfaces.cli.decision.run_night_calibrate",
        lambda issue, date, zucai_dir: report,
    )
    monkeypatch.setattr("nutmeg.notifications.notify.notify", service)

    result = CliRunner().invoke(app, [
        "zucai-night-calibrate",
        "--issue", "26111",
        "--date", "2026-08-26",
        "--zucai-dir", str(tmp_path),
        "--dispatch-telegram",
        "--dry-run",
    ])

    assert result.exit_code == 0
    (kind, key, fingerprint, text), kwargs = service.calls[0]
    assert kwargs["dry_run"] is True
    assert kind == "zucai.night-calibration"
    assert key == "26111:2026-08-26"
    assert fingerprint == sha256(report.encode()).hexdigest()
    assert text == report
    assert "notification: dry_run" in result.stdout


def test_night_cli_failed_required_delivery_exits_one(tmp_path, monkeypatch):
    service = _Notify("failed")
    monkeypatch.setattr(
        "nutmeg.interfaces.cli.decision.run_night_calibrate",
        lambda issue, date, zucai_dir: "report",
    )
    monkeypatch.setattr("nutmeg.notifications.notify.notify", service)

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
    service = _Notify("sent")
    monkeypatch.setattr(
        "nutmeg.interfaces.cli.decision.run_night_calibrate",
        lambda issue, date, zucai_dir: "report",
    )
    monkeypatch.setattr("nutmeg.notifications.notify.notify", service)

    result = CliRunner().invoke(app, [
        "zucai-night-calibrate",
        "--issue", "26111",
        "--date", "2026-08-26",
        "--zucai-dir", str(tmp_path),
        "--dispatch-telegram",
        "--no-dry-run",
    ])

    assert result.exit_code == 0
    assert service.calls[0][1]["dry_run"] is False
