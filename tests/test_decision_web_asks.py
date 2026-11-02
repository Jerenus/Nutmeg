"""行内追问接口（2026-11-02 产品形态 Task 10.4）：问 → 同步作答（测试替身）→ 线程带纠正草稿的样子 →
就地确认；坏对象 400；三张页都挂上 ask.js；页面数据拼不出也照样答。"""
import json
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from nutmeg.decision.bj_time import BJ
from nutmeg.interfaces.decision_web import create_decision_app


def _client(data: Path, runner, pushed: list) -> TestClient:
    (data / "jczq").mkdir(parents=True, exist_ok=True)
    app = create_decision_app(output_dir=data / "jczq", data_dir=data, launchctl=lambda: "")
    app.state.now = lambda: datetime(2026, 11, 2, 10, 41, tzinfo=BJ)
    app.state.ask_background = False
    app.state.ask_runner = runner
    app.state.ask_push = lambda q, row: pushed.append(row["status"])
    return TestClient(app)


def _runner(seen: list):
    def run(system, stdin, *, data_dir):
        seen.append(stdin)
        return 0, json.dumps({"answer": "④ 应记 ✗", "sources": ["研究 m7：原句"],
                              "corrections": [{"obj": "issue:26153/m7/q4", "old": "④ ✓",
                                               "new": "④ ✗", "kind": "premise"}],
                              "proposals": []}, ensure_ascii=False), {"duration_s": 3.0}
    return run


def test_ask_then_thread_shows_answer_with_draft_and_confirm_works(tmp_path):
    data, seen, pushed = tmp_path / "data", [], []
    client = _client(data, _runner(seen), pushed)
    got = client.post("/action/ask", json={"obj": "issue:26153/m7", "text": "④ 对吗"}).json()
    assert got == {"ok": True, "date": "2026-11-02", "seq": 1}
    assert pushed == ["answered"]
    assert "页面上这一行此刻显示的数据" in seen[0]          # 页面数据缺文件也照样答

    view = client.get("/api/ask", params={"obj": "issue:26153/m7"}).json()
    assert view["page"] == "/issue/26153" and view["quick"][0] == "要防平吗"
    (q,) = view["thread"]
    assert q["text"] == "④ 对吗" and q["answer"]["text"] == "④ 应记 ✗"
    (c,) = q["answer"]["correction_rows"]
    assert (c["old"], c["new"], c["status"]) == ("④ ✓", "④ ✗", "draft")

    ok = client.post(f"/action/correction/{c['id']}/status", json={"status": "confirmed"})
    assert ok.json()["ok"] is True
    view = client.get("/api/ask", params={"obj": "issue:26153"}).json()
    assert view["thread"][0]["answer"]["correction_rows"][0]["status"] == "confirmed"


def test_bad_obj_and_empty_text_are_400(tmp_path):
    client = _client(tmp_path / "data", _runner([]), [])
    assert client.post("/action/ask", json={"obj": "nope", "text": "x"}).status_code == 400
    assert client.post("/action/ask", json={"obj": "issue:1", "text": ""}).status_code == 400
    assert client.get("/api/ask", params={"obj": "x y"}).status_code == 400


def test_three_pages_load_the_ask_sheet(tmp_path):
    client = _client(tmp_path / "data", _runner([]), [])
    for path in ("/issue/26153", "/jczq/2026-11-02", "/ledger/2026-10"):
        html = client.get(path).text
        assert "/static/decision/ask.js" in html and "/static/decision/ask.css" in html, path
        assert html.index("ask.js") < html.index(path.split("/")[1] + ".js?"), path
