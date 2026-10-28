"""期页（2026-10-27 产品形态）：/issue/{期} 外壳、/api/issue 组装、/api/precheck 点格即审。"""
import json
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from nutmeg.decision.day_paths import PREVIEWS, day_dir
from nutmeg.interfaces.decision_web import create_decision_app

_FACES = {"13": "3", "8": "3", "9": "3", "10": "31", "2": "31",
          "4": "10", "5": "10", "7": "31", "12": "10"}


def _client(tmp_path: Path) -> TestClient:
    data = tmp_path / "data"
    z = data / "zucai"
    z.mkdir(parents=True)
    (data / "jczq").mkdir()
    legs = {str(i): {"name": f"甲{i}-乙{i}", "fair": {"home": 0.5, "draw": 0.3, "away": 0.2}}
            for i in range(1, 15)}
    (z / "26151-legs-base.json").write_text(json.dumps({"legs": legs}, ensure_ascii=False))
    (z / "26151-packet.json").write_text(json.dumps({
        "issue": "26151", "rows": [{"no": "13", "tier": "B", "k": 4, "n": 6, "default": "31"}],
        "main_shape": {"label": "W4", "faces": {"13": "3"}}}, ensure_ascii=False))
    app = create_decision_app(output_dir=data / "jczq", data_dir=data, launchctl=lambda: "")
    return TestClient(app)


def test_issue_api_joins_packet_market_and_brake(tmp_path):
    body = _client(tmp_path).get("/api/issue/26151").json()
    assert body["issue"] == "26151"
    assert len(body["matches"]) == 14
    m13 = body["matches"][12]
    assert m13["no"] == "13" and m13["packet"]["k"] == 4 and m13["fair"]["home"] == 0.5
    assert body["main_shape"]["label"] == "W4"
    assert "room" in body["brake"] and "line" in body["brake"]
    assert body["errors"] == [] or all(isinstance(e, str) for e in body["errors"])


def test_issue_page_shell(tmp_path):
    page = _client(tmp_path).get("/issue/26151")
    assert page.status_code == 200 and "/static/decision/issue.js" in page.text


def test_issue_rejects_bad_issue(tmp_path):
    c = _client(tmp_path)
    assert c.get("/api/issue/../x").status_code in (400, 404)
    assert c.get("/api/issue/2615x").status_code == 400


def test_issue_brake_counts_pending_slips_like_cli(tmp_path):
    """止损块与 CLI 同口径：待结实购票按全损计（实质余量），文字就是 precheck.brake_line。"""
    from nutmeg.decision.precheck import brake_line

    c = _client(tmp_path)
    today = date.today().isoformat()
    row = " ".join(_FACES.get(str(i), "*") for i in range(1, 15))
    assert c.post("/action/register-betslip", json={
        "slip_id": "26151-T1", "channel": "renjiu", "placed_at": today, "issue": "26151",
        "faces": row}).json()["ok"] is True
    brake = c.get("/api/issue/26151").json()["brake"]
    assert brake["pending"]["n"] == 1 and brake["pending"]["stake"] == 128
    assert brake["room"] == brake["stop_loss"] - 128
    assert brake["line"] == brake_line(tmp_path / "data", today)
    assert "待结 1 张" in brake["line"]


def test_precheck_returns_review_shape_row_and_gates(tmp_path):
    c = _client(tmp_path)
    body = c.post("/api/precheck", json={
        "channel": "renjiu", "issue": "26151", "placed_at": "2026-10-27",
        "faces": _FACES}).json()
    assert body["ok"] is True
    assert body["notes"] == 64 and body["stake"] == 128
    assert body["shape"] == "3单6双"
    assert body["faces_row"].split()[12] == "3" and body["faces_row"].split()[0] == "*"
    assert body["mode"] == "任九"
    assert [g["no"] for g in body["gates"]][:1] and all("p" in g for g in body["gates"])
    assert isinstance(body["verdicts"], list) and "brake_line" in body


def test_precheck_bad_faces_is_an_error_not_500(tmp_path):
    r = _client(tmp_path).post("/api/precheck", json={
        "channel": "renjiu", "issue": "26151", "placed_at": "2026-10-27", "faces": {"1": "33"}})
    assert r.status_code == 200 and r.json()["ok"] is False


def test_precheck_errors_read_as_page_words_not_cli_flags(tmp_path):
    c = _client(tmp_path)
    empty = c.post("/api/precheck", json={"channel": "renjiu", "issue": "26151",
                                          "placed_at": "2026-10-27", "faces": {}}).json()
    assert empty == {"ok": False, "error": "还没选场"}
    legs = c.post("/api/precheck", json={"channel": "jczq", "placed_at": "2026-10-27"}).json()
    assert legs["ok"] is False and "--" not in legs["error"]
    short = c.post("/api/precheck", json={"channel": "renjiu", "issue": "26151",
                                          "placed_at": "2026-10-27",
                                          "faces": {"1": "3", "2": "31"}}).json()
    assert short["ok"] is False and "还差 7 场" in short["error"]


def test_precheck_does_not_log_preview_unless_asked(tmp_path):
    """点格即审：每次点格都留痕会把截止播报的「审过未登记」刷屏；只有 log: true 才写。"""
    c = _client(tmp_path)
    payload = {"channel": "renjiu", "issue": "26151", "placed_at": "2026-10-27",
               "faces": _FACES}
    log = day_dir(tmp_path / "data", "2026-10-27") / PREVIEWS
    assert c.post("/api/precheck", json=payload).json()["ok"] is True
    assert not log.exists()
    assert c.post("/api/precheck", json={**payload, "log": True}).json()["ok"] is True
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1


def test_precheck_jczq_has_no_gates_and_shape_from_legs(tmp_path):
    legs = [{"key": "周二001", "name": "甲-乙", "selections": ["home"], "odds": [1.8],
             "fair": {"home": 0.55, "draw": 0.25, "away": 0.2}},
            {"key": "周二002", "name": "丙-丁", "selections": ["away"], "odds": [2.4],
             "fair": {"home": 0.3, "draw": 0.28, "away": 0.42}}]
    body = _client(tmp_path).post("/api/precheck", json={
        "channel": "jczq", "placed_at": "2026-10-27", "legs": legs}).json()
    assert body["ok"] is True
    assert body["gates"] == [] and body["shape"] == "2串1" and body["mode"] == "2串1"
    assert body["notes"] == 1 and body["faces_row"] is None


def test_issue_static_assets_served(tmp_path):
    c = _client(tmp_path)
    for name in ("issue.js", "issue.css"):
        assert c.get(f"/static/decision/{name}").status_code == 200


def test_issue_api_carries_matrix_rows(tmp_path):
    """取证抽屉的数据 = counter_matrix.issue_matrices 的结果原样透传（页面与 API 都不另算）。"""
    from nutmeg.decision.counter_matrix import issue_matrices

    client = _client(tmp_path)
    data = tmp_path / "data"
    (data / "zucai" / "26151-research-m13.json").write_text(json.dumps({
        "anchor_side": "home",
        "hole_location": {"unit": "goalkeeper", "side": "home", "priced_in": True,
                          "detail": "门将伤缺"},
        "strength_balance": {"events": [
            {"event": "中场核心停赛", "side": "home", "direction": "down", "grade": "moderate",
             "priced_in": False, "source": "https://example.com/a 原句"}]},
        "stance": {"falsifier": "主队不胜"}}, ensure_ascii=False))
    body = client.get("/api/issue/26151").json()
    expected = {m["no"]: m for m in issue_matrices(data, "26151")}["13"]
    assert body["matches"][12]["matrix"] == expected
    assert expected["rows"], "造的研究件要至少产出一行有区分力的证据"
    assert any(r["source_url"] and r["priced_in"] is False for r in expected["rows"])
    assert body["matches"][0]["matrix"] == {"no": "1", "name": "甲1-乙1", "missing": True}


# —— §3 桥（2026-10-28 第 3 阶段 Task 3.2）——

_MAIN = {**_FACES, "10": "3"}   # 主形与 _FACES 只差场 10（3 → 31）


def _bridge_client(tmp_path: Path) -> TestClient:
    client = _client(tmp_path)
    (tmp_path / "data" / "zucai" / "26151-packet.json").write_text(json.dumps({
        "issue": "26151",
        "rows": [{"no": no, "tier": "B", "k": 4, "n": 6, "default": f} for no, f in _MAIN.items()],
        "main_shape": {"label": "W4 4单5双", "faces": _MAIN}}, ensure_ascii=False))
    return client


def _files(root: Path) -> dict[str, float]:
    return {str(p): p.stat().st_mtime for p in root.rglob("*") if p.is_file()}


_BRIDGE = {"issue": "26151", "draft0": _MAIN, "faces": _FACES, "cites": {"10": "out"},
           "outs": {"10": "停售前看到客队主力回归"}, "whys": {"2": "13 这条单我认"},
           "deviation": "fact_self_judged", "prediction": "场 10 开平"}


def test_bridge_preview_returns_checks_diffs_readout_and_writes_nothing(tmp_path):
    client = _bridge_client(tmp_path)
    before = _files(tmp_path / "data")
    body = client.post("/api/bridge/26151/preview", json={
        "faces": _FACES, "cites": {"10": "out"}, "outs": {"10": "客队主力回归"}}).json()
    assert body["ok"] is True
    assert [c["id"] for c in body["checks"]] == [1, 2, 3, 4, 5]
    assert [d["no"] for d in body["diffs"]] == ["10"]
    assert body["diffs"][0]["mine"] == "31" and body["diffs"][0]["main"] == "3"
    assert body["diffs"][0]["reason"] == {"kind": "out", "text": "客队主力回归"}
    assert body["readout"] == {"diffs": 1, "matrix": 0, "outside": 1, "blank": 0}
    assert body["opening"][-1]["label"] == "死法清单第一门"
    assert body["shape"] == "3单6双" and body["stake"] == 128 and 0 < body["p"] < 1
    assert body["gates"] and all("p" in g for g in body["gates"])
    assert _files(tmp_path / "data") == before


def test_bridge_preview_errors_read_as_page_words(tmp_path):
    client = _bridge_client(tmp_path)
    body = client.post("/api/bridge/26151/preview", json={"faces": {"1": "3"}}).json()
    assert body["ok"] is False and "还差 8 场" in body["error"]
    assert client.post("/api/bridge/2615x/preview", json={"faces": _FACES}).status_code == 400


def test_bridge_action_registers_b1_trial_and_writes_record(tmp_path):
    from nutmeg.decision.betslip import load_slips
    from nutmeg.decision.bridge import bridge_ledger, bridge_record

    client = _bridge_client(tmp_path)
    data = tmp_path / "data"
    assert client.get("/api/issue/26151").json()["bridge"] is None
    body = client.post("/action/bridge", json=_BRIDGE).json()
    assert body["ok"] is True and body["at"]
    assert "26151-B1" in body["summary"] and "试玩" in body["summary"]
    assert body["readout"] == {"diffs": 1, "matrix": 0, "outside": 1, "blank": 0}
    assert isinstance(body["lines"], list)
    slip = {s.slip_id: s for s in load_slips(data, issue="26151")}["26151-B1"]
    assert slip.purchased is False and slip.channel == "renjiu"
    assert slip.deviation == "fact_self_judged" and slip.prediction == "场 10 开平"
    rec = bridge_record(data, "26151")
    assert rec["slip_id"] == "26151-B1" and rec["channel"] == "renjiu"
    assert rec["faces"]["10"] == "31" and rec["draft0"] == _MAIN
    assert rec["main_label"] == "W4 4单5双"
    assert rec["diffs"][0]["reason"]["text"] == "停售前看到客队主力回归"
    assert {c["id"]: c.get("why") for c in rec["checks"]}[2] == "13 这条单我认"
    assert rec["deviation"] == "fact_self_judged" and rec["prediction"] == "场 10 开平"
    assert bridge_ledger(data, "26151")["readout"] == body["readout"]
    assert client.get("/api/issue/26151").json()["bridge"]["slip_id"] == "26151-B1"


def test_bridge_action_twice_refused(tmp_path):
    client = _bridge_client(tmp_path)
    assert client.post("/action/bridge", json=_BRIDGE).json()["ok"] is True
    again = client.post("/action/bridge", json={**_BRIDGE, "faces": _MAIN}).json()
    assert again["ok"] is False
    assert again["error"].startswith("本期桥已走过（")
    assert again["error"].endswith("），再想改就照抄 §2 主形")
    lines = (tmp_path / "data" / "zucai" / "26151-bridge.jsonl").read_text("utf-8").splitlines()
    assert len(lines) == 1


def test_bridge_action_failed_registration_writes_no_record(tmp_path):
    client = _bridge_client(tmp_path)
    data = tmp_path / "data"
    short = client.post("/action/bridge", json={**_BRIDGE, "faces": {"1": "3", "2": "31"}})
    assert short.json()["ok"] is False and "还差 7 场" in short.json()["error"]
    bad = client.post("/action/bridge", json={**_BRIDGE, "deviation": "gut"}).json()
    assert bad["ok"] is False and "gut" in bad["error"]
    assert not (data / "zucai" / "26151-bridge.jsonl").exists()
    assert not (data / "betslips.jsonl").exists()


def test_bridge_action_fourteen_matches_is_shengfucai(tmp_path):
    from nutmeg.decision.bridge import bridge_record

    client = _bridge_client(tmp_path)
    faces = {str(i): _FACES.get(str(i), "3") for i in range(1, 15)}
    body = client.post("/action/bridge", json={**_BRIDGE, "faces": faces}).json()
    assert body["ok"] is True and "胜负彩" in body["summary"]
    assert bridge_record(tmp_path / "data", "26151")["channel"] == "shengfucai"


def test_bridge_action_rejects_bad_issue(tmp_path):
    r = _bridge_client(tmp_path).post("/action/bridge", json={**_BRIDGE, "issue": "../x"})
    assert r.status_code == 400


# —— 桥上签博胆（§2 胆表：博胆＝C/D 档人群另一边买奖金，每票 ≤1）——

def _two(body: dict) -> dict:
    return next(c for c in body["checks"] if c["id"] == 2)


def test_bridge_preview_signed_bold_turns_check2_green_for_that_single(tmp_path):
    client = _bridge_client(tmp_path)
    plain = client.post("/api/bridge/26151/preview", json={"faces": _FACES}).json()
    assert _two(plain)["ok"] is False and "13·3" in _two(plain)["detail"]
    assert [x["no"] for x in _two(plain)["signable"]] == ["8", "9", "13"]
    assert plain["signed_bold"] == []
    one = client.post("/api/bridge/26151/preview",
                      json={"faces": _FACES, "signed_bold": ["13"]}).json()
    assert "13·3 签过的博胆" not in _two(one)["detail"]          # ✗ 只列不许可的单
    assert "13·3" not in _two(one)["detail"] and "8·3" in _two(one)["detail"]
    assert [x["no"] for x in _two(one)["signable"]] == ["8", "9", "13"]   # 签了也留着开关
    every = client.post("/api/bridge/26151/preview",
                        json={"faces": _FACES, "signed_bold": ["8", "9", "13"]}).json()
    assert _two(every)["ok"] is True and "13·3 签过的博胆" in _two(every)["detail"]


def test_bridge_action_stores_signed_bold_with_ticket_face(tmp_path):
    from nutmeg.decision.bridge import bridge_record

    client = _bridge_client(tmp_path)
    body = client.post("/action/bridge", json={**_BRIDGE, "signed_bold": ["13", 9]}).json()
    assert body["ok"] is True
    rec = bridge_record(tmp_path / "data", "26151")
    assert rec["signed_bold"] == [{"no": "13", "face": "3"}, {"no": "9", "face": "3"}]
    two = {c["id"]: c for c in rec["checks"]}[2]
    assert two["ok"] is False and "8·3" in two["detail"] and "13·3" not in two["detail"]


def test_bridge_signed_bold_ignores_non_singles(tmp_path):
    from nutmeg.decision.bridge import bridge_record

    client = _bridge_client(tmp_path)
    # 10 是双、2 是双、1 不在票内：都不算签
    payload = {"faces": _FACES, "signed_bold": ["10", "2", "1", "13", "13"]}
    view = client.post("/api/bridge/26151/preview", json=payload).json()
    assert view["signed_bold"] == [{"no": "13", "face": "3"}]
    assert client.post("/action/bridge", json={**_BRIDGE, **payload}).json()["ok"] is True
    assert bridge_record(tmp_path / "data", "26151")["signed_bold"] == [{"no": "13", "face": "3"}]


def test_bridge_action_without_signatures_stores_empty_list(tmp_path):
    from nutmeg.decision.bridge import bridge_record

    client = _bridge_client(tmp_path)
    assert client.post("/action/bridge", json=_BRIDGE).json()["ok"] is True
    assert bridge_record(tmp_path / "data", "26151")["signed_bold"] == []
