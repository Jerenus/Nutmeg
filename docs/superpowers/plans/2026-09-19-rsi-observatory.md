# RSI 观察台（只读全景界面 ②）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 三个只读页面 + 三个只读 API：`/observe`（全景）、`/observe/exp/<id>`（一条实验的一生）、`/observe/day/<date>`（候选树 DAG + 资金方案）。零写操作，数据缺席优雅降级。

**Architecture:** 一个纯函数模块 `observe_views.py` 把仓库查询与事件流整理成页面 JSON（可离线测）；`decision_web.py` 加三个 API + 三个页面路由；模板 `observe/*.html` 只含 ECharts 初始化与轮询；样式独立 `observe.css`。不改 `app.js`。

**Tech Stack:** FastAPI + Jinja2 + 原生 JS + ECharts 5.5.1（cdnjs，固定版本）/ pytest。Spec：`docs/superpowers/specs/2026-09-19-rsi-observatory-design.md`。

**仓库纪律**：同前（显式路径 add；碰 `nutmeg/interfaces/web/**` 的提交会跑整套产品测试，提交期间不编辑）。

---

## 文件结构

- Create `nutmeg/decision/observe_views.py` — `panorama(repo, *, as_of, day, zucai_dir)`、`experiment_life(repo, exp_id, *, as_of)`、`day_view(events, plan)`、`candidate_dag(events)`
- Modify `nutmeg/interfaces/decision_web.py` — `/api/observe*` 与 `/observe*` 路由；顶栏链接
- Create `nutmeg/interfaces/web/templates/decision/observe/{panorama,exp,day}.html`、`nutmeg/interfaces/web/static/decision/observe.css`、`observe.js`
- Modify `nutmeg/interfaces/web/templates/decision/workbench.html`（顶栏加「观察台」）
- Tests：`tests/decision/test_observe_views.py`、`tests/test_decision_web_observe.py`

---

### Task 1: 视图函数（纯函数，先于任何路由）

**Files:** Create `nutmeg/decision/observe_views.py`; Test `tests/decision/test_observe_views.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_observe_views.py
from nutmeg.decision.observe_views import candidate_dag, day_view, experiment_card


def test_experiment_card_derives_progress_ci_bar_and_gap_heat():
    row = {"exp_id": "F2", "status": "observing", "n_cum": 10, "n_min": 140, "ci": [-21.3, 37.1],
           "distance_to_falsifier_pp": 35.1, "gaps": ["2026-09-14"], "verdict": None, "deployment": None,
           "tier": "observation", "layer": "judgment", "population": "zucai", "registered_at": "2026-09-14",
           "claim": "…"}
    falsifier = {"threshold_pp": 2.0, "bound": "ci_upper", "direction": "lt_means_falsified"}
    card = experiment_card(row, falsifier)
    assert card["progress"] == 10 / 140 and card["threshold_pp"] == 2.0
    assert card["ci"] == [-21.3, 37.1] and card["gap_count"] == 1 and card["color"] == "observing"


def test_candidate_dag_builds_nodes_and_edges_and_drops_orphans():
    evs = [{"kind": "candidate", "seq": 1, "payload": {"version": "tiers@abc", "parent_version": None, "verdict": "considered", "notes": 0, "stake_yuan": 0, "p_all": None}},
           {"kind": "candidate", "seq": 2, "payload": {"version": "frontier#0@¥400", "parent_version": "tiers@abc", "verdict": "considered", "notes": 200, "stake_yuan": 400, "p_all": 0.12}},
           {"kind": "candidate", "seq": 3, "payload": {"version": "chosen#0@renjiu", "parent_version": "frontier#0@¥400", "verdict": "chosen", "notes": 200, "stake_yuan": 400, "p_all": 0.12}},
           {"kind": "candidate", "seq": 4, "payload": {"version": "SFC-C", "parent_version": "SFC-B", "verdict": "rejected", "notes": 1, "stake_yuan": 2, "p_all": None}},
           {"kind": "note", "seq": 5, "text": "x"}]
    dag = candidate_dag(evs)
    assert [n["id"] for n in dag["nodes"]] == ["tiers@abc", "frontier#0@¥400", "chosen#0@renjiu", "SFC-C"]
    assert dag["edges"] == [{"source": "tiers@abc", "target": "frontier#0@¥400"},
                            {"source": "frontier#0@¥400", "target": "chosen#0@renjiu"}]
    assert dag["orphan_edges_dropped"] == 1                       # SFC-C 的父 SFC-B 不存在
    assert next(n for n in dag["nodes"] if n["id"] == "chosen#0@renjiu")["verdict"] == "chosen"


def test_day_view_degrades_gracefully_without_plan_or_tree():
    v = day_view(events=[{"kind": "slip", "payload": {"slip_id": "26129-RJ9", "notes": 384, "stake_yuan": 768}},
                         {"kind": "judgment", "obj_id": "fr-1", "payload": {"match": "A vs B", "market": "had"}}],
                 plan=None)
    assert v["plan"] is None and v["tree"]["nodes"] == [] and v["slips"][0]["slip_id"] == "26129-RJ9"
    assert v["judgments"] == [{"obj_id": "fr-1", "match": "A vs B", "market": "had"}]
```

- [ ] **Step 2: Run** → `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# nutmeg/decision/observe_views.py
"""观察台的视图整理：查询结果/事件流 → 页面 JSON。纯函数、只读、零判断。"""
from __future__ import annotations

import json
from pathlib import Path

_COLORS = {"registered": "registered", "observing": "observing", "graded": "graded",
           "falsified": "falsified", "survived": "survived", "inconclusive": "inconclusive",
           "deployed": "deployed", "held": "held", "retired": "retired", "extended": "extended"}


def experiment_card(row: dict, falsifier: dict) -> dict:
    n, n_min = int(row.get("n_cum") or 0), int(row.get("n_min") or 0)
    return {"exp_id": row["exp_id"], "claim": row.get("claim", ""), "status": row["status"],
            "color": _COLORS.get(row["status"], "registered"), "tier": row.get("tier"),
            "layer": row.get("layer"), "population": row.get("population"),
            "n_cum": n, "n_min": n_min, "progress": (n / n_min) if n_min else 0.0,
            "ci": row.get("ci"), "threshold_pp": float(falsifier.get("threshold_pp", 0.0)),
            "bound": falsifier.get("bound"), "direction": falsifier.get("direction"),
            "distance_to_falsifier_pp": row.get("distance_to_falsifier_pp"),
            "gaps": row.get("gaps") or [], "gap_count": len(row.get("gaps") or []),
            "verdict": row.get("verdict"), "deployment": row.get("deployment"),
            "registered_at": row.get("registered_at")}


def candidate_dag(events: list[dict]) -> dict:
    nodes, edges, ids, dropped = [], [], set(), 0
    for e in events:
        if e.get("kind") != "candidate":
            continue
        p = e.get("payload") or {}
        vid = str(p.get("version") or f"seq{e.get('seq')}")
        ids.add(vid)
        nodes.append({"id": vid, "verdict": p.get("verdict"), "notes": p.get("notes"),
                      "stake_yuan": p.get("stake_yuan"), "p_all": p.get("p_all"), "seq": e.get("seq"),
                      "reason": p.get("reason", "")})
    for e in events:
        if e.get("kind") != "candidate":
            continue
        p = e.get("payload") or {}
        parent = p.get("parent_version")
        if not parent:
            continue
        if parent in ids:
            edges.append({"source": parent, "target": str(p.get("version"))})
        else:
            dropped += 1
    return {"nodes": nodes, "edges": edges, "orphan_edges_dropped": dropped}


def day_view(*, events: list[dict], plan: dict | None) -> dict:
    slips = [dict(e["payload"]) for e in events if e.get("kind") == "slip"]
    judgments = [{"obj_id": e.get("obj_id"), "match": (e.get("payload") or {}).get("match"),
                  "market": (e.get("payload") or {}).get("market")} for e in events if e.get("kind") == "judgment"]
    return {"tree": candidate_dag(events), "plan": plan, "slips": slips, "judgments": judgments}


def wind_for_day(zucai_dir: Path, issue: str | None) -> dict | None:
    if not issue:
        return None
    p = Path(zucai_dir) / f"{issue}-tiers.json"
    if not p.exists():
        return None
    return json.loads(p.read_text("utf-8")).get("wind")
```
（两遍遍历是有意的：先收全部 id 再连边，否则先出现的子节点会被误判孤儿。）

- [ ] **Step 4: Run** → 3 passed
- [ ] **Step 5: Commit** `git add nutmeg/decision/observe_views.py tests/decision/test_observe_views.py && git commit -m "feat(observe): 视图纯函数——实验卡/候选树 DAG/日视图，缺数据优雅降级"`

---

### Task 2: 三个只读 API

**Files:** Modify `nutmeg/interfaces/decision_web.py`; Test `tests/test_decision_web_observe.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_decision_web_observe.py
from fastapi.testclient import TestClient

from nutmeg.decision.store import DecisionStore
from nutmeg.decision.workbench import append_candidate, append_event
from nutmeg.interfaces.decision_web import create_decision_app


def _app(tmp_path, kernel_state=None, repo=None):
    return TestClient(create_decision_app(store=DecisionStore(tmp_path / "decision"), output_dir=tmp_path,
                                          kernel_state=kernel_state, observe_repo=repo))


class _Repo:
    def experiments(self, *, as_of):
        return [{"exp_id": "F2", "status": "observing", "n_cum": 10, "n_min": 140, "ci": [-21.3, 37.1],
                 "distance_to_falsifier_pp": 35.1, "gaps": ["2026-09-14"], "verdict": None, "deployment": None,
                 "tier": "observation", "layer": "judgment", "population": "zucai", "registered_at": "2026-09-14",
                 "claim": "c", "falsifier": {"threshold_pp": 2.0, "bound": "ci_upper", "direction": "lt_means_falsified"}}]
    def experiment_timeline(self, exp_id, *, as_of):
        return [{"kind": "registered", "at": "2026-09-18T20:00:00+08:00"},
                {"kind": "grade", "at": "2026-09-19T01:00:00+08:00", "ci_low_pp": -21.3, "ci_high_pp": 37.1, "n_cum": 10}]
    def duties_due(self, day, *, now):
        return [{"duty_id": "F2:f2-observation", "due_at": f"{day}T00:30:00+08:00", "issue": "26130"}]
    def latest_capital_plan(self, issue):
        return None


def test_api_observe_returns_cards_duties_and_null_wind_when_absent(tmp_path):
    c = _app(tmp_path, repo=_Repo())
    r = c.get("/api/observe"); assert r.status_code == 200
    body = r.json()
    assert body["experiments"][0]["exp_id"] == "F2" and body["experiments"][0]["gap_count"] == 1
    assert body["wind"] is None and body["duties_today"][0]["duty_id"].startswith("F2")


def test_api_observe_exp_and_day(tmp_path):
    c = _app(tmp_path, repo=_Repo())
    assert c.get("/api/observe/exp/F2").json()[1]["kind"] == "grade"
    append_candidate(tmp_path, "2026-09-19", obj_id="ticket:26129", version="SFC-B", faces={}, notes=128,
                     stake_yuan=256, p_all=0.0038, verdict="rejected")
    append_candidate(tmp_path, "2026-09-19", obj_id="ticket:26129", version="SFC-C", parent_version="SFC-B",
                     faces={}, notes=128, stake_yuan=256, p_all=None, verdict="chosen")
    d = c.get("/api/observe/day/2026-09-19").json()
    assert d["plan"] is None and d["tree"]["edges"] == [{"source": "SFC-B", "target": "SFC-C"}]


def test_observe_api_is_read_only_and_survives_repo_errors(tmp_path):
    class Broken(_Repo):
        def experiments(self, *, as_of): raise RuntimeError("kernel down")
    c = _app(tmp_path, repo=Broken())
    r = c.get("/api/observe")
    assert r.status_code == 200 and r.json()["experiments"] == [] and "kernel down" in r.json()["errors"][0]
    assert c.post("/api/observe").status_code == 405
```

- [ ] **Step 2: Run** → FAIL（`create_decision_app` 无 `observe_repo`）

- [ ] **Step 3: Implement**

`create_decision_app(*, store, output_dir, kernel_state=None, zucai_dir=None, sop_invoke=None, observe_repo=None)`；`observe_repo` 缺省时若 `settings.ontology_v2` 用真 `ProductReadRepository`（在 `decision.py::decision_web` 里构造后传入，与 `kernel_state` 同处），并给它一个 `latest_capital_plan(issue)` 适配（`with OntologyUnitOfWork(engine) as uow: uow.capital.latest_plan(issue)`，`capital` 属性不存在时返回 None）。在 `/events` 路由之后加：

```python
    from nutmeg.decision.observe_views import candidate_dag, day_view, experiment_card, wind_for_day

    def _safe(fn, default, errors):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 观察台永不整页失败
            errors.append(str(exc)); return default

    @app.get("/api/observe")
    def api_observe(as_of: str | None = None, day: str | None = None) -> dict:
        from datetime import date as _d, datetime as _dt, timedelta
        now = as_of or _dt.now().astimezone().isoformat(timespec="seconds")
        today = day or _d.today().isoformat()
        tomorrow = (_d.fromisoformat(today) + timedelta(days=1)).isoformat()
        errors: list[str] = []
        rows = _safe(lambda: observe_repo.experiments(as_of=now), [], errors) if observe_repo else []
        cards = [experiment_card(r, r.get("falsifier") or {}) for r in rows]
        dt = _safe(lambda: observe_repo.duties_due(today, now=now), [], errors) if observe_repo else []
        dm = _safe(lambda: observe_repo.duties_due(tomorrow, now=now), [], errors) if observe_repo else []
        issue = next((d.get("issue") for d in dt if d.get("issue")), None)
        wind = _safe(lambda: wind_for_day(app.state.zucai_dir, issue), None, errors)
        return {"as_of": now, "experiments": cards, "duties_today": dt, "duties_tomorrow": dm,
                "wind": wind, "errors": errors}

    @app.get("/api/observe/exp/{exp_id}")
    def api_observe_exp(exp_id: str, as_of: str | None = None) -> list:
        from datetime import datetime as _dt
        now = as_of or _dt.now().astimezone().isoformat(timespec="seconds")
        errors: list[str] = []
        return _safe(lambda: observe_repo.experiment_timeline(exp_id, as_of=now), [], errors) if observe_repo else []

    @app.get("/api/observe/day/{date}")
    def api_observe_day(date: str) -> dict:
        errors: list[str] = []
        events = _day_state(store, output_dir, date, kernel_state)["events"]
        issue = next((str(e.get("obj_id", "")).split(":")[-1] for e in events
                      if e.get("kind") == "candidate" and str(e.get("obj_id", "")).startswith("ticket:")), None)
        plan = _safe(lambda: observe_repo.latest_capital_plan(issue), None, errors) if (observe_repo and issue) else None
        if plan is not None and not isinstance(plan, dict):
            plan = {"plan_id": plan.plan_id, "cap_source": plan.cap_source, "caps": plan.caps,
                    "max_p_matrix": plan.max_p_matrix, "max_p_strict": plan.max_p_strict,
                    "chosen_p": plan.chosen_p, "gate_cost_pp": plan.gate_cost_pp, "chosen": plan.chosen}
        view = day_view(events=events, plan=plan); view["errors"] = errors
        return view
```
`ProductReadRepository.experiments()` 当前返回体没有 `falsifier`——在 Task 10（RSI 计划）的 `experiments()` 里加一行 `"falsifier": e.falsifier`（读侧改动，与本任务一起提交）。

- [ ] **Step 4: Run** `uv run pytest tests/test_decision_web_observe.py tests/test_decision_web_kernel.py tests/product/test_repository_rsi.py -v` → 全绿
- [ ] **Step 5: Commit** `git add nutmeg/interfaces/decision_web.py nutmeg/interfaces/cli/decision.py nutmeg/product/repository.py tests/test_decision_web_observe.py && git commit -m "feat(observe): 三个只读 API（全景/一生/一天），每块独立降级"`

---

### Task 3: 三个页面 + ECharts + 样式 + 顶栏链接

**Files:** Create `templates/decision/observe/panorama.html`、`exp.html`、`day.html`、`static/decision/observe.css`、`observe.js`；Modify `decision_web.py`（三个页面路由）、`templates/decision/workbench.html`（顶栏链接）；Test `tests/test_decision_web_observe.py`

- [ ] **Step 1: Write the failing test**

```python
# 追加到 tests/test_decision_web_observe.py
def test_pages_render_read_only_with_pinned_echarts_and_nav_link(tmp_path):
    c = _app(tmp_path, repo=_Repo())
    for path in ("/observe", "/observe/exp/F2", "/observe/day/2026-09-19"):
        html = c.get(path).text
        assert "cdnjs.cloudflare.com/ajax/libs/echarts/5.5.1/echarts.min.js" in html
        assert "<form" not in html and "fetch(" in html and "method: 'POST'" not in html and 'method: "POST"' not in html
    assert "/observe" in c.get("/?date=2026-09-19").text          # 工作台顶栏有观察台链接
    assert "今日未定级" in c.get("/observe").text                 # 降级文案（无 tiers）
```

- [ ] **Step 2: Run** → 404

- [ ] **Step 3: Implement**

路由（`decision_web.py`）：
```python
    @app.get("/observe")
    def observe_page(request: Request):
        return templates.TemplateResponse(request, "decision/observe/panorama.html", {"title": "RSI 观察台"})

    @app.get("/observe/exp/{exp_id}")
    def observe_exp_page(request: Request, exp_id: str):
        return templates.TemplateResponse(request, "decision/observe/exp.html", {"title": f"实验 {exp_id}", "exp_id": exp_id})

    @app.get("/observe/day/{date}")
    def observe_day_page(request: Request, date: str):
        return templates.TemplateResponse(request, "decision/observe/day.html", {"title": f"过程 {date}", "date": date})
```

`panorama.html`（`exp.html`/`day.html` 同结构，只换容器与 JS 入口函数）：
```html
{% extends "decision/layout.html" %}
{% block body %}
<link rel="stylesheet" href="/static/decision/observe.css?v={{ asset_v }}">
<div class="topbar"><div class="brand"><span class="mk">◉</span> RSI 观察台</div>
  <div class="spacer"></div><a class="btn" href="/">工作台</a></div>
<section class="obs-wind" id="wind"><span class="muted">今日未定级</span></section>
<section class="obs-duties" id="duties"></section>
<section class="obs-grid" id="cards"></section>
<script src="https://cdnjs.cloudflare.com/ajax/libs/echarts/5.5.1/echarts.min.js"></script>
<script src="/static/decision/observe.js?v={{ asset_v }}"></script>
<script>Observe.panorama({ cards: "#cards", wind: "#wind", duties: "#duties" });</script>
{% endblock %}
```

`observe.js`（只读：只有 `fetch(url)` GET）：
```javascript
window.Observe = (function () {
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function ring(dom, progress, label) {
    var c = echarts.init(dom, null, { renderer: "svg" });
    c.setOption({ series: [{ type: "gauge", startAngle: 90, endAngle: -270, min: 0, max: 1, progress: { show: true, width: 8 },
      axisLine: { lineStyle: { width: 8 } }, axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false },
      pointer: { show: false }, detail: { formatter: label, fontSize: 12, offsetCenter: [0, 0] }, data: [{ value: progress }] }] });
    return c;
  }
  function ciBar(dom, ci, threshold) {
    var c = echarts.init(dom, null, { renderer: "svg" });
    var lo = Math.min(ci[0], threshold) - 5, hi = Math.max(ci[1], threshold) + 5;
    c.setOption({ grid: { left: 8, right: 8, top: 6, bottom: 18 }, xAxis: { min: lo, max: hi, axisLabel: { fontSize: 10 } }, yAxis: { show: false, min: 0, max: 1 },
      series: [{ type: "custom", renderItem: function (p, api) { var x0 = api.coord([ci[0], .5])[0], x1 = api.coord([ci[1], .5])[0], y = api.coord([0, .5])[1];
        return { type: "group", children: [{ type: "rect", shape: { x: x0, y: y - 6, width: x1 - x0, height: 12 }, style: { fill: "#5aa" } },
          { type: "line", shape: { x1: api.coord([threshold, 0])[0], y1: y - 14, x2: api.coord([threshold, 0])[0], y2: y + 14 }, style: { stroke: "#c33", lineWidth: 2 } }] }; }, data: [0] }] });
  }
  function card(x) {
    var a = el("a", "obs-card " + x.color); a.href = "/observe/exp/" + encodeURIComponent(x.exp_id);
    a.appendChild(el("div", "obs-id", x.exp_id + " · " + x.status));
    a.appendChild(el("div", "obs-claim", x.claim));
    var r = el("div", "obs-ring"); a.appendChild(r);
    var b = el("div", "obs-ci"); a.appendChild(b);
    var gaps = el("div", "obs-gaps"); (x.gaps || []).forEach(function (g) { var s = el("span", "gap", g.slice(5)); gaps.appendChild(s); }); a.appendChild(gaps);
    setTimeout(function () { ring(r, x.progress, x.n_cum + "/" + x.n_min); if (x.ci) ciBar(b, x.ci, x.threshold_pp); }, 0);
    return a;
  }
  function panorama(sel) {
    function load() {
      fetch("/api/observe").then(function (r) { return r.json(); }).then(function (d) {
        var cards = document.querySelector(sel.cards); cards.innerHTML = ""; d.experiments.forEach(function (x) { cards.appendChild(card(x)); });
        var w = document.querySelector(sel.wind); if (d.wind) { w.textContent = "今日风向 " + d.wind.regime + " · 各级 " + JSON.stringify(d.wind.tiers) + " · 建议帽档 " + d.wind.cap_band; }
        var du = document.querySelector(sel.duties); du.innerHTML = ""; du.appendChild(el("div", "obs-h", "今日到期 " + d.duties_today.length + " · 明日 " + d.duties_tomorrow.length));
        d.duties_today.forEach(function (t) { du.appendChild(el("div", "obs-duty", t.due_at.slice(11, 16) + "  " + t.duty_id)); });
      });
    }
    load(); setInterval(load, 60000);
  }
  function life(sel, expId) {
    fetch("/api/observe/exp/" + encodeURIComponent(expId)).then(function (r) { return r.json(); }).then(function (tl) {
      var grades = tl.filter(function (e) { return e.kind === "grade"; });
      var c = echarts.init(document.querySelector(sel.chart));
      c.setOption({ xAxis: { type: "category", data: grades.map(function (g) { return g.at.slice(0, 10); }) }, yAxis: { name: "pp" },
        series: [{ type: "line", data: grades.map(function (g) { return g.ci_high_pp; }), name: "CI 上界" },
                 { type: "line", data: grades.map(function (g) { return g.ci_low_pp; }), name: "CI 下界" }] });
      var list = document.querySelector(sel.list); tl.forEach(function (e) { list.appendChild(el("div", "obs-ev " + e.kind, e.at + "  " + e.kind + (e.verdict ? " → " + e.verdict : ""))); });
    });
  }
  function day(sel, date) {
    fetch("/api/observe/day/" + date).then(function (r) { return r.json(); }).then(function (d) {
      var box = document.querySelector(sel.tree);
      if (!d.tree.nodes.length) { box.textContent = "今日无候选树"; }
      else { var c = echarts.init(box); c.setOption({ series: [{ type: "graph", layout: "force", roam: true, label: { show: true, formatter: "{b}" },
        force: { repulsion: 220, edgeLength: 90 }, edgeSymbol: ["none", "arrow"],
        data: d.tree.nodes.map(function (n) { return { name: n.id, value: n.p_all, symbolSize: n.verdict === "chosen" ? 28 : 16, itemStyle: { color: n.verdict === "chosen" ? "#3a6" : n.verdict === "rejected" ? "#999" : "#58c" } }; }),
        links: d.tree.edges }] }); }
      var p = document.querySelector(sel.plan);
      p.textContent = d.plan ? ("方案 " + d.plan.plan_id + " · " + d.plan.cap_source + " · 帽 " + JSON.stringify(d.plan.caps) + " · maxP 矩阵/strict/所选 " + d.plan.max_p_matrix + "/" + d.plan.max_p_strict + "/" + d.plan.chosen_p + " · 门代价 " + d.plan.gate_cost_pp) : "未定案";
      var s = document.querySelector(sel.slips); d.slips.forEach(function (x) { s.appendChild(el("div", "obs-slip", x.slip_id + " · " + x.notes + " 注 ¥" + x.stake_yuan)); });
    });
  }
  return { panorama: panorama, life: life, day: day };
})();
```

`observe.css`：卡片网格、状态色（observing 青 / graded 琥珀 / falsified 灰 / survived 绿 / deployed 靛）、`prefers-color-scheme: dark`、移动端单列。`workbench.html` 顶栏加 `<a class="btn" href="/observe">观察台</a>`。

- [ ] **Step 4: Run** `uv run pytest tests/test_decision_web_observe.py tests/test_decision_web_kernel.py tests/test_decision_web.py -v` → 全绿；再起服务 `uv run nutmeg decision-web --port 8799`，浏览器打开 `/observe`、`/observe/exp/F2`、`/observe/day/2026-09-19` 各截一张图留档（zero-write 检查：Network 面板无 POST）
- [ ] **Step 5: Commit** `git add nutmeg/interfaces/decision_web.py nutmeg/interfaces/web/templates/decision/observe/panorama.html nutmeg/interfaces/web/templates/decision/observe/exp.html nutmeg/interfaces/web/templates/decision/observe/day.html nutmeg/interfaces/web/static/decision/observe.css nutmeg/interfaces/web/static/decision/observe.js nutmeg/interfaces/web/templates/decision/workbench.html tests/test_decision_web_observe.py && git commit -m "feat(observe): 全景/一生/一天三页，ECharts 5.5.1 固定版本，零写操作"`

---

### Task 4: RUNBOOK 与状态页入口

- [ ] RUNBOOK「每日先看一眼：状态页」加一行：`http://127.0.0.1:8787/observe`——RSI 全景（只读）；`/observe/day/<date>` 看当天候选树与资金方案
- [ ] Commit `git add docs/sop/RUNBOOK.md && git commit -m "docs(runbook): 观察台入口"`

## Self-review
spec §2 三页 → Task 2/3；§3 视觉（ECharts 固定版、状态色、暗色、移动端、60s 轮询）→ Task 3；§4 三个 API → Task 2；§5 降级（每块独立 `_safe`、缺 tiers/plan/tree 文案）→ Task 1/2/3 测试；§6 测试逐条有；§7 出口 → Task 3 Step 4 截图。类型：`experiment_card(row, falsifier)`、`candidate_dag(events)`、`day_view(events=, plan=)` 在 Task 1 定义、Task 2 调用一致；`observe_repo` 接口四方法在测试替身与 `decision.py` 适配里一致。
