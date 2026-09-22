# Daily Surface P4 · 逻辑层撰稿、审计列、`/today` 会话入口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给每场卡片补上「为什么落在这一格」的逻辑层（headless `claude -p`，只解释不判断，每句引用必须指向卡片里存在的字段）和三种默认表达的审计码列；并给 Claude Code / Codex 一个 `/today` 入口，让会话从 `session.md` 的结论与待人决定开始。

**Architecture:** 逻辑层与 `research_runner` 同一注入模式（`Claude = Callable[[str, str], tuple[int, str]]`），无联网、单轮、cwd 空目录；输出严格 JSON `{code, logic, cites}`；`cites` 用点路径（`market.drift_pp`）逐一在卡片里解析，任一不存在即拒收、该场写 `not_generated`。审计列直接调 `legs_audit.legs_from_dict` + `audit_legs`，把竞彩卡片标签映射成 `Leg`。

**Tech Stack:** Python、`claude` CLI（订阅）、pytest。**依赖 P1、P2。**

**Spec:** 设计 §6.1（审计码）、§6.3（逻辑层）、§8（会话入口）、§9（不产生 belief、cites 校验）。

---

## File structure

| 文件 | 职责 |
| --- | --- |
| Create `nutmeg/decision/day_audit.py` | `audit_defaults(card) -> dict`：裸单 / 模态双选 / 全包 三种表达的审计码 |
| Modify `nutmeg/decision/day_brief.py` | 卡片加 `audit` 字段；`render_brief_md` 加逻辑行 |
| Create `nutmeg/decision/brief_prompt.py` | `LOGIC_SYSTEM_PROMPT`、`render_logic_input(card, factors)` |
| Create `nutmeg/decision/brief_writer.py` | `write_logic(brief, *, claude, budget)`、`validate_cites`、`_claude_cli` |
| Modify `nutmeg/decision/day_runner.py`、`nutmeg/interfaces/cli/day.py` | `DayContext.claude`；`day run --job brief --with-logic` |
| Modify `nutmeg/interfaces/web/static/decision/day.js` | 显示 `m.logic.text` 与审计码 |
| Create `.claude/commands/today.md`；Modify `AGENTS.md` | `/today` 入口 |
| Tests | `tests/decision/test_day_audit.py`、`test_brief_writer.py`；追加 `test_day_brief.py`、`test_day_runner.py`、`tests/test_cli_day.py`、`tests/test_today_command.py` |

---

### Task 1: 审计列 `day_audit.audit_defaults`

`Leg` 的输入形状见 `nutmeg/decision/legs_audit.py:1132 legs_from_dict`：`legs[场次号] = {name, faces, fair, confidence, prior, directional_flags, nondirectional_flags, anchor_integrity, precedents, crash_markers, tracking_tags, team_tags:{home:[],away:[]}, license_questions}`。竞彩卡片的 `labels` 已是同一词典。

**Files:**
- Create: `nutmeg/decision/day_audit.py`
- Test: `tests/decision/test_day_audit.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_day_audit.py
from nutmeg.decision.day_audit import audit_defaults, default_expressions


def _card(**labels) -> dict:
    base = {"judgment_tier": "deep_research", "confidence": 4, "anchor_integrity": "pass",
            "directional_flags": [], "nondirectional_flags": [], "crash_markers": [],
            "precedents": [], "team_tags": [], "tracking_tags": [], "license_questions": None}
    base.update(labels)
    return {"code": "周三001", "name": "阿森纳 vs 切尔西",
            "market": {"fair": {"home": 0.52, "draw": 0.26, "away": 0.22}}, "labels": base}


def test_default_expressions_follow_fair_order():
    assert default_expressions({"home": 0.52, "draw": 0.26, "away": 0.22}) == {"naked": "3", "double": "31", "full": "310"}
    assert default_expressions({"home": 0.20, "draw": 0.30, "away": 0.50}) == {"naked": "0", "double": "10", "full": "310"}


def test_audit_defaults_returns_codes_per_expression():
    out = audit_defaults(_card())
    assert set(out) == {"naked", "double", "full"}
    assert out["full"]["faces"] == "310" and out["full"]["blocking"] is False
    assert all(isinstance(f["code"], str) and f["level"] in ("ERROR", "WARN", "INFO") for f in out["naked"]["findings"])


def test_broken_anchor_naked_single_is_blocking():
    out = audit_defaults(_card(anchor_integrity="fail"))
    assert out["naked"]["blocking"] is True
    assert any(f["code"] == "broken_anchor_single" for f in out["naked"]["findings"])


def test_audit_defaults_degrades_on_bad_input():
    out = audit_defaults({"code": "x", "name": "x", "market": {"fair": None}, "labels": {}})
    assert out["error"].startswith("fair 缺失")
```

- [ ] **Step 2: Run** `uv run pytest tests/decision/test_day_audit.py -q` → `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/day_audit.py
"""三种默认表达（裸单 / 模态双选 / 全包）各自会触发哪些审计码——纯算术，不推荐、不排序（设计 §6.1）。"""
from __future__ import annotations

from nutmeg.decision.legs_audit import audit_legs, has_blocking, legs_from_dict

FACE_OF = {"home": "3", "draw": "1", "away": "0"}
_ORDER = ("3", "1", "0")


def default_expressions(fair: dict) -> dict[str, str]:
    ranked = sorted(("home", "draw", "away"), key=lambda k: -float(fair.get(k, 0)))
    naked = FACE_OF[ranked[0]]
    pair = {FACE_OF[ranked[0]], FACE_OF[ranked[1]]}
    return {"naked": naked, "double": "".join(f for f in _ORDER if f in pair), "full": "310"}


def _leg_payload(card: dict, faces: str) -> dict:
    labels = card.get("labels") or {}
    team_tags = labels.get("team_tags") or []
    if isinstance(team_tags, list):  # 卡片里是 [[side, tag], …]；Leg 要 {side: [tag]}
        grouped: dict[str, list] = {"home": [], "away": []}
        for item in team_tags:
            if isinstance(item, (list, tuple)) and len(item) == 2 and item[0] in grouped:
                grouped[item[0]].append(item[1])
        team_tags = grouped
    return {
        "name": card.get("name", ""), "faces": faces, "fair": card["market"]["fair"],
        "confidence": labels.get("confidence") or 0,
        "directional_flags": labels.get("directional_flags") or [],
        "nondirectional_flags": labels.get("nondirectional_flags") or [],
        "anchor_integrity": labels.get("anchor_integrity") or "unknown",
        "precedents": labels.get("precedents") or [], "crash_markers": labels.get("crash_markers") or [],
        "tracking_tags": labels.get("tracking_tags") or [], "team_tags": team_tags,
        "license_questions": labels.get("license_questions"),
    }


def audit_defaults(card: dict) -> dict:
    fair = (card.get("market") or {}).get("fair")
    if not fair:
        return {"error": "fair 缺失，无法展开默认表达"}
    out: dict = {}
    try:
        for label, faces in default_expressions(fair).items():
            legs = legs_from_dict({"issue": card.get("code", ""), "legs": {"1": _leg_payload(card, faces)}})
            findings = audit_legs(legs)
            out[label] = {
                "faces": faces,
                "blocking": has_blocking(findings),
                "findings": [{"level": f.level, "code": f.code, "message": f.message} for f in findings],
            }
    except Exception as exc:  # noqa: BLE001 — 审计列缺席不塌卡片
        return {"error": f"audit 失败: {exc!r}"[:300]}
    return out
```

- [ ] **Step 4: Run** → `4 passed`（若 `broken_anchor_single` 的触发还要 `confidence` 门槛，按 `legs_audit.audit_legs` 里 C5 的条件调整测试 fixture 的 `confidence`，不改判据。）

- [ ] **Step 5: 接进 `compile_brief`**

`nutmeg/decision/day_brief.py` `_jczq` 里 `cards.append({...})` 之后加：

```python
        cards[-1]["audit"] = audit_defaults(cards[-1])
```

顶部 `from nutmeg.decision.day_audit import audit_defaults`。追加测试到 `tests/decision/test_day_brief.py`：

```python
def test_cards_carry_audit_of_three_default_expressions(tmp_path: Path):
    data, root = _fixture(tmp_path)
    brief = compile_brief(data_dir=data, date="2026-09-23", root=root, now=NOW)
    audit = brief["jczq"]["matches"][0]["audit"]
    assert set(audit) == {"naked", "double", "full"} and audit["full"]["faces"] == "310"
```

Run: `uv run pytest tests/decision/test_day_brief.py tests/decision/test_day_audit.py -q` → passed

- [ ] **Step 6: Commit**

```bash
git add nutmeg/decision/day_audit.py nutmeg/decision/day_brief.py tests/decision/test_day_audit.py tests/decision/test_day_brief.py
git commit -m "feat(day): audit codes for the three default expressions on every card"
```

---

### Task 2: 逻辑层提示与输入

**Files:**
- Create: `nutmeg/decision/brief_prompt.py`
- Test: 并入 Task 3 的测试

```python
# nutmeg/decision/brief_prompt.py
"""逻辑层撰稿的系统提示与输入（设计 §6.3）。⛔只解释已产生的判断；不产生 belief；不引用不存在的字段。"""
from __future__ import annotations

import json

LOGIC_SYSTEM_PROMPT = """你是 Nutmeg 当日报告的撰稿人。你收到一场比赛的两层事实：事实层（market / strength / research / labels / audit）
与判断层（read：judge、belief、prior、moved_pp、confidence；ladder：跟市场|偏移|翻面|未判）。

任务：用 3–6 句中文解释「这一场为什么落在这一格」，严格按宪法字典序复述：
1. 事实层哪一条定了面（机制三态：face_status / anchor_integrity / death proofs / 先例 alive|dead）；
2. P 层哪一条约束了结构（fair、位移、书商分歧、实力残差）；
3. 表达阶梯落点（ladder）与三种默认表达的审计码（audit.naked/double/full 的 blocking）；
4. 与市场分歧的是哪个因子，该因子在注册表里现在的状态（factors[].decision）。

硬约束：
- 不新增任何判断、不建议买什么、不改 belief、不给概率。
- 每一句必须能指回输入里的字段。输出 JSON：{"code": "<场次代码>", "logic": "<3–6 句>", "cites": ["<点路径>", ...]}
  点路径以输入 JSON 的键为准，例如 "market.drift_pp"、"read.moved_pp"、"labels.anchor_integrity"、"audit.naked.blocking"、"factors.0.decision"。
- 只输出 JSON，不要 Markdown 围栏，不要解释。"""


def render_logic_input(card: dict, factors: list[dict]) -> str:
    """撰稿输入 = 卡片（去掉 logic 自身）+ 因子注册状态。"""
    payload = {k: v for k, v in card.items() if k != "logic"}
    payload["factors"] = factors
    return json.dumps(payload, ensure_ascii=False, indent=1)
```

- [ ] Commit 与 Task 3 一起。

---

### Task 3: 撰稿器 `brief_writer.write_logic`

**Files:**
- Create: `nutmeg/decision/brief_writer.py`
- Test: `tests/decision/test_brief_writer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_brief_writer.py
import json

from nutmeg.decision.brief_writer import resolve_path, validate_cites, write_logic

CARD = {"code": "周三001", "name": "A vs B", "market": {"fair": {"home": 0.52}, "drift_pp": 2.0},
        "labels": {"anchor_integrity": "pass"}, "read": {"moved_pp": 6.0, "judge": "ai:jczq-analyst"},
        "ladder": "偏移", "audit": {"naked": {"blocking": False}}}
BRIEF = {"date": "2026-09-23", "jczq": {"matches": [CARD, {**CARD, "code": "周三002"}], "counts": {}},
         "factors": [{"factor_id": "C11", "decision": "propose_zero"}]}


def test_resolve_path_and_validate_cites():
    assert resolve_path(CARD, "market.drift_pp") == 2.0
    assert resolve_path(CARD, "audit.naked.blocking") is False
    assert resolve_path(CARD, "read.nope") is None and resolve_path(CARD, "factors.0.decision") is None
    assert validate_cites(["market.drift_pp", "read.moved_pp"], CARD, BRIEF["factors"]) == []
    assert validate_cites(["market.zzz", "factors.0.decision"], CARD, BRIEF["factors"]) == ["market.zzz"]


def _fake_claude(responses: dict[str, str]):
    calls = []

    def claude(prompt: str, stdin: str) -> tuple[int, str]:
        code = json.loads(stdin)["code"]
        calls.append(code)
        return 0, responses[code]

    claude.calls = calls  # type: ignore[attr-defined]
    return claude


def test_write_logic_accepts_valid_and_rejects_bad_cites_and_respects_budget():
    ok = json.dumps({"code": "周三001", "logic": "锚方完整度 pass 定了面；位移 +2pp。", "cites": ["labels.anchor_integrity", "market.drift_pp"]})
    bad = "```json\n" + json.dumps({"code": "周三002", "logic": "x", "cites": ["market.nope"]}) + "\n```"
    claude = _fake_claude({"周三001": ok, "周三002": bad})
    out = write_logic(BRIEF, claude=claude, budget=5)
    m1, m2 = out["jczq"]["matches"]
    assert m1["logic"] == {"status": "ok", "text": "锚方完整度 pass 定了面；位移 +2pp。",
                           "cites": ["labels.anchor_integrity", "market.drift_pp"], "author": "claude -p"}
    assert m2["logic"]["status"] == "rejected" and "market.nope" in m2["logic"]["reason"]
    assert claude.calls == ["周三001", "周三002"]
    limited = write_logic(BRIEF, claude=_fake_claude({"周三001": ok, "周三002": bad}), budget=1)
    assert limited["jczq"]["matches"][1]["logic"] == {"status": "not_generated", "reason": "budget"}


def test_write_logic_handles_nonzero_exit_and_invalid_json():
    claude = lambda prompt, stdin: (1, "boom")  # noqa: E731
    out = write_logic(BRIEF, claude=claude, budget=5)
    assert out["jczq"]["matches"][0]["logic"]["status"] == "not_generated"
    claude2 = lambda prompt, stdin: (0, "not json")  # noqa: E731
    assert write_logic(BRIEF, claude=claude2, budget=5)["jczq"]["matches"][0]["logic"]["status"] == "rejected"
```

- [ ] **Step 2: Run** → `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/brief_writer.py
"""逻辑层撰稿器：每场一次无联网 `claude -p`，输出 JSON，cites 逐一校验（设计 §6.3、§9）。"""
from __future__ import annotations

import json
import subprocess
import tempfile
from collections.abc import Callable

from nutmeg.decision.brief_prompt import LOGIC_SYSTEM_PROMPT, render_logic_input

Claude = Callable[[str, str], tuple[int, str]]
LOGIC_DAILY_BUDGET = 40


def _claude_cli(prompt: str, stdin: str) -> tuple[int, str]:
    argv = ["claude", "-p", "--system-prompt", prompt, "--allowedTools", "", "--max-turns", "1",
            "--output-format", "text"]
    with tempfile.TemporaryDirectory() as neutral:
        proc = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=300,
                              cwd=neutral, check=False)
    return proc.returncode, proc.stdout


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def resolve_path(obj, path: str):
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def validate_cites(cites: list, card: dict, factors: list[dict]) -> list[str]:
    scope = {**card, "factors": factors}
    bad = []
    for cite in cites:
        if not isinstance(cite, str) or resolve_path(scope, cite) is None and not _exists(scope, cite):
            bad.append(str(cite))
    return bad


def _exists(scope, path: str) -> bool:
    """`resolve_path` 把值为 None/False 的字段也返回 None/False；存在性单独判。"""
    cur = scope
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return False
    return True


def _one(card: dict, factors: list[dict], claude: Claude) -> dict:
    code, text = claude(LOGIC_SYSTEM_PROMPT, render_logic_input(card, factors))
    if code != 0:
        return {"status": "not_generated", "reason": f"claude exit {code}"}
    try:
        doc = json.loads(_strip_fence(text))
    except ValueError:
        return {"status": "rejected", "reason": "非法 JSON"}
    if not isinstance(doc, dict) or doc.get("code") != card.get("code"):
        return {"status": "rejected", "reason": "code 不匹配"}
    cites = doc.get("cites") or []
    bad = validate_cites(cites, card, factors)
    if bad or not cites:
        return {"status": "rejected", "reason": "cites 不存在: " + ", ".join(bad or ["<空>"])}
    logic = str(doc.get("logic") or "").strip()
    if not logic:
        return {"status": "rejected", "reason": "logic 为空"}
    return {"status": "ok", "text": logic, "cites": list(cites), "author": "claude -p"}


def write_logic(brief: dict, *, claude: Claude = _claude_cli, budget: int = LOGIC_DAILY_BUDGET) -> dict:
    """返回带 `logic` 字段的 brief 副本。超预算的场 `not_generated/budget`。不改其它字段。"""
    factors = brief.get("factors") or []
    matches = []
    for i, card in enumerate(brief.get("jczq", {}).get("matches", [])):
        card = dict(card)
        card["logic"] = (_one(card, factors, claude) if i < budget
                         else {"status": "not_generated", "reason": "budget"})
        matches.append(card)
    return {**brief, "jczq": {**brief["jczq"], "matches": matches}}
```

- [ ] **Step 4: Run** `uv run pytest tests/decision/test_brief_writer.py -q` → `3 passed`

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/brief_prompt.py nutmeg/decision/brief_writer.py tests/decision/test_brief_writer.py
git commit -m "feat(day): logic-layer writer via headless claude -p with cite validation"
```

---

### Task 4: 接进 brief 作业、Markdown 与页面

**Files:**
- Modify: `nutmeg/decision/day_runner.py`（`DayContext.claude: Claude | None = None`、`with_logic` 参数）
- Modify: `nutmeg/interfaces/cli/day.py`（`--with-logic`）
- Modify: `nutmeg/decision/day_brief.py:render_brief_md`（每场加一行逻辑）
- Modify: `nutmeg/interfaces/web/static/decision/day.js`（`m.logic.text`、审计码徽章）
- Test: 追加 `tests/decision/test_day_runner.py`、`tests/test_cli_day.py`

- [ ] **Step 1: Write the failing tests**

```python
# 追加 tests/decision/test_day_runner.py
def test_brief_job_with_logic_uses_injected_claude(tmp_path: Path):
    ctx = _ctx(tmp_path, [])
    day = ctx.data_dir / "jczq" / "daily" / "2026-09-23"
    (day / "jczq-legs-base.json").write_text(json.dumps({"day": "2026-09-23", "legs": {
        "周三001": {"match_id": "m", "name": "A vs B", "kickoff_bj": "2026-09-23T19:30:00+08:00",
                   "fair": {"home": 0.5, "draw": 0.3, "away": 0.2}}}}), encoding="utf-8")
    ctx.claude = lambda p, s: (0, json.dumps({"code": "周三001", "logic": "fair 定面。", "cites": ["market.fair"]}))
    rec = run_job(ctx, "brief", with_logic=True)
    brief = json.loads((day_dir(ctx.data_dir, "2026-09-23") / "brief.json").read_text(encoding="utf-8"))
    assert rec.exit == 0 and brief["jczq"]["matches"][0]["logic"]["status"] == "ok"
    assert "fair 定面。" in (day_dir(ctx.data_dir, "2026-09-23") / "brief.md").read_text(encoding="utf-8")
```

```python
# 追加 tests/test_cli_day.py
def test_day_run_brief_with_logic_flag_is_accepted(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("nutmeg.decision.brief_writer._claude_cli", lambda p, s: (1, ""))
    data = _data(tmp_path)
    r = runner.invoke(app, ["day", "run", "--job", "brief", "--date", "2026-09-23", "--data-dir", str(data), "--with-logic"])
    assert r.exit_code == 0, r.output
```

- [ ] **Step 2: Run** → `TypeError: run_job() got an unexpected keyword argument 'with_logic'`

- [ ] **Step 3: Implement**

`day_runner.py`：`DayContext` 加 `claude: Callable[[str, str], tuple[int, str]] | None = None`；`run_job(ctx, job, *, force=False, with_logic=False)`；`_brief_pipeline(ctx, with_logic)` 在 `compile_brief` 之后：

```python
    if with_logic:
        from nutmeg.decision.brief_writer import _claude_cli, write_logic

        brief = write_logic(brief, claude=ctx.claude or _claude_cli)
```

`cli/day.py`：`run` 加 `with_logic: bool = typer.Option(False, "--with-logic", help="逻辑层：每场一次无联网 claude -p")`，传 `run_job(ctx, job, force=force, with_logic=with_logic)`。

`day_brief.py` `render_brief_md` 表格之后加：

```python
    logic_lines = [f"- **{m['code']}** {m['logic']['text']}" for m in brief["jczq"]["matches"]
                   if isinstance(m.get("logic"), dict) and m["logic"].get("status") == "ok"]
    if logic_lines:
        lines += ["", "### 为什么落在这一格（claude -p 撰稿，只解释不判断）", ""] + logic_lines
```

`day.js` 的 `card()` 里把 `if (m.logic) c.appendChild(el("p", "day-logic", m.logic));` 改为：

```js
    if (m.logic && m.logic.status === "ok") c.appendChild(el("p", "day-logic", m.logic.text));
    else if (m.logic) c.appendChild(el("p", "obs-muted", "逻辑层 " + m.logic.status + (m.logic.reason ? "：" + m.logic.reason : "")));
    if (m.audit && !m.audit.error) ["naked", "double", "full"].forEach(function (k) {
      var a = m.audit[k]; badges.appendChild(el("span", "day-badge" + (a.blocking ? " alarm" : ""), k + " " + a.faces + (a.blocking ? " ✗" : " ✓")));
    });
```

- [ ] **Step 4: Run** `uv run pytest tests/decision/test_day_runner.py tests/test_cli_day.py tests/test_decision_web_day.py -q` → passed

- [ ] **Step 5: 真跑一次（走订阅额度，约 30 场 × 一次调用）**

Run: `uv run nutmeg day run --job brief --with-logic && grep -c "为什么落在这一格" .nutmeg-data/daily/$(date +%F)/brief.md`
Expected: `1`；`brief.json` 每场 `logic.status ∈ {ok, rejected, not_generated}`，被拒的场带 `reason`。

- [ ] **Step 6: Commit**

```bash
git add nutmeg/decision/day_runner.py nutmeg/interfaces/cli/day.py nutmeg/decision/day_brief.py nutmeg/interfaces/web/static/decision/day.js tests/decision/test_day_runner.py tests/test_cli_day.py
git commit -m "feat(day): --with-logic brief, logic and audit shown in brief.md and /day"
```

`ops/launchd/com.nutmeg.day.brief.plist` 的 12:00 那次加 `--with-logic`（14:20 / 18:35 不加，逻辑层一天写一次）：P3 的 plist 命令改为 `… day run --job brief $( [ "$(date +%H)" = "12" ] && echo --with-logic ) …`；对应把 `tests/test_launchd_plists.py` 的 `EXPECTED["com.nutmeg.day.brief"]` 片段加 `"--with-logic"`。

---

### Task 5: `/today` 会话入口

**Files:**
- Create: `.claude/commands/today.md`
- Modify: `AGENTS.md`（加一节）
- Test: `tests/test_today_command.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_today_command.py
from pathlib import Path


def test_today_command_reads_session_and_states_the_rules():
    text = Path(".claude/commands/today.md").read_text(encoding="utf-8")
    for needle in ("session.md", "decisions.json", "不重跑", "剩余", "plan choose", "空仓"):
        assert needle in text
    agents = Path("AGENTS.md").read_text(encoding="utf-8")
    assert "## /today" in agents and "daily/<日>/session.md" in agents
```

- [ ] **Step 2: Run** → FAIL `FileNotFoundError`

- [ ] **Step 3: Write the command**

`.claude/commands/today.md`：

```markdown
---
description: 从今天已跑完的结论开始对话（daily/<日>/session.md）
---

先读 `.nutmeg-data/daily/$(date +%F)/session.md`（没有就先跑 `uv run nutmeg day run --job brief`），再读同目录 `decisions.json`。

规则：
1. 不重跑时间线上已完成（exit=0）的作业；有失败先报失败，不自行修。
2. 对话从 `decisions.json` 里 status=open 的第一条开始；每一条给我「事实 → 判断 → 为什么」，引用 brief.json 的字段，不新增判断。
3. 每一轮回复末尾一行：`最近截止 HH:MM，剩余 N 分；未定则默认：<default_action>`。最后 30 分钟每轮必报；最后 10 分钟明写「现在不定＝空仓」。
4. 资金组合只在 `plan frontier` 的点上讨论；票面只从 `plan choose → plan commit` 出，聊天里不出票面；实票登记、register/deploy、购买确认都是我做，你只准备命令。
5. 我们的讨论用 `uv run nutmeg day note --text "…" --obj <场次>` 记进 discussion.jsonl，页面 /day 同步显示。
6. C 类赛后资讯不进今天任何一场的判断；研究 `captured_at` 晚于开球的卡片按 not_prospective 对待。
```

`AGENTS.md` 在「触发短语」一节后加：

```markdown
## /today 会话入口（Codex 同规）

对话前先读 `.nutmeg-data/daily/<日>/session.md` 与 `decisions.json`；不重跑已完成作业；从待人决定开始；
每轮末尾报最近截止与剩余分钟并明写默认动作（空仓）；讨论用 `nutmeg day note` 落盘。全文见 `.claude/commands/today.md`。
```

同步 `CLAUDE.md` 的「触发短语」加一行：`- "/today / 今天的结论 / 从今天开始" → 读 daily/<日>/session.md（`.claude/commands/today.md`）`。

- [ ] **Step 4: Run** `uv run pytest tests/test_today_command.py -q` → `1 passed`

- [ ] **Step 5: Commit**

```bash
git add .claude/commands/today.md AGENTS.md CLAUDE.md tests/test_today_command.py
git commit -m "feat(session): /today entry reads the day's session pack and pending decisions"
```

---

### Task 6: 证据

- [ ] `docs/superpowers/evidence/2026-09-2X-daily-surface-p4.md`：一天真实 `--with-logic` 的统计（ok / rejected / not_generated 各几场、被拒原因分布、总秒数）、一场卡片的逻辑层原文与 cites、`/today` 首轮对话的前 20 行。
- [ ] Commit。

---

## Self-review

- §6.1 审计码 ✓（三种默认表达）；§6.3 逻辑层 ✓（无联网、单轮、cites 校验、预算、失败写 not_generated）；§8 `/today` ✓；§9「不产生 belief」——撰稿器不写任何 belief/Read，只加 `logic` 字段 ✓；C 类 → 卡片 `research.prospective=False` 已由 P1 标出，`/today` 规则第 6 条引用 ✓。
- 类型一致：`write_logic(brief, *, claude, budget)`、`Claude = Callable[[str, str], tuple[int, str]]` 与 `research_runner.Claude` 同形；`run_job(ctx, job, *, force, with_logic)`；`card["logic"]` 是 dict（P2 的 `m.logic` 文本用法在 Task 4 改掉）。
