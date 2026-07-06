"""decision-am/close/settle 日循环编排(映射旧 6 任务)。

编排只串确定性动词,**不含判读**——判读(Read)由主循环 Claude 在 am 与 close 之间人工
插入(decision-read),express 的 legs 亦来自 Claude 判读(close 读 daily/<date>/legs.json)。
测试注入各动词替身(monkeypatch),断言调用顺序 + dispatch 旗标透传。不打网、不真推。
"""
from typer.testing import CliRunner

import nutmeg.decision.verbs as verbs
from nutmeg.interfaces.cli import app

runner = CliRunner()
_DATE = "2026-07-08"


def _recorder(calls, name):
    def _fn(*_args, **_kwargs):
        calls.append(name)
        return f"{name}-ok"
    return _fn


# --- am ---------------------------------------------------------------------

def test_decision_am_order(tmp_path, monkeypatch):
    calls: list[str] = []
    for name in ("fetch_day", "run_sense", "run_backfill"):
        monkeypatch.setattr(verbs, name, _recorder(calls, name))
    verbs.run_decision_am(_DATE, tmp_path)
    assert calls == ["fetch_day", "run_sense", "run_backfill"]


def test_decision_am_with_zucai_order(tmp_path, monkeypatch):
    calls: list[str] = []
    for name in ("fetch_day", "fetch_zucai", "run_sense", "run_sense_zucai", "run_backfill"):
        monkeypatch.setattr(verbs, name, _recorder(calls, name))
    verbs.run_decision_am(_DATE, tmp_path, zucai_dir=tmp_path / "zucai", issue="26091")
    assert calls == ["fetch_day", "fetch_zucai", "run_sense",
                     "run_sense_zucai", "run_backfill"]


def test_decision_am_no_issue_skips_zucai(tmp_path, monkeypatch):
    calls: list[str] = []
    for name in ("fetch_day", "fetch_zucai", "run_sense", "run_sense_zucai", "run_backfill"):
        monkeypatch.setattr(verbs, name, _recorder(calls, name))
    verbs.run_decision_am(_DATE, tmp_path, zucai_dir=tmp_path / "zucai")   # 无 issue
    assert "fetch_zucai" not in calls and "run_sense_zucai" not in calls
    assert calls == ["fetch_day", "run_sense", "run_backfill"]


# --- close ------------------------------------------------------------------

def test_decision_close_order_and_dispatch_passthrough(tmp_path, monkeypatch):
    calls: list[str] = []
    seen: dict = {}
    # legs.json 存在 → express 被调用
    legs = tmp_path / "daily" / _DATE / "legs.json"
    legs.parent.mkdir(parents=True)
    legs.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(verbs, "run_capture_closing", _recorder(calls, "capture"))
    monkeypatch.setattr(verbs, "run_express", _recorder(calls, "express"))

    def _report(rd, od, *, dispatch_telegram, dry_run):
        calls.append("report")
        seen.update(dispatch=dispatch_telegram, dry_run=dry_run)
        return "report-ok"

    monkeypatch.setattr(verbs, "run_report", _report)
    verbs.run_decision_close(_DATE, tmp_path, dispatch=True, dry_run=False)
    assert calls == ["capture", "express", "report"]
    assert seen == {"dispatch": True, "dry_run": False}     # 旗标透传


def test_decision_close_no_legs_yields_empty_ticket(tmp_path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(verbs, "run_capture_closing", _recorder(calls, "capture"))
    monkeypatch.setattr(verbs, "run_express", _recorder(calls, "express"))
    monkeypatch.setattr(verbs, "run_report", _recorder(calls, "report"))
    out = verbs.run_decision_close(_DATE, tmp_path, dispatch=False)   # 无 legs.json
    assert "express" not in calls                # Claude 未插判读票 → 不调 express
    assert calls == ["capture", "report"]
    assert "空票" in out


# --- settle -----------------------------------------------------------------

def test_decision_settle_order_and_dispatch(tmp_path, monkeypatch):
    calls: list[str] = []
    seen: dict = {}
    monkeypatch.setattr(verbs, "run_reconcile", _recorder(calls, "reconcile"))
    monkeypatch.setattr(verbs, "run_calibrate_panel", _recorder(calls, "calibrate"))

    def _report(rd, od, *, dispatch_telegram, dry_run):
        calls.append("report")
        seen.update(dispatch=dispatch_telegram, dry_run=dry_run)
        return "ok"

    monkeypatch.setattr(verbs, "run_report", _report)
    verbs.run_decision_settle(_DATE, tmp_path, dispatch=True, dry_run=False)
    assert calls == ["reconcile", "calibrate", "report"]
    assert seen == {"dispatch": True, "dry_run": False}


def test_decision_settle_with_zucai_order(tmp_path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(verbs, "run_reconcile", _recorder(calls, "reconcile"))
    monkeypatch.setattr(verbs, "run_reconcile_zucai", _recorder(calls, "reconcile_zucai"))
    monkeypatch.setattr(verbs, "run_calibrate_panel", _recorder(calls, "calibrate"))
    monkeypatch.setattr(verbs, "run_report", _recorder(calls, "report"))
    verbs.run_decision_settle(_DATE, tmp_path, issue="26091", zucai_dir=tmp_path / "z")
    assert calls == ["reconcile", "reconcile_zucai", "calibrate", "report"]


# --- CLI 旗标透传 -----------------------------------------------------------

def test_decision_am_cli(tmp_path, monkeypatch):
    seen: dict = {}

    def _fake(rd, od, *, zucai_dir=None, issue=None):
        seen.update(rd=rd, issue=issue)
        return "am-ok"

    monkeypatch.setattr(verbs, "run_decision_am", _fake)
    r = runner.invoke(app, ["decision-am", "--run-date", _DATE,
                            "--output-dir", str(tmp_path), "--issue", "26091"])
    assert r.exit_code == 0, r.output
    assert seen["rd"] == _DATE and seen["issue"] == "26091"


def test_decision_close_cli_passes_flags(tmp_path, monkeypatch):
    seen: dict = {}

    def _fake(rd, od, *, dispatch, dry_run):
        seen.update(dispatch=dispatch, dry_run=dry_run)
        return "close-ok"

    monkeypatch.setattr(verbs, "run_decision_close", _fake)
    r = runner.invoke(app, ["decision-close", "--run-date", _DATE,
                            "--output-dir", str(tmp_path),
                            "--dispatch-telegram", "--no-dry-run"])
    assert r.exit_code == 0, r.output
    assert seen == {"dispatch": True, "dry_run": False}


def test_decision_settle_cli_defaults_dry_run(tmp_path, monkeypatch):
    seen: dict = {}

    def _fake(rd, od, *, dispatch, dry_run, issue=None, zucai_dir=None):
        seen.update(dispatch=dispatch, dry_run=dry_run)
        return "settle-ok"

    monkeypatch.setattr(verbs, "run_decision_settle", _fake)
    r = runner.invoke(app, ["decision-settle", "--run-date", _DATE,
                            "--output-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert seen == {"dispatch": False, "dry_run": True}    # 默认 dry-run,不推
