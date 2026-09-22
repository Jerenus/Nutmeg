# Daily Surface P1 · `daily/<日>/` 对象与 `nutmeg day` 运行器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让一天的自动作业把结果落到一个对象 `.nutmeg-data/daily/<日>/`（时间线、日报事实层+判断层、待人决定、复盘草稿、会话包），由 `nutmeg day run --job settle|brief|session` 驱动，不产生任何新判断。

**Architecture:** 与 `nutmeg/decision/rsi_loop.py` 同一模式——子进程编排 + 可注入 `runner`/`now` + 幂等 + 只追加。事实层与判断层由纯函数 `compile_brief` 从既有文件（`jczq/daily/<日>/*`、`zucai/<期>-*.json`、`analytics/rsi-loop/<日>.json`、`experiments/factors.json`）编译；`build_decisions` 把「谁还没做」列成带截止的清单；`render_session_md` 把 brief 压成会话入口读的 ≤4k 字。

**Tech Stack:** Python 3.12, dataclasses, typer（已有 `nutmeg` CLI），pytest。无新依赖。

**Spec:** `docs/superpowers/specs/2026-09-22-daily-operator-surface-design.md` §4、§5（settle/brief/session 三作业）、§6.1–6.2、§8（会话包）、§9。

---

## File structure

| 文件 | 职责 |
| --- | --- |
| Create `nutmeg/decision/day_paths.py` | 目录与文件名常量 |
| Create `nutmeg/decision/day_timeline.py` | `JobRecord`、`timeline.json` 只追加读写 |
| Create `nutmeg/decision/day_brief.py` | `compile_brief` / `render_brief_md` / `write_brief`（事实层 + 判断层，零 LLM） |
| Create `nutmeg/decision/day_decisions.py` | `build_decisions`（待人决定 + 截止 + 默认动作 + 已完成判定） |
| Create `nutmeg/decision/day_session.py` | `render_session_md`、`append_discussion` |
| Create `nutmeg/decision/day_runner.py` | `DayContext`、`JOBS`、`planned_commands`、`run_job` |
| Create `nutmeg/interfaces/cli/day.py`；Modify `nutmeg/interfaces/cli/__init__.py:979` | `nutmeg day run/status/note` |
| Tests | `tests/decision/test_day_timeline.py`、`test_day_brief.py`、`test_day_decisions.py`、`test_day_session.py`、`test_day_runner.py`、`tests/test_cli_day.py` |

约定：所有时间字符串 ISO 8601 带时区；`date` = 北京业务日 `YYYY-MM-DD`；写文件一律 `ensure_ascii=False, indent=1`。

---

### Task 1: 路径常量与时间线

**Files:**
- Create: `nutmeg/decision/day_paths.py`
- Create: `nutmeg/decision/day_timeline.py`
- Test: `tests/decision/test_day_timeline.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_day_timeline.py
import json
from pathlib import Path

from nutmeg.decision.day_paths import TIMELINE, day_dir
from nutmeg.decision.day_timeline import JobRecord, append_job, latest, read_timeline


def _rec(job: str, exit_code: int = 0) -> JobRecord:
    return JobRecord(
        job=job, planned_at="2026-09-23T07:30:00+08:00",
        started_at="2026-09-23T07:30:02+08:00", finished_at="2026-09-23T07:30:20+08:00",
        exit=exit_code, summary=f"{job} done", evidence_path=None, commands=[],
    )


def test_append_job_creates_day_dir_and_appends_in_order(tmp_path: Path):
    path = append_job(tmp_path, "2026-09-23", _rec("settle"))
    append_job(tmp_path, "2026-09-23", _rec("brief", 1))
    assert path == day_dir(tmp_path, "2026-09-23") / TIMELINE
    rows = json.loads(path.read_text(encoding="utf-8"))
    assert [r["job"] for r in rows] == ["settle", "brief"]
    assert rows[1]["exit"] == 1


def test_read_timeline_is_empty_when_missing_and_latest_picks_last_row(tmp_path: Path):
    assert read_timeline(tmp_path, "2026-09-23") == []
    append_job(tmp_path, "2026-09-23", _rec("brief", 1))
    append_job(tmp_path, "2026-09-23", _rec("brief", 0))
    assert latest(read_timeline(tmp_path, "2026-09-23"), "brief")["exit"] == 0
    assert latest(read_timeline(tmp_path, "2026-09-23"), "settle") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_day_timeline.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'nutmeg.decision.day_paths'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/day_paths.py
"""`daily/<日>/` 对象：路径与文件名常量（设计 §4）。只此一处定义，其它模块 import。"""
from __future__ import annotations

from pathlib import Path

TIMELINE = "timeline.json"
BRIEF = "brief.json"
BRIEF_MD = "brief.md"
RETRO = "retro.md"
DECISIONS = "decisions.json"
SESSION = "session.md"
DISCUSSION = "discussion.jsonl"
BROADCASTS = "broadcasts.jsonl"
RESULTS_90 = "results-90.json"


def day_dir(data_dir: Path | str, date: str) -> Path:
    return Path(data_dir) / "daily" / date


def jczq_day_dir(data_dir: Path | str, date: str) -> Path:
    return Path(data_dir) / "jczq" / "daily" / date


def zucai_dir(data_dir: Path | str) -> Path:
    return Path(data_dir) / "zucai"
```

```python
# nutmeg/decision/day_timeline.py
"""`timeline.json`：每个作业一行，只追加；每行必须带时间证据（沿用 ops_status 的纪律）。"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from nutmeg.decision.day_paths import TIMELINE, day_dir


@dataclass
class JobRecord:
    job: str
    planned_at: str
    started_at: str
    finished_at: str
    exit: int
    summary: str
    evidence_path: str | None = None
    commands: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def read_timeline(data_dir: Path | str, date: str) -> list[dict]:
    path = day_dir(data_dir, date) / TIMELINE
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return []
    return rows if isinstance(rows, list) else []


def append_job(data_dir: Path | str, date: str, record: JobRecord) -> Path:
    path = day_dir(data_dir, date) / TIMELINE
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = read_timeline(data_dir, date)
    rows.append(record.to_dict())
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def latest(rows: list[dict], job: str) -> dict | None:
    hits = [r for r in rows if r.get("job") == job]
    return hits[-1] if hits else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_day_timeline.py -q`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/day_paths.py nutmeg/decision/day_timeline.py tests/decision/test_day_timeline.py
git commit -m "feat(day): daily/<date> paths and append-only timeline"
```

---

### Task 2: 日报事实层 + 判断层 `compile_brief`

**Files:**
- Create: `nutmeg/decision/day_brief.py`
- Test: `tests/decision/test_day_brief.py`

输入文件（全部可缺；缺则该块为 `None` 并进 `errors`）：

| 文件 | 用到的键 |
| --- | --- |
| `jczq/daily/<日>/jczq-legs-base.json` | `legs[code]`: `match_id name competition kickoff_bj home_team away_team fair hhad_line judgment_tier face_status anchor_integrity license_questions directional_flags nondirectional_flags crash_markers precedents team_tags tracking_tags confidence _d3` |
| `jczq/daily/<日>/reads.json` | list：`read_id match_id judge status judgment_tier confidence prior belief` |
| `jczq/daily/<日>/balance.json` | `rows[]`: `code prior belief` |
| `jczq/daily/<日>/research-<code>.json` / `.rejected.json` | `summary captured_at anchor_side hole_location schedule` |
| `jczq/daily/<日>/research-run-<日>.json` | `matches[]`: `code status` |
| `jczq/daily/<日>/price-band-<code>.json` | `fair_open fair_now drift_pp book_disagreement_pp` |
| `jczq/daily/<日>/closing_odds.json` | `[code]`: `book_count updated_at_max` |
| `analytics/team_strength.json` | `teams[name]`: `n record resid_shrunk market_strength last5_resid` |
| `analytics/rsi-loop/<日>.json` | `human_actions proposals verdicts grades failed_steps` |
| `zucai/<期>-issue.json` | `issue_id sale_deadline`（旧格式 `sale_stop`） |
| `zucai/<期>-prep-{morning,afternoon,revision}.json` | `slot captured_at n_matches` |
| `zucai/<期>-tiers.json` | `tiers wind tiers_hash` |
| `zucai/<期>-frontier-{renjiu,shengfucai}.json` | `points[]`: `k p_all notes stake_yuan shape narrowings`；`strict_max_p` |
| `experiments/factors.json` | `factors[]`: `factor_id layer current_weight_pp rule_name` |

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_day_brief.py
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from nutmeg.decision.day_brief import compile_brief, current_issue, render_brief_md, write_brief

BJ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=BJ)


def _w(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    data = tmp_path / "data"
    root = tmp_path / "root"
    day = data / "jczq" / "daily" / "2026-09-23"
    _w(day / "jczq-legs-base.json", {"day": "2026-09-23", "legs": {
        "周三001": {
            "match_id": "match-a", "name": "阿森纳 vs 切尔西", "competition": "英超",
            "kickoff_bj": "2026-09-23T19:30:00+08:00", "home_team": "阿森纳", "away_team": "切尔西",
            "fair": {"home": 0.52, "draw": 0.26, "away": 0.22}, "hhad_line": -1,
            "judgment_tier": "deep_research", "face_status": {"3": {"status": "alive"}},
            "anchor_integrity": "pass", "confidence": 4,
            "license_questions": {"q1_spine": True}, "directional_flags": [],
            "nondirectional_flags": ["information_asymmetry"], "crash_markers": [],
            "precedents": [], "team_tags": [], "tracking_tags": [],
        },
        "周三002": {
            "match_id": "match-b", "name": "热刺 vs 富勒姆", "competition": "英超",
            "kickoff_bj": "2026-09-23T22:00:00+08:00", "home_team": "热刺", "away_team": "富勒姆",
            "fair": {"home": 0.45, "draw": 0.28, "away": 0.27}, "hhad_line": -1,
            "judgment_tier": "price_only",
        },
    }})
    _w(day / "reads.json", [
        {"read_id": "read-1", "match_id": "match-a", "judge": "ai:jczq-analyst", "status": "draft",
         "judgment_tier": "deep_research", "confidence": 4,
         "prior": {"home": 0.52, "draw": 0.26, "away": 0.22},
         "belief": {"home": 0.58, "draw": 0.24, "away": 0.18}},
        {"read_id": "read-2", "match_id": "match-b", "judge": "market-anchor", "status": "draft",
         "judgment_tier": "price_only", "confidence": 1,
         "prior": {"home": 0.45, "draw": 0.28, "away": 0.27},
         "belief": {"home": 0.45, "draw": 0.28, "away": 0.27}},
    ])
    _w(day / "research-周三001.json", {"summary": "阿森纳主力齐整", "captured_at": "2026-09-23T10:20:00+08:00",
                                      "anchor_side": "home", "hole_location": None,
                                      "schedule": {"rotation_risk": "low", "rest_days": 6}})
    _w(day / "research-run-2026-09-23.json", {"day": "2026-09-23", "matches": [
        {"code": "周三001", "status": "done"}, {"code": "周三002", "status": "skipped_budget"}]})
    _w(day / "price-band-周三001.json", {"fair_open": {"home": 0.50}, "fair_now": {"home": 0.52},
                                        "drift_pp": 2.0, "book_disagreement_pp": 1.1})
    _w(day / "closing_odds.json", {"周三001": {"book_count": 9, "updated_at_max": "2026-09-23T11:00:00+08:00"}})
    _w(data / "analytics" / "team_strength.json", {"teams": {
        "阿森纳": {"n": 6, "record": "5-1-0", "resid_shrunk": 0.4, "market_strength": 0.61, "last5_resid": 0.3}}})
    _w(data / "analytics" / "rsi-loop" / "2026-09-23.json", {
        "human_actions": ["因子 C11：propose_zero"], "failed_steps": [],
        "proposals": [{"factor_id": "C11", "decision": "propose_zero"}], "verdicts": [], "grades": []})
    _w(data / "zucai" / "26132-issue.json", {"issue_id": "26132", "sale_deadline": "2026-09-23T21:00:00+08:00"})
    _w(data / "zucai" / "26132-prep-morning.json", {"issue": "26132", "slot": "morning",
                                                   "captured_at": "2026-09-23T11:00:00+08:00", "n_matches": 14})
    _w(data / "zucai" / "26132-tiers.json", {"issue": "26132", "tiers": {"1": "T1"}, "wind": {"regime": "hot"},
                                             "tiers_hash": "abc"})
    _w(data / "zucai" / "26132-frontier-renjiu.json", {"strict_max_p": 0.02, "points": [
        {"k": 0, "p_all": 0.05, "notes": 8, "stake_yuan": 16, "shape": "9x1", "narrowings": []}]})
    _w(root / "experiments" / "factors.json", {"factors": [
        {"factor_id": "C11", "layer": "probability", "current_weight_pp": 0, "rule_name": "价格带"}]})
    return data, root


def test_current_issue_prefers_issue_whose_deadline_is_ahead(tmp_path: Path):
    data, _ = _fixture(tmp_path)
    (data / "zucai" / "26131-issue.json").write_text(
        json.dumps({"issue_id": "26131", "sale_deadline": "2026-09-20T21:00:00+08:00"}), encoding="utf-8")
    assert current_issue(data / "zucai", now=NOW) == "26132"


def test_compile_brief_joins_every_source_into_cards(tmp_path: Path):
    data, root = _fixture(tmp_path)
    brief = compile_brief(data_dir=data, date="2026-09-23", root=root, now=NOW)
    cards = {c["code"]: c for c in brief["jczq"]["matches"]}
    a = cards["周三001"]
    assert a["market"]["drift_pp"] == 2.0 and a["market"]["closing_books"] == 9
    assert a["strength"]["home"]["record"] == "5-1-0" and a["strength"]["away"] is None
    assert a["research"]["status"] == "done" and a["research"]["prospective"] is True
    assert a["read"]["judge"] == "ai:jczq-analyst" and a["read"]["moved_pp"] == 6.0
    assert a["ladder"] == "偏移"
    b = cards["周三002"]
    assert b["research"]["status"] == "skipped_budget" and b["ladder"] == "跟市场"
    assert brief["jczq"]["counts"] == {"matches": 2, "deep_research": 1, "price_only": 1, "drafts": 2}
    assert brief["zucai"]["issue"] == "26132" and brief["zucai"]["sale_deadline"].startswith("2026-09-23T21:00")
    assert brief["zucai"]["tiers"]["wind"]["regime"] == "hot"
    assert brief["zucai"]["frontier"]["renjiu"]["points"][0]["p_all"] == 0.05
    assert brief["rsi"]["human_actions"] == ["因子 C11：propose_zero"]
    assert brief["factors"][0] == {"factor_id": "C11", "layer": "probability",
                                   "current_weight_pp": 0, "rule_name": "价格带", "decision": "propose_zero"}
    assert brief["errors"] == []


def test_compile_brief_degrades_block_by_block(tmp_path: Path):
    brief = compile_brief(data_dir=tmp_path / "none", date="2026-09-23", root=tmp_path, now=NOW)
    assert brief["jczq"]["matches"] == [] and brief["zucai"]["issue"] is None
    assert brief["rsi"] is None and brief["factors"] == []
    assert any("jczq-legs-base.json" in e for e in brief["errors"])


def test_research_after_kickoff_is_not_prospective(tmp_path: Path):
    data, root = _fixture(tmp_path)
    p = data / "jczq" / "daily" / "2026-09-23" / "research-周三001.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["captured_at"] = "2026-09-23T20:00:00+08:00"
    p.write_text(json.dumps(doc), encoding="utf-8")
    brief = compile_brief(data_dir=data, date="2026-09-23", root=root, now=NOW)
    assert brief["jczq"]["matches"][0]["research"]["prospective"] is False


def test_render_and_write_brief(tmp_path: Path):
    data, root = _fixture(tmp_path)
    brief = compile_brief(data_dir=data, date="2026-09-23", root=root, now=NOW)
    md = render_brief_md(brief)
    assert "# 当日报告 · 2026-09-23" in md and "周三001" in md and "26132" in md
    assert "只解释已产生的判断" in md
    path = write_brief(data, "2026-09-23", brief)
    assert path.name == "brief.json" and (path.parent / "brief.md").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_day_brief.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'nutmeg.decision.day_brief'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/day_brief.py
"""当日报告的事实层与判断层（设计 §6.1–6.2）。零 LLM；只读既有文件；每块独立降级。

⛔判断层只原样引用已有 Read 与标签，不在这里加任何看法；逻辑层（§6.3）在 P4。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from nutmeg.decision.day_paths import BRIEF, BRIEF_MD, day_dir, jczq_day_dir, zucai_dir

MOVE_EPS_PP = 0.05
"""与 F9 同一冻结常量：max|belief−prior| 超过它才算「拨动」。"""


def _load(path: Path, errors: list[str]):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"缺 {path.name}")
    except ValueError as exc:
        errors.append(f"{path.name} 不是合法 JSON: {exc}")
    return None


def _optional(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None


def _pp(a: dict | None, b: dict | None) -> float:
    if not a or not b:
        return 0.0
    return round(max(abs(float(a.get(k, 0)) - float(b.get(k, 0))) for k in ("home", "draw", "away")) * 100, 1)


def _argmax(p: dict | None) -> str | None:
    if not p:
        return None
    return max(("home", "draw", "away"), key=lambda k: float(p.get(k, 0)))


def _ladder(read: dict | None) -> str:
    """判决表阶梯位置，只从 belief/prior 算得出来的三档；降格需要 confidence 变化史，不在此推断。"""
    if read is None:
        return "未判"
    if read["moved_pp"] <= MOVE_EPS_PP:
        return "跟市场"
    return "翻面" if _argmax(read["belief"]) != _argmax(read["prior"]) else "偏移"


def _strength(teams: dict | None, name: str | None) -> dict | None:
    if not teams or not name or name not in teams:
        return None
    t = teams[name]
    return {k: t.get(k) for k in ("n", "record", "resid_shrunk", "market_strength", "last5_resid")}


def _research(day: Path, code: str, run_status: dict[str, str], kickoff: str | None) -> dict:
    doc = _optional(day / f"research-{code}.json")
    rejected = (day / f"research-{code}.rejected.json").exists()
    status = run_status.get(code) or ("rejected" if rejected else ("done" if doc else "none"))
    out = {"status": status, "captured_at": None, "summary": None, "anchor_side": None,
           "hole_location": None, "schedule": None, "prospective": None}
    if doc:
        out.update({k: doc.get(k) for k in ("captured_at", "summary", "anchor_side", "hole_location", "schedule")})
        if doc.get("captured_at") and kickoff:
            try:
                out["prospective"] = (
                    datetime.fromisoformat(doc["captured_at"]) < datetime.fromisoformat(kickoff)
                )
            except ValueError:
                out["prospective"] = None
    return out


LABEL_KEYS = ("judgment_tier", "face_status", "anchor_integrity", "license_questions", "_d3",
              "directional_flags", "nondirectional_flags", "crash_markers", "precedents",
              "team_tags", "tracking_tags", "confidence")


def _jczq(data_dir: Path, date: str, errors: list[str]) -> dict:
    day = jczq_day_dir(data_dir, date)
    board = _load(day / "jczq-legs-base.json", errors)
    legs: dict = (board or {}).get("legs") or {}
    reads = {r.get("match_id"): r for r in (_optional(day / "reads.json") or []) if isinstance(r, dict)}
    balance = {r.get("code"): r for r in ((_optional(day / "balance.json") or {}).get("rows") or [])}
    run = _optional(day / f"research-run-{date}.json") or {}
    run_status = {m.get("code"): m.get("status") for m in run.get("matches") or []}
    closing = _optional(day / "closing_odds.json") or {}
    teams = (_optional(data_dir / "analytics" / "team_strength.json") or {}).get("teams")
    cards = []
    for code, leg in sorted(legs.items(), key=lambda kv: str(kv[1].get("kickoff_bj") or "")):
        band = _optional(day / f"price-band-{code}.json") or {}
        close = closing.get(code) or {}
        raw_read = reads.get(leg.get("match_id"))
        read = None
        if raw_read:
            prior = raw_read.get("prior") or (balance.get(code) or {}).get("prior")
            belief = raw_read.get("belief") or (balance.get(code) or {}).get("belief")
            read = {
                "read_id": raw_read.get("read_id"), "judge": raw_read.get("judge"),
                "status": raw_read.get("status"), "judgment_tier": raw_read.get("judgment_tier"),
                "confidence": raw_read.get("confidence"), "prior": prior, "belief": belief,
                "moved_pp": _pp(prior, belief),
            }
        cards.append({
            "code": code, "name": leg.get("name"), "competition": leg.get("competition"),
            "kickoff_bj": leg.get("kickoff_bj"), "home_team": leg.get("home_team"),
            "away_team": leg.get("away_team"),
            "market": {
                "fair": leg.get("fair"), "hhad_line": leg.get("hhad_line"),
                "fair_open": band.get("fair_open"), "drift_pp": band.get("drift_pp"),
                "book_disagreement_pp": band.get("book_disagreement_pp"),
                "closing_books": close.get("book_count"), "closing_updated_at": close.get("updated_at_max"),
            },
            "strength": {"home": _strength(teams, leg.get("home_team")),
                         "away": _strength(teams, leg.get("away_team"))},
            "research": _research(day, code, run_status, leg.get("kickoff_bj")),
            "labels": {k: leg.get(k) for k in LABEL_KEYS},
            "read": read,
            "ladder": _ladder(read),
        })
    counts = {
        "matches": len(cards),
        "deep_research": sum(1 for c in cards if c["labels"]["judgment_tier"] == "deep_research"),
        "price_only": sum(1 for c in cards if c["labels"]["judgment_tier"] == "price_only"),
        "drafts": sum(1 for c in cards if c["read"] and c["read"]["status"] == "draft"),
    }
    return {"matches": cards, "counts": counts}


def current_issue(zdir: Path, *, now: datetime) -> str | None:
    """在售期：截止在 now 之后的最大期号；都过了就取最大期号；没有 issue 文件则 None。"""
    candidates: list[tuple[str, str | None]] = []
    for path in zdir.glob("*-issue.json"):
        doc = _optional(path) or {}
        issue = str(doc.get("issue_id") or path.name.split("-")[0])
        candidates.append((issue, doc.get("sale_deadline") or doc.get("sale_stop")))
    if not candidates:
        return None
    ahead = []
    for issue, deadline in candidates:
        try:
            if deadline and datetime.fromisoformat(deadline) > now:
                ahead.append(issue)
        except ValueError:
            continue
    return max(ahead) if ahead else max(issue for issue, _ in candidates)


def _zucai(data_dir: Path, now: datetime) -> dict:
    zdir = zucai_dir(data_dir)
    issue = current_issue(zdir, now=now) if zdir.exists() else None
    out = {"issue": issue, "sale_deadline": None, "prep": {}, "tiers": None,
           "frontier": {}, "plan": None}
    if not issue:
        return out
    meta = _optional(zdir / f"{issue}-issue.json") or {}
    out["sale_deadline"] = meta.get("sale_deadline") or meta.get("sale_stop")
    for slot in ("morning", "afternoon", "revision"):
        doc = _optional(zdir / f"{issue}-prep-{slot}.json")
        if doc:
            out["prep"][slot] = {k: doc.get(k) for k in ("captured_at", "n_matches")}
    out["tiers"] = _optional(zdir / f"{issue}-tiers.json")
    for channel in ("renjiu", "shengfucai"):
        doc = _optional(zdir / f"{issue}-frontier-{channel}.json")
        if doc:
            out["frontier"][channel] = {
                "strict_max_p": doc.get("strict_max_p"),
                "points": [{k: p.get(k) for k in ("k", "p_all", "notes", "stake_yuan", "shape")}
                           | {"narrowings": len(p.get("narrowings") or [])}
                           for p in (doc.get("points") or [])[:8]],
            }
    return out


def _rsi(data_dir: Path, date: str) -> dict | None:
    doc = _optional(data_dir / "analytics" / "rsi-loop" / f"{date}.json")
    if not doc:
        return None
    return {k: doc.get(k) for k in ("human_actions", "proposals", "verdicts", "grades", "failed_steps")}


def _factors(root: Path, rsi: dict | None) -> list[dict]:
    doc = _optional(root / "experiments" / "factors.json") or {}
    decisions = {p.get("factor_id"): p.get("decision") for p in ((rsi or {}).get("proposals") or [])}
    return [
        {"factor_id": f.get("factor_id"), "layer": f.get("layer"),
         "current_weight_pp": f.get("current_weight_pp"), "rule_name": f.get("rule_name"),
         "decision": decisions.get(f.get("factor_id"), "hold")}
        for f in doc.get("factors") or []
    ]


def compile_brief(*, data_dir: Path, date: str, root: Path, now: datetime) -> dict:
    errors: list[str] = []
    jczq = _jczq(Path(data_dir), date, errors)
    rsi = _rsi(Path(data_dir), date)
    return {
        "date": date,
        "generated_at": now.isoformat(timespec="seconds"),
        "jczq": jczq,
        "zucai": _zucai(Path(data_dir), now),
        "rsi": rsi,
        "factors": _factors(Path(root), rsi),
        "errors": errors,
    }


def _fmt_fair(fair: dict | None) -> str:
    if not fair:
        return "—"
    return "/".join(f"{float(fair.get(k, 0)) * 100:.0f}" for k in ("home", "draw", "away"))


def render_brief_md(brief: dict) -> str:
    lines = [f"# 当日报告 · {brief['date']}", "",
             f"生成 {brief['generated_at']} · 事实层与判断层为机器编译；本报告只解释已产生的判断，不产生新判断。", ""]
    c = brief["jczq"]["counts"]
    lines += [f"## 竞彩 {c['matches']} 场（深研 {c['deep_research']} / 跟市场 {c['price_only']} / 草稿 Read {c['drafts']}）", "",
              "| 场 | 开球 | 对阵 | fair 3/1/0 | 位移pp | 研究 | Read | 阶梯 |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for m in brief["jczq"]["matches"]:
        read = m["read"] or {}
        lines.append(
            f"| {m['code']} | {(m['kickoff_bj'] or '')[11:16]} | {m['name']} | {_fmt_fair(m['market']['fair'])} | "
            f"{m['market']['drift_pp'] if m['market']['drift_pp'] is not None else '—'} | {m['research']['status']} | "
            f"{read.get('judge') or '—'}/{read.get('status') or '—'} | {m['ladder']} |"
        )
    z = brief["zucai"]
    lines += ["", f"## 传统足彩 {z['issue'] or '（无在售期）'}", ""]
    if z["issue"]:
        lines.append(f"- 截止 {z['sale_deadline'] or '未知'}；备料槽 {', '.join(z['prep']) or '无'}")
        if z["tiers"]:
            lines.append(f"- 风向 {json.dumps(z['tiers'].get('wind'), ensure_ascii=False)}；定级 hash {z['tiers'].get('tiers_hash')}")
        for channel, doc in z["frontier"].items():
            top = doc["points"][0] if doc["points"] else None
            lines.append(f"- {channel} 前沿 {len(doc['points'])} 点，strict 地板 P={doc['strict_max_p']}"
                         + (f"；k0 P={top['p_all']} 注数 {top['notes']} ¥{top['stake_yuan']}" if top else ""))
    lines += ["", "## RSI", ""]
    if brief["rsi"]:
        lines += [f"- {a}" for a in brief["rsi"]["human_actions"]] or ["- 无待人决定"]
        if brief["rsi"]["failed_steps"]:
            lines.append(f"- ⚠️闭环失败步骤：{', '.join(brief['rsi']['failed_steps'])}")
    else:
        lines.append("- 今日闭环报告缺席")
    if brief["errors"]:
        lines += ["", "## 缺席的输入", ""] + [f"- {e}" for e in brief["errors"]]
    return "\n".join(lines) + "\n"


def write_brief(data_dir: Path | str, date: str, brief: dict) -> Path:
    out = day_dir(data_dir, date)
    out.mkdir(parents=True, exist_ok=True)
    (out / BRIEF).write_text(json.dumps(brief, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / BRIEF_MD).write_text(render_brief_md(brief), encoding="utf-8")
    return out / BRIEF
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_day_brief.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/day_brief.py tests/decision/test_day_brief.py
git commit -m "feat(day): compile the daily brief facts and judgment layers from existing files"
```

---

### Task 3: 待人决定 `build_decisions`

**Files:**
- Create: `nutmeg/decision/day_decisions.py`
- Test: `tests/decision/test_day_decisions.py`

规则：每条 `{id, kind, subject, deadline, default_action, status, source}`；
`status` = `done` 当 `jczq/daily/<日>/decisions.jsonl`（`workbench.record_decision` 写的）里有 `approve_read`/`reject_read` 且 `obj_id` == read_id；否则 `open`；`deadline` 已过 → `expired`。

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_day_decisions.py
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nutmeg.decision.day_decisions import build_decisions, write_decisions

BJ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=BJ)


def _brief() -> dict:
    return {
        "date": "2026-09-23",
        "jczq": {"matches": [
            {"code": "周三001", "name": "A vs B", "kickoff_bj": "2026-09-23T19:30:00+08:00",
             "read": {"read_id": "read-1", "status": "draft", "judge": "ai:jczq-analyst"}},
            {"code": "周三002", "name": "C vs D", "kickoff_bj": "2026-09-23T11:00:00+08:00",
             "read": {"read_id": "read-2", "status": "draft", "judge": "market-anchor"}},
            {"code": "周三003", "name": "E vs F", "kickoff_bj": "2026-09-23T22:00:00+08:00", "read": None},
        ], "counts": {}},
        "zucai": {"issue": "26132", "sale_deadline": "2026-09-23T21:00:00+08:00",
                  "tiers": {"tiers_hash": "abc"}, "frontier": {"renjiu": {"points": []}}, "plan": None},
        "rsi": {"human_actions": ["因子 C11：propose_zero"], "failed_steps": ["team_strength"]},
    }


def test_build_decisions_lists_reads_plan_rsi_and_failures_with_deadlines(tmp_path: Path):
    timeline = [{"job": "settle", "exit": 1, "summary": "boom"}]
    rows = build_decisions(_brief(), timeline, data_dir=tmp_path, now=NOW)
    by_id = {r["id"]: r for r in rows}
    assert by_id["read:周三001"] == {
        "id": "read:周三001", "kind": "approve_read", "subject": "周三001 A vs B（ai:jczq-analyst 草稿）",
        "deadline": "2026-09-23T19:30:00+08:00", "default_action": "草稿不入库＝跟市场",
        "status": "open", "source": "reads.json",
    }
    assert by_id["read:周三002"]["status"] == "expired"
    assert "read:周三003" not in by_id
    assert by_id["plan:26132"]["kind"] == "plan_choose_commit"
    assert by_id["plan:26132"]["default_action"] == "空仓"
    assert by_id["plan:26132"]["deadline"] == "2026-09-23T21:00:00+08:00"
    assert by_id["rsi:0"]["subject"] == "因子 C11：propose_zero" and by_id["rsi:0"]["deadline"] is None
    assert by_id["job:settle"]["kind"] == "failed_job"
    assert by_id["loop:team_strength"]["kind"] == "failed_step"


def test_approved_read_is_marked_done(tmp_path: Path):
    log = tmp_path / "jczq" / "daily" / "2026-09-23" / "decisions.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps({"action": "approve_read", "obj_id": "read-1", "result": "read-1 入库"}) + "\n",
                   encoding="utf-8")
    rows = build_decisions(_brief(), [], data_dir=tmp_path, now=NOW)
    assert {r["id"]: r["status"] for r in rows}["read:周三001"] == "done"


def test_write_decisions(tmp_path: Path):
    path = write_decisions(tmp_path, "2026-09-23", build_decisions(_brief(), [], data_dir=tmp_path, now=NOW))
    assert path.name == "decisions.json" and json.loads(path.read_text(encoding="utf-8"))[0]["id"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_day_decisions.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'nutmeg.decision.day_decisions'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/day_decisions.py
"""待人决定清单（设计 §4 `decisions.json`、§7「待人决定」块、§5 播报的输入）。

只列「系统做不了、只有人能做」的事，并给每条截止时间与默认动作（宪法：空仓是对着数字做的选择）。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from nutmeg.decision.day_paths import DECISIONS, day_dir, jczq_day_dir

DEFAULT_EMPTY = "空仓"


def _decided_reads(data_dir: Path, date: str) -> set[str]:
    path = jczq_day_dir(data_dir, date) / "decisions.jsonl"
    if not path.exists():
        return set()
    done: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("action") in ("approve_read", "reject_read"):
            done.add(str(row.get("obj_id")))
    return done


def _status(deadline: str | None, done: bool, now: datetime) -> str:
    if done:
        return "done"
    if deadline:
        try:
            if datetime.fromisoformat(deadline) <= now:
                return "expired"
        except ValueError:
            pass
    return "open"


def build_decisions(brief: dict, timeline: list[dict], *, data_dir: Path | str, now: datetime) -> list[dict]:
    decided = _decided_reads(Path(data_dir), brief["date"])
    rows: list[dict] = []
    for m in brief.get("jczq", {}).get("matches", []):
        read = m.get("read")
        if not read or read.get("status") != "draft":
            continue
        rows.append({
            "id": f"read:{m['code']}", "kind": "approve_read",
            "subject": f"{m['code']} {m.get('name')}（{read.get('judge')} 草稿）",
            "deadline": m.get("kickoff_bj"), "default_action": "草稿不入库＝跟市场",
            "status": _status(m.get("kickoff_bj"), str(read.get("read_id")) in decided, now),
            "source": "reads.json",
        })
    z = brief.get("zucai") or {}
    if z.get("issue") and z.get("tiers") and z.get("plan") is None:
        rows.append({
            "id": f"plan:{z['issue']}", "kind": "plan_choose_commit",
            "subject": f"{z['issue']} 在前沿上选点并定案（plan choose → commit）",
            "deadline": z.get("sale_deadline"), "default_action": DEFAULT_EMPTY,
            "status": _status(z.get("sale_deadline"), False, now), "source": "zucai",
        })
    rsi = brief.get("rsi") or {}
    for i, action in enumerate(rsi.get("human_actions") or []):
        rows.append({"id": f"rsi:{i}", "kind": "rsi", "subject": action, "deadline": None,
                     "default_action": "不动（hold）", "status": "open", "source": "rsi-loop"})
    for step in rsi.get("failed_steps") or []:
        rows.append({"id": f"loop:{step}", "kind": "failed_step", "subject": f"rsi loop 步骤 {step} 失败",
                     "deadline": None, "default_action": "看 latest.md 后决定是否 --force 重跑",
                     "status": "open", "source": "rsi-loop"})
    for job in timeline:
        if job.get("exit", 0) != 0:
            rows.append({"id": f"job:{job['job']}", "kind": "failed_job",
                         "subject": f"day 作业 {job['job']} 失败：{job.get('summary', '')[:120]}",
                         "deadline": None, "default_action": "看 timeline.json 的 commands 尾行",
                         "status": "open", "source": "timeline"})
    return rows


def write_decisions(data_dir: Path | str, date: str, rows: list[dict]) -> Path:
    out = day_dir(data_dir, date)
    out.mkdir(parents=True, exist_ok=True)
    path = out / DECISIONS
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_day_decisions.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/day_decisions.py tests/decision/test_day_decisions.py
git commit -m "feat(day): pending human decisions with deadlines and default actions"
```

---

### Task 4: 会话包 `session.md` 与讨论流

**Files:**
- Create: `nutmeg/decision/day_session.py`
- Test: `tests/decision/test_day_session.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_day_session.py
import json
from pathlib import Path

from nutmeg.decision.day_session import append_discussion, read_discussion, render_session_md, write_session


def test_render_session_md_is_compact_and_starts_from_decisions():
    brief = {"date": "2026-09-23", "generated_at": "2026-09-23T12:00:00+08:00",
             "jczq": {"matches": [{"code": "周三001", "name": "A vs B", "kickoff_bj": "2026-09-23T19:30:00+08:00",
                                   "ladder": "偏移", "research": {"status": "done"},
                                   "read": {"judge": "ai:jczq-analyst", "status": "draft", "moved_pp": 6.0},
                                   "labels": {"judgment_tier": "deep_research"}}],
                      "counts": {"matches": 1, "deep_research": 1, "price_only": 0, "drafts": 1}},
             "zucai": {"issue": "26132", "sale_deadline": "2026-09-23T21:00:00+08:00", "tiers": None,
                       "frontier": {}, "prep": {}, "plan": None},
             "rsi": {"human_actions": [], "failed_steps": []}, "factors": [], "errors": []}
    decisions = [{"id": "read:周三001", "kind": "approve_read", "subject": "周三001 A vs B", "status": "open",
                  "deadline": "2026-09-23T19:30:00+08:00", "default_action": "草稿不入库＝跟市场"}]
    timeline = [{"job": "brief", "exit": 0, "finished_at": "2026-09-23T12:00:10+08:00", "summary": "ok"}]
    md = render_session_md(brief, decisions, timeline)
    assert md.startswith("# 会话入口 · 2026-09-23")
    assert "## 待人决定（从这里开始）" in md and "read:周三001" in md and "19:30" in md
    assert "brief ✓" in md and "周三001 A vs B · 偏移 · 6.0pp" in md
    assert "不重跑已完成作业" in md
    assert len(md) < 4000


def test_discussion_is_append_only_jsonl(tmp_path: Path):
    p1 = append_discussion(tmp_path, "2026-09-23", who="jun", text="场1 我想双选", obj="周三001",
                           at="2026-09-23T13:00:00+08:00")
    append_discussion(tmp_path, "2026-09-23", who="claude", text="双选要过 C6", obj="周三001",
                      at="2026-09-23T13:01:00+08:00")
    rows = read_discussion(tmp_path, "2026-09-23")
    assert p1.name == "discussion.jsonl" and [r["who"] for r in rows] == ["jun", "claude"]
    assert rows[0]["seq"] == 1 and rows[1]["seq"] == 2


def test_write_session(tmp_path: Path):
    path = write_session(tmp_path, "2026-09-23", "# 会话入口 · 2026-09-23\n")
    assert path.name == "session.md" and path.read_text(encoding="utf-8").startswith("# 会话入口")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_day_session.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/day_session.py
"""会话入口读的上下文包 `session.md`（设计 §8）与讨论流 `discussion.jsonl`。"""
from __future__ import annotations

import json
from pathlib import Path

from nutmeg.decision.day_paths import DISCUSSION, SESSION, day_dir

MAX_CHARS = 4000


def _hm(iso: str | None) -> str:
    return (iso or "")[11:16] or "—"


def render_session_md(brief: dict, decisions: list[dict], timeline: list[dict]) -> str:
    lines = [f"# 会话入口 · {brief['date']}", "",
             "规则：不重跑已完成作业；先看失败；对话从待人决定开始；每轮末尾报最近截止与剩余分钟。", "",
             "## 作业", ""]
    seen: dict[str, dict] = {}
    for job in timeline:
        seen[job["job"]] = job
    lines += [f"- {j} {'✓' if r.get('exit', 0) == 0 else '✗ ' + str(r.get('summary', ''))[:80]} @{_hm(r.get('finished_at'))}"
              for j, r in seen.items()] or ["- 今日尚无作业记录"]
    lines += ["", "## 待人决定（从这里开始）", ""]
    open_rows = [d for d in decisions if d.get("status") == "open"]
    lines += [f"- [{d['id']}] {d['subject']} · 截止 {_hm(d.get('deadline'))} · 默认 {d['default_action']}"
              for d in open_rows] or ["- 无"]
    c = brief["jczq"]["counts"]
    lines += ["", f"## 竞彩 {c.get('matches', 0)} 场（深研 {c.get('deep_research', 0)}）", ""]
    for m in brief["jczq"]["matches"]:
        read = m.get("read") or {}
        lines.append(
            f"- {m['code']} {m.get('name')} · {m.get('ladder')} · {read.get('moved_pp', 0)}pp · "
            f"{_hm(m.get('kickoff_bj'))} · 研究 {m['research']['status']} · Read {read.get('judge') or '—'}/{read.get('status') or '—'}"
        )
    z = brief["zucai"]
    lines += ["", f"## 足彩 {z.get('issue') or '无在售期'}" + (f" · 截止 {_hm(z.get('sale_deadline'))}" if z.get("issue") else ""), ""]
    if z.get("tiers"):
        lines.append(f"- 风向 {json.dumps(z['tiers'].get('wind'), ensure_ascii=False)}")
    for channel, doc in (z.get("frontier") or {}).items():
        lines.append(f"- {channel} 前沿 {len(doc.get('points') or [])} 点")
    rsi = brief.get("rsi") or {}
    lines += ["", "## RSI", ""] + ([f"- {a}" for a in rsi.get("human_actions") or []] or ["- 无待人决定"])
    text = "\n".join(lines) + "\n"
    if len(text) > MAX_CHARS:
        text = text[: MAX_CHARS - 40].rstrip() + "\n\n…（已截断，全文见 brief.md）\n"
    return text


def write_session(data_dir: Path | str, date: str, text: str) -> Path:
    out = day_dir(data_dir, date)
    out.mkdir(parents=True, exist_ok=True)
    path = out / SESSION
    path.write_text(text, encoding="utf-8")
    return path


def read_discussion(data_dir: Path | str, date: str) -> list[dict]:
    path = day_dir(data_dir, date) / DISCUSSION
    if not path.exists():
        return []
    rows = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            row = json.loads(line)
            row.setdefault("seq", i)
            rows.append(row)
    return rows


def append_discussion(data_dir: Path | str, date: str, *, who: str, text: str, obj: str = "", at: str) -> Path:
    path = day_dir(data_dir, date) / DISCUSSION
    path.parent.mkdir(parents=True, exist_ok=True)
    seq = len(read_discussion(data_dir, date)) + 1
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"seq": seq, "who": who, "obj": obj, "text": text, "at": at},
                            ensure_ascii=False) + "\n")
    return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_day_session.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/day_session.py tests/decision/test_day_session.py
git commit -m "feat(day): session context pack and append-only discussion log"
```

---

### Task 5: 运行器 `day_runner`（settle / brief / session）

**Files:**
- Create: `nutmeg/decision/day_runner.py`
- Test: `tests/decision/test_day_runner.py`

作业语义：

| job | 做什么 | 幂等 |
| --- | --- | --- |
| `settle` | 对昨日：`workbench-export --date 昨日 --out daily/<日>/retro.md`；若 `daily/<日>/results-90.json` 存在则 `betslip settle --results-file`；若 `zucai/<期>-rx.json` 存在则 `workflow grade-rx` | `retro.md` 已在且未 `--force` → skipped |
| `brief` | `compile_brief` → `write_brief` → `build_decisions` → `write_decisions` → `render_session_md` → `write_session` | 每次覆盖（它就是要随时更新） |
| `session` | 只重渲染 `session.md`（brief.json/decisions.json 已在） | 覆盖 |

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_day_runner.py
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nutmeg.decision.day_paths import RESULTS_90, day_dir
from nutmeg.decision.day_runner import JOBS, DayContext, planned_commands, run_job
from nutmeg.decision.day_timeline import read_timeline

BJ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=BJ)


def _runner(log: list[list[str]]):
    def run(cmd):
        log.append(list(cmd))
        if "workbench-export" in cmd:
            out = Path(cmd[cmd.index("--out") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("# 复盘底稿\n", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "ok", "")
        if "grade-rx" in cmd:
            return subprocess.CompletedProcess(cmd, 1, "", "rx error: 没有 outcome")
        return subprocess.CompletedProcess(cmd, 0, "ok", "")
    return run


def _ctx(tmp_path: Path, log) -> DayContext:
    data = tmp_path / "data"
    (data / "jczq" / "daily" / "2026-09-23").mkdir(parents=True)
    (data / "jczq" / "daily" / "2026-09-23" / "jczq-legs-base.json").write_text(
        json.dumps({"day": "2026-09-23", "legs": {}}), encoding="utf-8")
    return DayContext(root=tmp_path, data_dir=data, date="2026-09-23", runner=_runner(log), now=lambda: NOW)


def test_jobs_and_planned_settle_commands(tmp_path: Path):
    ctx = _ctx(tmp_path, [])
    assert JOBS == ("settle", "brief", "session")
    cmds = planned_commands(ctx, "settle")
    assert cmds[0][:4] == ["uv", "run", "nutmeg", "workbench-export"] and "2026-09-22" in cmds[0]
    assert not any("betslip" in c for c in cmds)  # no results-90.json yet
    (day_dir(ctx.data_dir, "2026-09-23") / RESULTS_90).parent.mkdir(parents=True, exist_ok=True)
    (day_dir(ctx.data_dir, "2026-09-23") / RESULTS_90).write_text("{}", encoding="utf-8")
    assert any("betslip" in c and "settle" in c for c in planned_commands(ctx, "settle"))
    assert planned_commands(ctx, "brief") == [] and planned_commands(ctx, "session") == []


def test_settle_runs_subprocesses_records_timeline_and_is_idempotent(tmp_path: Path):
    log: list[list[str]] = []
    ctx = _ctx(tmp_path, log)
    (ctx.data_dir / "zucai").mkdir()
    (ctx.data_dir / "zucai" / "26132-issue.json").write_text(
        json.dumps({"issue_id": "26132", "sale_deadline": "2026-09-23T21:00:00+08:00"}), encoding="utf-8")
    (ctx.data_dir / "zucai" / "26132-rx.json").write_text("{}", encoding="utf-8")
    rec = run_job(ctx, "settle")
    assert rec.exit == 1 and "grade-rx" in rec.summary  # one sub-command failed → job exit 1, but retro exists
    assert (day_dir(ctx.data_dir, "2026-09-23") / "retro.md").exists()
    assert rec.evidence_path.endswith("retro.md")
    rows = read_timeline(ctx.data_dir, "2026-09-23")
    assert rows[-1]["job"] == "settle" and rows[-1]["commands"][0]["exit"] == 0
    calls = len(log)
    assert run_job(ctx, "settle").summary.startswith("skipped") and len(log) == calls
    assert run_job(ctx, "settle", force=True).job == "settle" and len(log) > calls


def test_brief_job_writes_brief_decisions_and_session(tmp_path: Path):
    ctx = _ctx(tmp_path, [])
    rec = run_job(ctx, "brief")
    out = day_dir(ctx.data_dir, "2026-09-23")
    assert rec.exit == 0 and (out / "brief.json").exists() and (out / "brief.md").exists()
    assert (out / "decisions.json").exists() and (out / "session.md").exists()
    assert json.loads((out / "brief.json").read_text(encoding="utf-8"))["date"] == "2026-09-23"


def test_session_job_requires_brief_first(tmp_path: Path):
    ctx = _ctx(tmp_path, [])
    rec = run_job(ctx, "session")
    assert rec.exit == 1 and "brief.json" in rec.summary
    run_job(ctx, "brief")
    assert run_job(ctx, "session").exit == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_day_runner.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'nutmeg.decision.day_runner'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/day_runner.py
"""`nutmeg day run --job …`：把一天的自动作业落到 daily/<日>/（设计 §4–§5）。

与 rsi_loop 同一纪律：子进程编排、可注入 runner/now、只追加、失败只记一行不抛。
⛔不 approve Read、不 choose/commit、不 register/deploy、不登记实票、不推送购买。
"""
from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime, timedelta
from pathlib import Path

from nutmeg.decision.day_brief import compile_brief, current_issue, write_brief
from nutmeg.decision.day_decisions import build_decisions, write_decisions
from nutmeg.decision.day_paths import BRIEF, DECISIONS, RESULTS_90, RETRO, day_dir, zucai_dir
from nutmeg.decision.day_session import render_session_md, write_session
from nutmeg.decision.day_timeline import JobRecord, append_job, read_timeline

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]
Now = Callable[[], datetime]

JOBS = ("settle", "brief", "session")


@dataclass
class DayContext:
    root: Path
    data_dir: Path
    date: str
    runner: Runner
    now: Now

    @property
    def out_dir(self) -> Path:
        return day_dir(self.data_dir, self.date)


def default_runner(cmd: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True, check=False)


def _yesterday(date: str) -> str:
    return (_date.fromisoformat(date) - timedelta(days=1)).isoformat()


def _tail(text: str, lines: int = 3) -> str:
    chunks = [line for line in (text or "").strip().splitlines() if line.strip()]
    return " / ".join(chunks[-lines:])[:600]


def planned_commands(ctx: DayContext, job: str) -> list[list[str]]:
    if job != "settle":
        return []
    uv = ["uv", "run", "nutmeg"]
    data = ["--data-dir", str(ctx.data_dir)]
    cmds = [[*uv, "workbench-export", "--date", _yesterday(ctx.date),
             "--output-dir", str(ctx.data_dir / "jczq"), "--out", str(ctx.out_dir / RETRO)]]
    results = ctx.out_dir / RESULTS_90
    if results.exists():
        cmds.append([*uv, "betslip", "settle", "--results-file", str(results), *data])
    zdir = zucai_dir(ctx.data_dir)
    issue = current_issue(zdir, now=ctx.now()) if zdir.exists() else None
    if issue and (zdir / f"{issue}-rx.json").exists():
        cmds.append([*uv, "workflow", "grade-rx", "--rx-file", str(zdir / f"{issue}-rx.json"),
                     "--issue", issue, *data])
    return cmds


def _run_commands(ctx: DayContext, cmds: list[list[str]]) -> tuple[list[dict], int]:
    rows, exit_code = [], 0
    for cmd in cmds:
        proc = ctx.runner(cmd)
        text = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        rows.append({"cmd": " ".join(cmd[2:]), "exit": proc.returncode, "tail": _tail(text)})
        if proc.returncode != 0:
            exit_code = 1
    return rows, exit_code


def _brief_pipeline(ctx: DayContext) -> str:
    brief = compile_brief(data_dir=ctx.data_dir, date=ctx.date, root=ctx.root, now=ctx.now())
    write_brief(ctx.data_dir, ctx.date, brief)
    timeline = read_timeline(ctx.data_dir, ctx.date)
    decisions = build_decisions(brief, timeline, data_dir=ctx.data_dir, now=ctx.now())
    write_decisions(ctx.data_dir, ctx.date, decisions)
    write_session(ctx.data_dir, ctx.date, render_session_md(brief, decisions, timeline))
    n_open = sum(1 for d in decisions if d["status"] == "open")
    return (f"brief {brief['jczq']['counts']['matches']} 场 · 待人 {n_open} · "
            f"缺席输入 {len(brief['errors'])}")


def _session_only(ctx: DayContext) -> tuple[str, int]:
    brief_path = ctx.out_dir / BRIEF
    if not brief_path.exists():
        return f"缺 {BRIEF}：先跑 --job brief", 1
    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    dec_path = ctx.out_dir / DECISIONS
    decisions = json.loads(dec_path.read_text(encoding="utf-8")) if dec_path.exists() else []
    write_session(ctx.data_dir, ctx.date, render_session_md(brief, decisions, read_timeline(ctx.data_dir, ctx.date)))
    return "session.md 重渲染", 0


def run_job(ctx: DayContext, job: str, *, force: bool = False) -> JobRecord:
    if job not in JOBS:
        raise ValueError(f"unknown job {job!r}; JOBS={JOBS}")
    planned = ctx.now().isoformat(timespec="seconds")
    started = time.monotonic()
    started_at = ctx.now().isoformat(timespec="seconds")
    commands: list[dict] = []
    evidence: str | None = None
    if job == "settle":
        retro = ctx.out_dir / RETRO
        if retro.exists() and not force:
            summary, exit_code = f"skipped: {RETRO} 已存在（--force 重跑）", 0
        else:
            commands, exit_code = _run_commands(ctx, planned_commands(ctx, "settle"))
            failed = [" ".join(c["cmd"].split(" ")[1:3]) for c in commands if c["exit"] != 0]
            summary = "settle 完成" if not failed else "失败: " + ", ".join(failed)
            evidence = str(retro) if retro.exists() else None
    elif job == "brief":
        try:
            summary, exit_code = _brief_pipeline(ctx), 0
            evidence = str(ctx.out_dir / BRIEF)
        except Exception as exc:  # noqa: BLE001 — 只留痕不抛
            summary, exit_code = f"brief 异常: {exc!r}"[:300], 1
    else:
        summary, exit_code = _session_only(ctx)
    record = JobRecord(job=job, planned_at=planned, started_at=started_at,
                       finished_at=ctx.now().isoformat(timespec="seconds"), exit=exit_code,
                       summary=summary, evidence_path=evidence, commands=commands)
    append_job(ctx.data_dir, ctx.date, record)
    _ = round(time.monotonic() - started, 1)
    return record
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_day_runner.py -q`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/day_runner.py tests/decision/test_day_runner.py
git commit -m "feat(day): day runner with settle/brief/session jobs recorded on the timeline"
```

---

### Task 6: CLI `nutmeg day run/status/note`

**Files:**
- Create: `nutmeg/interfaces/cli/day.py`
- Modify: `nutmeg/interfaces/cli/__init__.py:980`（在 `core` 之后加一行注册）
- Test: `tests/test_cli_day.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_day.py
import json
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app

runner = CliRunner()


def _data(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    (data / "jczq" / "daily" / "2026-09-23").mkdir(parents=True)
    (data / "jczq" / "daily" / "2026-09-23" / "jczq-legs-base.json").write_text(
        json.dumps({"day": "2026-09-23", "legs": {}}), encoding="utf-8")
    return data


def test_day_run_brief_then_status_and_note(tmp_path: Path):
    data = _data(tmp_path)
    result = runner.invoke(app, ["day", "run", "--job", "brief", "--date", "2026-09-23", "--data-dir", str(data)])
    assert result.exit_code == 0, result.output
    assert "brief 0 场" in result.output
    status = runner.invoke(app, ["day", "status", "--date", "2026-09-23", "--data-dir", str(data)])
    assert status.exit_code == 0 and "brief" in status.output and "exit=0" in status.output
    note = runner.invoke(app, ["day", "note", "--date", "2026-09-23", "--data-dir", str(data),
                               "--text", "场1 想双选", "--obj", "周三001"])
    assert note.exit_code == 0
    rows = (data / "daily" / "2026-09-23" / "discussion.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(rows[0])["text"] == "场1 想双选"


def test_day_run_dry_run_prints_settle_commands(tmp_path: Path):
    data = _data(tmp_path)
    result = runner.invoke(app, ["day", "run", "--job", "settle", "--date", "2026-09-23",
                                 "--data-dir", str(data), "--dry-run"])
    assert result.exit_code == 0 and "workbench-export" in result.output
    assert not (data / "daily" / "2026-09-23" / "timeline.json").exists()


def test_day_run_rejects_unknown_job(tmp_path: Path):
    result = runner.invoke(app, ["day", "run", "--job", "deploy", "--data-dir", str(_data(tmp_path))])
    assert result.exit_code == 1 and "未知作业" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_day.py -q`
Expected: FAIL — `No such command 'day'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/interfaces/cli/day.py
"""`nutmeg day`：每日对象 daily/<日>/ —— 先跑完、再对话（设计 2026-09-22-daily-operator-surface）。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer

import nutmeg.interfaces.cli as _cli

day_app = typer.Typer(help="每日对象 daily/<日>：settle / brief / session 作业、状态、讨论")
_cli.app.add_typer(day_app, name="day")

_DATE = typer.Option(None, "--date", help="业务日 YYYY-MM-DD，默认今天")
_DATA_DIR = typer.Option(Path(".nutmeg-data"), "--data-dir")
_JOB = typer.Option(..., "--job", help="settle | brief | session")
_FORCE = typer.Option(False, "--force", help="settle 已有 retro.md 也重跑")
_DRY = typer.Option(False, "--dry-run", help="只打印子进程命令，不执行、不写时间线")


def _now() -> datetime:
    return datetime.now().astimezone()


def _ctx(date: str | None, data_dir: Path):
    from nutmeg.decision.day_runner import DayContext, default_runner

    return DayContext(
        root=Path(__file__).resolve().parents[3],
        data_dir=Path(data_dir).expanduser().resolve(),
        date=date or _now().date().isoformat(),
        runner=default_runner,
        now=_now,
    )


@day_app.command("run")
def run(job: str = _JOB, date: str | None = _DATE, data_dir: Path = _DATA_DIR,
        force: bool = _FORCE, dry_run: bool = _DRY) -> None:
    """跑一个作业并把结果追加到 daily/<日>/timeline.json。"""
    from nutmeg.decision.day_runner import JOBS, planned_commands, run_job

    if job not in JOBS:
        typer.echo(f"day error: 未知作业 {job!r}；可用：{', '.join(JOBS)}")
        raise typer.Exit(code=1)
    ctx = _ctx(date, data_dir)
    if dry_run:
        for cmd in planned_commands(ctx, job):
            typer.echo("    " + " ".join(cmd))
        if job != "settle":
            typer.echo(f"    [{job}] 纯 Python 作业，不起子进程")
        return
    record = run_job(ctx, job, force=force)
    typer.echo(f"day {ctx.date} {job}: {record.summary} (exit={record.exit})")
    for row in record.commands:
        typer.echo(f"    [{row['exit']}] {row['cmd'][:80]} · {row['tail'][:120]}")
    if record.exit != 0:
        raise typer.Exit(code=1)


@day_app.command("status")
def status(date: str | None = _DATE, data_dir: Path = _DATA_DIR) -> None:
    """打印当日时间线（每行带时间证据）。"""
    from nutmeg.decision.day_timeline import read_timeline

    ctx = _ctx(date, data_dir)
    rows = read_timeline(ctx.data_dir, ctx.date)
    if not rows:
        typer.echo(f"{ctx.date}: 尚无作业记录（{ctx.out_dir}）")
        return
    for r in rows:
        typer.echo(f"{r['finished_at']}  {r['job']:8} exit={r['exit']}  {r['summary'][:100]}")


@day_app.command("note")
def note(text: str = typer.Option(..., "--text"), obj: str = typer.Option("", "--obj"),
         who: str = typer.Option("jun", "--who"), date: str | None = _DATE,
         data_dir: Path = _DATA_DIR) -> None:
    """把一句讨论追加进 daily/<日>/discussion.jsonl（页面同步显示）。"""
    from nutmeg.decision.day_session import append_discussion

    ctx = _ctx(date, data_dir)
    path = append_discussion(ctx.data_dir, ctx.date, who=who, text=text, obj=obj,
                             at=_now().isoformat(timespec="seconds"))
    typer.echo(f"记入 {path}")
```

在 `nutmeg/interfaces/cli/__init__.py` 的注册块（`from nutmeg.interfaces.cli import core as core  # noqa: E402` 之后）加：

```python
from nutmeg.interfaces.cli import day as day  # noqa: E402
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_day.py tests/decision/test_day_runner.py -q`
Expected: `7 passed`

- [ ] **Step 5: Run the real thing once (read-only side effects: only daily/<today>/ is written)**

Run: `uv run nutmeg day run --job brief && uv run nutmeg day status && sed -n 1,30p .nutmeg-data/daily/$(date +%F)/session.md`
Expected: `brief N 场 · 待人 K · 缺席输入 M (exit=0)`，status 一行 `brief exit=0`，session.md 以「# 会话入口」开头。

- [ ] **Step 6: Commit**

```bash
git add nutmeg/interfaces/cli/day.py nutmeg/interfaces/cli/__init__.py tests/test_cli_day.py
git commit -m "feat(cli): nutmeg day run/status/note"
```

---

### Task 7: 证据文档

**Files:**
- Create: `docs/superpowers/evidence/2026-09-2X-daily-surface-p1.md`

- [ ] **Step 1: Write the evidence file** with: `uv run nutmeg day run --job brief` 的真实输出、`ls .nutmeg-data/daily/<日>/`、`session.md` 前 30 行、`uv run pytest tests/decision/test_day_*.py tests/test_cli_day.py -q` 的结果行、以及一句「未做：broadcast（P3）、逻辑层（P4）、页面（P2）」。

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/evidence/2026-09-2X-daily-surface-p1.md
git commit -m "docs(evidence): daily surface P1 first run"
```

---

## Self-review

- Spec §4 对象：timeline.json（T1）、brief.json/md（T2）、decisions.json（T3）、session.md + discussion.jsonl（T4）、retro.md（T5 settle）✓；broadcasts.jsonl 常量已留，由 P3 使用。
- Spec §5 settle/brief/session 三作业 ✓；research 定时、broadcast 在 P3。
- Spec §6.1 事实层：市场（fair/位移/分歧/终盘书数）、实力、研究（含 prospective 门 §9）、标签、因子注册状态 ✓；审计码列在 P4（需 `legs_from_dict` 适配）。
- Spec §6.2 判断层：Read 原样 + 阶梯（跟市场/偏移/翻面，降格如实标为不推断）✓。
- Spec §8 会话包 ✓（`/today` 命令文件在 P4）。
- 类型一致性：`compile_brief(*, data_dir, date, root, now)`、`build_decisions(brief, timeline, *, data_dir, now)`、`render_session_md(brief, decisions, timeline)`、`run_job(ctx, job, *, force)`、`JobRecord` 字段在 T1/T5/T6 一致。
