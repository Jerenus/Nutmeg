import json
from pathlib import Path

from fastapi.testclient import TestClient

from nutmeg.interfaces.decision_web import create_decision_app


def _client(tmp_path: Path) -> TestClient:
    data = tmp_path / "data"
    (data / "daily" / "2026-09-22").mkdir(parents=True)
    (data / "daily" / "2026-09-22" / "brief.json").write_text(json.dumps(
        {"date": "2026-09-22",
         "jczq": {"matches": [{"code": "周二001", "name": "A vs B", "ladder": "跟市场",
                               "read": None}],
                  "counts": {}},
         "zucai": {"issue": None}, "rsi": None, "factors": [], "errors": []}), encoding="utf-8")
    app = create_decision_app(output_dir=data / "jczq", data_dir=data, launchctl=lambda: "",
                              git=lambda args: "abc1234|2026-09-19T10:00:00+08:00|feat(rules): x\n")
    return TestClient(app)


def test_three_history_pages_render_read_only(tmp_path: Path):
    c = _client(tmp_path)
    for url, needle in (("/observe/rules", "abc1234"), ("/observe/factors", "因子"),
                        ("/observe/trace/2026-09-22", "周二001")):
        r = c.get(url)
        assert r.status_code == 200 and needle in r.text
        assert "<form" not in r.text and "POST" not in r.text


def test_history_apis(tmp_path: Path):
    c = _client(tmp_path)
    assert c.get("/api/observe/rules").json()[0]["sha"] == "abc1234"
    assert "factors" in c.get("/api/observe/factors").json()
    assert c.get("/api/observe/trace/2026-09-22").json()["matches"][0]["code"] == "周二001"
