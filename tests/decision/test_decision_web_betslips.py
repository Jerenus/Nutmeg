# tests/decision/test_decision_web_betslips.py
"""判读工作台的实票登记页：「没入账 = 没打」的界面入口。"""
import json

import pytest
from fastapi.testclient import TestClient

from nutmeg.decision.store import DecisionStore
from nutmeg.interfaces.decision_web import create_decision_app

_ROW = "310 10 0 3 310 31 30 * 1 * * * 3 *"


@pytest.fixture
def client(tmp_path):
    output_dir = tmp_path / "jczq"
    (output_dir / "decision").mkdir(parents=True)
    zucai = tmp_path / "zucai"
    zucai.mkdir()
    (zucai / "26122-prep-revision.json").write_text(json.dumps({"records": {
        str(i): {"name": f"甲{i}-乙{i}", "match_date": "2026-09-12",
                 "fair_had": {"home": 0.5, "draw": 0.3, "away": 0.2}}
        for i in range(1, 15)}}, ensure_ascii=False), encoding="utf-8")
    app = create_decision_app(store=DecisionStore(output_dir / "decision"),
                              output_dir=output_dir)
    return TestClient(app)


def _register(client, **over):
    body = {"slip_id": "26122-T2", "channel": "renjiu", "placed_at": "2026-09-11",
            "issue": "26122", "multiplier": 1, "faces": _ROW, "note": ""}
    body.update(over)
    return client.post("/action/register-betslip", json=body)


def test_page_renders_empty_state_before_any_ticket(client):
    page = client.get("/betslips")
    assert page.status_code == 200
    assert "尚无登记票面" in page.text


def test_registration_computes_notes_and_probability_from_prep_fair(client):
    """P 由 store 的去水 fair 算，不由页面输入——禁嘴算是宪法第 5 条。"""
    body = _register(client).json()
    assert body["ok"] is True
    assert "72 注" in body["summary"]           # 2^? 面集合决定的注数
    assert "P(全对)=" in body["summary"]
    assert "26122-T2" in client.get("/betslips").text


def test_missing_scheme_number_is_surfaced_on_the_page(client):
    """方案号缺失要在页面上喊——26120/26121/26122 的账就是这么空着的。"""
    _register(client)
    assert "张票缺方案号" in client.get("/betslips").text
    _register(client, slip_id="26122-T3", scheme_no="20260911000322610009007")
    page = client.get("/betslips")
    assert "20260911000322610009007" in page.text


def test_trial_slip_is_marked_and_excluded_from_purchased_total(client):
    """试玩方案登记但不计入实购净值，否则会污染行权记分。"""
    _register(client, slip_id="26122-trial", trial=True)
    page = client.get("/betslips")
    assert "试玩" in page.text
    assert "已登记（实购 ¥0）" in page.text


def test_malformed_row_is_rejected_with_the_reason(client):
    """位置式少 token 会整列错位——必须报错并说明，不能猜也不能静默。"""
    body = _register(client, faces="310 10").json()
    assert body["ok"] is False
    assert "14 个 token" in body["error"]


def test_parlay_channel_is_refused_rather_than_half_registered(client):
    """竞彩串关有过关方式/让球线/多市场，表单撑不住：半张票入账比不入账更糟。"""
    body = _register(client, channel="jczq").json()
    assert body["ok"] is False
    assert "CLI" in body["error"]


def test_registration_is_idempotent_by_slip_id(client):
    _register(client)
    _register(client, note="改过备注")
    page = client.get("/betslips")
    assert page.text.count("26122-T2") == 1
    assert "改过备注" in page.text
