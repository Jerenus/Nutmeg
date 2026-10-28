# tests/decision/test_decision_web_betslips.py
"""判读工作台的实票登记页：「没入账 = 没打」的界面入口。"""
import json

import pytest
from fastapi.testclient import TestClient

from nutmeg.interfaces.decision_web import create_decision_app

_ROW = "310 10 0 3 310 31 30 * 1 * * * 3 *"


@pytest.fixture
def client(tmp_path):
    output_dir = tmp_path / "jczq"
    (output_dir / "decision").mkdir(parents=True)
    zucai = tmp_path / "zucai"
    zucai.mkdir()
    # 足彩 fair 与 CLI 同口径：legs-base 判断概率（data_dir＝output_dir 上一级）
    (zucai / "26122-legs-base.json").write_text(json.dumps({"legs": {
        str(i): {"fair": {"home": 0.5, "draw": 0.3, "away": 0.2}}
        for i in range(1, 15)}}, ensure_ascii=False), encoding="utf-8")
    app = create_decision_app(output_dir=output_dir)
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


def test_registration_computes_notes_and_probability_from_legs_base_fair(client):
    """P 由 legs-base 的判断概率算，不由页面输入——禁嘴算是宪法第 5 条。"""
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


def test_jczq_without_structured_legs_is_refused_rather_than_half_registered(client):
    """竞彩只收结构化腿（竞彩板生成）；自由文本票面不收：半张票入账比不入账更糟。"""
    body = _register(client, channel="jczq").json()
    assert body["ok"] is False
    assert "竞彩板" in body["error"] and "--legs-file" not in body["error"]


def test_registration_is_idempotent_by_slip_id(client):
    _register(client)
    _register(client, note="改过备注")
    page = client.get("/betslips")
    assert page.text.count("26122-T2") == 1
    assert "改过备注" in page.text


def test_web_registration_records_the_review_with_the_ticket(client, tmp_path):
    """审票记录随票入账（宪法 §6）：网页登记与 CLI 同口径，审票结论写进 diagnosis.review。"""
    assert _register(client).json()["ok"] is True
    [row] = [json.loads(line) for line in
             (tmp_path / "betslips.jsonl").read_text(encoding="utf-8").splitlines() if line]
    review = row["diagnosis"]["review"]
    assert "error" not in review and set(review) == {"vetoed", "ratio", "codes"}
    assert row["registered_at"]


def test_register_keeps_deviation_and_prediction(client, tmp_path):
    r = _register(client, deviation="fact_self_judged", prediction="门兴赢不了")
    assert r.json()["ok"] is True
    row = json.loads((tmp_path / "betslips.jsonl").read_text("utf-8").splitlines()[-1])
    assert row["deviation"] == "fact_self_judged" and row["prediction"] == "门兴赢不了"
    assert "codes" in row["diagnosis"]["review"]


def test_register_records_day_cap_code_like_the_cli(client, tmp_path):
    """日帽超帽（宪法 §4）记码不拦登记：72 注 × 14 倍 = ¥2,016 > ¥2,000。"""
    assert _register(client, multiplier=14).json()["ok"] is True
    row = json.loads((tmp_path / "betslips.jsonl").read_text("utf-8").splitlines()[-1])
    review = row["diagnosis"]["review"]
    assert review["vetoed"] is True and "DAYCAP" in review["codes"]


def test_register_jczq_with_structured_legs(client, tmp_path):
    legs = [{"key": "周日006", "market": "had", "selections": ["home"], "odds": [1.22],
             "fair": {"home": 0.702, "draw": 0.173, "away": 0.124}},
            {"key": "周日011", "market": "had", "selections": ["home"], "odds": [1.33],
             "fair": {"home": 0.622, "draw": 0.205, "away": 0.173}}]
    r = client.post("/action/register-betslip", json={
        "slip_id": "20261025-J1", "channel": "jczq", "placed_at": "2026-10-25",
        "legs": legs, "combo": "2", "multiplier": 5})
    assert r.json()["ok"] is True, r.json()
    row = json.loads((tmp_path / "betslips.jsonl").read_text("utf-8").splitlines()[-1])
    assert [leg["key"] for leg in row["legs"]] == ["周日006", "周日011"]
    assert row["combo_sizes"] == [2] and row["multiplier"] == 5
