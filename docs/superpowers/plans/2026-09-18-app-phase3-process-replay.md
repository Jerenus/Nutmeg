# App 化 · 阶段三：过程回放（讨论变成事件，事件变成回放）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 一期从备料到出票的全部过程——任务运行、判读入库、追问往来、被否掉的候选票面、人的裁决——都能在 `/replay?date=` 按时间顺序重放，并能导出成一份 Markdown 复盘底稿。

**Architecture:** 不新造存储：阶段一/二已经把任务与对话写进 `workbench.jsonl`；本阶段补两种**人写**的事件（`note` 手记、`candidate` 被考虑过的票面）和一个只读回放视图 + 导出命令。前提是阶段一、二已合入（`task_*` / `agent_reply` 事件存在）。

**Tech Stack:** FastAPI + Jinja2 / 原生 JS / typer / pytest。

**出生事故（写进代码注释）：** 2026-09-18 的 26129，SFC-B→C→D→E 四轮票面迭代、「平局是不是太少」的曲线、「全是 3」的分散代价表，全部只存在于聊天窗口，仓库里只剩终版文件——第二天在 app 里什么都看不到。

---

## 文件结构

- Modify `nutmeg/decision/workbench.py` — `append_note`、`append_candidate`
- Modify `nutmeg/interfaces/decision_web.py` — `POST /action/note`、`POST /action/candidate`、`GET /replay`、`GET /replay.md`
- Create `nutmeg/interfaces/web/templates/decision/replay.html`
- Modify `nutmeg/interfaces/web/static/decision/app.js` — 手记输入框 + `note/candidate` 事件卡
- Create `nutmeg/decision/workbench_export.py` — 事件流 → Markdown
- Modify `nutmeg/interfaces/cli/decision.py` — `workbench-export`
- Tests: `tests/test_decision_web_kernel.py`、`tests/decision/test_workbench_export.py`

---

### Task 1: 两种人写事件

**Files:**
- Modify: `nutmeg/decision/workbench.py`
- Test: `tests/decision/test_workbench_export.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_workbench_export.py
from nutmeg.decision.workbench import append_candidate, append_note, read_events


def test_note_and_candidate_events_have_stable_shapes(tmp_path):
    d = "2026-09-19"
    append_note(tmp_path, d, obj_id="ticket:26129", text="SFC-B 否决：C2 ×3（旗面没盖住）")
    append_candidate(tmp_path, d, obj_id="ticket:26129", version="SFC-B",
                     faces={"1": "30", "2": "3"}, notes=128, stake_yuan=256,
                     p_all=0.0038, verdict="rejected", reason="三处 C2")
    n, c = read_events(tmp_path, d)
    assert n["kind"] == "note" and n["obj_id"] == "ticket:26129" and "C2" in n["text"]
    assert c["kind"] == "candidate" and c["payload"]["version"] == "SFC-B"
    assert c["payload"]["verdict"] == "rejected" and c["payload"]["stake_yuan"] == 256
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_workbench_export.py -v`
Expected: FAIL with `ImportError: cannot import name 'append_candidate'`

- [ ] **Step 3: Write minimal implementation**

```python
# 追加到 nutmeg/decision/workbench.py
from datetime import datetime as _dt


def append_note(output_dir, date: str, *, obj_id: str, text: str) -> int:
    """人写手记（裁决理由、否决原因、临场观察）——今天说过的话明天还在。"""
    return append_event(output_dir, date, {
        "kind": "note", "obj_id": obj_id, "text": text,
        "at": _dt.now().astimezone().isoformat(timespec="seconds")})


def append_candidate(output_dir, date: str, *, obj_id: str, version: str, faces: dict,
                     notes: int, stake_yuan: int, p_all: float | None,
                     verdict: str, reason: str = "") -> int:
    """被考虑过的票面（含被否掉的）。verdict ∈ {considered, rejected, chosen}。"""
    return append_event(output_dir, date, {
        "kind": "candidate", "obj_id": obj_id,
        "payload": {"version": version, "faces": faces, "notes": notes,
                    "stake_yuan": stake_yuan, "p_all": p_all,
                    "verdict": verdict, "reason": reason},
        "at": _dt.now().astimezone().isoformat(timespec="seconds")})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_workbench_export.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/workbench.py tests/decision/test_workbench_export.py
git commit -m "feat(workbench): note / candidate 两种人写事件"
```

---

### Task 2: 端点 + 页面手记框 + 事件卡

**Files:**
- Modify: `nutmeg/interfaces/decision_web.py`
- Modify: `nutmeg/interfaces/web/templates/decision/workbench.html`（`askbar` 之前）
- Modify: `nutmeg/interfaces/web/static/decision/app.js`
- Test: `tests/test_decision_web_kernel.py`

- [ ] **Step 1: Write the failing test**

```python
# 追加到 tests/test_decision_web_kernel.py
def test_note_and_candidate_endpoints_append_events(tmp_path):
    store = DecisionStore(tmp_path / "decision")
    client = TestClient(create_decision_app(store=store, output_dir=tmp_path))
    d = "2026-09-19"
    r = client.post("/action/note", json={"date": d, "obj_id": "ticket:26129", "text": "SFC-B 否决"})
    assert r.status_code == 200 and r.json()["ok"] is True
    r = client.post("/action/candidate", json={"date": d, "obj_id": "ticket:26129",
        "version": "SFC-B", "faces": {"1": "30"}, "notes": 128, "stake_yuan": 256,
        "p_all": 0.0038, "verdict": "rejected", "reason": "三处 C2"})
    assert r.status_code == 200
    kinds = [e["kind"] for e in client.get(f"/events?date={d}&since=0").json()["events"]]
    assert kinds == ["note", "candidate"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_decision_web_kernel.py -v -k note_and_candidate`
Expected: FAIL（404）

- [ ] **Step 3: Write minimal implementation**

`decision_web.py`（`/thread` 之后）：

```python
    @app.post("/action/note")
    def note_post(payload: dict = Body(...)) -> Any:  # noqa: B008
        from nutmeg.decision.workbench import append_note
        seq = append_note(output_dir, str(payload["date"]),
                          obj_id=str(payload.get("obj_id") or "day"),
                          text=str(payload.get("text") or ""))
        return {"ok": True, "seq": seq}

    @app.post("/action/candidate")
    def candidate_post(payload: dict = Body(...)) -> Any:  # noqa: B008
        from nutmeg.decision.workbench import append_candidate
        seq = append_candidate(output_dir, str(payload["date"]),
                               obj_id=str(payload.get("obj_id") or "ticket"),
                               version=str(payload.get("version") or ""),
                               faces=dict(payload.get("faces") or {}),
                               notes=int(payload.get("notes") or 0),
                               stake_yuan=int(payload.get("stake_yuan") or 0),
                               p_all=payload.get("p_all"),
                               verdict=str(payload.get("verdict") or "considered"),
                               reason=str(payload.get("reason") or ""))
        return {"ok": True, "seq": seq}
```

`workbench.html` 在 `<div class="askbar">` 之前加：

```html
  <div class="notebar">
    <input class="field" id="note" placeholder="手记：裁决理由 / 否决原因 / 临场观察…" autocomplete="off">
    <button class="send" id="note-send">记</button>
  </div>
```

`app.js`：

```javascript
      case "note": if (e.obj_id === selectedObj || e.obj_id === "day") appendTurn({kind:"note", text:"📝 " + e.text}); break;
      case "candidate": renderCandidate(e); break;
```

```javascript
  var noteEl = document.getElementById("note"), noteSend = document.getElementById("note-send");
  function sendNote() {
    var text = (noteEl.value || "").trim(); if (!text) return;
    noteEl.value = "";
    post("/action/note", { date: DATE, obj_id: selectedObj || "day", text: text });
  }
  if (noteSend) noteSend.addEventListener("click", sendNote);
  if (noteEl) noteEl.addEventListener("keydown", function (ev) { if (ev.key === "Enter") { ev.preventDefault(); sendNote(); } });

  function renderCandidate(e) {
    var p = e.payload || {};
    if (verdictEl.querySelector('[data-card="cand-' + e.seq + '"]')) return;
    var card = el("article", "acard slip cand " + (p.verdict || ""));
    card.setAttribute("data-card", "cand-" + e.seq);
    var inner = el("div", "inner");
    inner.appendChild(el("div", "actype", "候选 " + (p.version || "") + " · " +
      ({rejected:"已否决", chosen:"已选", considered:"考虑过"}[p.verdict] || p.verdict)));
    inner.appendChild(el("div", "acmarket", (p.notes || 0) + " 注 ¥" + (p.stake_yuan || 0) +
      (p.p_all != null ? " · P " + (p.p_all * 100).toFixed(2) + "%" : "")));
    if (p.reason) inner.appendChild(el("div", "profile-line", p.reason));
    card.appendChild(inner); verdictEl.appendChild(card);
  }
```

`appendTurn` 里 `who` 的判断改为：`var who = e.kind === "user_message" ? "你" : e.kind === "note" ? "记" : "判";`（原代码用 `you` 布尔，改成三态）。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_decision_web_kernel.py tests/test_decision_web.py -v`
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add nutmeg/interfaces/decision_web.py nutmeg/interfaces/web/templates/decision/workbench.html nutmeg/interfaces/web/static/decision/app.js tests/test_decision_web_kernel.py
git commit -m "feat(web): 手记与候选票面进事件流（讨论不再只活在聊天窗口）"
```

---

### Task 3: 回放视图 `/replay?date=`

**Files:**
- Create: `nutmeg/interfaces/web/templates/decision/replay.html`
- Modify: `nutmeg/interfaces/decision_web.py`
- Test: `tests/test_decision_web_kernel.py`

- [ ] **Step 1: Write the failing test**

```python
# 追加到 tests/test_decision_web_kernel.py
def test_replay_page_orders_all_event_kinds_by_seq(tmp_path):
    from nutmeg.decision.workbench import append_event
    d = "2026-09-19"
    for ev in [
        {"kind": "task_started", "obj_id": "task:B0_prep_morning", "label": "B0 早刷新", "argv": ["zucai-prep"]},
        {"kind": "task_done", "obj_id": "task:B0_prep_morning", "label": "B0 早刷新", "exit_code": 0, "text": "备料完成"},
        {"kind": "user_message", "obj_id": "fr-8", "text": "朗斯不败？"},
        {"kind": "agent_reply", "obj_id": "fr-8", "text": "平局最被支持。"},
        {"kind": "candidate", "obj_id": "ticket:26129", "payload": {"version": "SFC-B", "verdict": "rejected", "reason": "三处 C2", "notes": 128, "stake_yuan": 256, "p_all": 0.0038, "faces": {}}},
        {"kind": "note", "obj_id": "day", "text": "刹车：¥1000 帽用户裁定"},
    ]:
        append_event(tmp_path, d, ev)
    store = DecisionStore(tmp_path / "decision")
    html = TestClient(create_decision_app(store=store, output_dir=tmp_path)).get(f"/replay?date={d}").text
    assert html.index("B0 早刷新") < html.index("朗斯不败？") < html.index("SFC-B") < html.index("刹车")
    assert "已否决" in html and "exit=0" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_decision_web_kernel.py -v -k replay_page`
Expected: FAIL（404）

- [ ] **Step 3: Write minimal implementation**

`decision_web.py`：

```python
    @app.get("/replay")
    def replay_page(request: Request, date: str):
        from nutmeg.decision.workbench import read_events
        return templates.TemplateResponse(
            request, "decision/replay.html",
            {"title": f"回放 {date}", "date": date, "events": read_events(output_dir, date)})
```

`replay.html`：

```html
{% extends "decision/layout.html" %}
{% block body %}
<div class="topbar"><div class="brand"><span class="mk">▸</span> 过程回放 · {{ date }}</div>
  <div class="spacer"></div><a class="btn" href="/replay.md?date={{ date }}">导出 Markdown</a></div>
<div class="replay">
{% for e in events %}
  <div class="rp {{ e.kind }}">
    <span class="mono seq">#{{ e.seq }}</span>
    <span class="mono at">{{ (e.at or '')[:16] }}</span>
    {% if e.kind == "task_started" %}<b>▶ {{ e.label }}</b> <code>$ nutmeg {{ e.argv | join(" ") }}</code>
    {% elif e.kind in ("task_done", "task_failed") %}<b>{{ "✓" if e.kind == "task_done" else "✗" }} {{ e.label }} exit={{ e.exit_code }}</b><pre class="tasklog">{{ e.text }}</pre>
    {% elif e.kind == "user_message" %}<b>你 · {{ e.obj_id }}</b> {{ e.text }}
    {% elif e.kind == "agent_reply" %}<b>判 · {{ e.obj_id }}</b> {{ e.text }}
    {% elif e.kind == "note" %}<b>📝 手记 · {{ e.obj_id }}</b> {{ e.text }}
    {% elif e.kind == "candidate" %}<b>候选 {{ e.payload.version }} · {{ {"rejected": "已否决", "chosen": "已选", "considered": "考虑过"}.get(e.payload.verdict, e.payload.verdict) }}</b>
      {{ e.payload.notes }} 注 ¥{{ e.payload.stake_yuan }}{% if e.payload.p_all is not none %} · P {{ "%.2f" | format(e.payload.p_all * 100) }}%{% endif %} — {{ e.payload.reason }}
    {% elif e.kind == "slip" %}<b>🎫 实票 {{ e.payload.slip_id }}</b> {{ e.payload.notes }} 注 ¥{{ e.payload.stake_yuan }}
    {% elif e.kind == "judgment" %}<b>判读入库 · {{ e.payload.match }}</b>
    {% else %}<b>{{ e.kind }}</b> {{ e.get("text", "") }}{% endif %}
  </div>
{% else %}<p class="empty">这一天没有事件。</p>{% endfor %}
</div>
{% endblock %}
```

`app.css` 追加：

```css
.replay{padding:12px 18px;max-width:960px}
.rp{display:grid;grid-template-columns:52px 110px 1fr;gap:8px;padding:6px 0;border-bottom:1px solid var(--line);font-size:13px}
.rp .seq,.rp .at{color:var(--sub)}
.rp.user_message b{color:var(--pine)} .rp.task_failed b{color:var(--cinnabar)} .rp.candidate b{color:var(--sub)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_decision_web_kernel.py -v -k replay_page`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nutmeg/interfaces/decision_web.py nutmeg/interfaces/web/templates/decision/replay.html nutmeg/interfaces/web/static/decision/app.css tests/test_decision_web_kernel.py
git commit -m "feat(web): /replay 过程回放视图"
```

---

### Task 4: Markdown 导出（`/replay.md` + CLI）

**Files:**
- Create: `nutmeg/decision/workbench_export.py`
- Modify: `nutmeg/interfaces/decision_web.py`、`nutmeg/interfaces/cli/decision.py`
- Test: `tests/decision/test_workbench_export.py`

- [ ] **Step 1: Write the failing test**

```python
# 追加到 tests/decision/test_workbench_export.py
from nutmeg.decision.workbench import append_event
from nutmeg.decision.workbench_export import events_to_markdown


def test_markdown_export_is_a_retro_skeleton(tmp_path):
    d = "2026-09-19"
    append_event(tmp_path, d, {"kind": "task_done", "obj_id": "task:B6_audit", "label": "B6 审计门", "exit_code": 1, "text": "1 个 ERROR"})
    append_event(tmp_path, d, {"kind": "user_message", "obj_id": "fr-8", "text": "朗斯不败？"})
    append_event(tmp_path, d, {"kind": "agent_reply", "obj_id": "fr-8", "text": "平局最被支持。"})
    append_candidate(tmp_path, d, obj_id="ticket:26129", version="SFC-D", faces={}, notes=192,
                     stake_yuan=384, p_all=0.00321, verdict="chosen", reason="裸单全 ≥50%")
    md = events_to_markdown(tmp_path, d)
    assert md.startswith("# 2026-09-19 过程回放")
    assert "## 任务" in md and "B6 审计门 · exit=1" in md
    assert "## 追问" in md and "**你**（fr-8）：朗斯不败？" in md and "**判**：平局最被支持。" in md
    assert "## 候选票面" in md and "SFC-D · 已选 · 192 注 ¥384 · P 0.32%" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_workbench_export.py -v -k markdown`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/workbench_export.py
"""事件流 → Markdown 复盘底稿。只排版，不总结（总结是判断，归主循环）。"""
from __future__ import annotations

from nutmeg.decision.workbench import read_events

_VERDICT_ZH = {"rejected": "已否决", "chosen": "已选", "considered": "考虑过"}


def events_to_markdown(output_dir, date: str) -> str:
    evs = read_events(output_dir, date)
    tasks, thread, cands, notes, slips = [], [], [], [], []
    for e in evs:
        k = e.get("kind")
        if k in ("task_done", "task_failed"):
            tasks.append(f"- {'✓' if k == 'task_done' else '✗'} {e.get('label')} · exit={e.get('exit_code')}")
        elif k == "user_message":
            thread.append(f"- **你**（{e.get('obj_id')}）：{e.get('text')}")
        elif k == "agent_reply":
            thread.append(f"  - **判**：{e.get('text')}")
        elif k == "candidate":
            p = e.get("payload") or {}
            pa = p.get("p_all")
            cands.append(f"- {p.get('version')} · {_VERDICT_ZH.get(p.get('verdict'), p.get('verdict'))}"
                         f" · {p.get('notes')} 注 ¥{p.get('stake_yuan')}"
                         + (f" · P {pa * 100:.2f}%" if pa is not None else "")
                         + (f" — {p.get('reason')}" if p.get("reason") else ""))
        elif k == "note":
            notes.append(f"- {e.get('text')}")
        elif k == "slip":
            p = e.get("payload") or {}
            slips.append(f"- {p.get('slip_id')} · {p.get('notes')} 注 ¥{p.get('stake_yuan')}")
    out = [f"# {date} 过程回放", ""]
    for title, rows in (("任务", tasks), ("追问", thread), ("候选票面", cands),
                        ("实票", slips), ("手记", notes)):
        out += [f"## {title}", *(rows or ["（无）"]), ""]
    return "\n".join(out)
```

`decision_web.py`：

```python
    @app.get("/replay.md")
    def replay_markdown(date: str):
        from fastapi.responses import PlainTextResponse

        from nutmeg.decision.workbench_export import events_to_markdown
        return PlainTextResponse(events_to_markdown(output_dir, date), media_type="text/markdown")
```

`cli/decision.py`：

```python
@_cli.app.command("workbench-export")
def workbench_export(
    date: str = _cli.typer.Option(..., "--date"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
    out: Path | None = _cli.typer.Option(None, "--out", help="不给则打印到 stdout"),
) -> None:
    """事件流 → Markdown 复盘底稿（只排版不总结）。"""
    from nutmeg.decision.workbench_export import events_to_markdown
    md = events_to_markdown(Path(output_dir), date)
    if out:
        Path(out).write_text(md, encoding="utf-8"); _cli.typer.echo(f"→ {out}")
    else:
        _cli.typer.echo(md)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_workbench_export.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/workbench_export.py nutmeg/interfaces/decision_web.py nutmeg/interfaces/cli/decision.py tests/decision/test_workbench_export.py
git commit -m "feat: 过程回放导出 Markdown（/replay.md + workbench-export）"
```

---

### Task 5: 让主循环也往流里写（RUNBOOK 纪律）

**Files:**
- Modify: `docs/sop/RUNBOOK.md`（B5 行末）

- [ ] **Step 1: 加一句**

在 B5「首版构票」那一行末尾追加：

```markdown
**每一版被考虑过的票面（含否决的）用 `POST /action/candidate` 或 `append_candidate()` 进事件流，否决理由进 `note`——出生事故 26129：SFC-B/C/D/E 四轮只剩终版文件，第二天在 app 里什么都看不到。**
```

- [ ] **Step 2: Commit**

```bash
git add docs/sop/RUNBOOK.md
git commit -m "docs(runbook): 候选票面与否决理由必须进事件流"
```

---

## Self-review

- 覆盖：人写事件 ✓ 端点+UI ✓ 回放页 ✓ 导出 ✓ 纪律入册 ✓。依赖：`task_*` 来自阶段一，`agent_reply` 来自阶段二（无阶段二时回放仍可用，只是「判」一栏由人肉回复填）。
- 类型一致：`append_candidate(output_dir, date, *, obj_id, version, faces, notes, stake_yuan, p_all, verdict, reason)` 在 Task 1/2/4 一致；`events_to_markdown(output_dir, date)`。
- 无占位。
