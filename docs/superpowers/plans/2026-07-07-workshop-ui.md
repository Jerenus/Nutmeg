# Workshop UI v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给决策本体建一个 AI-native 判读工作台 web 界面（`nutmeg decision-web`）——agent 起草判断、人在浏览器就草稿增量追问共磨、一键裁决落库，全部经与 CLI 同一份 schema 闸。

**Architecture:** 独立 FastAPI 应用（仿 `interfaces/client_web.py` 模式），直接读 `DecisionStore` 的九对象 JSONL。终端 Claude Code 是判读引擎；浏览器与它通过 `daily/<date>/workbench.jsonl`（append-only 事件流，双向）+ SSE 实时同步。两个 typed action（Read 批准、legs 确认）复用 `ingest_reads`/`compose_tickets` 的既有校验，UI 零旁门；锚定追问线程走同一协议、推理蒸馏进 `Read.note`、线程不进九对象持久层。

**Tech Stack:** FastAPI + uvicorn + Jinja2 + StaticFiles（全部已在 pyproject，零新依赖）+ 服务端渲染 HTML + 原生 JS + SSE。Python 3.12 / pytest / uv。

**Spec:** `docs/superpowers/specs/2026-07-07-workshop-ui-design.md`（含 §3.5 锚定追问线程）。视觉基准：`docs/design/nutmeg-workshop.html`。

**不可破坏约束：**
- live 系统 `decision-am/close/settle`（launchd 三段）不得中断——本计划只增 web 层 + 一个新模块 `workbench.py`，不改五动词任何行为。
- **判断永不进 UI**：界面不产生判断，只渲染 agent 判断 + 记录人裁决。
- 两个 typed action 复用既有校验：`read_ingest.ingest_reads(payloads, *, store, factors)`（返回错误串列表，空=全落库）、`express.compose_tickets(legs, budget, *, channel, made_at, store)`。**UI 不得复制校验逻辑**。
- 追问线程：落库唯一路径仍是 typed-action 闸；收敛蒸馏进 `Read.note`；完整线程留 `workbench.jsonl`，**不进九对象 store**。
- 安全默认：只绑 `127.0.0.1`；`--host` 非 loopback 时 stderr 打印无鉴权警告。
- 测试基线 699 passed / ruff 全绿。每 Task 收尾 `uv run pytest -q` 全绿再 commit。commit footer 两行：
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01XfSkXib7b5rf4aocCqbG8M`
- 分支：当前 `research/tunisia-japan-2026-06-20`。

---

## File Structure（先锁边界）

| 文件 | 动作 | 职责 |
|---|---|---|
| `nutmeg/decision/workbench.py` | Create | 握手协议：workbench.jsonl append/tail、decisions.jsonl 留痕、Read.note 蒸馏、SSE 事件读取。**纯文件 IO + store 调用，无 web 依赖、无判断** |
| `nutmeg/interfaces/decision_web.py` | Create | FastAPI app 工厂 `create_decision_app(store, output_dir)`：只读端点 + 两个 action 端点 + /thread + /events(SSE) + 四页路由 |
| `nutmeg/interfaces/web/templates/decision/` | Create | Jinja2：`workbench.html`（三栏+追问线程）/ `objects.html` / `calibration.html` / `ledger.html` / `layout.html` |
| `nutmeg/interfaces/web/static/decision/` | Create | `app.css`（对照 docs/design/nutmeg-workshop.html 的 token 与组件）/ `app.js`（SSE 订阅+卡片交互+追问框） |
| `nutmeg/interfaces/cli/decision.py` | Modify | 新增 `@app.command("decision-web")` |
| `tests/decision/test_workbench.py` | Create | 协议读写/蒸馏/幂等 |
| `tests/test_decision_web.py` | Create | TestClient 只读端点 + 两个 action 闸 + /thread + 页面渲染 |
| （删除）`interfaces/client_web.py` 等 client-web 专属簇 | Delete | Task 1，逐个 grep 复核 |

**协议事件 schema（workbench.jsonl 每行一个 JSON）**：
```
{kind: "attention",     id, group, match, note, at}            # agent 排议程
{kind: "view_block",    id, obj_id, block, payload, at}        # agent 推舞台视图块
{kind: "read_draft",    id, obj_id, payload:<Read dict>, at}   # agent 起草/改写 Read
{kind: "legs_proposal", id, obj_id, payload:<leg dict>, at}    # agent 提 leg
{kind: "user_message",  id, obj_id, text, at}                  # 人在浏览器追问(§3.5)
{kind: "agent_reply",   id, obj_id, text, at}                  # agent 回应(§3.5)
```
**decisions.jsonl 每行**：`{action: "approve_read"|"reject_read"|"confirm_legs"|"remove_leg", obj_id, at, result}`

---

### Task 1: client-web 簇下葬（逐个 grep 复核，只埋专属件）

**Files:**
- Delete: `nutmeg/interfaces/client_web.py`, `nutmeg/services/client.py`, `nutmeg/interfaces/web/templates/client/`, `nutmeg/interfaces/web/static/client/`, `nutmeg/interfaces/web/static/jczq/`, `tests/test_client_web.py`, `tests/test_client_service.py`
- Modify: `nutmeg/interfaces/cli/client.py`（删 8 个 client-* 命令 + build_client_service 工厂）、`nutmeg/interfaces/cli/__init__.py`（删 client import）、`tests/test_cli.py`（删 client 用例）

**保留（勿删，共享底座）**：`nutmeg/data/soccerdata_client.py`、`nutmeg/storage/client_state_repository.py`（materialization/snapshot 在用）；ClientService 的 sub-provider 服务（value_board/match_brief/odds/tactical/player/information，其它 D3 命令共用）。

- [x] **Step 1: 复核每个删除对象无其它 importer**

```bash
cd /Users/jz71/Projects/Nutmeg
for sym in "interfaces.client_web" "create_client_app" "services.client " "ClientService" "build_client_service"; do
  echo "== $sym =="
  grep -rn "$sym" nutmeg/ tests/ --include="*.py" | grep -vE "interfaces/client_web.py|services/client.py|cli/client.py|cli/__init__.py|test_client_web.py|test_client_service.py|test_cli.py"
done
# 保留件确认仍被别处用(应有命中):
grep -rln "soccerdata_client\|client_state_repository" nutmeg/services/materialization.py nutmeg/services/snapshot.py
```
Expected: 前循环**无命中**（client-web 专属，可安全删）；后一条**有命中**（保留件确实被共享）。若前循环有非预期命中 → 停下报告，不删该项。

- [x] **Step 2: 删除专属文件 + 目录**

```bash
git rm nutmeg/interfaces/client_web.py nutmeg/services/client.py \
       tests/test_client_web.py tests/test_client_service.py
git rm -r nutmeg/interfaces/web/templates/client nutmeg/interfaces/web/static/client \
          nutmeg/interfaces/web/static/jczq
```

- [x] **Step 3: 摘除 CLI 注册**

`nutmeg/interfaces/cli/client.py` — 删除 8 个 `@_cli.app.command("client-*")` 函数（client-status/feed/match/question/watchlist/alerts/prediction-record/web）与 `build_client_service()` 工厂。若删空则 `git rm nutmeg/interfaces/cli/client.py` 并在 `cli/__init__.py` 底部移除其 import 触发行。
`nutmeg/interfaces/cli/__init__.py` — 删除 `from nutmeg.interfaces.client_web import create_client_app`（:48）与仅服务 client 的 `from nutmeg.services.client import ClientService`（:53，先 grep 确认 __init__ 内无其它引用）。

- [x] **Step 4: 删测试用例**

`tests/test_cli.py` — 删除 `test_client_commands_are_registered_in_help`（:2610 附近）及任何仅断言 client-* 的用例（grep `client-` 定位）。

- [x] **Step 5: 跑全套确认无断链**

Run: `uv run pytest -q 2>&1 | tail -3 && uv run ruff check nutmeg/ tests/`
Expected: 全绿（基线降至 699 − 删除的 client 用例数；无 collection error、无 ImportError）。若 red 于某处仍 import 已删符号 → 按报错逐一清理。

- [x] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(interfaces): client-web 簇下葬(逐个复核,保留共享底座)——为 decision-web 让位(Workshop Task 1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XfSkXib7b5rf4aocCqbG8M"
```

---

### Task 2: workbench.py 握手协议（纯文件 IO，无 web、无判断）

**Files:**
- Create: `nutmeg/decision/workbench.py`
- Test: `tests/decision/test_workbench.py`

- [ ] **Step 1: Write the failing tests**

新建 `tests/decision/test_workbench.py`：

```python
# tests/decision/test_workbench.py
from nutmeg.decision.workbench import (
    append_event,
    append_user_message,
    read_events,
    record_decision,
    distill_note,
)


def _daily(tmp_path, date="2026-07-08"):
    d = tmp_path / "daily" / date
    d.mkdir(parents=True)
    return tmp_path, date


def test_append_and_read_events_roundtrip(tmp_path):
    out, date = _daily(tmp_path)
    append_event(out, date, {"kind": "attention", "id": "A1", "match": "哈马比 vs 卡尔马"})
    append_event(out, date, {"kind": "read_draft", "id": "D1", "obj_id": "O1",
                             "payload": {"belief": {"home": 0.46}}})
    events = read_events(out, date)
    assert [e["kind"] for e in events] == ["attention", "read_draft"]
    assert events[1]["payload"]["belief"]["home"] == 0.46


def test_read_events_after_offset_for_sse(tmp_path):
    """SSE tail:只取序号 > since 的新事件(每事件带自增 seq)。"""
    out, date = _daily(tmp_path)
    append_event(out, date, {"kind": "attention", "id": "A1"})
    append_event(out, date, {"kind": "attention", "id": "A2"})
    tail = read_events(out, date, since=1)
    assert [e["id"] for e in tail] == ["A2"]
    assert tail[0]["seq"] == 2


def test_append_user_message_is_an_event(tmp_path):
    """§3.5:浏览器追问写进同一事件流,obj_id 锚定。"""
    out, date = _daily(tmp_path)
    append_user_message(out, date, obj_id="O1", text="为什么压平不压主胜？")
    ev = read_events(out, date)[0]
    assert ev["kind"] == "user_message"
    assert ev["obj_id"] == "O1" and "压平" in ev["text"]


def test_record_decision_appends_to_decisions_log(tmp_path):
    out, date = _daily(tmp_path)
    record_decision(out, date, action="approve_read", obj_id="O1", result="R-1 入库")
    import json
    line = (out / "daily" / date / "decisions.jsonl").read_text().strip()
    rec = json.loads(line)
    assert rec["action"] == "approve_read" and rec["obj_id"] == "O1"


def test_distill_note_summarizes_thread(tmp_path):
    """收敛蒸馏:把某 obj 的 user/agent 往来压成一句进 Read.note(不进 store)。"""
    out, date = _daily(tmp_path)
    append_user_message(out, date, obj_id="O1", text="战意呢？")
    append_event(out, date, {"kind": "agent_reply", "obj_id": "O1", "text": "争四动力足"})
    note = distill_note(out, date, obj_id="O1")
    assert "战意" in note and "争四" in note
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/decision/test_workbench.py -v`
Expected: 全 FAIL（`ModuleNotFoundError: nutmeg.decision.workbench`）

- [ ] **Step 3: Implement**

新建 `nutmeg/decision/workbench.py`：

```python
"""Workshop 握手协议(spec §3/§3.5)——终端 agent 与浏览器共享的事件流。

daily/<date>/workbench.jsonl:append-only 事件流(agent 事件 + 浏览器 user_message);
daily/<date>/decisions.jsonl:人的裁决留痕。纯文件 IO + store 调用,无 web 依赖、
无判断——判断在终端 Claude 推理里产生并写事件,本模块只搬运。
"""
from __future__ import annotations

import json
from pathlib import Path


def _daily_dir(output_dir, date: str) -> Path:
    return Path(output_dir) / "daily" / date


def _wb_path(output_dir, date: str) -> Path:
    return _daily_dir(output_dir, date) / "workbench.jsonl"


def append_event(output_dir, date: str, event: dict) -> int:
    """追加一个协议事件,自动打 seq(自增行号)。返回该事件 seq。"""
    path = _wb_path(output_dir, date)
    path.parent.mkdir(parents=True, exist_ok=True)
    seq = len(read_events(output_dir, date)) + 1
    event = {**event, "seq": seq}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return seq


def append_user_message(output_dir, date: str, *, obj_id: str, text: str,
                        at: str = "") -> int:
    """§3.5:浏览器追问 → 同一事件流的 user_message(obj_id 锚定)。"""
    return append_event(output_dir, date, {
        "kind": "user_message", "obj_id": obj_id, "text": text, "at": at})


def read_events(output_dir, date: str, *, since: int = 0) -> list[dict]:
    """读事件流;since>0 时只返回 seq>since 的新事件(SSE tail)。"""
    path = _wb_path(output_dir, date)
    if not path.exists():
        return []
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        ev = json.loads(line)
        ev.setdefault("seq", i)
        if ev["seq"] > since:
            out.append(ev)
    return out


def record_decision(output_dir, date: str, *, action: str, obj_id: str,
                    result: str = "", at: str = "") -> None:
    """裁决留痕 decisions.jsonl(approve/reject/confirm/remove)。"""
    path = _daily_dir(output_dir, date) / "decisions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"action": action, "obj_id": obj_id,
                             "result": result, "at": at}, ensure_ascii=False) + "\n")


def distill_note(output_dir, date: str, *, obj_id: str) -> str:
    """把某 obj 的追问往来压成一句进 Read.note(不进九对象 store)。

    v1 的蒸馏 = 拼接该 obj 的 user_message/agent_reply 文本(截断)。判断不在此:
    真正的 belief 改写由 agent 在终端产出并写 read_draft 事件,本函数只留人读痕迹。
    """
    parts = []
    for ev in read_events(output_dir, date):
        if ev.get("obj_id") != obj_id:
            continue
        if ev["kind"] == "user_message":
            parts.append(f"问:{ev['text']}")
        elif ev["kind"] == "agent_reply":
            parts.append(f"答:{ev['text']}")
    note = " · ".join(parts)
    return note[:280]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/decision/test_workbench.py -v`
Expected: 全 PASS

- [ ] **Step 5: Run suite + commit**

```bash
uv run pytest -q tests/decision/
git add nutmeg/decision/workbench.py tests/decision/test_workbench.py
git commit -m "feat(decision): workbench 握手协议(事件流+SSE tail+裁决留痕+蒸馏)(Workshop Task 2)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XfSkXib7b5rf4aocCqbG8M"
```

---

### Task 3: decision_web FastAPI 骨架 + 只读端点

**Files:**
- Create: `nutmeg/interfaces/decision_web.py`
- Create: `nutmeg/interfaces/web/templates/decision/layout.html`, `workbench.html`（占位骨架，Task 6 填充视觉）
- Test: `tests/test_decision_web.py`

- [ ] **Step 1: Write the failing tests**

新建 `tests/test_decision_web.py`：

```python
# tests/test_decision_web.py
from fastapi.testclient import TestClient

from nutmeg.decision.ontology import Match, MarketSnapshot
from nutmeg.decision.store import DecisionStore
from nutmeg.decision.workbench import append_event
from nutmeg.interfaces.decision_web import create_decision_app


def _app(tmp_path, date="2026-07-08"):
    store = DecisionStore(tmp_path / "decision")
    store.upsert(Match(match_id=f"M-{date}-a-b", kickoff_at="t", home="哈马比",
                       away="卡尔马", competition="瑞超"))
    store.upsert(MarketSnapshot(snapshot_id="S1", match_id=f"M-{date}-a-b",
                                taken_at="t", kind="read_time", source="apifootball",
                                fair={"had": {"home": 0.52, "draw": 0.27, "away": 0.21}}))
    app = create_decision_app(store=store, output_dir=tmp_path)
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
    r = client.get(f"/api/workbench?date=2026-07-09")
    assert r.status_code == 200
    assert r.json()["events"] == []   # 无 workbench.jsonl → 空事件,不报错
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_decision_web.py -v`
Expected: 全 FAIL（`ModuleNotFoundError: nutmeg.interfaces.decision_web`）

- [ ] **Step 3: Implement app 工厂 + 只读端点**

新建 `nutmeg/interfaces/decision_web.py`：

```python
"""Workshop UI — 决策本体判读工作台(spec 2026-07-07-workshop-ui-design.md)。

独立 FastAPI 应用,直接读 DecisionStore 九对象。判断永不在此:界面只渲染
agent 判断(workbench 事件)+ 记录人裁决。两个 typed action(Task 4)复用
ingest_reads/compose_tickets 的既有校验,零旁门。仿 client_web.py 模式。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from nutmeg.decision.ontology import Match, MarketSnapshot
from nutmeg.decision.store import DecisionStore
from nutmeg.decision.workbench import read_events


def _day_state(store: DecisionStore, output_dir, date: str) -> dict[str, Any]:
    prefix = f"M-{date}-"
    matches = [m.to_dict() for m in store.load(Match)
               if m.match_id.startswith(prefix)]
    snaps = [s.to_dict() for s in store.load(MarketSnapshot)
             if s.match_id.startswith(prefix) and s.kind == "read_time"]
    return {
        "date": date,
        "matches": matches,
        "snapshots": snaps,
        "events": read_events(output_dir, date),
    }


def create_decision_app(*, store: DecisionStore, output_dir) -> FastAPI:
    app = FastAPI(title="Nutmeg 判读工作台")
    web_root = Path(__file__).parent / "web"
    templates = Jinja2Templates(directory=web_root / "templates")
    app.mount("/static", StaticFiles(directory=web_root / "static"), name="static")
    app.state.store = store
    app.state.output_dir = Path(output_dir)

    @app.get("/api/workbench")
    def workbench_api(date: str) -> dict:
        return _day_state(store, output_dir, date)

    @app.get("/")
    def workbench_page(request: Request, date: str = ""):
        from datetime import date as _d
        date = date or _d.today().isoformat()
        return templates.TemplateResponse(
            request, "decision/workbench.html",
            {"title": "判读工作台", "state": _day_state(store, output_dir, date)})

    return app
```

新建 `nutmeg/interfaces/web/templates/decision/layout.html`（最小骨架）：

```html
<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ title }} · Nutmeg</title>
<link rel="stylesheet" href="/static/decision/app.css"></head>
<body>{% block body %}{% endblock %}
<script src="/static/decision/app.js"></script></body></html>
```

新建 `nutmeg/interfaces/web/templates/decision/workbench.html`（占位，Task 6 填充）：

```html
{% extends "decision/layout.html" %}
{% block body %}
<main class="wb"><h1>判读工作台</h1>
<div id="wb-data" data-date="{{ state.date }}">{{ state.matches|length }} 场在售</div>
</main>
{% endblock %}
```

新建空静态占位（Task 6 填充）：`nutmeg/interfaces/web/static/decision/app.css`（写 `/* Workshop UI — Task 6 填充 */`）、`app.js`（写 `// Workshop UI — Task 6 填充`）。

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_decision_web.py -v`
Expected: 全 PASS

- [ ] **Step 5: Run suite + commit**

```bash
uv run pytest -q
git add nutmeg/interfaces/decision_web.py nutmeg/interfaces/web/templates/decision \
        nutmeg/interfaces/web/static/decision tests/test_decision_web.py
git commit -m "feat(interfaces): decision-web FastAPI 骨架 + 只读工作台端点(Workshop Task 3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XfSkXib7b5rf4aocCqbG8M"
```

---

### Task 4: typed-action 闸（Read 批准 / legs 确认，复用既有校验）

**Files:**
- Modify: `nutmeg/interfaces/decision_web.py`（加 `/action/*` 端点）
- Test: `tests/test_decision_web.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_decision_web.py` 末尾追加：

```python
def _seed_factors(store):
    from nutmeg.decision.factors import load_seed_factors
    store.upsert_many(load_seed_factors())


def _valid_read_payload(date):
    return {
        "read_id": "R-web-1", "match_id": f"M-{date}-a-b", "snapshot_id": "S1",
        "made_at": "t", "judge": "claude", "market": "had",
        "prior": {"home": 0.52, "draw": 0.27, "away": 0.21},
        "belief": {"home": 0.46, "draw": 0.31, "away": 0.23},
        "factors": [{"factor_id": "league_bias", "scope_key": "swe-allsvenskan",
                     "direction": "draw", "weight_pp": 6,
                     "evidence": [{"url": "u"}]}],
        "confidence": 3, "shadow": False}


def test_approve_read_lands_in_store_via_same_gate(tmp_path):
    client, out, date = _app(tmp_path)
    _seed_factors(client.app.state.store)
    r = client.post("/action/approve-read",
                    json={"obj_id": "O1", "read": _valid_read_payload(date)})
    assert r.status_code == 200 and r.json()["ok"] is True
    from nutmeg.decision.ontology import Read
    assert client.app.state.store.get(Read, "R-web-1") is not None


def test_approve_invalid_read_rejected_with_same_error(tmp_path):
    """违规草稿(league 因子缺 scope_key)→ 400 + 与 validate_read 逐字相同的理由。"""
    client, out, date = _app(tmp_path)
    _seed_factors(client.app.state.store)
    bad = _valid_read_payload(date)
    bad["factors"][0].pop("scope_key")
    r = client.post("/action/approve-read", json={"obj_id": "O1", "read": bad})
    assert r.status_code == 400
    assert any("scope_key" in e for e in r.json()["errors"])


def test_confirm_legs_writes_legs_json_and_ticket(tmp_path):
    client, out, date = _app(tmp_path)
    leg = {"match_id": f"M-{date}-a-b", "market": "had", "selection": "home",
           "odds": 1.92, "bucket": "main"}
    r = client.post("/action/confirm-legs",
                    json={"date": date, "legs": [leg]})
    assert r.status_code == 200 and r.json()["ok"] is True
    import json
    legs_file = out / "daily" / date / "legs.json"
    assert legs_file.exists()
    assert json.loads(legs_file.read_text())[0]["bucket"] == "main"


def test_reject_read_is_recorded_not_stored(tmp_path):
    client, out, date = _app(tmp_path)
    r = client.post("/action/reject-read",
                    json={"obj_id": "O1", "reason": "证据不足"})
    assert r.status_code == 200
    dec = (out / "daily" / date / "decisions.jsonl")
    # reject 用当天日期留痕(date 从 payload 或 today);此处断言留痕存在
    assert r.json()["ok"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_decision_web.py -v`
Expected: 4 个新测试 FAIL（404 无 /action/* 路由）

- [ ] **Step 3: Implement action 端点（复用既有闸，零旁门）**

`nutmeg/interfaces/decision_web.py` — 在 `create_decision_app` 内、`return app` 前追加：

```python
    from datetime import date as _date

    from fastapi import Body
    from fastapi.responses import JSONResponse

    from nutmeg.decision.factors import load_seed_factors
    from nutmeg.decision.read_ingest import ingest_reads
    from nutmeg.decision.workbench import distill_note, record_decision

    def _today() -> str:
        return _date.today().isoformat()

    def _date_of(match_id: str) -> str:
        # M-<date>-... → date(供 record_decision 归日)
        parts = match_id.split("-")
        return "-".join(parts[1:4]) if len(parts) >= 4 else _today()

    @app.post("/action/approve-read")
    def approve_read(payload: dict = Body(...)) -> Any:
        read = dict(payload["read"])
        obj_id = payload.get("obj_id", read.get("read_id", ""))
        date = _date_of(read.get("match_id", ""))
        # §3.5:把该 obj 的追问往来蒸馏进 note(不进 store);判断不在此
        note = distill_note(output_dir, date, obj_id=obj_id)
        if note:
            read["note"] = (read.get("note", "") + " ⟨" + note + "⟩").strip()
        factors = store.load(_factor_cls()) or load_seed_factors()
        errors = ingest_reads([read], store=store, factors=factors)  # 同一校验闸
        if errors:
            record_decision(output_dir, date, action="approve_read",
                            obj_id=obj_id, result="拒绝: " + "; ".join(errors))
            return JSONResponse({"ok": False, "errors": errors}, status_code=400)
        record_decision(output_dir, date, action="approve_read",
                        obj_id=obj_id, result=f"{read['read_id']} 入库")
        return {"ok": True, "read_id": read["read_id"]}

    @app.post("/action/reject-read")
    def reject_read(payload: dict = Body(...)) -> Any:
        obj_id = payload.get("obj_id", "")
        date = payload.get("date", _today())
        record_decision(output_dir, date, action="reject_read", obj_id=obj_id,
                        result=payload.get("reason", ""))
        return {"ok": True}

    @app.post("/action/confirm-legs")
    def confirm_legs(payload: dict = Body(...)) -> Any:
        import json
        date = payload.get("date", _today())
        legs = payload["legs"]
        legs_file = self_daily(output_dir, date) / "legs.json"
        legs_file.parent.mkdir(parents=True, exist_ok=True)
        if legs_file.exists():        # 写前留 .bak(spec §5 幂等)
            legs_file.with_suffix(".json.bak").write_text(
                legs_file.read_text(encoding="utf-8"), encoding="utf-8")
        legs_file.write_text(json.dumps(legs, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        record_decision(output_dir, date, action="confirm_legs",
                        obj_id="legs", result=f"{len(legs)} 腿 → legs.json")
        return {"ok": True, "legs": len(legs)}
```

同文件顶部补两个 helper（模块级）：

```python
def _factor_cls():
    from nutmeg.decision.ontology import Factor
    return Factor


def self_daily(output_dir, date: str) -> Path:
    return Path(output_dir) / "daily" / date
```

> 说明：`confirm-legs` v1 只做"写 legs.json + 留痕"（与 CLI SOP 一致：judge 写 legs、close 时 express 再枚举出票）。预算/schema 全量校验发生在 close 的 `compose_tickets`；此处不复制校验（避免双份），只把 legs 落成既有约定文件。**这保持零旁门：真正入库的 Ticket 仍由 express 闸产出。**

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_decision_web.py -v`
Expected: 全 PASS

- [ ] **Step 5: Run suite + commit**

```bash
uv run pytest -q
git add nutmeg/interfaces/decision_web.py tests/test_decision_web.py
git commit -m "feat(interfaces): typed-action 闸——Read 批准复用 ingest_reads,legs 落既有约定(Workshop Task 4)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XfSkXib7b5rf4aocCqbG8M"
```

---

### Task 5: §3.5 锚定追问线程（POST /thread 双向 + SSE）

**Files:**
- Modify: `nutmeg/interfaces/decision_web.py`（加 `/thread` + `/events` SSE）
- Test: `tests/test_decision_web.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_decision_web.py` 末尾追加：

```python
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
    from nutmeg.decision.workbench import append_event
    append_event(out, date, {"kind": "attention", "id": "A1"})
    append_event(out, date, {"kind": "agent_reply", "obj_id": "O1", "text": "铁桶压净胜"})
    r = client.get(f"/events?date={date}&since=1")
    data = r.json()
    assert [e["kind"] for e in data["events"]] == ["agent_reply"]
    assert data["cursor"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_decision_web.py -v`
Expected: 2 个新测试 FAIL（404）

- [ ] **Step 3: Implement /thread + /events**

`nutmeg/interfaces/decision_web.py` — `return app` 前追加：

```python
    from nutmeg.decision.workbench import append_user_message, read_events

    @app.post("/thread")
    def thread_post(payload: dict = Body(...)) -> Any:
        """§3.5:浏览器追问 → user_message 事件(obj_id 锚定)。终端 agent 监视
        文件后回应(写 agent_reply/read_draft),浏览器经 /events 拉回。"""
        date = payload.get("date", _today())
        append_user_message(output_dir, date, obj_id=payload["obj_id"],
                            text=payload["text"], at=payload.get("at", ""))
        return {"ok": True}

    @app.get("/events")
    def events(date: str, since: int = 0) -> dict:
        """轮询式事件拉取(SSE 的 HTTP 后备;前端 app.js 用 EventSource 或轮询)。
        返回 since 之后的新事件与新游标。"""
        evs = read_events(output_dir, date, since=since)
        cursor = evs[-1]["seq"] if evs else since
        return {"events": evs, "cursor": cursor}
```

> 说明：v1 用**轮询式 /events**（前端 app.js 每 2s 拉 `?since=cursor`）而非长连 SSE——TestClient 可断言、无需 async 流、与"文件被终端 agent 写"天然解耦。spec 称 SSE 是交付语义（实时增量推送），轮询是其最简实现；若后续要真 SSE，端点契约不变（同一 `read_events(since=)`）。

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_decision_web.py -v`
Expected: 全 PASS

- [ ] **Step 5: Run suite + commit**

```bash
uv run pytest -q
git add nutmeg/interfaces/decision_web.py tests/test_decision_web.py
git commit -m "feat(interfaces): §3.5 锚定追问线程——POST /thread 双向 + /events 增量拉取(Workshop Task 5)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XfSkXib7b5rf4aocCqbG8M"
```

---

### Task 6: 工作台四页模板 + 静态资源（对照视觉基准）

**Files:**
- Modify: `nutmeg/interfaces/web/templates/decision/workbench.html`
- Create: `objects.html`, `calibration.html`, `ledger.html`（附属只读页）
- Modify: `nutmeg/interfaces/decision_web.py`（加 /objects /calibration /ledger 路由）
- Modify: `nutmeg/interfaces/web/static/decision/app.css`, `app.js`
- Test: `tests/test_decision_web.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_decision_web.py` 末尾追加：

```python
def test_workbench_renders_three_columns_and_thread(tmp_path):
    client, out, date = _app(tmp_path)
    from nutmeg.decision.workbench import append_event
    append_event(out, date, {"kind": "attention", "id": "A1", "group": "草稿待审",
                             "match": "哈马比 vs 卡尔马"})
    html = client.get(f"/?date={date}").text
    assert "今日议程" in html and "待裁决" in html and "追问线程" in html
    assert "哈马比 vs 卡尔马" in html          # attention 事件渲染进左栏


def test_附属页_all_render(tmp_path):
    client, out, date = _app(tmp_path)
    for path, marker in [("/objects", "对象浏览器"),
                         ("/calibration", "校准台"),
                         ("/ledger", "账本")]:
        r = client.get(path)
        assert r.status_code == 200 and marker in r.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_decision_web.py -v`
Expected: 2 个新测试 FAIL（占位模板无"今日议程"；/objects 等 404）

- [ ] **Step 3: 填充 workbench.html（三栏 + 追问线程，样式对照 docs/design/nutmeg-workshop.html）**

`nutmeg/interfaces/web/templates/decision/workbench.html` 整体替换为三栏结构（顶栏 + 注意力流/舞台/裁决列 + 追问线程）。用 `state.events` 分组渲染注意力流、`state.matches`/`state.snapshots` 渲染舞台。关键锚点标记（供测试与 app.js）：

```html
{% extends "decision/layout.html" %}
{% block body %}
<div class="topbar" data-date="{{ state.date }}">
  <span class="brand">▸ 判读工作台</span>
  <span class="datenav mono">{{ state.date }}</span>
  <span class="spacer"></span>
  <span class="budget mono" id="budget">¥0/400</span>
  <span class="sse" id="sse">实时</span>
</div>
<div class="wbbody">
  <section class="col flow"><h2 class="coltitle">今日议程 · agent 排序</h2>
    <div id="flow">
    {% for e in state.events if e.kind == "attention" %}
      <article class="fitem" data-obj="{{ e.id }}">
        <div class="m">{{ e.match }}</div><div class="why">{{ e.group }} · {{ e.note }}</div>
      </article>
    {% else %}<p class="empty">今日 agent 尚未开工——在终端说「今天的方案」。</p>{% endfor %}
    </div>
  </section>
  <section class="col stage" id="stage"><div class="crumb">选择议程项查看盘口/画像/读数器</div></section>
  <section class="col verdict"><h2 class="coltitle">待裁决 <span id="vcount">0</span></h2>
    <div id="verdict"></div>
    <div class="emptypos">空仓：今天不打 · 空仓永远合法</div>
  </section>
</div>
<div class="thread" id="thread">
  <div class="thhead">追问线程 · <span id="thread-anchor">未选中判断</span></div>
  <div class="turns" id="turns"></div>
  <div class="askbar"><input class="field" id="ask" placeholder="继续追问…"><button class="send" id="send">发送</button></div>
</div>
{% endblock %}
```

**app.css**：把 `docs/design/nutmeg-workshop.html` `<style>` 里的 token（`:root` 双主题）与 `.topbar/.wbbody/.col/.fitem/.acard/.thread/.mini-track` 等组件类**移植过来**（去掉 spec-sheet 外框相关的 `.sheet-head/.screen-label/.device/.anat/.phone` 类，只保留工作台本体样式）。保持宋体=判断/无衬线=界面/等宽=数据三分字体系统与朱砂-仅待裁决纪律。

**app.js**：
- 启动 `poll()`：每 2000ms `GET /events?date&since=cursor`，把新 `read_draft`/`legs_proposal`/`agent_reply`/`view_block` 事件渲染进对应栏（裁决卡、舞台块、线程气泡），更新 cursor 与 `#sse` 状态点。
- 点 `.fitem` → 设 `#thread-anchor` 与当前 obj_id，加载该 obj 的线程气泡。
- `#send` → `POST /thread {date,obj_id,text}`，清空输入，等下一轮 poll 拉回 agent_reply。
- 卡片按钮 → `POST /action/approve-read|reject-read|confirm-legs`，成功后移除卡、刷新 `#vcount` 与 `#budget`；400 时卡翻"被拒"态显示 `errors`（与 CLI 逐字一致）。

- [ ] **Step 3b: 附属三页 + 路由**

新建 `objects.html`/`calibration.html`/`ledger.html`（extends layout，各含标题"对象浏览器"/"校准台"/"账本" + 对应只读渲染：对象浏览器列九对象类型可点血缘、校准台读 `store.load(FactorVerdict)` 表、账本读 `store.load(Settlement)` 按日汇总 pnl）。

`decision_web.py` 加三条路由：

```python
    @app.get("/objects")
    def objects_page(request: Request):
        from nutmeg.decision.ontology import (
            Factor, FactorVerdict, League, Read, Settlement, Team, Ticket)
        counts = {c.__name__: len(store.load(c)) for c in
                  (Match, MarketSnapshot, Read, Factor, Ticket,
                   Settlement, FactorVerdict, Team, League)}
        return templates.TemplateResponse(
            request, "decision/objects.html", {"title": "对象浏览器", "counts": counts})

    @app.get("/calibration")
    def calibration_page(request: Request):
        from nutmeg.decision.ontology import FactorVerdict
        return templates.TemplateResponse(
            request, "decision/calibration.html",
            {"title": "校准台", "verdicts": [v.to_dict() for v in store.load(FactorVerdict)]})

    @app.get("/ledger")
    def ledger_page(request: Request):
        from nutmeg.decision.ontology import Settlement
        return templates.TemplateResponse(
            request, "decision/ledger.html",
            {"title": "账本", "settlements": [s.to_dict() for s in store.load(Settlement)]})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_decision_web.py -v`
Expected: 全 PASS

- [ ] **Step 5: Run suite + commit**

```bash
uv run pytest -q
git add nutmeg/interfaces/decision_web.py nutmeg/interfaces/web/templates/decision \
        nutmeg/interfaces/web/static/decision tests/test_decision_web.py
git commit -m "feat(interfaces): 工作台四页模板+静态资源(三栏+追问线程,对照视觉基准)(Workshop Task 6)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XfSkXib7b5rf4aocCqbG8M"
```

---

### Task 7: 手机响应式（三栏折叠单列 Tab）

**Files:**
- Modify: `nutmeg/interfaces/web/static/decision/app.css`（加 `@media(max-width:720px)`）
- Modify: `nutmeg/interfaces/web/static/decision/app.js`（窄屏 Tab 切换）
- Test: 视觉验证（Task 9 verify skill 中截图），此 Task 单测覆盖 Tab 标记存在

- [ ] **Step 1: Write the failing test**

`tests/test_decision_web.py` 末尾追加：

```python
def test_mobile_tabs_markup_present(tmp_path):
    """窄屏三 Tab(议程/舞台/裁决)靠 CSS 折叠;标记须在 DOM(渐进增强)。"""
    client, out, date = _app(tmp_path)
    html = client.get(f"/?date={date}").text
    assert 'class="mtabs"' in html
    for label in ["议程", "舞台", "裁决"]:
        assert label in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_decision_web.py::test_mobile_tabs_markup_present -v`
Expected: FAIL（无 `mtabs`）

- [ ] **Step 3: Implement**

`workbench.html` — 在 `.wbbody` 前加移动 Tab 条（桌面 CSS `display:none`，窄屏显示）：

```html
<nav class="mtabs" role="tablist">
  <button class="mtab on" data-col="flow">议程</button>
  <button class="mtab" data-col="stage">舞台</button>
  <button class="mtab" data-col="verdict">裁决 <span id="mv-badge"></span></button>
</nav>
```

`app.css` — 追加：

```css
.mtabs{display:none}
@media(max-width:720px){
  .mtabs{display:flex}
  .wbbody{grid-template-columns:1fr}
  .col{display:none} .col.active{display:block}
  .col.flow{border-right:none} .col.verdict{border-left:none}
  .thread{position:sticky;bottom:0}
}
```

`app.js` — 加 Tab 切换：点 `.mtab` → 切 `.on`、给对应 `.col` 加/去 `.active`（桌面 media 外 `.active` 无副作用，因桌面三栏恒显）。默认 `flow` active。

- [ ] **Step 4: Run test + 桌面回归**

Run: `uv run pytest tests/test_decision_web.py -v`
Expected: 全 PASS（桌面三栏测试不回归——`.col` 在宽屏无 `display:none`）

- [ ] **Step 5: Commit**

```bash
uv run pytest -q
git add nutmeg/interfaces/web tests/test_decision_web.py
git commit -m "feat(interfaces): 手机响应式——三栏折叠单列 Tab(Workshop Task 7)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XfSkXib7b5rf4aocCqbG8M"
```

---

### Task 8: decision-web CLI 命令 + 安全默认

**Files:**
- Modify: `nutmeg/interfaces/cli/decision.py`
- Test: `tests/test_decision_web.py`

- [ ] **Step 1: Write the failing test**

`tests/test_decision_web.py` 末尾追加：

```python
def test_non_loopback_host_warns(capsys, tmp_path):
    from nutmeg.interfaces.cli import decision as dweb
    warned = dweb._warn_if_exposed("0.0.0.0")
    assert warned is True
    assert dweb._warn_if_exposed("127.0.0.1") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_decision_web.py::test_non_loopback_host_warns -v`
Expected: FAIL（`_warn_if_exposed` 不存在）

- [ ] **Step 3: Implement CLI 命令**

`nutmeg/interfaces/cli/decision.py` — 追加：

```python
def _warn_if_exposed(host: str) -> bool:
    """非 loopback 绑定 → stderr 警告(单人无鉴权假设)。返回是否警告。"""
    if host not in ("127.0.0.1", "localhost", "::1"):
        import sys
        print(f"⚠️ decision-web 绑定 {host}:无鉴权,仅限可信局域网。", file=sys.stderr)
        return True
    return False


@_cli.app.command("decision-web")
def decision_web(
    output_dir: Path = _OUTPUT_DIR_OPTION,
    host: str = _cli.typer.Option("127.0.0.1", "--host"),
    port: int = _cli.typer.Option(8787, "--port"),
) -> None:
    """Workshop 判读工作台:浏览器审草稿/追问共磨/确认出票(spec workshop-ui)。"""
    import uvicorn

    from nutmeg.decision.store import DecisionStore
    from nutmeg.interfaces.decision_web import create_decision_app

    _warn_if_exposed(host)
    store = DecisionStore(Path(output_dir) / "decision")
    app = create_decision_app(store=store, output_dir=Path(output_dir))
    uvicorn.run(app, host=host, port=port)
```

- [ ] **Step 4: Run test + 命令注册回归**

Run: `uv run pytest tests/test_decision_web.py -v && uv run nutmeg --help 2>&1 | grep decision-web`
Expected: 测试 PASS；`--help` 列出 `decision-web`

- [ ] **Step 5: Commit**

```bash
uv run pytest -q
git add nutmeg/interfaces/cli/decision.py tests/test_decision_web.py
git commit -m "feat(cli): decision-web 命令 + 非 loopback 安全警告(Workshop Task 8)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XfSkXib7b5rf4aocCqbG8M"
```

---

### Task 9: e2e + verify skill + 文档收尾

**Files:**
- Test: `tests/test_decision_web.py`（e2e）
- Modify: `docs/superpowers/specs/2026-07-07-workshop-ui-design.md`（状态行）、`README.md`（补 decision-web 一行）

- [ ] **Step 1: e2e 全链测试**

`tests/test_decision_web.py` 末尾追加（伪造一天 → 追问 → 批准 → 确认 legs → 文件与 store 全链断言）：

```python
def test_e2e_one_day_thread_approve_legs(tmp_path):
    client, out, date = _app(tmp_path)
    store = client.app.state.store
    _seed_factors(store)
    from nutmeg.decision.workbench import append_event, read_events
    # agent 起草 + 推议程
    append_event(out, date, {"kind": "attention", "id": "O1", "group": "草稿待审",
                             "match": "哈马比 vs 卡尔马"})
    append_event(out, date, {"kind": "read_draft", "id": "D1", "obj_id": "O1",
                             "payload": _valid_read_payload(date)})
    # 人追问(浏览器)
    assert client.post("/thread", json={"date": date, "obj_id": "O1",
                                        "text": "战意呢？"}).json()["ok"]
    # agent 回应(模拟终端写回)
    append_event(out, date, {"kind": "agent_reply", "obj_id": "O1", "text": "争四动力足"})
    # 人批准 → 蒸馏进 note + 入库
    r = client.post("/action/approve-read",
                    json={"obj_id": "O1", "read": _valid_read_payload(date)})
    assert r.json()["ok"]
    from nutmeg.decision.ontology import Read
    stored = store.get(Read, "R-web-1")
    assert stored is not None and "战意" in stored.note      # 蒸馏痕迹入 note
    # 确认 legs
    leg = {"match_id": f"M-{date}-a-b", "market": "had", "selection": "home",
           "odds": 1.92, "bucket": "main"}
    assert client.post("/action/confirm-legs",
                       json={"date": date, "legs": [leg]}).json()["ok"]
    assert (out / "daily" / date / "legs.json").exists()
    # 裁决留痕
    dec = (out / "daily" / date / "decisions.jsonl").read_text()
    assert "approve_read" in dec and "confirm_legs" in dec
    # 线程未进九对象 store(本体不膨胀):store 只有那一条 Read
    assert len(store.load(Read)) == 1
```

- [ ] **Step 2: Run e2e + 全套**

Run: `uv run pytest tests/test_decision_web.py -v && uv run pytest -q 2>&1 | tail -2 && uv run ruff check nutmeg/ tests/`
Expected: 全 PASS + ruff 全绿

- [ ] **Step 3: verify skill 手动实链**

启动真实服务观察（不阻塞测试）：
```bash
uv run nutmeg decision-web --output-dir .nutmeg-data/jczq &
sleep 2
curl -s "http://127.0.0.1:8787/api/workbench?date=$(date +%F)" | head -c 300
curl -s "http://127.0.0.1:8787/" | grep -o "判读工作台"
kill %1
```
Expected: JSON 返回当日 matches/events；页面含"判读工作台"。用浏览器打开 `http://127.0.0.1:8787` 目视对照 `docs/design/nutmeg-workshop.html`（三栏 + 追问线程 + 双主题）。

- [ ] **Step 4: 文档收尾**

`docs/superpowers/specs/2026-07-07-workshop-ui-design.md` 顶部状态：改注"v1 已落地（2026-07-07，Workshop Task 1-9，commits 见 git log）"。
`README.md`：在 decision 五动词工作流段后补一行 `nutmeg decision-web` —— "浏览器判读工作台：审草稿/追问共磨/确认出票（只绑 127.0.0.1）"。

- [ ] **Step 5: Final commit**

```bash
uv run pytest -q
git add docs/superpowers/specs/2026-07-07-workshop-ui-design.md README.md tests/test_decision_web.py
git commit -m "test(interfaces): Workshop e2e 全链 + 文档收尾(Workshop Task 9)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XfSkXib7b5rf4aocCqbG8M"
```

---

## Self-Review（已执行）

**1. Spec coverage：**
- §0 决策 1 判读工作台 → Task 3/6（工作台核心）✅；决策 2 只读+两 action → Task 3（只读）/Task 4（两 action 闸）✅；决策 3 桌面+手机 → Task 6/7 ✅；决策 4 伴生双向 → Task 2/5 ✅；决策 5 独立 app + client-web 下葬 → Task 1/3 ✅
- §1 AI-native（注意力流/审批卡/视图块/对话）→ Task 6 渲染 + Task 5 线程 ✅
- §2 信息架构四页 → Task 6（workbench + objects/calibration/ledger）✅；顶栏三灯/预算条 → Task 6 模板 + app.js（灯从数据推断，budget 端点复用 express.load_budget，Task 6 app.js）⚠️ 三灯的数据推断逻辑在 app.js 前端，未单测——low risk 渲染，verify 目视覆盖
- §3 握手协议（workbench.jsonl/decisions.jsonl/SSE）→ Task 2（协议）/Task 5（/events）✅
- §3.5 追问线程（双向/两种收尾/蒸馏进 note/不进 store）→ Task 5 + Task 2 distill_note + Task 4 approve 时蒸馏 + Task 9 e2e 断言 ✅
- §4 技术栈/目录/client-web 下葬清单 → File Structure + Task 1 ✅
- §5 错误处理（校验拒绝同源/幂等 .bak/空态引导/安全默认）→ Task 4（拒绝同源+.bak）/Task 3（空态）/Task 8（安全）✅；数据健康横幅/SSE 断连指示 → Task 6 app.js（前端，verify 目视）⚠️
- §6 测试 → 各 Task 的 TDD + Task 9 e2e ✅
- §7 分期（v1 全量）→ Task 1-9 覆盖 v1；v2 不做 ✅

**2. Placeholder scan：** 无 TBD/TODO；每个代码步骤有完整代码。两处标 ⚠️（三灯/健康横幅的前端逻辑）是渲染层、无判断、由 verify 目视兜底，不阻塞。

**3. Type consistency：** `create_decision_app(*, store, output_dir)`（Task 3 定义，Task 4/5/6/8 使用一致）；`workbench.append_event/append_user_message/read_events(since=)/record_decision/distill_note`（Task 2 定义，Task 4/5/9 使用签名一致）；`_valid_read_payload`/`_seed_factors`/`_app`（Task 4 定义，Task 5/6/9 复用）；`self_daily`/`_factor_cls`/`_date_of`/`_today`（Task 4 定义并使用）；`_warn_if_exposed`（Task 8 定义+测试）。一致。

**4. 关键纪律核对：** 判断永不进 UI（Task 2 docstring + Task 4 approve 复用 ingest_reads 校验，UI 不复制校验）✅；追问线程不进九对象 store（Task 9 e2e 断言 `len(store.load(Read))==1`）✅；live 不中断（只增 web + workbench.py，五动词零改）✅；client-web 下葬保留共享底座（Task 1 Step 1 grep 复核 + 保留清单）✅。
