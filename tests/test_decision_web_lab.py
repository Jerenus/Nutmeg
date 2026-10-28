"""实验室页接口（2026-10-28 产品形态第 8 阶段 Task 8.1）：退役实验不在 live、内核不可达照样 200、
导航指向 /lab。"""
import json
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from nutmeg.decision.bj_time import BJ
from nutmeg.interfaces.cli import app as cli
from nutmeg.interfaces.decision_web import create_decision_app

_NOW = datetime(2026, 10, 28, 9, 0, tzinfo=BJ)
DOC = {
    "claim": "c", "mechanism": "m", "tier": "observation", "layer": "judgment",
    "population": "zucai", "min_tier": "price_only",
    "window": {"issue_from": "26126", "issue_to": "26137"},
    "falsifier": {"metric": "home_resid_pp", "stratum": "zucai", "n_min": 140,
                  "bound": "ci_upper", "threshold_pp": 2.0, "direction": "lt_means_falsified"},
    "stop_rule": "n≥140", "quota_slot": False, "buckets": ["向主 ≥+0.5"], "rule_ids": [],
    "source_doc": "experiments/prereg-x.json", "registered_at": "2026-09-14", "duties": [],
}


def _client(data: Path, registry: Path) -> TestClient:
    (data / "jczq").mkdir(parents=True, exist_ok=True)
    web = create_decision_app(output_dir=data / "jczq", data_dir=data, launchctl=lambda: "")
    web.state.now = lambda: _NOW
    web.state.lab_registry = registry
    return TestClient(web)


def _register(data: Path, registry: Path, exp_id: str, **extra) -> None:
    path = registry / f"{exp_id}.json"
    path.write_text(json.dumps({**DOC, "exp_id": exp_id, **extra}), encoding="utf-8")
    r = CliRunner().invoke(cli, ["rsi", "register", "--by", "Jun", str(path),
                                 "--data-dir", str(data)])
    assert r.exit_code == 0, r.output


def test_lab_api_lists_live_experiments(tmp_path: Path):
    data, reg = tmp_path / "data", tmp_path / "registry"
    data.mkdir()
    reg.mkdir()
    _register(data, reg, "F18", exits={"on_survived": "packet_column:许可证",
                                       "on_falsified": "none", "on_expired": "none"})
    _register(data, reg, "F99")
    r = CliRunner().invoke(cli, ["rsi", "deploy", "--exp", "F99", "--retire", "--reason", "x",
                                 "--by", "Jun", "--data-dir", str(data)])
    assert r.exit_code == 0, r.output
    (data / "zucai").mkdir()
    (data / "zucai" / "26150-bridge.jsonl").write_text(
        json.dumps({"diffs": [{"reason": {"kind": "matrix"}}]}) + "\n", encoding="utf-8")
    (data / "logs").mkdir()
    (data / "logs" / "runs.jsonl").write_text("".join(json.dumps(row) + "\n" for row in [
        {"ts": "2026-10-28T08:00:00+08:00", "label": "rsi.loop", "step": 1, "n": 2, "exit": 1},
        {"ts": "2026-10-28T08:01:00+08:00", "label": "rsi.loop", "step": 2, "n": 2, "exit": 0},
        {"ts": "2026-10-27T08:00:00+08:00", "label": "rsi.loop", "step": 1, "n": 2, "exit": 1},
    ]), encoding="utf-8")

    body = _client(data, reg).get("/api/lab").json()
    assert body["errors"] == []
    live = {row["exp_id"]: row for row in body["board"]["live"]}
    assert list(live) == ["F18"]                      # 退役的 F99 不在 live
    assert live["F18"]["columns"] == ["许可证"] and live["F18"]["label"] == "未证 0/140"
    assert set(live["F18"]) == {"exp_id", "claim", "layer", "tier", "n", "n_min", "metric_pp",
                                "ci", "label", "verdict", "columns", "window", "source_doc"}
    assert [(r["exp_id"], r["label"]) for r in body["board"]["settled"]] == [("F99", "退役")]
    assert body["cites"] == {"issues": 1, "diffs": 1, "matrix": 1, "outside": 0, "blank": 0}
    assert body["ops"]["failed_runs"] == 1           # 只数今天 exit≠0 的段
    assert body["ops"]["jobs"] >= 1 and isinstance(body["ops"]["alarms"], list)


def test_lab_api_survives_unreachable_kernel(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "ontology").write_text("不是目录", encoding="utf-8")   # 内核建不起来
    client = _client(data, tmp_path / "registry")
    r = client.get("/api/lab")
    assert r.status_code == 200
    body = r.json()
    assert body["board"] == {"live": [], "settled": []}
    assert any("内核读不出" in e for e in body["errors"])
    assert body["cites"] is not None and body["ops"] is not None


def test_nav_points_to_lab(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    client = _client(data, tmp_path / "registry")
    html = client.get("/lab").text
    assert '<a href="/lab" aria-current="page">实验室</a>' in html
    assert 'id="lab"' in html and 'id="errors"' in html
    assert "/static/decision/lab.js" in html and "/static/decision/lab.css" in html
    day = client.get("/day/2026-10-28").text
    assert 'href="/lab">实验室' in day and 'href="/observe">实验室' not in day
    assert client.get("/static/decision/lab.js").status_code == 200
