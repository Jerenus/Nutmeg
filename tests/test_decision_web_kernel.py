# tests/test_decision_web_kernel.py
"""判读工作台读侧接内核——写侧早已切到 ForecastRevision，页面却还在读 8/24 的旧 store。"""
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from nutmeg.decision.store import DecisionStore
from nutmeg.interfaces.decision_web import create_decision_app
from nutmeg.interfaces.decision_web_kernel import kernel_day_state

_AS_OF = datetime(2026, 9, 18, 8, 0, tzinfo=UTC)


class _FakeRepository:
    """只实现 kernel_day_state 用到的三个查询；行形状照抄 ProductReadRepository。"""

    def __init__(self):
        self.calls = []

    def board_matches(self, start_at, end_at, as_of):
        self.calls.append(("board_matches", start_at, end_at, as_of))
        return [{
            "match_id": "match-473c", "scheduled_at": "2026-09-19",
            "home_team": "布伦特福德", "away_team": "切尔西", "competition": "英超",
            "status": "scheduled", "schedule_status": "scheduled",
        }]

    def latest_snapshot(self, match_id, market_definition_id, as_of):
        self.calls.append(("latest_snapshot", match_id, market_definition_id))
        return {
            "market_snapshot_id": "snapshot-2abf", "match_id": match_id,
            "market_definition_id": market_definition_id, "snapshot_kind": "read_time",
            "as_of": "2026-09-18T03:27:51+00:00",
            "fair_distribution_json": '{"home": 0.3506, "draw": 0.2517, "away": 0.3977}',
            "devig_method": "c500", "source_coverage_json": '{"provider": "c500"}',
        }

    def forecasts_for_match(self, match_id, as_of):
        self.calls.append(("forecasts_for_match", match_id))
        return [
            {"forecast_revision_id": "frev-1", "status": "committed",
             "made_at": "2026-09-18T07:40:00+00:00", "market_definition_id": "md-had",
             "prior_distribution": {"home": 0.3506, "draw": 0.2517, "away": 0.3977},
             "belief_distribution": {"home": 0.3506, "draw": 0.2517, "away": 0.3977},
             "actor_id": "judge:owner", "commitment_tier": "commit"},
            {"forecast_revision_id": "frev-0", "status": "superseded",
             "made_at": "2026-09-18T07:00:00+00:00", "market_definition_id": "md-had",
             "prior_distribution": {}, "belief_distribution": {},
             "actor_id": "judge:owner", "commitment_tier": "commit"},
        ]


def test_kernel_day_state_windows_by_shanghai_day_and_maps_legacy_shape():
    repo = _FakeRepository()
    state = kernel_day_state(repo, "2026-09-19", as_of=_AS_OF)
    # 上海日界 [2026-09-19 00:00+08, 2026-09-20 00:00+08) → UTC
    assert repo.calls[0] == ("board_matches", "2026-09-18T16:00:00+00:00",
                             "2026-09-19T16:00:00+00:00", _AS_OF.isoformat())
    m = state["matches"][0]
    assert (m["match_id"], m["home"], m["away"], m["competition"]) == \
        ("match-473c", "布伦特福德", "切尔西", "英超")
    s = state["snapshots"][0]
    assert s["kind"] == "read_time" and s["match_id"] == "match-473c"
    assert s["fair"]["had"]["home"] == 0.3506          # 旧模板读 fair.had.*


def test_kernel_day_state_exposes_committed_reads_only_and_synthesizes_agenda():
    state = kernel_day_state(_FakeRepository(), "2026-09-19", as_of=_AS_OF)
    assert [r["read_id"] for r in state["reads"]] == ["frev-1"]   # superseded 不算
    r = state["reads"][0]
    assert r["match_id"] == "match-473c" and r["market"] == "had"
    assert r["belief"]["away"] == 0.3977
    att = [e for e in state["events"] if e["kind"] == "attention"]
    assert len(att) == 1 and att[0]["obj_id"] == "frev-1"
    assert "布伦特福德" in att[0]["match"] and "切尔西" in att[0]["match"]
    # 点开议程项后中栏要能渲染：app.js 只认 `judgment` 事件的 payload
    jud = [e for e in state["events"] if e["kind"] == "judgment"]
    assert len(jud) == 1 and jud[0]["obj_id"] == "frev-1"
    p = jud[0]["payload"]
    assert p["match"] == "布伦特福德 vs 切尔西" and p["competition"] == "英超"
    assert p["prior"]["home"] == 0.3506 and p["belief"]["away"] == 0.3977
    # 已提交的内核 Read 不是草稿：不得合成 read_draft（否则「批准入库」会往旧 store 重写）
    assert not [e for e in state["events"] if e["kind"] == "read_draft"]


def test_app_uses_kernel_state_when_injected(tmp_path):
    store = DecisionStore(tmp_path / "decision")          # 旧 store 是空的
    app = create_decision_app(
        store=store, output_dir=tmp_path,
        kernel_state=lambda date: kernel_day_state(_FakeRepository(), date, as_of=_AS_OF),
    )
    client = TestClient(app)
    body = client.get("/api/workbench?date=2026-09-19").json()
    assert [m["home"] for m in body["matches"]] == ["布伦特福德"]
    assert body["reads"][0]["read_id"] == "frev-1"
    html = client.get("/?date=2026-09-19").text
    assert "布伦特福德 vs 切尔西" in html                 # 议程行渲染进左栏


def test_app_without_kernel_state_keeps_legacy_path(tmp_path):
    store = DecisionStore(tmp_path / "decision")
    client = TestClient(create_decision_app(store=store, output_dir=tmp_path))
    body = client.get("/api/workbench?date=2026-09-19").json()
    assert body["matches"] == [] and body["events"] == [] and "reads" not in body


def _slip():
    """两腿竞彩 2串1：登记簿的校验对足彩要求 9/14 场，测试夹具用竞彩最省。"""
    from nutmeg.decision.betslip import BetSlip, SlipLeg
    return BetSlip(
        slip_id="26129-JC-T", channel="jczq", placed_at="2026-09-18", issue="26129",
        combo_sizes=(2,),
        legs=[SlipLeg(key="周五008", name="拜仁-柏林联", market="had",
                      selections=("home",), odds=(1.1,),
                      fair={"home": 0.898, "draw": 0.065, "away": 0.037}),
              SlipLeg(key="周五012", name="布里斯-沃特福", market="had",
                      selections=("home", "draw"), odds=(1.8, 3.4),
                      fair={"home": 0.501, "draw": 0.26, "away": 0.239})],
    )


def test_registered_slips_become_readonly_my_plan_cards():
    state = kernel_day_state(_FakeRepository(), "2026-09-19", as_of=_AS_OF, slips=[_slip()])
    slips = [e for e in state["events"] if e["kind"] == "slip"]
    assert len(slips) == 1 and slips[0]["id"] == "26129-JC-T"
    p = slips[0]["payload"]
    assert p["channel"] == "jczq" and p["stake_yuan"] == 4           # 1×2=2 注 × ¥2
    assert [lg["selections"] for lg in p["legs"]] == [["home"], ["home", "draw"]]
    assert p["legs"][1]["coverage"] == 0.761


def test_slips_for_date_picks_issues_whose_matches_fall_on_that_day(tmp_path):
    import json

    from nutmeg.decision.betslip import register_slip
    from nutmeg.interfaces.decision_web_kernel import slips_for_date
    zucai = tmp_path / "zucai"
    zucai.mkdir()
    (zucai / "26129-issue.json").write_text(json.dumps({
        "issue_id": "26129", "matches": [{"match_no": 1, "match_date": "2026-09-19"}]}),
        encoding="utf-8")
    (zucai / "26130-issue.json").write_text(json.dumps({
        "issue_id": "26130", "matches": [{"match_no": 1, "match_date": "2026-09-20"}]}),
        encoding="utf-8")
    register_slip(tmp_path, _slip())
    other = _slip()
    other.slip_id = "26130-JC-T"
    other.issue = "26130"
    register_slip(tmp_path, other)
    got = slips_for_date(tmp_path, zucai, "2026-09-19")
    assert [x.slip_id for x in got] == ["26129-JC-T"]
    assert slips_for_date(tmp_path, zucai, "2026-09-21") == []


def test_static_assets_carry_a_version_so_browsers_do_not_serve_stale_js(tmp_path):
    """2026-09-18：加了 renderSlip 之后浏览器仍跑旧 app.js，右栏空着，硬刷新才出来。"""
    store = DecisionStore(tmp_path / "decision")
    client = TestClient(create_decision_app(store=store, output_dir=tmp_path))
    html = client.get("/?date=2026-09-19").text
    assert "/static/decision/app.js?v=" in html and "/static/decision/app.css?v=" in html


# ── SOP 任务栏端点（阶段一）──────────────────────────────────────────────
def test_sop_steps_endpoint_lists_steps_with_done_state(tmp_path):
    zucai = tmp_path / "zucai"
    zucai.mkdir()
    (zucai / "26129-prep-morning.json").write_text("{}", encoding="utf-8")
    store = DecisionStore(tmp_path / "decision")
    client = TestClient(create_decision_app(store=store, output_dir=tmp_path / "jczq",
                                            zucai_dir=zucai))
    body = client.get("/api/sop-steps?issue=26129&date=2026-09-19").json()
    ids = [s["step_id"] for s in body["steps"]]
    assert ids[0] == "B0_prep_morning" and body["steps"][0]["done"] is True
    assert body["steps"][1]["step_id"] == "B1_prep_afternoon"
    assert body["steps"][1]["done"] is False


def test_run_task_endpoint_uses_injected_invoker_and_returns_result(tmp_path):
    calls = []

    def fake_invoke(argv):
        calls.append(argv)
        return 0, "备料完成"

    store = DecisionStore(tmp_path / "decision")
    app = create_decision_app(store=store, output_dir=tmp_path / "jczq",
                              zucai_dir=tmp_path / "zucai", sop_invoke=fake_invoke)
    client = TestClient(app)
    r = client.post("/action/run-task",
                    json={"step_id": "B0_prep_morning", "issue": "26129",
                          "date": "2026-09-19"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert calls == [["zucai-prep", "--slot", "morning", "--issue", "26129"]]
    evs = client.get("/events?date=2026-09-19&since=0").json()["events"]
    assert [e["kind"] for e in evs] == ["task_started", "task_done"]


def test_run_task_rejects_unknown_step(tmp_path):
    store = DecisionStore(tmp_path / "decision")
    client = TestClient(create_decision_app(store=store, output_dir=tmp_path / "jczq",
                                            zucai_dir=tmp_path / "zucai"))
    r = client.post("/action/run-task",
                    json={"step_id": "B99", "issue": "26129", "date": "2026-09-19"})
    assert r.status_code == 400 and "未登记" in r.json()["error"]


def test_workbench_page_has_sop_bar_bound_to_issue(tmp_path):
    store = DecisionStore(tmp_path / "decision")
    client = TestClient(create_decision_app(store=store, output_dir=tmp_path / "jczq",
                                            zucai_dir=tmp_path / "zucai"))
    html = client.get("/?date=2026-09-19&issue=26129").text
    assert 'id="sopbar"' in html and 'data-issue="26129"' in html


def test_note_and_candidate_endpoints_append_events(tmp_path):
    store = DecisionStore(tmp_path / "decision")
    client = TestClient(create_decision_app(store=store, output_dir=tmp_path))
    d = "2026-09-19"
    r = client.post("/action/note",
                    json={"date": d, "obj_id": "ticket:26129", "text": "SFC-B 否决"})
    assert r.status_code == 200 and r.json()["ok"] is True
    r = client.post("/action/candidate", json={"date": d, "obj_id": "ticket:26129",
        "version": "SFC-B", "faces": {"1": "30"}, "notes": 128, "stake_yuan": 256,
        "p_all": 0.0038, "verdict": "rejected", "reason": "三处 C2"})
    assert r.status_code == 200
    kinds = [e["kind"] for e in client.get(f"/events?date={d}&since=0").json()["events"]]
    assert kinds == ["note", "candidate"]


def test_replay_page_orders_all_event_kinds_by_seq(tmp_path):
    from nutmeg.decision.workbench import append_event
    d = "2026-09-19"
    for ev in [
        {"kind": "task_started", "obj_id": "task:B0_prep_morning",
         "label": "B0 早刷新", "argv": ["zucai-prep"]},
        {"kind": "task_done", "obj_id": "task:B0_prep_morning",
         "label": "B0 早刷新", "exit_code": 0, "text": "备料完成"},
        {"kind": "user_message", "obj_id": "fr-8", "text": "朗斯不败？"},
        {"kind": "agent_reply", "obj_id": "fr-8", "text": "平局最被支持。"},
        {"kind": "candidate", "obj_id": "ticket:26129",
         "payload": {"version": "SFC-B", "verdict": "rejected", "reason": "三处 C2",
                     "notes": 128, "stake_yuan": 256, "p_all": 0.0038, "faces": {}}},
        {"kind": "note", "obj_id": "day", "text": "刹车：¥1000 帽用户裁定"},
    ]:
        append_event(tmp_path, d, ev)
    store = DecisionStore(tmp_path / "decision")
    html = TestClient(create_decision_app(store=store, output_dir=tmp_path)).get(
        f"/replay?date={d}").text
    assert html.index("B0 早刷新") < html.index("朗斯不败？") < html.index("SFC-B") \
        < html.index("刹车")
    assert "已否决" in html and "exit=0" in html


def test_replay_page_tolerates_missing_optional_keys(tmp_path):
    """p_all 为 None、缺 at/label 的事件不得让模板炸掉。"""
    from nutmeg.decision.workbench import append_event
    d = "2026-09-20"
    append_event(tmp_path, d, {"kind": "candidate", "obj_id": "ticket:x",
                               "payload": {"version": "A", "verdict": "considered",
                                           "notes": 1, "stake_yuan": 2, "p_all": None}})
    append_event(tmp_path, d, {"kind": "task_started", "obj_id": "task:z"})
    append_event(tmp_path, d, {"kind": "weird_kind", "obj_id": "q"})
    store = DecisionStore(tmp_path / "decision")
    client = TestClient(create_decision_app(store=store, output_dir=tmp_path))
    r = client.get(f"/replay?date={d}")
    assert r.status_code == 200 and "考虑过" in r.text
    r2 = client.get("/replay?date=2026-09-21")
    assert r2.status_code == 200 and "这一天没有事件" in r2.text
