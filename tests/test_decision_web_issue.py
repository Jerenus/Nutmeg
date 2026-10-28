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
