# App 化 · 阶段一：SOP 任务运行器（A 类流水线做成按钮）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在判读工作台（`decision-web`，8787）里按一个按钮就能跑 RUNBOOK 泳道 B 的任一确定性步骤（备料→前提卡→入 canonical→build-reads→候选穷举→审计门→裁决单签发→结算），每次运行的命令、退出码、输出尾巴都作为事件写进当日 `workbench.jsonl`，页面实时显示。

**Architecture:** 一个纯函数的「步骤登记表」（`sop_tasks.py`）把每一步描述成 `(step_id, argv 构造器, 产物路径)`；一个运行器用 typer 的 `CliRunner` **进程内**调用现有 CLI（不写新命令、不 subprocess），把 `task_started/task_done/task_failed` 三种事件追加进事件流；`decision_web` 加两个端点（列步骤+跑步骤）和一条任务栏；`app.js` 加一种事件卡。判断永不入脚本：本阶段**不含** B3 深研（需要 agent，见阶段二）与 B6b 裁决单的 ruling（只签发空单，人填）。

**Tech Stack:** Python 3.13 / FastAPI + Jinja2 / typer `CliRunner` / 原生 JS（`app.js` 无框架）/ pytest。

**背景（必读）：**
- 事件流 API：`nutmeg/decision/workbench.py` 的 `append_event(output_dir, date, event) -> seq` 与 `read_events(output_dir, date, since=0)`。`output_dir` 是 `.nutmeg-data/jczq`，文件在 `daily/<date>/workbench.jsonl`。
- 工作台 app 工厂：`nutmeg/interfaces/decision_web.py::create_decision_app(*, store, output_dir, kernel_state=None)`；测试夹具见 `tests/test_decision_web.py::_app`。
- 前端事件分发：`nutmeg/interfaces/web/static/decision/app.js` 的 `ingest(e)` 里 `switch (e.kind)`；页面加载先 `fetch("/api/workbench?date=")` 把 `state.events` 逐条 `ingest`，之后轮询 `/events?date=&since=`。
- CLI 根：`nutmeg/interfaces/cli/__init__.py` 里 `app = typer.Typer(...)`；命令用 `@_cli.app.command("zucai-prep")` 注册在 `nutmeg/interfaces/cli/zucai.py` / `decision.py`。
- 今天（2026-09-18）人肉跑过的准确命令行（本计划的 argv 以它们为准）：
  - `zucai-prep --slot morning|afternoon|revision --issue <issue>`
  - `decision-am --run-date <date> --issue <issue> --output-dir .nutmeg-data/jczq`
  - `zucai-premise-card --issue <issue> --out .nutmeg-data/zucai/<issue>-premise-card.md`
  - `zucai-research-intake --issue <issue> --legs-file <legs-base> [--write]`
  - `zucai-build-reads --judgment-file <j> --issue <issue> --store-ids-file <s> --fair-file <f> --made-at <iso>`
  - `decision-read --reads-file .nutmeg-data/zucai/<issue>-reads.json`
  - `decision-audit-legs --legs-file <legs>`（ERROR→退出码 1，这是**预期行为**，不是任务失败）
  - `decision-adjudicate --legs-file <legs> --out <sheet>`
  - `betslip settle --results-file <r> --issue <issue> --prize-per-note <n>`

---

## 文件结构

- Create `nutmeg/decision/sop_tasks.py` — 步骤登记表 + 运行器（纯 Python，可无网测试）
- Create `tests/decision/test_sop_tasks.py`
- Modify `nutmeg/interfaces/decision_web.py` — `GET /api/sop-steps`、`POST /action/run-task`
- Modify `nutmeg/interfaces/web/templates/decision/workbench.html` — 顶栏下加任务栏容器
- Modify `nutmeg/interfaces/web/static/decision/app.js` — 任务栏渲染、`task_*` 事件卡
- Modify `nutmeg/interfaces/web/static/decision/app.css` — 任务栏样式
- Modify `tests/test_decision_web_kernel.py` — 端点测试
- Modify `docs/sop/RUNBOOK.md` — 泳道 B 表头加一行「页面按钮＝同一条命令」

---

### Task 1: 步骤登记表（SopStep + 内置 8 步）

**Files:**
- Create: `nutmeg/decision/sop_tasks.py`
- Test: `tests/decision/test_sop_tasks.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_sop_tasks.py
from pathlib import Path

from nutmeg.decision.sop_tasks import STEPS, SopParams, step_by_id


def test_registry_has_the_eight_deterministic_lane_b_steps_in_runbook_order():
    assert [s.step_id for s in STEPS] == [
        "B0_prep_morning", "B1_prep_afternoon", "B2_canonical", "B3a_premise_card",
        "B4_build_reads", "B4b_candidates", "B6_audit", "B6b_adjudicate_issue",
    ]


def test_argv_is_built_from_params_and_matches_the_runbook_command_lines():
    p = SopParams(issue="26129", date="2026-09-18", zucai_dir=Path(".nutmeg-data/zucai"),
                  output_dir=Path(".nutmeg-data/jczq"), legs_file=Path("x/legs.json"))
    assert step_by_id("B0_prep_morning").argv(p) == \
        ["zucai-prep", "--slot", "morning", "--issue", "26129"]
    assert step_by_id("B2_canonical").argv(p) == \
        ["decision-am", "--run-date", "2026-09-18", "--issue", "26129",
         "--output-dir", ".nutmeg-data/jczq"]
    assert step_by_id("B6_audit").argv(p) == ["decision-audit-legs", "--legs-file", "x/legs.json"]


def test_steps_declare_their_artifacts_so_the_ui_can_show_done_state():
    p = SopParams(issue="26129", date="2026-09-18", zucai_dir=Path("/z"),
                  output_dir=Path("/o"), legs_file=None)
    assert step_by_id("B0_prep_morning").artifacts(p) == [Path("/z/26129-prep-morning.json")]
    assert step_by_id("B4_build_reads").artifacts(p) == \
        [Path("/z/26129-reads.json"), Path("/z/26129-legs-base.json")]


def test_audit_step_treats_exit_code_1_as_a_verdict_not_a_crash():
    assert step_by_id("B6_audit").ok_exit_codes == (0, 1)
    assert step_by_id("B0_prep_morning").ok_exit_codes == (0,)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_sop_tasks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nutmeg.decision.sop_tasks'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/sop_tasks.py
"""RUNBOOK 泳道 B 的确定性步骤登记表 + 进程内运行器。

出生事故 2026-09-18：26129 一期，B0→B9 的每一条命令都是我在终端手敲的，用户问
「不开聊天窗口能不能把一期跑完」——答案取决于这些命令能不能从页面上按出来。
本模块只做两件事：①把每一步描述成 (argv 构造器, 产物路径, 允许的退出码)，
②用 typer 的 CliRunner 在进程内调用**同一个** CLI，并把过程写进事件流。

⛔判断永不入脚本：这里没有 B3（深研，需要 agent）、没有 B5（构票是判断）、
   没有 B6b 的 ruling（只签发空裁决单，ruling 由人填）。
⛔审计门退出码 1 是「有 ERROR」这个**判决**，不是任务失败——`ok_exit_codes` 里显式列出。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class SopParams:
    issue: str
    date: str                       # 业务日 YYYY-MM-DD（decision-am --run-date）
    zucai_dir: Path
    output_dir: Path                # .nutmeg-data/jczq
    legs_file: Path | None = None   # B6 / B6b 需要；其余步骤忽略
    made_at: str = field(default_factory=lambda: datetime.now().astimezone()
                         .isoformat(timespec="minutes"))


@dataclass(frozen=True)
class SopStep:
    step_id: str
    label: str
    argv: Callable[[SopParams], list[str]]
    artifacts: Callable[[SopParams], list[Path]]
    ok_exit_codes: tuple[int, ...] = (0,)
    needs_legs: bool = False


def _z(p: SopParams, name: str) -> Path:
    return p.zucai_dir / f"{p.issue}-{name}"


STEPS: tuple[SopStep, ...] = (
    SopStep("B0_prep_morning", "B0 早刷新",
            lambda p: ["zucai-prep", "--slot", "morning", "--issue", p.issue],
            lambda p: [_z(p, "prep-morning.json")]),
    SopStep("B1_prep_afternoon", "B1 14:00 备料",
            lambda p: ["zucai-prep", "--slot", "afternoon", "--issue", p.issue],
            lambda p: [_z(p, "prep-afternoon.json")]),
    SopStep("B2_canonical", "B2 入 canonical",
            lambda p: ["decision-am", "--run-date", p.date, "--issue", p.issue,
                       "--output-dir", str(p.output_dir)],
            lambda p: [_z(p, "store-ids.json")]),
    SopStep("B3a_premise_card", "B3a 前提卡",
            lambda p: ["zucai-premise-card", "--issue", p.issue,
                       "--out", str(_z(p, "premise-card.md"))],
            lambda p: [_z(p, "premise-card.md")]),
    SopStep("B4_build_reads", "B4 落 Read",
            lambda p: ["zucai-build-reads", "--judgment-file", str(_z(p, "judgment-v1.json")),
                       "--issue", p.issue, "--store-ids-file", str(_z(p, "store-ids.json")),
                       "--fair-file", str(_z(p, "fair.json")), "--made-at", p.made_at],
            lambda p: [_z(p, "reads.json"), _z(p, "legs-base.json")]),
    SopStep("B4b_candidates", "B4b 候选穷举",
            lambda p: ["zucai-candidates", "--options-file", str(_z(p, "options.json")),
                       "--fair-file", str(_z(p, "fair.json")),
                       "--legs-file", str(_z(p, "legs-base.json"))],
            lambda p: []),   # ⚠️zucai-candidates 只 echo 到 stdout，不落盘（核实于 2026-09-18）
    SopStep("B6_audit", "B6 审计门",
            lambda p: ["decision-audit-legs", "--legs-file", str(p.legs_file)],
            lambda p: [], ok_exit_codes=(0, 1), needs_legs=True),
    SopStep("B6b_adjudicate_issue", "B6b 签发裁决单",
            lambda p: ["decision-adjudicate", "--legs-file", str(p.legs_file),
                       "--out", str(_z(p, "adjudication.json"))],
            lambda p: [_z(p, "adjudication.json")], needs_legs=True),
)


def step_by_id(step_id: str) -> SopStep:
    for s in STEPS:
        if s.step_id == step_id:
            return s
    raise KeyError(f"未登记的 SOP 步骤: {step_id}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_sop_tasks.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/sop_tasks.py tests/decision/test_sop_tasks.py
git commit -m "feat(sop): 泳道 B 确定性步骤登记表（argv/产物/允许退出码）"
```

---

### Task 2: 进程内运行器 → 事件流

**Files:**
- Modify: `nutmeg/decision/sop_tasks.py`
- Test: `tests/decision/test_sop_tasks.py`

- [ ] **Step 1: Write the failing test**

```python
# 追加到 tests/decision/test_sop_tasks.py
from nutmeg.decision.sop_tasks import run_step
from nutmeg.decision.workbench import read_events


class _FakeInvoker:
    """替身：不真跑 CLI，只记录 argv 并返回预设退出码/输出。"""
    def __init__(self, exit_code=0, output="ok\nline2\n"):
        self.exit_code, self.output, self.calls = exit_code, output, []

    def __call__(self, argv):
        self.calls.append(argv)
        return self.exit_code, self.output


def test_run_step_writes_started_and_done_events_with_output_tail(tmp_path):
    p = SopParams(issue="26129", date="2026-09-19", zucai_dir=tmp_path / "z",
                  output_dir=tmp_path / "o", legs_file=None)
    inv = _FakeInvoker()
    result = run_step("B0_prep_morning", p, invoke=inv)
    assert inv.calls == [["zucai-prep", "--slot", "morning", "--issue", "26129"]]
    assert result["ok"] is True and result["exit_code"] == 0
    evs = read_events(tmp_path / "o", "2026-09-19")
    assert [e["kind"] for e in evs] == ["task_started", "task_done"]
    assert evs[1]["obj_id"] == "task:B0_prep_morning" and "line2" in evs[1]["text"]


def test_audit_exit_1_is_done_not_failed(tmp_path):
    p = SopParams(issue="26129", date="2026-09-19", zucai_dir=tmp_path / "z",
                  output_dir=tmp_path / "o", legs_file=tmp_path / "legs.json")
    result = run_step("B6_audit", p, invoke=_FakeInvoker(exit_code=1, output="1 个 ERROR"))
    assert result["ok"] is True                       # 判决≠崩溃
    assert read_events(tmp_path / "o", "2026-09-19")[-1]["kind"] == "task_done"


def test_unexpected_exit_code_is_task_failed(tmp_path):
    p = SopParams(issue="26129", date="2026-09-19", zucai_dir=tmp_path / "z",
                  output_dir=tmp_path / "o", legs_file=None)
    result = run_step("B0_prep_morning", p, invoke=_FakeInvoker(exit_code=2, output="boom"))
    assert result["ok"] is False
    assert read_events(tmp_path / "o", "2026-09-19")[-1]["kind"] == "task_failed"


def test_step_needing_legs_refuses_without_legs_file(tmp_path):
    p = SopParams(issue="26129", date="2026-09-19", zucai_dir=tmp_path / "z",
                  output_dir=tmp_path / "o", legs_file=None)
    inv = _FakeInvoker()
    result = run_step("B6_audit", p, invoke=inv)
    assert result["ok"] is False and inv.calls == [] and "legs_file" in result["error"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_sop_tasks.py -v -k run_step`
Expected: FAIL with `ImportError: cannot import name 'run_step'`

- [ ] **Step 3: Write minimal implementation**

```python
# 追加到 nutmeg/decision/sop_tasks.py
from nutmeg.decision.workbench import append_event

_TAIL_LINES = 12


def cli_invoke(argv: list[str]) -> tuple[int, str]:
    """生产 invoker：进程内跑同一个 typer app（不 subprocess，测试可替身）。"""
    from typer.testing import CliRunner

    from nutmeg.interfaces.cli import app

    result = CliRunner().invoke(app, argv)
    return result.exit_code, result.output


def run_step(step_id: str, params: SopParams, *, invoke=cli_invoke) -> dict:
    """跑一步；开始/结束各写一条事件（obj_id=task:<step_id>），返回结果摘要。"""
    step = step_by_id(step_id)
    obj = f"task:{step.step_id}"
    if step.needs_legs and params.legs_file is None:
        return {"ok": False, "step_id": step.step_id, "error": "该步骤需要 legs_file"}
    argv = step.argv(params)
    append_event(params.output_dir, params.date, {
        "kind": "task_started", "obj_id": obj, "step_id": step.step_id,
        "label": step.label, "argv": argv,
        "at": datetime.now().astimezone().isoformat(timespec="seconds")})
    exit_code, output = invoke(argv)
    tail = "\n".join(output.strip().splitlines()[-_TAIL_LINES:])
    ok = exit_code in step.ok_exit_codes
    append_event(params.output_dir, params.date, {
        "kind": "task_done" if ok else "task_failed", "obj_id": obj,
        "step_id": step.step_id, "label": step.label, "exit_code": exit_code,
        "text": tail,
        "artifacts": [str(a) for a in step.artifacts(params) if a.exists()],
        "at": datetime.now().astimezone().isoformat(timespec="seconds")})
    return {"ok": ok, "step_id": step.step_id, "exit_code": exit_code, "tail": tail}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_sop_tasks.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/sop_tasks.py tests/decision/test_sop_tasks.py
git commit -m "feat(sop): 进程内运行器，task_started/done/failed 进事件流"
```

---

### Task 3: 端点 `GET /api/sop-steps` 与 `POST /action/run-task`

**Files:**
- Modify: `nutmeg/interfaces/decision_web.py`（在 `@app.get("/events")` 之前插入）
- Test: `tests/test_decision_web_kernel.py`

- [ ] **Step 1: Write the failing test**

```python
# 追加到 tests/test_decision_web_kernel.py
def test_sop_steps_endpoint_lists_steps_with_done_state(tmp_path):
    zucai = tmp_path / "zucai"; zucai.mkdir()
    (zucai / "26129-prep-morning.json").write_text("{}", encoding="utf-8")
    store = DecisionStore(tmp_path / "decision")
    client = TestClient(create_decision_app(store=store, output_dir=tmp_path / "jczq",
                                           zucai_dir=zucai))
    body = client.get("/api/sop-steps?issue=26129&date=2026-09-19").json()
    ids = [s["step_id"] for s in body["steps"]]
    assert ids[0] == "B0_prep_morning" and body["steps"][0]["done"] is True
    assert body["steps"][1]["step_id"] == "B1_prep_afternoon" and body["steps"][1]["done"] is False


def test_run_task_endpoint_uses_injected_invoker_and_returns_result(tmp_path):
    calls = []
    def fake_invoke(argv):
        calls.append(argv); return 0, "备料完成"
    store = DecisionStore(tmp_path / "decision")
    app = create_decision_app(store=store, output_dir=tmp_path / "jczq",
                              zucai_dir=tmp_path / "zucai", sop_invoke=fake_invoke)
    client = TestClient(app)
    r = client.post("/action/run-task",
                    json={"step_id": "B0_prep_morning", "issue": "26129", "date": "2026-09-19"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert calls == [["zucai-prep", "--slot", "morning", "--issue", "26129"]]
    evs = client.get("/events?date=2026-09-19&since=0").json()["events"]
    assert [e["kind"] for e in evs] == ["task_started", "task_done"]


def test_run_task_rejects_unknown_step(tmp_path):
    store = DecisionStore(tmp_path / "decision")
    client = TestClient(create_decision_app(store=store, output_dir=tmp_path / "jczq",
                                           zucai_dir=tmp_path / "zucai"))
    r = client.post("/action/run-task", json={"step_id": "B99", "issue": "26129", "date": "2026-09-19"})
    assert r.status_code == 400 and "未登记" in r.json()["error"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_decision_web_kernel.py -v -k "sop_steps or run_task"`
Expected: FAIL with `TypeError: create_decision_app() got an unexpected keyword argument 'zucai_dir'`

- [ ] **Step 3: Write minimal implementation**

改 `create_decision_app` 签名并加两个端点（插在 `@app.get("/events")` 之前）：

```python
def create_decision_app(*, store: DecisionStore, output_dir, kernel_state=None,
                        zucai_dir=None, sop_invoke=None) -> FastAPI:
    ...
    app.state.zucai_dir = Path(zucai_dir) if zucai_dir else Path(output_dir).parent / "zucai"

    # ---- SOP 任务栏（阶段一）：同一条命令，从页面按 ----------------------------
    @app.get("/api/sop-steps")
    def sop_steps(issue: str, date: str) -> dict:
        from nutmeg.decision.sop_tasks import STEPS, SopParams
        p = SopParams(issue=issue, date=date, zucai_dir=app.state.zucai_dir,
                      output_dir=Path(output_dir), legs_file=None)
        return {"issue": issue, "date": date, "steps": [
            {"step_id": s.step_id, "label": s.label, "needs_legs": s.needs_legs,
             "done": bool(s.artifacts(p)) and all(a.exists() for a in s.artifacts(p))}
            for s in STEPS]}

    @app.post("/action/run-task")
    def run_task(payload: dict = Body(...)) -> Any:  # noqa: B008
        from nutmeg.decision.sop_tasks import SopParams, cli_invoke, run_step
        legs = payload.get("legs_file")
        p = SopParams(issue=str(payload["issue"]), date=str(payload["date"]),
                      zucai_dir=app.state.zucai_dir, output_dir=Path(output_dir),
                      legs_file=Path(legs) if legs else None)
        try:
            return run_step(str(payload.get("step_id")), p, invoke=sop_invoke or cli_invoke)
        except KeyError as exc:
            return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})
```

（文件顶部已 `from fastapi import Body`; 若无 `JSONResponse`，加 `from fastapi.responses import JSONResponse`。）

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_decision_web_kernel.py tests/test_decision_web.py -v`
Expected: 全部 passed（旧测试不受影响：新参数都有默认值）

- [ ] **Step 5: Commit**

```bash
git add nutmeg/interfaces/decision_web.py tests/test_decision_web_kernel.py
git commit -m "feat(web): /api/sop-steps 与 /action/run-task，页面按钮跑同一条 CLI"
```

---

### Task 4: 任务栏 UI + `task_*` 事件卡

**Files:**
- Modify: `nutmeg/interfaces/web/templates/decision/workbench.html`（`topbar` 之后、三栏之前）
- Modify: `nutmeg/interfaces/web/static/decision/app.js`
- Modify: `nutmeg/interfaces/web/static/decision/app.css`
- Test: `tests/test_decision_web_kernel.py`

- [ ] **Step 1: Write the failing test**

```python
# 追加到 tests/test_decision_web_kernel.py
def test_workbench_page_has_sop_bar_bound_to_issue(tmp_path):
    store = DecisionStore(tmp_path / "decision")
    client = TestClient(create_decision_app(store=store, output_dir=tmp_path / "jczq",
                                           zucai_dir=tmp_path / "zucai"))
    html = client.get("/?date=2026-09-19&issue=26129").text
    assert 'id="sopbar"' in html and 'data-issue="26129"' in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_decision_web_kernel.py -v -k sop_bar`
Expected: FAIL（`sopbar` 不在页面里）

- [ ] **Step 3: Write minimal implementation**

`decision_web.py` 的 `workbench_page` 加 `issue: str = ""` 参数并传进模板 context：`{"title": "判读工作台", "state": ..., "issue": issue}`。

`workbench.html` 在 `</div>`（topbar 结束）之后插入：

```html
<div class="sopbar" id="sopbar" data-issue="{{ issue }}" data-date="{{ state.date }}">
  <span class="sopttl">SOP 泳道 B</span>
  <input class="field sopissue" id="sop-issue" placeholder="期号 如 26129" value="{{ issue }}">
  <span id="sop-steps"></span>
</div>
```

`app.js` 在 `ingest` 的 switch 加两行，并新增渲染函数：

```javascript
      case "task_started": renderTaskEvent(e, "running"); break;
      case "task_done": renderTaskEvent(e, "done"); break;
      case "task_failed": renderTaskEvent(e, "failed"); break;
```

```javascript
  // ---- SOP 任务栏（阶段一）：同一条命令，从页面按 -----------------------------
  var sopBar = document.getElementById("sopbar");
  var sopSteps = document.getElementById("sop-steps");
  var sopIssue = document.getElementById("sop-issue");
  function loadSopSteps() {
    var issue = (sopIssue && sopIssue.value || "").trim();
    if (!sopSteps || !issue) return;
    fetch("/api/sop-steps?issue=" + encodeURIComponent(issue) + "&date=" + encodeURIComponent(DATE))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        sopSteps.innerHTML = "";
        (d.steps || []).forEach(function (s) {
          var b = el("button", "btn sopstep" + (s.done ? " done" : ""), s.label);
          b.setAttribute("data-step", s.step_id);
          b.addEventListener("click", function () {
            b.disabled = true; b.classList.add("running");
            post("/action/run-task", { step_id: s.step_id, issue: issue, date: DATE,
                                       legs_file: s.needs_legs ? window.prompt("legs 文件路径") : null })
              .then(function () { b.disabled = false; b.classList.remove("running"); loadSopSteps(); });
          });
          sopSteps.appendChild(b);
        });
      });
  }
  if (sopIssue) { sopIssue.addEventListener("change", loadSopSteps); loadSopSteps(); }

  function renderTaskEvent(e, state) {
    var id = "task-" + (e.step_id || "") ;
    var old = stageEl.querySelector('[data-task="' + id + '"]');
    if (old) old.remove();
    var blk = el("div", "vblock task " + state);
    blk.setAttribute("data-task", id);
    blk.appendChild(el("div", "vbhead",
      (e.label || e.step_id) + " · " + (state === "running" ? "运行中" : state === "done" ? "完成 exit=" + e.exit_code : "失败 exit=" + e.exit_code)));
    if (e.argv) blk.appendChild(el("div", "mono small", "$ nutmeg " + e.argv.join(" ")));
    if (e.text) { var pre = el("pre", "tasklog"); pre.textContent = e.text; blk.appendChild(pre); }
    stageEl.appendChild(blk);
  }
```

`app.css` 追加：

```css
.sopbar{display:flex;gap:8px;align-items:center;padding:6px 14px;border-bottom:1px solid var(--line);font-size:12.5px}
.sopttl{color:var(--sub);margin-right:4px}
.sopissue{width:110px}
.btn.sopstep.done{border-color:var(--pine);color:var(--pine)}
.btn.sopstep.running{opacity:.6}
.vblock.task.failed .vbhead{color:var(--cinnabar)}
.tasklog{font-size:11.5px;white-space:pre-wrap;max-height:220px;overflow:auto;margin:6px 0 0}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_decision_web_kernel.py tests/test_decision_web.py -v`
Expected: 全部 passed

- [ ] **Step 5: 人肉验证（必做，截图留档）**

Run: `uv run nutmeg decision-web` → 打开 `http://127.0.0.1:8787/?date=2026-09-19&issue=26129` → 任务栏出 8 个按钮，已有产物的显示绿边 → 点「B0 早刷新」→ 中栏出现 `task_started` 块随后变 `完成 exit=0`，尾巴里有「备料完成」。
Expected: 与终端 `uv run nutmeg zucai-prep --slot morning --issue 26129` 输出一致。

- [ ] **Step 6: Commit**

```bash
git add nutmeg/interfaces/web/templates/decision/workbench.html nutmeg/interfaces/web/static/decision/app.js nutmeg/interfaces/web/static/decision/app.css nutmeg/interfaces/decision_web.py tests/test_decision_web_kernel.py
git commit -m "feat(web): SOP 任务栏——泳道 B 八步从页面按，过程进事件流"
```

---

### Task 5: RUNBOOK 入册

**Files:**
- Modify: `docs/sop/RUNBOOK.md`（泳道 B 表格之前）

- [ ] **Step 1: 加一段**

在「## 泳道 B」标题下、表格之前插入：

```markdown
> **页面按钮＝同一条命令（2026-09-1x 起）**：`uv run nutmeg decision-web` → 顶部 SOP 任务栏按期号列出 B0/B1/B2/B3a/B4/B4b/B6/B6b 八步，
> 点一下＝进程内跑本表同一条 CLI，`task_started/task_done/task_failed` 进当日 `workbench.jsonl`。
> ⛔按钮里没有 B3 深研（要 agent，阶段二）、B5 构票（判断）、B6b 的 ruling（人填）——那是设计，不是缺功能。
```

- [ ] **Step 2: Commit**

```bash
git add docs/sop/RUNBOOK.md
git commit -m "docs(runbook): 泳道 B 页面按钮与 CLI 同源"
```

---

## Self-review

- 覆盖：八步登记 ✓ 运行器 ✓ 事件 ✓ 端点 ✓ UI ✓ RUNBOOK ✓；B3/B5/B6b-ruling 明确排除（阶段二）。
- 类型一致：`SopParams(issue,date,zucai_dir,output_dir,legs_file,made_at)`、`run_step(step_id, params, *, invoke)`、`invoke(argv)->(exit_code, output)` 在 Task 2/3 一致。
- 无占位：每步有代码与命令。
