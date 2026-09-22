# Daily Surface P5 · 对外发布与 RSI 历史三页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把当日报告的分析成果以只读、去内部信息的形式导出成静态站 `site/`（当日页、首页、方法页、战绩页），并在 `/observe` 上加三页只读历史（规则变更、因子提案轨迹、昨日追溯），帮助 Jun 与成员看懂「昨天为什么输、今天为什么这样判、系统在验证什么」。**不重做任何分析，只呈现 P1–P4 的产物。**

**Architecture:** 发布器 `day_publish.py` 只读 `daily/<日>/brief.json`、`decisions.json`（只取 kind 与 status 计数）、`experiments/scoreboard-tallies.json`、`analytics/rsi-loop/<日>.json`，用独立 Jinja 模板目录 `templates/site/` 渲染；守则以代码强制：输出 HTML 里不得含 `.nutmeg-data`、`discussion`、`timeline` 尾行、审计码明细。历史三页的数据函数在 `observe_history.py`，`git log` 与文件读取都可注入。

**Tech Stack:** Jinja2（独立 Environment）、`subprocess`（git）、FastAPI 路由、pytest。**依赖 P1–P4。**

**Spec:** 设计 §10。

---

## File structure

| 文件 | 职责 |
| --- | --- |
| Create `nutmeg/decision/observe_history.py` | `rule_changes(root, *, git)`、`factor_history(root)`、`trace_day(data_dir, date)` |
| Modify `nutmeg/interfaces/decision_web.py` | `/observe/rules`、`/observe/factors`、`/observe/trace/{date}` + `/api/observe/{rules,factors,trace/{date}}` |
| Create `templates/decision/observe/{rules,factors,trace}.html` | 服务端渲染表格，零 JS |
| Create `nutmeg/decision/day_publish.py` | `public_view(...)`、`publish_day(...)`、`SCRUB_FORBIDDEN` |
| Create `templates/site/{layout,day,index,method,record}.html` | 对外页 |
| Modify `nutmeg/interfaces/cli/day.py` | `nutmeg day publish --date --out site` |
| Tests | `tests/decision/test_observe_history.py`、`tests/test_decision_web_observe_history.py`、`tests/decision/test_day_publish.py`、追加 `tests/test_cli_day.py` |

---

### Task 1: 历史数据函数 `observe_history`

`attempts.log` 行格式（`experiments/attempts.py`）：`ts | 实验 | 参数 | 结果 | 结论`，前两行是 `#` 头。
`scoreboard-tallies.json`：`{"chains": {name: {n, issues, R_pp, ci_contains_zero, verdict, status, raw, machine_readable}}, "coverage": {...}}`。

**Files:**
- Create: `nutmeg/decision/observe_history.py`
- Test: `tests/decision/test_observe_history.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_observe_history.py
import json
from pathlib import Path

from nutmeg.decision.observe_history import factor_history, parse_attempts, rule_changes, trace_day

GIT_OUT = ("abc1234|2026-09-19T10:00:00+08:00|feat(rules): C14 exemption\n"
           "def5678|2026-09-14T09:00:00+08:00|docs(rulebook): probation r3\n")


def test_rule_changes_parses_git_log_per_tracked_file(tmp_path: Path):
    calls = []

    def git(args: list[str]) -> str:
        calls.append(args)
        return GIT_OUT if "RULEBOOK.md" in args[-1] else ""

    rows = rule_changes(tmp_path, git=git)
    assert rows[0] == {"file": "docs/sop/RULEBOOK.md", "sha": "abc1234", "at": "2026-09-19T10:00:00+08:00",
                       "subject": "feat(rules): C14 exemption"}
    assert [r["file"] for r in rows] == ["docs/sop/RULEBOOK.md"] * 2
    assert any("experiments/factors.json" in c[-1] for c in calls)


def test_parse_attempts_and_factor_history(tmp_path: Path):
    log = tmp_path / "experiments" / "attempts.log"
    log.parent.mkdir(parents=True)
    log.write_text("# 头\n# ts | 实验 | 参数 | 结果 | 结论\n"
                   "2026-09-22T17:11 | propose C11 | n=120 | R=+0.2pp | propose_zero\n"
                   "2026-09-22T17:11 | hyp 基线 | corpus=v2 | R=+1.5pp | 证伪\n"
                   "bad line\n", encoding="utf-8")
    rows = parse_attempts(log)
    assert rows == [
        {"ts": "2026-09-22T17:11", "experiment": "propose C11", "params": "n=120", "result": "R=+0.2pp", "conclusion": "propose_zero"},
        {"ts": "2026-09-22T17:11", "experiment": "hyp 基线", "params": "corpus=v2", "result": "R=+1.5pp", "conclusion": "证伪"},
    ]
    (tmp_path / "experiments" / "factors.json").write_text(json.dumps({"factors": [
        {"factor_id": "C11", "layer": "probability", "current_weight_pp": 0, "rule_name": "价格带"}]}), encoding="utf-8")
    hist = factor_history(tmp_path)
    assert hist["factors"][0]["factor_id"] == "C11" and hist["factors"][0]["attempts"][0]["conclusion"] == "propose_zero"
    assert hist["other_attempts"][0]["experiment"] == "hyp 基线"


def test_trace_day_joins_reads_with_next_day_results(tmp_path: Path):
    out = tmp_path / "daily" / "2026-09-22"; out.mkdir(parents=True)
    (out / "brief.json").write_text(json.dumps({"date": "2026-09-22", "jczq": {"matches": [
        {"code": "周二001", "name": "A vs B", "ladder": "偏移",
         "read": {"judge": "ai", "prior": {"home": .5, "draw": .3, "away": .2}, "belief": {"home": .3, "draw": .3, "away": .4}}},
        {"code": "周二002", "name": "C vs D", "ladder": "跟市场",
         "read": {"judge": "market-anchor", "prior": {"home": .6, "draw": .2, "away": .2}, "belief": {"home": .6, "draw": .2, "away": .2}}},
        {"code": "周二003", "name": "E vs F", "ladder": "未判", "read": None},
    ], "counts": {}}, "zucai": {"issue": None}, "rsi": None, "factors": [], "errors": []}), encoding="utf-8")
    nxt = tmp_path / "daily" / "2026-09-23"; nxt.mkdir()
    (nxt / "results-90.json").write_text(json.dumps({"周二001": {"outcome_90": "0", "goals_h": 0, "goals_a": 1},
                                                      "周二002": {"outcome_90": "1", "goals_h": 1, "goals_a": 1}}), encoding="utf-8")
    (tmp_path / "analytics" / "rsi-loop").mkdir(parents=True)
    (tmp_path / "analytics" / "rsi-loop" / "2026-09-22.json").write_text(json.dumps({"verdicts": [
        {"cmd": "rsi verdict --exp F3", "status": "not_due", "line": "未到期：距 n_min 还差 97"}]}), encoding="utf-8")
    tr = trace_day(tmp_path, "2026-09-22")
    by = {r["code"]: r for r in tr["matches"]}
    assert by["周二001"] == {"code": "周二001", "name": "A vs B", "ladder": "偏移", "judge": "ai", "prior_top": "home",
                            "belief_top": "away", "outcome": "away", "market_right": False, "read_right": True, "moved_helped": True}
    assert by["周二002"]["read_right"] is False and by["周二002"]["moved_helped"] is None
    assert by["周二003"]["outcome"] is None
    assert tr["not_due"] == [{"exp": "F3", "line": "未到期：距 n_min 还差 97"}]
    assert tr["summary"] == {"graded": 2, "read_right": 1, "market_right": 0, "moved": 1, "moved_helped": 1}
```

- [ ] **Step 2: Run** → `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/observe_history.py
"""`/observe/{rules,factors,trace}` 的只读数据（设计 §10）。git 与文件读取可注入；缺数据返回空结构。"""
from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from datetime import date as _date
from datetime import timedelta
from pathlib import Path

from nutmeg.decision.day_paths import BRIEF, RESULTS_90, day_dir

Git = Callable[[list[str]], str]
TRACKED = ("docs/sop/RULEBOOK.md", "experiments/factors.json", "docs/sop/CONSTITUTION.md")
OUTCOME_FACE = {"3": "home", "1": "draw", "0": "away"}


def run_git(args: list[str]) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=False).stdout
    except OSError:
        return ""


def rule_changes(root: Path, *, git: Git = run_git, limit: int = 60) -> list[dict]:
    rows = []
    for rel in TRACKED:
        out = git(["-C", str(root), "log", f"-{limit}", "--date=iso-strict", "--format=%h|%ad|%s", "--", rel])
        for line in out.splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3:
                rows.append({"file": rel, "sha": parts[0], "at": parts[1], "subject": parts[2]})
    return sorted(rows, key=lambda r: r["at"], reverse=True)


def parse_attempts(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = [p.strip() for p in line.split(" | ")]
        if len(parts) != 5:
            continue
        rows.append(dict(zip(("ts", "experiment", "params", "result", "conclusion"), parts)))
    return rows


def factor_history(root: Path) -> dict:
    attempts = parse_attempts(root / "experiments" / "attempts.log")
    try:
        factors = json.loads((root / "experiments" / "factors.json").read_text(encoding="utf-8")).get("factors") or []
    except (FileNotFoundError, ValueError):
        factors = []
    used: set[int] = set()
    out = []
    for f in factors:
        fid = str(f.get("factor_id"))
        mine = []
        for i, a in enumerate(attempts):
            if fid and fid in a["experiment"] and i not in used:
                used.add(i)
                mine.append(a)
        out.append({"factor_id": fid, "layer": f.get("layer"), "current_weight_pp": f.get("current_weight_pp"),
                    "rule_name": f.get("rule_name"), "attempts": mine})
    return {"factors": out, "other_attempts": [a for i, a in enumerate(attempts) if i not in used]}


def _top(p: dict | None) -> str | None:
    if not p:
        return None
    return max(("home", "draw", "away"), key=lambda k: float(p.get(k, 0)))


def trace_day(data_dir: Path, date: str) -> dict:
    try:
        brief = json.loads((day_dir(data_dir, date) / BRIEF).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        brief = {"jczq": {"matches": []}}
    nxt = (_date.fromisoformat(date) + timedelta(days=1)).isoformat()
    try:
        results = json.loads((day_dir(data_dir, nxt) / RESULTS_90).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        results = {}
    matches, summary = [], {"graded": 0, "read_right": 0, "market_right": 0, "moved": 0, "moved_helped": 0}
    for m in brief.get("jczq", {}).get("matches", []):
        read = m.get("read") or {}
        outcome = OUTCOME_FACE.get(str((results.get(m["code"]) or {}).get("outcome_90")))
        prior_top, belief_top = _top(read.get("prior")), _top(read.get("belief"))
        moved = bool(read) and prior_top != belief_top
        row = {"code": m["code"], "name": m.get("name"), "ladder": m.get("ladder"), "judge": read.get("judge"),
               "prior_top": prior_top, "belief_top": belief_top, "outcome": outcome,
               "market_right": (prior_top == outcome) if outcome and prior_top else None,
               "read_right": (belief_top == outcome) if outcome and belief_top else None,
               "moved_helped": ((belief_top == outcome) if outcome else None) if moved else None}
        matches.append(row)
        if outcome and read:
            summary["graded"] += 1
            summary["read_right"] += int(row["read_right"] is True)
            summary["market_right"] += int(row["market_right"] is True)
            summary["moved"] += int(moved)
            summary["moved_helped"] += int(row["moved_helped"] is True)
    try:
        loop = json.loads((Path(data_dir) / "analytics" / "rsi-loop" / f"{date}.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        loop = {}
    not_due = [{"exp": v["cmd"].split("--exp")[-1].split()[0], "line": v.get("line", "")}
               for v in loop.get("verdicts") or [] if v.get("status") == "not_due" and "--exp" in v.get("cmd", "")]
    return {"date": date, "matches": matches, "not_due": not_due, "summary": summary}
```

- [ ] **Step 4: Run** `uv run pytest tests/decision/test_observe_history.py -q` → `3 passed`

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/observe_history.py tests/decision/test_observe_history.py
git commit -m "feat(observe): rule-change log, factor proposal history and day trace data"
```

---

### Task 2: 三页路由（服务端渲染，零写操作）

**Files:**
- Modify: `nutmeg/interfaces/decision_web.py`
- Create: `nutmeg/interfaces/web/templates/decision/observe/rules.html`、`factors.html`、`trace.html`
- Test: `tests/test_decision_web_observe_history.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_decision_web_observe_history.py
import json
from pathlib import Path

from fastapi.testclient import TestClient

from nutmeg.decision.store import DecisionStore
from nutmeg.interfaces.decision_web import create_decision_app


def _client(tmp_path: Path) -> TestClient:
    data = tmp_path / "data"
    (data / "daily" / "2026-09-22").mkdir(parents=True)
    (data / "daily" / "2026-09-22" / "brief.json").write_text(json.dumps(
        {"date": "2026-09-22", "jczq": {"matches": [{"code": "周二001", "name": "A vs B", "ladder": "跟市场", "read": None}], "counts": {}},
         "zucai": {"issue": None}, "rsi": None, "factors": [], "errors": []}), encoding="utf-8")
    app = create_decision_app(store=DecisionStore(data / "jczq" / "decision"), output_dir=data / "jczq",
                              data_dir=data, launchctl=lambda: "",
                              git=lambda args: "abc1234|2026-09-19T10:00:00+08:00|feat(rules): x\n")
    return TestClient(app)


def test_three_history_pages_render_read_only(tmp_path: Path):
    c = _client(tmp_path)
    for url, needle in (("/observe/rules", "abc1234"), ("/observe/factors", "因子"), ("/observe/trace/2026-09-22", "周二001")):
        r = c.get(url)
        assert r.status_code == 200 and needle in r.text and "<form" not in r.text and "POST" not in r.text


def test_history_apis(tmp_path: Path):
    c = _client(tmp_path)
    assert c.get("/api/observe/rules").json()[0]["sha"] == "abc1234"
    assert "factors" in c.get("/api/observe/factors").json()
    assert c.get("/api/observe/trace/2026-09-22").json()["matches"][0]["code"] == "周二001"
```

- [ ] **Step 2: Run** → `TypeError: ... 'git'`

- [ ] **Step 3: Implement**

签名再加 `git=None`；`app.state.git = git or run_git`（`from nutmeg.decision.observe_history import run_git, rule_changes, factor_history, trace_day`）。路由（放在 `/observe/day/{date}` 之后）：

```python
    _root = Path(__file__).resolve().parents[2]

    @app.get("/api/observe/rules")
    def observe_rules_api() -> list[dict]:
        return rule_changes(_root, git=app.state.git)

    @app.get("/api/observe/factors")
    def observe_factors_api() -> dict:
        return factor_history(_root)

    @app.get("/api/observe/trace/{date}")
    def observe_trace_api(date: str) -> dict:
        return trace_day(app.state.data_dir, date)

    @app.get("/observe/rules")
    def observe_rules_page(request: Request):
        return templates.TemplateResponse(request, "decision/observe/rules.html",
                                          {"title": "规则变更", "rows": rule_changes(_root, git=app.state.git)})

    @app.get("/observe/factors")
    def observe_factors_page(request: Request):
        return templates.TemplateResponse(request, "decision/observe/factors.html",
                                          {"title": "因子提案史", "hist": factor_history(_root)})

    @app.get("/observe/trace/{date}")
    def observe_trace_page(request: Request, date: str):
        return templates.TemplateResponse(request, "decision/observe/trace.html",
                                          {"title": f"追溯 {date}", "tr": trace_day(app.state.data_dir, date)})
```

模板（三个都 `{% extends "decision/observe/layout.html" %}`）：

`rules.html`：

```html
{% extends "decision/observe/layout.html" %}
{% block body %}
<header class="obs-topbar"><div><span class="obs-mark">RSI</span><strong>规则变更时间线</strong></div>
<nav><a class="obs-back" href="/observe">观察台</a></nav></header>
<main class="obs-main"><section class="obs-panel">
<p class="obs-kicker">RULEBOOK / factors.json / CONSTITUTION 的每次提交；每条变更都应能挂到一条实验或判决</p>
<table class="obs-table"><tr><th>时间</th><th>文件</th><th>提交</th><th>主题</th></tr>
{% for r in rows %}<tr><td>{{ r.at[:16] }}</td><td>{{ r.file }}</td><td><code>{{ r.sha }}</code></td><td>{{ r.subject }}</td></tr>{% endfor %}
{% if not rows %}<tr><td colspan="4" class="obs-muted">无记录（git 不可用或文件未变过）</td></tr>{% endif %}
</table></section></main>
{% endblock %}
```

`factors.html`：

```html
{% extends "decision/observe/layout.html" %}
{% block body %}
<header class="obs-topbar"><div><span class="obs-mark">RSI</span><strong>因子提案史</strong></div>
<nav><a class="obs-back" href="/observe">观察台</a></nav></header>
<main class="obs-main">
{% for f in hist.factors %}
<section class="obs-panel"><h3>{{ f.factor_id }} <span class="obs-muted">{{ f.layer }} · 现 {{ f.current_weight_pp }}pp · {{ f.rule_name }}</span></h3>
<table class="obs-table"><tr><th>时间</th><th>参数</th><th>结果</th><th>结论</th></tr>
{% for a in f.attempts %}<tr><td>{{ a.ts }}</td><td>{{ a.params }}</td><td>{{ a.result }}</td><td>{{ a.conclusion }}</td></tr>{% endfor %}
{% if not f.attempts %}<tr><td colspan="4" class="obs-muted">尚无提案记录</td></tr>{% endif %}
</table></section>
{% endfor %}
<section class="obs-panel"><h3>其它尝试（假设批次 / 搜索）</h3>
<table class="obs-table">{% for a in hist.other_attempts[-40:] %}<tr><td>{{ a.ts }}</td><td>{{ a.experiment }}</td><td>{{ a.result }}</td><td>{{ a.conclusion }}</td></tr>{% endfor %}</table></section>
</main>
{% endblock %}
```

`trace.html`：

```html
{% extends "decision/observe/layout.html" %}
{% block body %}
<header class="obs-topbar"><div><span class="obs-mark">RSI</span><strong>追溯 {{ tr.date }}</strong><span class="obs-sub">昨天哪条实验本可以改变哪场</span></div>
<nav><a class="obs-back" href="/observe">观察台</a></nav></header>
<main class="obs-main">
<section class="obs-panel"><p>已结账 {{ tr.summary.graded }} 场 · Read 对 {{ tr.summary.read_right }} · 市场对 {{ tr.summary.market_right }} · 拨动 {{ tr.summary.moved }} 场，拨对 {{ tr.summary.moved_helped }}</p>
<table class="obs-table"><tr><th>场</th><th>阶梯</th><th>judge</th><th>市场面</th><th>判断面</th><th>开出</th><th>Read</th><th>拨动</th></tr>
{% for m in tr.matches %}<tr><td>{{ m.code }} {{ m.name }}</td><td>{{ m.ladder }}</td><td>{{ m.judge or "—" }}</td><td>{{ m.prior_top or "—" }}</td><td>{{ m.belief_top or "—" }}</td><td>{{ m.outcome or "未结" }}</td>
<td>{% if m.read_right is none %}—{% elif m.read_right %}✓{% else %}✗{% endif %}</td><td>{% if m.moved_helped is none %}—{% elif m.moved_helped %}✓{% else %}✗{% endif %}</td></tr>{% endfor %}
</table></section>
<section class="obs-panel"><h3>当天未到判决期的实验</h3>
<ul>{% for e in tr.not_due %}<li><a href="/observe/exp/{{ e.exp }}">{{ e.exp }}</a> — {{ e.line }}</li>{% endfor %}</ul>
{% if not tr.not_due %}<p class="obs-muted">无（或当天闭环报告缺席）</p>{% endif %}
</section></main>
{% endblock %}
```

`observe.css` 加：

```css
.obs-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.obs-table th, .obs-table td { text-align: left; padding: 5px 8px; border-bottom: 1px solid rgba(127,127,127,.25); }
```

`panorama.html` 顶栏加三个链接：`<a href="/observe/rules">规则</a><a href="/observe/factors">因子</a><a href="/observe/trace/{{ today }}">追溯</a>`（`today` 由路由传 `_today()`）。

- [ ] **Step 4: Run** `uv run pytest tests/test_decision_web_observe_history.py tests/test_decision_web_observe.py -q` → passed

- [ ] **Step 5: Commit**

```bash
git add nutmeg/interfaces/decision_web.py nutmeg/interfaces/web/templates/decision/observe/rules.html nutmeg/interfaces/web/templates/decision/observe/factors.html nutmeg/interfaces/web/templates/decision/observe/trace.html nutmeg/interfaces/web/templates/decision/observe/panorama.html nutmeg/interfaces/web/static/decision/observe.css tests/test_decision_web_observe_history.py
git commit -m "feat(observe): rules / factors / trace read-only history pages"
```

---

### Task 3: 对外视图与发布器 `day_publish`

守则（§10）：显示亏损与空仓；不出现购买指令式措辞；不放 C 类资讯；不放内部路径与讨论记录。以代码强制：`SCRUB_FORBIDDEN = (".nutmeg-data", "discussion", "timeline", "override", "user-override")`，任一出现在输出 HTML 即 `PublishError`。

**Files:**
- Create: `nutmeg/decision/day_publish.py`
- Create: `nutmeg/interfaces/web/templates/site/layout.html`、`day.html`、`index.html`、`method.html`、`record.html`
- Test: `tests/decision/test_day_publish.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_day_publish.py
import json
from pathlib import Path

import pytest

from nutmeg.decision.day_publish import PublishError, public_view, publish_day


def _data(tmp_path: Path) -> tuple[Path, Path]:
    data, root = tmp_path / "data", tmp_path / "root"
    out = data / "daily" / "2026-09-23"; out.mkdir(parents=True)
    (out / "brief.json").write_text(json.dumps({"date": "2026-09-23", "generated_at": "2026-09-23T12:00:00+08:00",
        "jczq": {"matches": [{"code": "周三001", "name": "A vs B", "competition": "英超", "kickoff_bj": "2026-09-23T19:30:00+08:00",
                              "market": {"fair": {"home": .52, "draw": .26, "away": .22}, "drift_pp": 2.0},
                              "labels": {"judgment_tier": "deep_research", "anchor_integrity": "pass"},
                              "research": {"status": "done", "prospective": True, "summary": "秘密内部备注 .nutmeg-data/x"},
                              "read": {"judge": "ai:jczq-analyst", "status": "draft", "moved_pp": 6.0, "confidence": 4},
                              "ladder": "偏移", "audit": {"naked": {"faces": "3", "blocking": False, "findings": []}},
                              "logic": {"status": "ok", "text": "锚方完整度 pass 定了面。", "cites": ["labels.anchor_integrity"]}}],
                 "counts": {"matches": 1, "deep_research": 1, "price_only": 0, "drafts": 1}},
        "zucai": {"issue": "26132", "sale_deadline": "2026-09-23T21:00:00+08:00", "tiers": {"wind": {"regime": "hot"}},
                  "frontier": {"renjiu": {"points": [{"k": 0, "p_all": .05, "notes": 8, "stake_yuan": 16}], "strict_max_p": .02}}, "plan": None, "prep": {}},
        "rsi": {"human_actions": ["因子 C11：propose_zero"], "failed_steps": []}, "factors": [], "errors": []}), encoding="utf-8")
    (out / "decisions.json").write_text(json.dumps([{"id": "read:周三001", "kind": "approve_read", "status": "open"}]), encoding="utf-8")
    (out / "discussion.jsonl").write_text('{"who":"jun","text":"私下讨论"}\n', encoding="utf-8")
    (root / "experiments").mkdir(parents=True)
    (root / "experiments" / "scoreboard-tallies.json").write_text(json.dumps({"chains": {
        "被排面链": {"n": 291, "issues": 18, "R_pp": -2.3, "ci_contains_zero": True, "verdict": "falsified", "status": "falsified",
                  "raw": "⛔证伪", "machine_readable": True}}, "coverage": {"chains": 1, "machine_readable": 1}}), encoding="utf-8")
    return data, root


def test_public_view_drops_internal_fields(tmp_path: Path):
    data, root = _data(tmp_path)
    view = public_view(data_dir=data, root=root, date="2026-09-23")
    m = view["matches"][0]
    assert set(m) == {"code", "name", "competition", "kickoff", "fair", "drift_pp", "tier", "ladder", "judge", "confidence",
                      "research_status", "prospective", "logic", "expressions"}
    assert m["logic"] == "锚方完整度 pass 定了面。" and m["expressions"] == {"naked": "3 ✓"}
    assert "summary" not in json.dumps(m) and view["decisions"] == {"open": 1, "total": 1}
    assert view["zucai"] == {"issue": "26132", "sale_deadline": "2026-09-23T21:00:00+08:00", "wind": {"regime": "hot"},
                             "frontier_points": {"renjiu": 1}, "plan_status": "未定案"}
    assert view["record"]["chains"][0]["name"] == "被排面链" and view["record"]["coverage"]["chains"] == 1


def test_publish_day_writes_four_pages_and_scrubs(tmp_path: Path):
    data, root = _data(tmp_path)
    report = publish_day(data_dir=data, root=root, date="2026-09-23", out_dir=tmp_path / "site")
    for rel in ("2026-09-23/index.html", "index.html", "method.html", "record.html"):
        html = (tmp_path / "site" / rel).read_text(encoding="utf-8")
        assert ".nutmeg-data" not in html and "私下讨论" not in html and "discussion" not in html, rel
    day = (tmp_path / "site" / "2026-09-23" / "index.html").read_text(encoding="utf-8")
    assert "A vs B" in day and "锚方完整度 pass 定了面。" in day and "空仓" in day
    assert "被排面链" in (tmp_path / "site" / "record.html").read_text(encoding="utf-8")
    assert report == {"date": "2026-09-23", "pages": 4, "matches": 1}


def test_publish_refuses_when_forbidden_text_leaks(tmp_path: Path, monkeypatch):
    data, root = _data(tmp_path)
    monkeypatch.setattr("nutmeg.decision.day_publish.SCRUB_FORBIDDEN", ("A vs B",))
    with pytest.raises(PublishError):
        publish_day(data_dir=data, root=root, date="2026-09-23", out_dir=tmp_path / "site")
```

- [ ] **Step 2: Run** → `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/day_publish.py
"""对外只读导出（设计 §10）：只呈现 P1–P4 的产物，不重做分析；守则以代码强制。"""
from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from nutmeg.decision.day_paths import BRIEF, DECISIONS, day_dir

SCRUB_FORBIDDEN = (".nutmeg-data", "discussion", "timeline", "override")
TEMPLATES = Path(__file__).resolve().parents[1] / "interfaces" / "web" / "templates" / "site"


class PublishError(RuntimeError):
    pass


def _json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


def _match(m: dict) -> dict:
    read, audit, logic = m.get("read") or {}, m.get("audit") or {}, m.get("logic") or {}
    return {
        "code": m.get("code"), "name": m.get("name"), "competition": m.get("competition"),
        "kickoff": (m.get("kickoff_bj") or "")[11:16],
        "fair": (m.get("market") or {}).get("fair"), "drift_pp": (m.get("market") or {}).get("drift_pp"),
        "tier": (m.get("labels") or {}).get("judgment_tier"), "ladder": m.get("ladder"),
        "judge": read.get("judge"), "confidence": read.get("confidence"),
        "research_status": (m.get("research") or {}).get("status"),
        "prospective": (m.get("research") or {}).get("prospective"),
        "logic": logic.get("text") if logic.get("status") == "ok" else None,
        "expressions": {k: f"{v['faces']} {'✗' if v.get('blocking') else '✓'}"
                        for k, v in audit.items() if isinstance(v, dict) and "faces" in v},
    }


def public_view(*, data_dir: Path, root: Path, date: str) -> dict:
    out = day_dir(data_dir, date)
    brief = _json(out / BRIEF, {"jczq": {"matches": [], "counts": {}}, "zucai": {}, "rsi": None})
    decisions = _json(out / DECISIONS, [])
    tallies = _json(root / "experiments" / "scoreboard-tallies.json", {"chains": {}, "coverage": {}})
    z = brief.get("zucai") or {}
    return {
        "date": date, "generated_at": brief.get("generated_at"),
        "counts": brief.get("jczq", {}).get("counts", {}),
        "matches": [_match(m) for m in brief.get("jczq", {}).get("matches", [])],
        "zucai": {"issue": z.get("issue"), "sale_deadline": z.get("sale_deadline"),
                  "wind": (z.get("tiers") or {}).get("wind"),
                  "frontier_points": {ch: len(doc.get("points") or []) for ch, doc in (z.get("frontier") or {}).items()},
                  "plan_status": "已定案" if z.get("plan") else "未定案"},
        "rsi_pending": len((brief.get("rsi") or {}).get("human_actions") or []),
        "decisions": {"open": sum(1 for d in decisions if d.get("status") == "open"), "total": len(decisions)},
        "record": {"chains": [{"name": k, **v} for k, v in (tallies.get("chains") or {}).items()],
                   "coverage": tallies.get("coverage") or {}},
    }


def _env() -> Environment:
    return Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))


def publish_day(*, data_dir: Path, root: Path, date: str, out_dir: Path) -> dict:
    view = public_view(data_dir=data_dir, root=root, date=date)
    env = _env()
    days = sorted(p.name for p in (Path(data_dir) / "daily").glob("20*") if (p / BRIEF).exists())[-30:]
    pages = {
        Path(date) / "index.html": env.get_template("day.html").render(v=view),
        Path("index.html"): env.get_template("index.html").render(v=view, days=days),
        Path("method.html"): env.get_template("method.html").render(v=view),
        Path("record.html"): env.get_template("record.html").render(v=view),
    }
    for rel, html in pages.items():
        for bad in SCRUB_FORBIDDEN:
            if bad in html:
                raise PublishError(f"{rel}: 输出含禁用文本 {bad!r}")
        target = Path(out_dir) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
    return {"date": date, "pages": len(pages), "matches": len(view["matches"])}
```

`templates/site/layout.html`：

```html
<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{% block title %}Nutmeg{% endblock %}</title>
<style>
:root{color-scheme:light dark;--fg:#1c1c1c;--bg:#fbfaf7;--mute:#6b6b6b;--line:rgba(127,127,127,.3)}
@media(prefers-color-scheme:dark){:root{--fg:#ecebe7;--bg:#141414;--mute:#a3a3a3}}
body{margin:0;padding:20px 16px;font:14px/1.6 system-ui,-apple-system,"PingFang SC",sans-serif;color:var(--fg);background:var(--bg);max-width:960px;margin-inline:auto}
nav a{margin-right:14px;color:inherit}h1{font-size:22px;margin:.4em 0}h2{font-size:16px;margin:1.4em 0 .5em;opacity:.8}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
.card{border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0}.mute{color:var(--mute)}.badge{display:inline-block;padding:1px 8px;border-radius:999px;background:rgba(127,127,127,.18);font-size:11px;margin-right:6px}
</style></head><body>
<nav><a href="/index.html">今日</a><a href="/record.html">战绩</a><a href="/method.html">方法</a></nav>
{% block body %}{% endblock %}
<p class="mute">本站只呈现判断过程与结果；不构成购买建议；亏损与空仓如实显示。</p>
</body></html>
```

`day.html`：

```html
{% extends "layout.html" %}{% block title %}当日 {{ v.date }}{% endblock %}
{% block body %}
<h1>当日报告 · {{ v.date }}</h1>
<p class="mute">生成 {{ v.generated_at }} · 竞彩 {{ v.counts.matches }} 场（深研 {{ v.counts.deep_research }}）· 待人决定 {{ v.decisions.open }}/{{ v.decisions.total }} · 默认动作：空仓</p>
<h2>竞彩</h2>
{% for m in v.matches %}<div class="card"><strong>{{ m.code }} {{ m.name }}</strong> <span class="mute">{{ m.competition }} · {{ m.kickoff }}</span><br>
<span class="badge">{{ m.ladder }}</span><span class="badge">{{ m.tier }}</span><span class="badge">研究 {{ m.research_status }}</span>{% if m.prospective is false %}<span class="badge">非前瞻</span>{% endif %}
{% for k, e in m.expressions.items() %}<span class="badge">{{ k }} {{ e }}</span>{% endfor %}
<div>fair {% if m.fair %}{{ (m.fair.home*100)|round|int }}/{{ (m.fair.draw*100)|round|int }}/{{ (m.fair.away*100)|round|int }}{% else %}—{% endif %} · 位移 {{ m.drift_pp if m.drift_pp is not none else "—" }}pp · {{ m.judge or "无 Read" }}{% if m.confidence %} conf {{ m.confidence }}{% endif %}</div>
{% if m.logic %}<p>{{ m.logic }}</p>{% else %}<p class="mute">逻辑层未生成</p>{% endif %}</div>{% endfor %}
{% if not v.matches %}<p class="mute">今日无板面</p>{% endif %}
<h2>传统足彩 {{ v.zucai.issue or "" }}</h2>
{% if v.zucai.issue %}<p>截止 {{ v.zucai.sale_deadline }} · 风向 {{ v.zucai.wind }} · 前沿点 {{ v.zucai.frontier_points }} · {{ v.zucai.plan_status }}（未定案＝空仓）</p>{% else %}<p class="mute">无在售期</p>{% endif %}
<h2>系统在验证什么</h2><p>今日 RSI 待人决定 {{ v.rsi_pending }} 条；实验状态见方法页。</p>
{% endblock %}
```

`index.html`：

```html
{% extends "layout.html" %}{% block title %}Nutmeg 日报{% endblock %}
{% block body %}<h1>Nutmeg 日报</h1><p><a href="/{{ v.date }}/index.html">最新：{{ v.date }}</a></p>
<ul>{% for d in days|reverse %}<li><a href="/{{ d }}/index.html">{{ d }}</a></li>{% endfor %}</ul>{% endblock %}
```

`method.html`（静态方法页；文字来自 CONSTITUTION 摘要与设计 §6）：

```html
{% extends "layout.html" %}{% block title %}方法{% endblock %}
{% block body %}<h1>方法</h1>
<h2>判断的字典序</h2><ol><li>事实层定面：机制三态（活 / 死 / 从不），死必有三证。</li><li>P 层定结构：帽内最大化命中概率；期望值不进决策层。</li><li>奖池只破平局。</li></ol>
<h2>表达阶梯</h2><p>跟市场 → 偏移 → 降格 → 翻面；每一格都要过审计门，翻面需三门槛。</p>
<h2>判断如何自我修正（RSI）</h2>
<figure><svg viewBox="0 0 720 140" role="img" aria-label="每日闭环：终盘补采到记分牌解析九步，判决与部署由人">
<defs><marker id="a" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="currentColor"/></marker></defs>
{% set steps = ["终盘补采","语料重建","前瞻结账","判决到期","因子提案","假设批次","因子搜索","实力指数","记分牌"] %}
{% for s in steps %}<rect x="{{ 10 + loop.index0*78 }}" y="40" width="70" height="36" rx="6" fill="none" stroke="currentColor"/><text x="{{ 45 + loop.index0*78 }}" y="63" font-size="11" text-anchor="middle" fill="currentColor">{{ s }}</text>
{% if not loop.last %}<line x1="{{ 80 + loop.index0*78 }}" y1="58" x2="{{ 88 + loop.index0*78 }}" y2="58" stroke="currentColor" marker-end="url(#a)"/>{% endif %}{% endfor %}
<text x="360" y="120" font-size="12" text-anchor="middle" fill="currentColor">判决只由系统出，部署与规则修改只由人做；提案从不直接改权重</text></svg>
<figcaption>每日闭环九步与人的门。</figcaption></figure>
<p>每条判据都是一个实验：登记 → 观察 → 结账 → 判决（证伪 / 存活）→ 只有存活且到期才可能由人部署。</p>
{% endblock %}
```

`record.html`：

```html
{% extends "layout.html" %}{% block title %}战绩{% endblock %}
{% block body %}<h1>战绩与判据存亡</h1>
<p class="mute">来自记分牌的机器可读链：{{ v.record.coverage.machine_readable }}/{{ v.record.coverage.chains }}。证伪的判据照登。</p>
<table><tr><th>判据链</th><th>n</th><th>期</th><th>残差 pp</th><th>CI 含 0</th><th>判决</th></tr>
{% for c in v.record.chains %}<tr><td>{{ c.name }}</td><td>{{ c.n }}</td><td>{{ c.issues }}</td><td>{{ c.R_pp }}</td><td>{{ "是" if c.ci_contains_zero else "否" }}</td><td>{{ c.verdict }}</td></tr>{% endfor %}
</table>{% endblock %}
```

- [ ] **Step 4: Run** `uv run pytest tests/decision/test_day_publish.py -q` → `3 passed`

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/day_publish.py nutmeg/interfaces/web/templates/site tests/decision/test_day_publish.py
git commit -m "feat(publish): read-only public export of the daily brief with scrub guard"
```

---

### Task 4: CLI `nutmeg day publish` 与发布流程

**Files:**
- Modify: `nutmeg/interfaces/cli/day.py`
- Test: 追加 `tests/test_cli_day.py`

- [ ] **Step 1: Write the failing test**

```python
def test_day_publish_writes_site(tmp_path: Path):
    data = _data(tmp_path)
    runner.invoke(app, ["day", "run", "--job", "brief", "--date", "2026-09-23", "--data-dir", str(data)])
    r = runner.invoke(app, ["day", "publish", "--date", "2026-09-23", "--data-dir", str(data), "--out", str(tmp_path / "site")])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "site" / "2026-09-23" / "index.html").exists() and "pages=4" in r.output
```

- [ ] **Step 2: Run** → `No such command 'publish'`

- [ ] **Step 3: Implement**

```python
@day_app.command("publish")
def publish(date: str | None = _DATE, data_dir: Path = _DATA_DIR,
            out: Path = typer.Option(Path("site"), "--out", help="静态站输出目录（gitignored）")) -> None:
    """对外只读导出：site/<日>/index.html + index/method/record。含禁用文本即失败。"""
    from nutmeg.decision.day_publish import PublishError, publish_day

    ctx = _ctx(date, data_dir)
    try:
        report = publish_day(data_dir=ctx.data_dir, root=ctx.root, date=ctx.date, out_dir=Path(out))
    except PublishError as exc:
        typer.echo(f"day error: {exc}")
        raise typer.Exit(code=1) from exc
    typer.echo(f"published {report['date']} pages={report['pages']} matches={report['matches']} → {out}")
```

`.gitignore` 加 `site/`。

- [ ] **Step 4: Run** `uv run pytest tests/test_cli_day.py -q` → passed

- [ ] **Step 5: 发布流程写进 evidence（分享是 Jun 的门）**

- 小圈子：在 Claude Code 会话里用 Artifact 工具把 `site/<日>/index.html` 发布为私有页并把链接给 Jun 决定分享（发布器不自动做）。
- 静态托管：`site/` 整目录推到任一静态主机；每日由 `day brief` 之后追加 `nutmeg day publish` 一步（P3 的 `com.nutmeg.day.brief.plist` 命令末尾加 `; uv run nutmeg day publish`）。

- [ ] **Step 6: Commit**

```bash
git add nutmeg/interfaces/cli/day.py .gitignore tests/test_cli_day.py ops/launchd/com.nutmeg.day.brief.plist tests/test_launchd_plists.py
git commit -m "feat(cli): nutmeg day publish; brief timer publishes the public site"
```

---

### Task 5: 证据

- [ ] `docs/superpowers/evidence/2026-09-2X-daily-surface-p5.md`：`/observe/rules` 前 10 行、`/observe/trace/<昨日>` 的 summary 行、`site/` 四页大小、scrub 守则命中过什么（应为 0）、Artifact 链接（若发布）。
- [ ] Commit。

---

## Self-review

- §10 四页 ✓（当日 / 首页 / 方法 / 战绩）；三页 `/observe/{rules,factors,trace}` ✓；守则四条 → `SCRUB_FORBIDDEN` + 模板不含 discussion/审计明细 + 页脚声明 + 战绩表照登证伪 ✓；「不重做分析」：发布器只读 brief/decisions/tallies ✓。
- 类型一致：`public_view(*, data_dir, root, date)`、`publish_day(*, data_dir, root, date, out_dir)`、`trace_day(data_dir, date)`、`rule_changes(root, *, git, limit)`、`factor_history(root)`；`create_decision_app` 新增 `git` 参数与 P2 的 `data_dir/launchctl` 并列。
- 未覆盖、明说：成员账号 / 访问控制不在本包（artifact 私有链接或静态主机的访问策略由 Jun 定）。
