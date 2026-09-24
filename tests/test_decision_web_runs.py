import json
from pathlib import Path

from fastapi.testclient import TestClient

from nutmeg.decision.store import DecisionStore
from nutmeg.interfaces.decision_web import create_decision_app


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    data = tmp_path / "data"
    out = data / "daily" / "2026-09-23"
    out.mkdir(parents=True)
    (out / "retro.md").write_text("# 复盘底稿\n场1 断", encoding="utf-8")
    (out / "brief.json").write_text(json.dumps({"jczq": {"matches": []}}), encoding="utf-8")
    app = create_decision_app(store=DecisionStore(data / "jczq" / "decision"),
                              output_dir=data / "jczq", data_dir=data)
    return TestClient(app), data


def test_runs_page_api_and_redirect_keep_the_filter(tmp_path: Path):
    client, _ = _client(tmp_path)
    page = client.get("/runs/2026-09-23")
    assert page.status_code == 200 and "/static/decision/runs.js" in page.text
    body = client.get("/api/runs/2026-09-23").json()
    assert body["date"] == "2026-09-23" and "2026-09-23" in body["days"]
    assert {job["id"] for job in body["jobs"]} >= {"day.brief", "zucai.prep"}   # 读仓内 plist
    assert body["errors"] == []
    r = client.get("/runs?lane=zucai", follow_redirects=False)
    assert r.status_code == 307
    location = r.headers["location"]
    assert location.startswith("/runs/20") and location.endswith("?lane=zucai")


def test_runs_rejects_a_malformed_date(tmp_path: Path):
    client, _ = _client(tmp_path)
    assert client.get("/api/runs/2026-9-3").status_code == 404


def test_runs_file_preview_stays_inside_the_data_dir(tmp_path: Path):
    client, data = _client(tmp_path)
    ok = client.get("/api/runs-file", params={"path": "daily/2026-09-23/retro.md"})
    assert ok.status_code == 200 and ok.json()["text"].startswith("# 复盘底稿")
    (tmp_path / "secret.md").write_text("x", encoding="utf-8")
    assert client.get("/api/runs-file", params={"path": "../secret.md"}).status_code == 403
    assert client.get("/api/runs-file", params={"path": "ontology/ontology.db"}).status_code == 403
    assert client.get("/api/runs-file", params={"path": "daily/nope.md"}).status_code == 404
