# tests/test_decision_web.py
from fastapi.testclient import TestClient

from nutmeg.decision.workbench import append_event
from nutmeg.interfaces.decision_web import create_decision_app


def _kernel_state(date):
    """内核读侧替身：当天一场 + 一份 read_time 快照，无已提交 Read。"""
    return {
        "matches": [{"match_id": "match-1", "home": "哈马比", "away": "卡尔马",
                     "competition": "瑞超", "kickoff_at": date}],
        "snapshots": [{"snapshot_id": "S1", "match_id": "match-1", "kind": "read_time",
                       "fair": {"had": {"home": 0.52, "draw": 0.27, "away": 0.21}}}],
        "reads": [],
        "events": [],
    }


def _app(tmp_path, date="2026-07-08"):
    app = create_decision_app(output_dir=tmp_path, kernel_state=_kernel_state)
    return TestClient(app), tmp_path, date


def test_workbench_api_returns_day_state(tmp_path):
    client, out, date = _app(tmp_path)
    append_event(out, date, {"kind": "attention", "id": "A1", "group": "草稿待审",
                             "match": "哈马比 vs 卡尔马"})
    r = client.get(f"/api/workbench?date={date}")
    assert r.status_code == 200
    body = r.json()
    assert body["date"] == date
    assert any(m["home"] == "哈马比" for m in body["matches"])
    assert any(e["kind"] == "attention" for e in body["events"])


def test_workbench_page_renders(tmp_path):
    client, out, date = _app(tmp_path)
    r = client.get(f"/?date={date}")
    assert r.status_code == 200
    assert "判读工作台" in r.text


def test_empty_day_is_explicit_not_silent(tmp_path):
    client, out, date = _app(tmp_path, date="2026-07-09")
    r = client.get("/api/workbench?date=2026-07-09")
    assert r.status_code == 200
    assert r.json()["events"] == []   # 无 workbench.jsonl → 空事件,不报错


def test_retired_v1_routes_are_gone(tmp_path):
    """旧 DecisionStore 读写路由(批准/拒绝 Read、确认 legs、SOP 任务栏、对象/校准/账本页)已退役。"""
    client, out, date = _app(tmp_path)
    # /ledger 2026-10-28 起是新账房页（第 7 阶段），不再列为退役路由
    for path in ("/objects", "/calibration", "/api/sop-steps?issue=1&date=" + date):
        assert client.get(path).status_code == 404
    for path in ("/action/approve-read", "/action/reject-read", "/action/confirm-legs",
                 "/action/run-task"):
        assert client.post(path, json={}).status_code == 404


def test_thread_post_appends_user_message(tmp_path):
    client, out, date = _app(tmp_path)
    r = client.post("/thread", json={"date": date, "obj_id": "O1",
                                     "text": "为什么压平不压主胜？"})
    assert r.status_code == 200 and r.json()["ok"] is True
    from nutmeg.decision.workbench import read_events
    evs = [e for e in read_events(out, date) if e["kind"] == "user_message"]
    assert evs and evs[0]["obj_id"] == "O1" and "压平" in evs[0]["text"]


def test_events_endpoint_returns_new_since(tmp_path):
    """SSE 拉取:/events?since=N 只回新事件(轮询式,便于 TestClient 断言)。"""
    client, out, date = _app(tmp_path)
    append_event(out, date, {"kind": "attention", "id": "A1"})
    append_event(out, date, {"kind": "agent_reply", "obj_id": "O1", "text": "铁桶压净胜"})
    r = client.get(f"/events?date={date}&since=1")
    data = r.json()
    assert [e["kind"] for e in data["events"]] == ["agent_reply"]
    assert data["cursor"] == 2


def test_workbench_renders_three_columns_and_thread(tmp_path):
    client, out, date = _app(tmp_path)
    append_event(out, date, {"kind": "attention", "id": "A1", "group": "草稿待审",
                             "match": "哈马比 vs 卡尔马"})
    html = client.get(f"/?date={date}").text
    assert "今日议程" in html and "待裁决" in html and "追问线程" in html
    assert "哈马比 vs 卡尔马" in html          # attention 事件渲染进左栏
    assert 'id="sopbar"' not in html


def test_mobile_tabs_markup_present(tmp_path):
    """窄屏三 Tab(议程/舞台/裁决)靠 CSS 折叠;标记须在 DOM(渐进增强)。"""
    client, out, date = _app(tmp_path)
    html = client.get(f"/?date={date}").text
    assert 'class="mtabs"' in html
    for label in ["议程", "舞台", "裁决"]:
        assert label in html


def test_non_loopback_host_needs_password(tmp_path):
    """对网络开放（2026-10-30 校园网）：没设密码拒绝启动；设了放行；本机绑定不管。"""
    import pytest

    from nutmeg.interfaces.cli import decision as dweb
    with pytest.raises(SystemExit):
        dweb._warn_if_exposed("0.0.0.0")
    assert dweb._warn_if_exposed("0.0.0.0", "pw") is True
    assert dweb._warn_if_exposed("127.0.0.1") is False


def _gated(tmp_path, client_host="10.209.1.2"):
    app = create_decision_app(output_dir=tmp_path, kernel_state=_kernel_state,
                              web_password="s3cret")
    return TestClient(app, client=(client_host, 50000))


def test_password_gate_for_other_machines(tmp_path):
    """非本机：页面跳登录、接口 401；manifest/图标不设门；输对密码后 cookie 通行，next 只许站内。"""
    c = _gated(tmp_path)
    r = c.get("/day/2026-10-30", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login?next=/day/2026-10-30"
    assert c.get("/api/workbench?date=2026-10-30").status_code == 401
    assert c.post("/action/note", json={"date": "d", "text": "x"}).status_code == 401
    assert c.get("/manifest.webmanifest").status_code == 200
    assert c.get("/static/decision/icons/icon-192.png").status_code == 200
    bad = c.post("/login", data={"password": "nope", "next": "/day"}, follow_redirects=False)
    assert bad.status_code == 200 and "密码不对" in bad.text
    ok = c.post("/login", data={"password": "s3cret", "next": "//evil.example"},
                follow_redirects=False)
    assert ok.status_code == 303 and ok.headers["location"] == "/day"
    assert "max-age=15552000" in ok.headers["set-cookie"].lower()
    assert c.get("/api/workbench?date=2026-10-30").status_code == 200


def test_password_gate_locks_after_five_misses_and_spares_localhost(tmp_path):
    c = _gated(tmp_path)
    for _ in range(5):
        c.post("/login", data={"password": "nope"})
    locked = c.post("/login", data={"password": "s3cret"}, follow_redirects=False)
    assert locked.status_code == 200 and "15 分钟" in locked.text
    assert _gated(tmp_path, "127.0.0.1").get("/api/workbench?date=2026-10-30").status_code == 200


def test_push_link_base_follows_lan_ip(monkeypatch):
    """`lan:<端口>` 每次发送时取本机当下 IP；其余原样去尾斜杠。"""
    import socket

    from nutmeg.config.settings import decision_web_base_url

    class FakeSock:
        def __init__(self, *a): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def connect(self, addr): pass
        def getsockname(self): return ("10.209.80.225", 5555)

    monkeypatch.setattr(socket, "socket", FakeSock)
    assert decision_web_base_url("lan:8787") == "http://10.209.80.225:8787"
    assert decision_web_base_url("https://x.example/") == "https://x.example"
    assert decision_web_base_url("") == ""


def test_manifest_and_icons_for_home_screen(tmp_path):
    """手机主屏幕（Task 9.3）：manifest 从 /day 起、全屏；图标文件真在；页头挂了 manifest。"""
    client, _, date = _app(tmp_path)
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/manifest+json")
    m = r.json()
    assert (m["start_url"], m["display"], m["scope"]) == ("/day", "standalone", "/")
    for icon in m["icons"]:
        assert client.get(icon["src"]).status_code == 200
    assert client.get("/static/decision/icons/apple-touch-icon.png").status_code == 200
    page = client.get(f"/?date={date}").text
    assert '<link rel="manifest" href="/manifest.webmanifest">' in page
    assert 'apple-touch-icon' in page and "/static/decision/pwa.js?v=" in page


def test_cross_site_writes_are_refused(tmp_path):
    """真域名下（Tailscale serve）别的站点不能往账本写；同源与无 Origin 照旧。"""
    client, _, date = _app(tmp_path)
    body = {"date": date, "obj_id": "day", "text": "手记"}
    bad = client.post("/action/note", json=body, headers={"Origin": "https://evil.example"})
    assert bad.status_code == 403
    same = client.post("/action/note", json=body,
                       headers={"Origin": "https://mac.tail1.ts.net", "Host": "mac.tail1.ts.net"})
    assert same.status_code == 200
    proxied = client.post("/action/note", json=body,
                          headers={"Origin": "https://mac.tail1.ts.net", "Host": "127.0.0.1:8787",
                                   "X-Forwarded-Host": "mac.tail1.ts.net"})
    assert proxied.status_code == 200
    assert client.post("/action/note", json=body).status_code == 200
