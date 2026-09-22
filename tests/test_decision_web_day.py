import json
from pathlib import Path

from fastapi.testclient import TestClient

from nutmeg.decision.store import DecisionStore
from nutmeg.interfaces.decision_web import create_decision_app


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    data = tmp_path / "data"
    out = data / "daily" / "2026-09-23"
    out.mkdir(parents=True)
    brief = {"date": "2026-09-23", "jczq": {"matches": [], "counts": {}},
             "zucai": {"issue": None}, "rsi": None, "factors": [], "errors": []}
    (out / "brief.json").write_text(json.dumps(brief), encoding="utf-8")
    store = DecisionStore(data / "jczq" / "decision")
    app = create_decision_app(store=store, output_dir=data / "jczq", data_dir=data,
                              launchctl=lambda: "-\t0\tcom.nutmeg.rsi.loop\n")
    return TestClient(app), data


def test_day_page_and_api(tmp_path: Path):
    client, _ = _client(tmp_path)
    page = client.get("/day/2026-09-23")
    assert page.status_code == 200
    assert "当日" in page.text and "/static/decision/day.js" in page.text
    assert "<form" not in page.text
    api = client.get("/api/day/2026-09-23")
    assert api.status_code == 200
    body = api.json()
    assert body["brief"]["date"] == "2026-09-23" and isinstance(body["launchd"], list)
    assert "缺 decisions.json" in body["errors"]


def test_day_root_redirects_to_today(tmp_path: Path):
    client, _ = _client(tmp_path)
    r = client.get("/day", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"].startswith("/day/20")


def test_day_note_appends_discussion(tmp_path: Path):
    client, data = _client(tmp_path)
    r = client.post("/action/day-note",
                    json={"date": "2026-09-23", "obj": "周三001", "text": "想双选"})
    assert r.status_code == 200 and r.json()["seq"] == 1
    path = data / "daily" / "2026-09-23" / "discussion.jsonl"
    rows = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(rows[0])["who"] == "jun"
    assert client.get("/api/day/2026-09-23").json()["discussion"][0]["text"] == "想双选"


def test_day_note_rejects_empty_text(tmp_path: Path):
    client, _ = _client(tmp_path)
    r = client.post("/action/day-note", json={"date": "2026-09-23", "text": "  "})
    assert r.status_code == 400
