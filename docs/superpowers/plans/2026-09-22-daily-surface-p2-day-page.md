# Daily Surface P2 · 当日页 `/day/<date>` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `decision-web`（8787）上加一页 `/day/<date>`，把 P1 的 `daily/<日>/` 对象与 launchd 证据合成一个视图：状态条、昨日、竞彩板、足彩期、RSI、待人决定、会话入口、讨论框。每块独立降级，写操作只有一个（讨论留言）。

**Architecture:** 一个只读 JSON 端点 `/api/day/<date>` 把 `brief.json`、`decisions.json`、`timeline.json`、`discussion.jsonl`、launchd 行合成；页面 Jinja 骨架 + `day.js` 渲染（与 `/observe` 同一套 `element()/getJson()` 习惯），无前端工具链。launchd 证据由新模块 `day_ops.py` 读 `launchctl list` 文本 + `ops/launchd/*.plist` + `.nutmeg-data/logs/*.log` mtime，复用 `ops_status.agent_status/describe_calendar`。

**Tech Stack:** FastAPI + Jinja2（已有）、原生 JS、`plistlib`（标准库）、pytest + `fastapi.testclient`。

**Spec:** 设计 §7（当日页）、§5（状态条要亮 results-backfill 退出 2）。**依赖 P1 已合入。**

---

## File structure

| 文件 | 职责 |
| --- | --- |
| Create `nutmeg/decision/day_ops.py` | `launchd_rows(...)`：launchd 标签 → 计划时刻 / 装载 / 退出码 / 日志尾行 + mtime |
| Create `nutmeg/decision/day_view.py` | `day_view(...)`：把七份输入合成页面 JSON，每块 try/except |
| Modify `nutmeg/interfaces/decision_web.py` | `create_decision_app(..., data_dir=None)`；路由 `/day`、`/day/{date}`、`/api/day/{date}`、`POST /action/day-note` |
| Modify `nutmeg/interfaces/cli/decision.py:600` | 传 `data_dir=Path(output_dir).parent` |
| Create `nutmeg/interfaces/web/templates/decision/day.html`、`static/decision/day.css`、`static/decision/day.js` | 页面 |
| Modify `nutmeg/interfaces/web/templates/decision/workbench.html` | 顶栏加「当日」链接 |
| Tests | `tests/decision/test_day_ops.py`、`tests/decision/test_day_view.py`、`tests/test_decision_web_day.py` |

---

### Task 1: launchd 证据行 `day_ops.launchd_rows`

**Files:**
- Create: `nutmeg/decision/day_ops.py`
- Test: `tests/decision/test_day_ops.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_day_ops.py
import plistlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from nutmeg.decision.day_ops import launchd_rows

BJ = timezone(timedelta(hours=8))
LAUNCHCTL = "-\t0\tcom.nutmeg.rsi.loop\n-\t2\tcom.nutmeg.jczq.results-backfill\n123\t0\tcom.apple.foo\n"


def _plist(path: Path, label: str, hour: int, minute: int, program: str) -> None:
    path.write_bytes(plistlib.dumps({
        "Label": label,
        "ProgramArguments": ["/bin/zsh", "-lc", program],
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
    }))


def test_launchd_rows_pair_each_label_with_time_evidence(tmp_path: Path):
    plists, logs = tmp_path / "plists", tmp_path / "logs"
    plists.mkdir(); logs.mkdir()
    _plist(plists / "com.nutmeg.rsi.loop.plist", "com.nutmeg.rsi.loop", 10, 45, "uv run nutmeg rsi loop")
    _plist(plists / "com.nutmeg.jczq.results-backfill.plist", "com.nutmeg.jczq.results-backfill", 9, 30,
           "uv run python scripts/jczq_result_backfill.py")
    _plist(plists / "com.nutmeg.decision.close.plist", "com.nutmeg.decision.close", 19, 0, "x")
    out = logs / "rsi.loop.out.log"
    out.write_text("RSI 闭环 2026-09-23：9 步，失败 0\n", encoding="utf-8")
    err = logs / "jczq.results-backfill.out.log"
    err.write_text("⚠️RESULTS_STALE lag=3d\n", encoding="utf-8")
    rows = launchd_rows(plists_dir=plists, logs_dir=logs, launchctl_text=LAUNCHCTL,
                        today=date(2026, 9, 23))
    by = {r["label"]: r for r in rows}
    assert by["com.nutmeg.rsi.loop"]["schedule"] == "10:45" and by["com.nutmeg.rsi.loop"]["loaded"] is True
    assert by["com.nutmeg.rsi.loop"]["last_exit"] == "0" and by["com.nutmeg.rsi.loop"]["log_at"] is not None
    assert by["com.nutmeg.jczq.results-backfill"]["last_exit"] == "2"
    assert by["com.nutmeg.jczq.results-backfill"]["alarm"] is True
    assert by["com.nutmeg.decision.close"]["loaded"] is False and by["com.nutmeg.decision.close"]["log_at"] is None
    assert [r["label"] for r in rows] == sorted(by)  # stable order by label
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_day_ops.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/day_ops.py
"""状态条的 launchd 半边：每个 com.nutmeg.* 标签一行，结局与时间证据并排（沿用 ops_status 纪律）。"""
from __future__ import annotations

import plistlib
from datetime import date, datetime
from pathlib import Path

from nutmeg.decision.ops_status import describe_calendar


def parse_launchctl(text: str) -> dict[str, str]:
    """`launchctl list` 文本 → {label: last_exit}（只留 com.nutmeg.*）。"""
    out: dict[str, str] = {}
    for line in (text or "").splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[2].startswith("com.nutmeg."):
            out[parts[2].strip()] = parts[1].strip()
    return out


def _log_evidence(logs_dir: Path, label: str) -> tuple[str, datetime | None]:
    short = label.removeprefix("com.nutmeg.")
    best: tuple[str, datetime | None] = ("", None)
    for suffix in ("out", "err"):
        path = logs_dir / f"{short}.{suffix}.log"
        if not path.exists():
            continue
        at = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
        lines = [ln for ln in path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
        tail = lines[-1][:200] if lines else ""
        if best[1] is None or at > best[1]:
            best = (tail, at)
    return best


def launchd_rows(*, plists_dir: Path, logs_dir: Path, launchctl_text: str, today: date) -> list[dict]:
    exits = parse_launchctl(launchctl_text)
    rows = []
    for plist in sorted(plists_dir.glob("com.nutmeg.*.plist")):
        try:
            doc = plistlib.loads(plist.read_bytes())
        except Exception as exc:  # noqa: BLE001 — 坏 plist 也要出现在状态条上
            rows.append({"label": plist.stem, "schedule": "?", "loaded": False, "last_exit": "-",
                         "tail": f"plist 解析失败: {exc}", "log_at": None, "alarm": True})
            continue
        label = str(doc.get("Label") or plist.stem)
        tail, at = _log_evidence(logs_dir, label)
        loaded = label in exits
        last_exit = exits.get(label, "-")
        stale = at is not None and (today - at.date()).days > 2
        rows.append({
            "label": label,
            "schedule": describe_calendar(doc.get("StartCalendarInterval") or doc.get("StartInterval")),
            "loaded": loaded,
            "last_exit": last_exit,
            "tail": tail,
            "log_at": at.isoformat(timespec="minutes") if at else None,
            "alarm": (loaded and last_exit not in ("0", "-")) or stale or "RESULTS_STALE" in tail
                     or "NUTMEG_FAILED" in tail,
        })
    return sorted(rows, key=lambda r: r["label"])
```

> `describe_calendar` 已在 `nutmeg/decision/ops_status.py:139`；若它对 `StartInterval`（整数）抛错，在本模块加 `if isinstance(interval, int): return f"每 {interval // 60} 分"` 分支再调用。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_day_ops.py -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/day_ops.py tests/decision/test_day_ops.py
git commit -m "feat(day): launchd evidence rows for the status bar"
```

---

### Task 2: 视图合成 `day_view`

**Files:**
- Create: `nutmeg/decision/day_view.py`
- Test: `tests/decision/test_day_view.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_day_view.py
import json
from datetime import date
from pathlib import Path

from nutmeg.decision.day_paths import day_dir
from nutmeg.decision.day_view import day_view


def test_day_view_merges_everything_and_degrades(tmp_path: Path):
    data = tmp_path / "data"
    out = day_dir(data, "2026-09-23")
    out.mkdir(parents=True)
    (out / "brief.json").write_text(json.dumps({"date": "2026-09-23", "jczq": {"matches": [], "counts": {}},
                                                "zucai": {"issue": None}, "rsi": None, "factors": [], "errors": []}),
                                     encoding="utf-8")
    (out / "decisions.json").write_text(json.dumps([{"id": "rsi:0", "status": "open"}]), encoding="utf-8")
    (out / "timeline.json").write_text(json.dumps([{"job": "brief", "exit": 0, "finished_at": "x", "summary": "ok"}]),
                                        encoding="utf-8")
    (out / "retro.md").write_text("# 复盘底稿\n- 场1 断", encoding="utf-8")
    view = day_view(data_dir=data, date="2026-09-23", plists_dir=tmp_path / "nope", logs_dir=tmp_path / "nope",
                    launchctl_text="", today=date(2026, 9, 23))
    assert view["date"] == "2026-09-23" and view["brief"]["date"] == "2026-09-23"
    assert view["decisions"][0]["id"] == "rsi:0" and view["timeline"][0]["job"] == "brief"
    assert view["retro"].startswith("# 复盘底稿") and view["discussion"] == []
    assert view["launchd"] == [] and view["errors"] == []


def test_day_view_reports_missing_brief_without_failing(tmp_path: Path):
    view = day_view(data_dir=tmp_path, date="2026-09-23", plists_dir=tmp_path, logs_dir=tmp_path,
                    launchctl_text="", today=date(2026, 9, 23))
    assert view["brief"] is None and view["retro"] is None
    assert any("brief.json" in e for e in view["errors"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_day_view.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/day_view.py
"""`/api/day/<date>` 的合成：七份输入各自 try，缺一块不塌整页（设计 §7 与观察台同规）。"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from nutmeg.decision.day_ops import launchd_rows
from nutmeg.decision.day_paths import BRIEF, DECISIONS, RETRO, TIMELINE, day_dir
from nutmeg.decision.day_session import read_discussion


def _json(path: Path, errors: list[str], default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"缺 {path.name}")
    except ValueError as exc:
        errors.append(f"{path.name} 坏: {exc}")
    return default


def day_view(*, data_dir: Path, date: str, plists_dir: Path, logs_dir: Path,
             launchctl_text: str, today: date) -> dict:
    errors: list[str] = []
    out = day_dir(data_dir, date)
    brief = _json(out / BRIEF, errors, None)
    decisions = _json(out / DECISIONS, errors, [])
    timeline = _json(out / TIMELINE, errors, [])
    retro = None
    try:
        retro = (out / RETRO).read_text(encoding="utf-8")
    except FileNotFoundError:
        errors.append(f"缺 {RETRO}")
    try:
        discussion = read_discussion(data_dir, date)
    except ValueError as exc:
        discussion, _ = [], errors.append(f"discussion.jsonl 坏: {exc}")
    try:
        launchd = launchd_rows(plists_dir=plists_dir, logs_dir=logs_dir, launchctl_text=launchctl_text, today=today)
    except Exception as exc:  # noqa: BLE001
        launchd, _ = [], errors.append(f"launchd 行失败: {exc}")
    return {"date": date, "brief": brief, "decisions": decisions, "timeline": timeline,
            "retro": retro, "discussion": discussion, "launchd": launchd, "errors": errors}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_day_view.py -q`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/day_view.py tests/decision/test_day_view.py
git commit -m "feat(day): compose the day view from daily/<date> files and launchd evidence"
```

---

### Task 3: 路由 `/day`、`/api/day/{date}`、`POST /action/day-note`

**Files:**
- Modify: `nutmeg/interfaces/decision_web.py:57-75`（签名 + app.state）与末尾（新路由）
- Modify: `nutmeg/interfaces/cli/decision.py:600-605`
- Test: `tests/test_decision_web_day.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_decision_web_day.py
import json
from pathlib import Path

from fastapi.testclient import TestClient

from nutmeg.decision.store import DecisionStore
from nutmeg.interfaces.decision_web import create_decision_app


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    data = tmp_path / "data"
    out = data / "daily" / "2026-09-23"
    out.mkdir(parents=True)
    (out / "brief.json").write_text(json.dumps({"date": "2026-09-23", "jczq": {"matches": [], "counts": {}},
                                                "zucai": {"issue": None}, "rsi": None, "factors": [], "errors": []}),
                                     encoding="utf-8")
    store = DecisionStore(data / "jczq" / "decision")
    app = create_decision_app(store=store, output_dir=data / "jczq", data_dir=data,
                              launchctl=lambda: "-\t0\tcom.nutmeg.rsi.loop\n")
    return TestClient(app), data


def test_day_page_and_api(tmp_path: Path):
    client, _ = _client(tmp_path)
    page = client.get("/day/2026-09-23")
    assert page.status_code == 200
    assert "当日" in page.text and "/static/decision/day.js" in page.text and "<form" not in page.text
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
    r = client.post("/action/day-note", json={"date": "2026-09-23", "obj": "周三001", "text": "想双选"})
    assert r.status_code == 200 and r.json()["seq"] == 1
    rows = (data / "daily" / "2026-09-23" / "discussion.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(rows[0])["who"] == "jun"
    assert client.get("/api/day/2026-09-23").json()["discussion"][0]["text"] == "想双选"


def test_day_note_rejects_empty_text(tmp_path: Path):
    client, _ = _client(tmp_path)
    assert client.post("/action/day-note", json={"date": "2026-09-23", "text": "  "}).status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_decision_web_day.py -q`
Expected: FAIL — `create_decision_app() got an unexpected keyword argument 'data_dir'`

- [ ] **Step 3: Write minimal implementation**

签名（`decision_web.py:57`）改为：

```python
def create_decision_app(*, store: DecisionStore, output_dir, kernel_state=None,
                        zucai_dir=None, sop_invoke=None, observe_repo=None,
                        data_dir=None, launchctl=None) -> FastAPI:
```

在 `app.state.zucai_dir = ...` 之后加：

```python
    # 当日页（设计 2026-09-22-daily-operator-surface §7）：数据根默认 output_dir 的上一级。
    app.state.data_dir = Path(data_dir) if data_dir else Path(output_dir).parent
    app.state.launchctl = launchctl or _launchctl_list
    _assets.append(web_root / "static" / "decision" / "day.js")
```

（`_assets` 的定义在其前面，把 `day.js` 加进版本号计算；`_mtimes` 那两行保持在 `_assets` 最终定义之后——把新增行放在 `_assets = [...]` 列表字面量里最简单：`for name in ("app.js", "observe.js", "observe.css", "day.js")`。）

模块级加：

```python
def _launchctl_list() -> str:
    import subprocess

    try:
        return subprocess.run(["launchctl", "list"], capture_output=True, text=True, check=False).stdout
    except OSError:
        return ""
```

在 `/observe/day/{date}` 路由之后加：

```python
    # ── 当日页：先跑完、再对话 ────────────────────────────────────────────
    from fastapi.responses import RedirectResponse

    from nutmeg.decision.day_session import append_discussion
    from nutmeg.decision.day_view import day_view

    def _day_payload(date: str) -> dict:
        root = Path(__file__).resolve().parents[2]
        return day_view(
            data_dir=app.state.data_dir, date=date,
            plists_dir=root / "ops" / "launchd", logs_dir=app.state.data_dir / "logs",
            launchctl_text=app.state.launchctl(), today=_date.today(),
        )

    @app.get("/day")
    def day_root():
        return RedirectResponse(url=f"/day/{_today()}", status_code=307)

    @app.get("/day/{date}")
    def day_page(request: Request, date: str):
        return templates.TemplateResponse(request, "decision/day.html",
                                          {"title": f"当日 {date}", "date": date})

    @app.get("/api/day/{date}")
    def day_api(date: str) -> dict:
        return _day_payload(date)

    @app.post("/action/day-note")
    def day_note(payload: dict = Body(...)) -> Any:  # noqa: B008
        text = str(payload.get("text") or "").strip()
        if not text:
            return JSONResponse({"ok": False, "error": "text 为空"}, status_code=400)
        date = str(payload.get("date") or _today())
        append_discussion(app.state.data_dir, date, who=str(payload.get("who") or "jun"),
                          text=text, obj=str(payload.get("obj") or ""),
                          at=datetime.now().astimezone().isoformat(timespec="seconds"))
        return {"ok": True, "seq": len(read_discussion(app.state.data_dir, date))}
```

需要的 import：在文件顶部已有 `from datetime import date as _date`（工厂内）；`datetime` 若未导入则加 `from datetime import datetime`；`read_discussion` 从 `nutmeg.decision.day_session` 一并导入。

`nutmeg/interfaces/cli/decision.py:600` 的 `create_decision_app(...)` 调用加 `data_dir=Path(output_dir).parent,`。

- [ ] **Step 4: 先放一个最小模板让路由 200**

`nutmeg/interfaces/web/templates/decision/day.html`（Task 4 会扩成完整页面）：

```html
{% extends "decision/observe/layout.html" %}
{% block body %}
<header class="obs-topbar"><div><span class="obs-mark">DAY</span><strong>当日 {{ date }}</strong></div>
<a class="obs-back" href="/">工作台</a></header>
<main class="obs-main" id="day" data-date="{{ date }}"></main>
<script src="/static/decision/day.js?v={{ asset_v }}"></script>
{% endblock %}
```

`nutmeg/interfaces/web/static/decision/day.js` 先只放：

```js
window.Day = (function () { "use strict"; return {}; })();
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_decision_web_day.py tests/test_decision_web.py tests/test_decision_web_observe.py -q`
Expected: 全部 passed（旧测试不受 `data_dir` 默认值影响）

- [ ] **Step 6: Commit**

```bash
git add nutmeg/interfaces/decision_web.py nutmeg/interfaces/cli/decision.py nutmeg/interfaces/web/templates/decision/day.html nutmeg/interfaces/web/static/decision/day.js tests/test_decision_web_day.py
git commit -m "feat(web): /day page, /api/day JSON and day-note endpoint on decision-web"
```

---

### Task 4: 页面渲染 `day.js` / `day.css`

**Files:**
- Modify: `nutmeg/interfaces/web/templates/decision/day.html`
- Create: `nutmeg/interfaces/web/static/decision/day.css`
- Modify: `nutmeg/interfaces/web/static/decision/day.js`
- Modify: `nutmeg/interfaces/web/templates/decision/workbench.html`（顶栏加 `<a href="/day">当日</a>`）
- Test: 追加到 `tests/test_decision_web_day.py`

- [ ] **Step 1: Write the failing test**

```python
def test_day_page_has_every_block_and_links_back(tmp_path: Path):
    client, _ = _client(tmp_path)
    html = client.get("/day/2026-09-23").text
    for block in ("day-status", "day-retro", "day-jczq", "day-zucai", "day-rsi", "day-decisions", "day-session", "day-talk"):
        assert f'id="{block}"' in html
    assert "/static/decision/day.css" in html
    assert 'href="/observe"' in html and 'href="/betslips"' in html


def test_workbench_topbar_links_to_day(tmp_path: Path):
    client, _ = _client(tmp_path)
    assert 'href="/day"' in client.get("/").text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_decision_web_day.py -q -k "every_block or topbar"`
Expected: 2 FAIL

- [ ] **Step 3: Write the page**

`day.html`：

```html
{% extends "decision/observe/layout.html" %}
{% block body %}
<link rel="stylesheet" href="/static/decision/day.css?v={{ asset_v }}">
<header class="obs-topbar">
  <div><span class="obs-mark">DAY</span><strong>当日 {{ date }}</strong><span class="obs-sub">先跑完、再对话</span></div>
  <nav class="day-nav"><a href="/observe">观察台</a><a href="/betslips">实票</a><a href="/">工作台</a></nav>
</header>
<main class="obs-main" id="day" data-date="{{ date }}">
  <section class="day-block" id="day-status"><h2>状态条</h2><div class="day-body"></div></section>
  <section class="day-block" id="day-decisions"><h2>待人决定</h2><div class="day-body"></div></section>
  <section class="day-block" id="day-retro"><h2>昨日</h2><pre class="day-body day-pre"></pre></section>
  <section class="day-block" id="day-jczq"><h2>竞彩板</h2><div class="day-body day-cards"></div></section>
  <section class="day-block" id="day-zucai"><h2>足彩期</h2><div class="day-body"></div></section>
  <section class="day-block" id="day-rsi"><h2>RSI</h2><div class="day-body"></div></section>
  <section class="day-block" id="day-session"><h2>会话入口</h2><div class="day-body"></div></section>
  <section class="day-block" id="day-talk"><h2>讨论</h2><div class="day-body"></div>
    <div class="day-talk-input"><input id="day-talk-obj" placeholder="对象（如 周三001）">
      <input id="day-talk-text" placeholder="一句话，回车发送"><button id="day-talk-send">记入</button></div>
  </section>
  <p class="obs-error" id="day-errors" hidden></p>
</main>
<script src="/static/decision/day.js?v={{ asset_v }}"></script>
<script>Day.mount("#day");</script>
{% endblock %}
```

`day.css`（跟随 observe 的暗浅色变量；只给本页新类）：

```css
.day-nav a { margin-left: 12px; color: inherit; opacity: .8; }
.day-block { margin: 18px 0; padding: 14px 16px; border: 1px solid rgba(127,127,127,.25); border-radius: 12px; }
.day-block h2 { margin: 0 0 10px; font-size: 15px; letter-spacing: .04em; opacity: .75; }
.day-pre { white-space: pre-wrap; font: 12px/1.5 ui-monospace, Menlo, monospace; max-height: 260px; overflow: auto; }
.day-row { display: grid; grid-template-columns: 1.6fr 1fr 1fr 2.4fr; gap: 8px; padding: 6px 0; border-top: 1px dashed rgba(127,127,127,.25); font-size: 13px; }
.day-row.alarm { color: #c0392b; }
.day-row.ok { opacity: .85; }
.day-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; }
.day-card { border: 1px solid rgba(127,127,127,.3); border-radius: 10px; padding: 10px 12px; }
.day-card h3 { margin: 0 0 6px; font-size: 14px; }
.day-card .day-badge { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 11px; background: rgba(127,127,127,.18); margin-right: 6px; }
.day-card details summary { cursor: pointer; font-size: 12px; opacity: .8; }
.day-card pre { font: 11px/1.4 ui-monospace, Menlo, monospace; white-space: pre-wrap; max-height: 220px; overflow: auto; }
.day-decision { display: flex; gap: 10px; align-items: baseline; padding: 5px 0; font-size: 13px; }
.day-decision .due { font: 12px ui-monospace, Menlo, monospace; opacity: .8; }
.day-decision.expired { opacity: .5; text-decoration: line-through; }
.day-talk-input { display: flex; gap: 8px; margin-top: 8px; }
.day-talk-input input { flex: 1; padding: 6px 8px; }
@media (max-width: 640px) { .day-row { grid-template-columns: 1fr 1fr; } }
```

`day.js`：

```js
window.Day = (function () {
  "use strict";

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }
  function hm(iso) { return iso ? String(iso).slice(11, 16) : "—"; }
  function body(id) { return document.querySelector("#" + id + " .day-body"); }

  function renderStatus(view) {
    var box = body("day-status"); box.innerHTML = "";
    (view.timeline || []).forEach(function (j) {
      var r = el("div", "day-row " + (j.exit === 0 ? "ok" : "alarm"));
      r.appendChild(el("span", null, "day " + j.job)); r.appendChild(el("span", null, hm(j.finished_at)));
      r.appendChild(el("span", null, "exit=" + j.exit)); r.appendChild(el("span", null, j.summary || ""));
      box.appendChild(r);
    });
    (view.launchd || []).forEach(function (a) {
      var r = el("div", "day-row " + (a.alarm ? "alarm" : "ok"));
      r.appendChild(el("span", null, a.label.replace("com.nutmeg.", "") + (a.loaded ? "" : "（未装载）")));
      r.appendChild(el("span", null, a.schedule)); r.appendChild(el("span", null, "exit=" + a.last_exit + " @" + (a.log_at ? hm(a.log_at) + " " + a.log_at.slice(5, 10) : "无时间证据")));
      r.appendChild(el("span", null, a.tail || "")); box.appendChild(r);
    });
    if (!box.children.length) box.appendChild(el("p", "obs-muted", "今日无作业记录"));
  }

  function renderDecisions(view) {
    var box = body("day-decisions"); box.innerHTML = "";
    var rows = (view.decisions || []).filter(function (d) { return d.status !== "done"; });
    if (!rows.length) box.appendChild(el("p", "obs-muted", "无待人决定"));
    rows.forEach(function (d) {
      var r = el("div", "day-decision " + d.status);
      r.appendChild(el("span", "due", d.deadline ? "截止 " + hm(d.deadline) : "无截止"));
      r.appendChild(el("span", null, "[" + d.kind + "] " + d.subject));
      r.appendChild(el("span", "obs-muted", "默认：" + d.default_action));
      box.appendChild(r);
    });
  }

  function card(m) {
    var c = el("article", "day-card");
    c.appendChild(el("h3", null, m.code + " " + (m.name || "") + " · " + hm(m.kickoff_bj)));
    var badges = el("div");
    [m.ladder, (m.labels || {}).judgment_tier, "研究 " + (m.research || {}).status,
     m.read ? (m.read.judge + "/" + m.read.status) : "无 Read"].forEach(function (t) { badges.appendChild(el("span", "day-badge", t)); });
    if (m.research && m.research.prospective === false) badges.appendChild(el("span", "day-badge alarm", "not_prospective"));
    c.appendChild(badges);
    var mk = m.market || {}, f = mk.fair || {};
    c.appendChild(el("p", null, "fair " + [f.home, f.draw, f.away].map(function (x) { return x == null ? "—" : Math.round(x * 100); }).join("/") +
      " · 位移 " + (mk.drift_pp == null ? "—" : mk.drift_pp + "pp") + " · 分歧 " + (mk.book_disagreement_pp == null ? "—" : mk.book_disagreement_pp + "pp") +
      " · 终盘 " + (mk.closing_books || "—") + " 书"));
    if (m.read) c.appendChild(el("p", null, "Read 拨动 " + m.read.moved_pp + "pp · conf " + (m.read.confidence == null ? "—" : m.read.confidence)));
    if (m.logic) c.appendChild(el("p", "day-logic", m.logic));
    var d = el("details"); d.appendChild(el("summary", null, "标签 / 实力 / 研究摘要"));
    var pre = el("pre"); pre.textContent = JSON.stringify({ labels: m.labels, strength: m.strength, research: m.research }, null, 1);
    d.appendChild(pre); c.appendChild(d);
    return c;
  }

  function renderJczq(view) {
    var box = body("day-jczq"); box.innerHTML = "";
    var b = view.brief;
    if (!b) { box.appendChild(el("p", "obs-muted", "brief.json 缺席")); return; }
    (b.jczq.matches || []).forEach(function (m) { box.appendChild(card(m)); });
    if (!(b.jczq.matches || []).length) box.appendChild(el("p", "obs-muted", "今日无板面"));
  }

  function renderZucai(view) {
    var box = body("day-zucai"); box.innerHTML = "";
    var z = view.brief && view.brief.zucai;
    if (!z || !z.issue) { box.appendChild(el("p", "obs-muted", "无在售期")); return; }
    box.appendChild(el("p", null, "期 " + z.issue + " · 截止 " + (z.sale_deadline || "未知") + " · 备料槽 " + Object.keys(z.prep || {}).join(",")));
    if (z.tiers) box.appendChild(el("p", null, "风向 " + JSON.stringify(z.tiers.wind) + " · tiers " + z.tiers.tiers_hash));
    Object.keys(z.frontier || {}).forEach(function (ch) {
      var f = z.frontier[ch];
      box.appendChild(el("p", null, ch + " 前沿 " + f.points.length + " 点 · strict 地板 P=" + f.strict_max_p));
      f.points.forEach(function (p) { box.appendChild(el("div", "day-row ok", "k" + p.k + " P=" + p.p_all + " 注数 " + p.notes + " ¥" + p.stake_yuan + " 收窄 " + p.narrowings)); });
    });
    box.appendChild(el("p", "obs-muted", z.plan ? "已定案" : "未定案（plan choose → commit 是人的门）"));
  }

  function renderRsi(view) {
    var box = body("day-rsi"); box.innerHTML = "";
    var r = view.brief && view.brief.rsi;
    if (!r) { box.appendChild(el("p", "obs-muted", "今日闭环报告缺席")); return; }
    (r.human_actions || []).forEach(function (a) { box.appendChild(el("div", "day-row ok", a)); });
    (r.failed_steps || []).forEach(function (s) { box.appendChild(el("div", "day-row alarm", "闭环步骤失败 " + s)); });
    if (!box.children.length) box.appendChild(el("p", "obs-muted", "无待人决定；判决未到期"));
  }

  function renderSession(view) {
    var box = body("day-session"); box.innerHTML = "";
    var cmd = "uv run nutmeg day status --date " + view.date + " && sed -n 1,60p .nutmeg-data/daily/" + view.date + "/session.md";
    var pre = el("pre", "day-pre", cmd); box.appendChild(pre);
    var btn = el("button", null, "复制"); btn.onclick = function () { navigator.clipboard && navigator.clipboard.writeText(cmd); };
    box.appendChild(btn);
    box.appendChild(el("p", "obs-muted", "Claude Code 里输入 /today 即读同一份 session.md（P4）。"));
  }

  function renderTalk(view) {
    var box = body("day-talk"); box.innerHTML = "";
    (view.discussion || []).forEach(function (d) { box.appendChild(el("div", "day-row ok", hm(d.at) + " " + d.who + (d.obj ? " [" + d.obj + "]" : "") + "：" + d.text)); });
  }

  function renderRetro(view) { document.querySelector("#day-retro .day-body").textContent = view.retro || "昨日复盘草稿缺席（day settle 未跑）"; }

  function render(view) {
    renderStatus(view); renderDecisions(view); renderRetro(view); renderJczq(view);
    renderZucai(view); renderRsi(view); renderSession(view); renderTalk(view);
    var err = document.querySelector("#day-errors");
    if (view.errors && view.errors.length) { err.hidden = false; err.textContent = "部分数据缺席：" + view.errors.join("；"); }
  }

  function load(date) {
    return fetch("/api/day/" + date).then(function (r) { return r.json(); }).then(render);
  }

  function mount(selector) {
    var root = document.querySelector(selector), date = root.dataset.date;
    load(date);
    var send = function () {
      var text = document.querySelector("#day-talk-text").value.trim(); if (!text) return;
      fetch("/action/day-note", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date: date, obj: document.querySelector("#day-talk-obj").value.trim(), text: text }) })
        .then(function () { document.querySelector("#day-talk-text").value = ""; load(date); });
    };
    document.querySelector("#day-talk-send").onclick = send;
    document.querySelector("#day-talk-text").addEventListener("keydown", function (e) { if (e.key === "Enter") send(); });
    setInterval(function () { load(date); }, 60000);
  }

  return { mount: mount, render: render };
})();
```

`workbench.html` 顶栏：在现有观察台链接旁加 `<a href="/day">当日</a>`（找 `href="/observe"` 那一行，在其前插入）。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_decision_web_day.py -q`
Expected: `6 passed`

- [ ] **Step 5: 手动看一眼**

Run: `uv run nutmeg day run --job brief && uv run nutmeg decision-web` 然后打开 `http://127.0.0.1:8787/day`
Expected: 八个块都在；`results-backfill` 若退出码 2 在状态条红行；讨论框回车后立刻出现在讨论块。

- [ ] **Step 6: Commit**

```bash
git add nutmeg/interfaces/web/templates/decision/day.html nutmeg/interfaces/web/templates/decision/workbench.html nutmeg/interfaces/web/static/decision/day.css nutmeg/interfaces/web/static/decision/day.js tests/test_decision_web_day.py
git commit -m "feat(web): render the day page blocks with independent degradation"
```

---

### Task 5: 证据

- [ ] 写 `docs/superpowers/evidence/2026-09-2X-daily-surface-p2.md`：`/day` 截图描述（不提交 png）、`/api/day/<date>` 的 `errors` 字段实况、测试结果行、「未做：逻辑层 m.logic 字段由 P4 填」。
- [ ] `git add docs/superpowers/evidence/2026-09-2X-daily-surface-p2.md && git commit -m "docs(evidence): daily surface P2"`

---

## Self-review

- §7 八个块 ✓（状态条含 launchd 与 day 作业；待人决定含截止与默认；竞彩卡三层的前两层 + `m.logic` 预留给 P4；足彩块保留 plan 按钮的说明，按钮本身仍在工作台 SOP 栏）。
- 写操作只有 `POST /action/day-note` ✓；页面无 `<form>` ✓。
- 降级：`day_view` 每块 try ✓；页面 `errors` 条 ✓。
- 类型一致：`day_view(*, data_dir, date, plists_dir, logs_dir, launchctl_text, today)`、`launchd_rows(*, plists_dir, logs_dir, launchctl_text, today)`、`append_discussion(data_dir, date, *, who, text, obj, at)` 与 P1 一致。
