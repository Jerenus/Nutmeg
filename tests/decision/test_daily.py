"""decision-am/close/settle 日循环编排(映射旧 6 任务)。

编排只串确定性动词,**不含判读**——判读(Read)由主循环 Claude 在 am 与 close 之间人工
插入(decision-read),express 的 legs 亦来自 Claude 判读(close 读 daily/<date>/legs.json)。
测试注入各动词替身(monkeypatch),断言调用顺序 + dispatch 旗标透传。不打网、不真推。
"""
from typer.testing import CliRunner

import nutmeg.decision.ontology_adapter as ontology_adapter
from nutmeg.interfaces.cli import app

runner = CliRunner()
_DATE = "2026-07-08"


def _recorder(calls, name):
    def _fn(*_args, **_kwargs):
        calls.append(name)
        return f"{name}-ok"
    return _fn


# --- am ---------------------------------------------------------------------


# --- close ------------------------------------------------------------------


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
