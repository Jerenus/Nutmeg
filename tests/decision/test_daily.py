"""decision-am/close/settle 日循环编排(映射旧 6 任务)。

编排只串确定性动词,**不含判读**——判读(Read)由主循环 Claude 在 am 与 close 之间人工
插入(decision-read),express 的 legs 亦来自 Claude 判读(close 读 daily/<date>/legs.json)。
测试注入各动词替身(monkeypatch),断言调用顺序 + dispatch 旗标透传。不打网、不真推。
"""
from typer.testing import CliRunner

import nutmeg.decision.ontology_adapter as ontology_adapter
import nutmeg.decision.verbs as verbs
from nutmeg.decision.report import DecisionReportResult
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
    for name in ("fetch_day", "run_sense", "run_backfill", "run_day_regime"):
        monkeypatch.setattr(verbs, name, _recorder(calls, name))
    verbs.run_decision_am(_DATE, tmp_path)
    assert calls == ["fetch_day", "run_sense", "run_backfill", "run_day_regime"]


def test_decision_am_with_zucai_order(tmp_path, monkeypatch):
    calls: list[str] = []
    for name in ("fetch_day", "fetch_zucai", "run_sense", "run_sense_zucai",
                 "run_backfill", "run_day_regime"):
        monkeypatch.setattr(verbs, name, _recorder(calls, name))
    verbs.run_decision_am(_DATE, tmp_path, zucai_dir=tmp_path / "zucai", issue="26091")
    assert calls == ["fetch_day", "fetch_zucai", "run_sense",
                     "run_sense_zucai", "run_backfill", "run_day_regime"]


def test_decision_am_no_issue_skips_zucai(tmp_path, monkeypatch):
    calls: list[str] = []
    for name in ("fetch_day", "fetch_zucai", "run_sense", "run_sense_zucai",
                 "run_backfill", "run_day_regime"):
        monkeypatch.setattr(verbs, name, _recorder(calls, name))
    verbs.run_decision_am(_DATE, tmp_path, zucai_dir=tmp_path / "zucai")   # 无 issue
    assert "fetch_zucai" not in calls and "run_sense_zucai" not in calls
    assert calls == ["fetch_day", "run_sense", "run_backfill", "run_day_regime"]


# --- close ------------------------------------------------------------------


def test_decision_settle_order_and_dispatch(tmp_path, monkeypatch):
    calls: list[str] = []
    seen: dict = {}
    monkeypatch.setattr(verbs, "run_reconcile", _recorder(calls, "reconcile"))
    monkeypatch.setattr(verbs, "run_calibrate_panel", _recorder(calls, "calibrate"))

    def _report(rd, od, *, dispatch_telegram, dry_run, stage):
        calls.append("report")
        seen.update(dispatch=dispatch_telegram, dry_run=dry_run, stage=stage)
        return DecisionReportResult.success(rd, stage, tmp_path / "report.pdf", 10)

    monkeypatch.setattr(verbs, "run_report", _report)
    verbs.run_decision_settle(_DATE, tmp_path, dispatch=True, dry_run=False)
    assert calls == ["reconcile", "calibrate", "report"]
    assert seen == {"dispatch": True, "dry_run": False, "stage": "settle"}


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

    def _fake(rd, od, *, issue=None, zucai_dir=None):
        seen.update(rd=rd, issue=issue)
        return "am-ok"

    monkeypatch.setattr(ontology_adapter, "run_decision_am_v2", _fake)
    r = runner.invoke(app, ["decision-am", "--run-date", _DATE,
                            "--output-dir", str(tmp_path), "--issue", "26091"])
    assert r.exit_code == 0, r.output
    assert seen["rd"] == _DATE and seen["issue"] == "26091"


def test_decision_settle_cli_defaults_dry_run(tmp_path, monkeypatch):
    seen: dict = {}

    def _fake(rd, od, *, dispatch, dry_run):
        seen.update(dispatch=dispatch, dry_run=dry_run)
        return "settle-ok"

    monkeypatch.setattr(ontology_adapter, "run_decision_settle_v2", _fake)
    r = runner.invoke(app, ["decision-settle", "--run-date", _DATE,
                            "--output-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert seen == {"dispatch": False, "dry_run": True}    # 默认 dry-run,不推
