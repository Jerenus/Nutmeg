# 竞彩全板深研桥 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 竞彩当日板每场 headless 深研 → 结构化研究 JSON → 回填 legs-base（含 `face_status`）→ 内核草稿 Read；研不到的场如实记 `price_only`；每场深研是 R0 实验的 duty，覆盖率有账。

**Architecture:** 一个板面 legs-base 生成器（读内核 board + bold_odds）、一个 headless 运行器（子进程 `claude -p`，可注入假 runner）、intake 复用足彩的每场校验（键改 code）、build-reads 复用 `read_builder.build` 的字段契约。全部写文件，落库只经既有 `decision-read`。

**Tech Stack:** Python 3.13 / subprocess / typer / pytest。Spec：`docs/superpowers/specs/2026-09-19-jczq-board-research-bridge-design.md`。

**仓库纪律**：同专项计划（显式路径 add；提交不接管道；提交期间不编辑；不跑真 `decision-am`/真 `claude`；测试用假 runner 与 `tmp_path`）。

---

## 文件结构

- Create `nutmeg/decision/jczq_board.py` — 板面 legs-base 生成（price_only）
- Create `nutmeg/decision/research_runner.py` — headless 运行器（队列、预算、幂等、泄漏闸、rejected）
- Create `nutmeg/decision/research_prompt.py` — 系统提示词 = agent 正文 + JSON 契约；简报渲染
- Modify `nutmeg/decision/research_intake.py` — 抽出 `intake_one(leg, research, key)` 供 code 键复用（若已是每场函数则只加薄封装）
- Create `nutmeg/decision/jczq_reads.py` — research → judgment 字段 → reads.json（`judge="ai:jczq-analyst"`）
- Create `nutmeg/interfaces/cli/research.py`（子组 `research board|run|intake`）+ `jczq-build-reads` 命令；Modify `cli/__init__.py`
- Create `experiments/registry/R0.json`（覆盖率实验，per-match duty）
- Modify `nutmeg/decision/rsi_wiring.py` — `after_am`（`research board` + `rsi schedule`）；Modify `cli/decision.py::decision_am` 末尾一行
- Tests：`tests/decision/test_jczq_board.py`、`test_research_runner.py`、`test_research_prompt.py`、`test_jczq_reads.py`、`tests/test_cli_research.py`

---

### Task 1: 板面 legs-base（price_only）

**Files:** Create `nutmeg/decision/jczq_board.py`; Test `tests/decision/test_jczq_board.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_jczq_board.py
import json

from nutmeg.decision.jczq_board import build_board_legs, devig

def test_devig_normalises_1x2_odds():
    p = devig({"home": 2.0, "draw": 3.5, "away": 4.0})
    assert abs(sum(p.values()) - 1.0) < 1e-9 and p["home"] > p["draw"] > p["away"]

def test_build_board_legs_joins_kernel_matches_with_bold_odds(tmp_path):
    day = tmp_path / "daily" / "2026-09-19"; day.mkdir(parents=True)
    (day / "bold_odds.json").write_text(json.dumps({
        "周五001": {"match_winner": {"odds": {"home": 2.0, "draw": 3.5, "away": 4.0}, "line": None}},
        "周五002": {"match_winner": {"odds": {"home": 1.5, "draw": 4.0, "away": 6.0}, "line": -1}},
    }), encoding="utf-8")
    matches = [{"match_id": "m-1", "home_team": "A", "away_team": "B", "competition": "英超",
                "scheduled_at": "2026-09-19T19:00:00+00:00", "board_code": "周五001"},
               {"match_id": "m-2", "home_team": "C", "away_team": "D", "competition": "德甲",
                "scheduled_at": "2026-09-19T20:30:00+00:00", "board_code": "周五002"}]
    doc = build_board_legs(day="2026-09-19", matches=matches, jczq_dir=tmp_path)
    assert set(doc["legs"]) == {"周五001", "周五002"}
    leg = doc["legs"]["周五001"]
    assert leg["match_id"] == "m-1" and leg["judgment_tier"] == "price_only"
    assert leg["kickoff_bj"] == "2026-09-20T03:00:00+08:00" and abs(sum(leg["fair"].values()) - 1) < 1e-9
    assert doc["legs"]["周五002"]["hhad_line"] == -1
    assert (day / "jczq-legs-base.json").exists()
```

- [ ] **Step 2: Run** `uv run pytest tests/decision/test_jczq_board.py -v` → `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# nutmeg/decision/jczq_board.py
"""竞彩当日板 legs-base（price_only）：内核 board 场次 × bold_odds 去水 fair。零判断。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BJ = ZoneInfo("Asia/Shanghai")


def devig(odds: dict[str, float]) -> dict[str, float]:
    raw = {k: 1.0 / float(v) for k, v in odds.items()}
    s = sum(raw.values())
    return {k: v / s for k, v in raw.items()}


def _bj(iso_utc: str) -> str:
    return datetime.fromisoformat(iso_utc).astimezone(BJ).isoformat(timespec="seconds")


def build_board_legs(*, day: str, matches: list[dict], jczq_dir: Path) -> dict:
    day_dir = Path(jczq_dir) / "daily" / day
    odds = json.loads((day_dir / "bold_odds.json").read_text("utf-8"))
    legs: dict[str, dict] = {}
    for m in matches:
        code = m.get("board_code")
        if not code or code not in odds:
            continue
        mw = odds[code].get("match_winner") or {}
        o = mw.get("odds") or {}
        if not {"home", "draw", "away"} <= set(o):
            continue
        legs[code] = {"match_id": m["match_id"], "name": f"{m['home_team']}-{m['away_team']}",
                      "competition": m.get("competition"), "kickoff_bj": _bj(m["scheduled_at"]),
                      "fair": devig(o), "hhad_line": mw.get("line"),
                      "judgment_tier": "price_only", "faces": "310"}
    doc = {"day": day, "legs": legs}
    (day_dir / "jczq-legs-base.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), "utf-8")
    return doc
```
（`board_code` 从哪来：`ProductReadRepository.board_matches` 行里若无板面代码，用 `sporttery_markets.json` 的 `match_id → code` 映射；`grep -n "code" nutmeg/product/repository.py` 与 `python -c "import json;print(list(json.load(open('.nutmeg-data/jczq/daily/2026-09-18/sporttery_markets.json'))[:1]))"` 看真形状后在 CLI 层做映射，本模块只吃已带 `board_code` 的行。）

- [ ] **Step 4: Run** → 2 passed
- [ ] **Step 5: Commit** `git add nutmeg/decision/jczq_board.py tests/decision/test_jczq_board.py && git commit -m "feat(research): 竞彩板面 legs-base（price_only）"`

---

### Task 2: 提示词与简报（`research_prompt.py`）

**Files:** Create `nutmeg/decision/research_prompt.py`; Test `tests/decision/test_research_prompt.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_research_prompt.py
from nutmeg.decision.research_prompt import RESEARCH_JSON_CONTRACT, render_brief, system_prompt

def test_system_prompt_carries_agent_body_and_json_contract():
    sp = system_prompt()
    assert "反偏置约束" in sp and "禁嘴算" in sp            # agent 正文
    assert "death_three_proofs" in sp and "只输出 JSON" in sp  # 输出契约
    assert RESEARCH_JSON_CONTRACT in sp

def test_brief_contains_fair_line_and_kickoff_only_from_inputs():
    leg = {"name": "A-B", "competition": "英超", "kickoff_bj": "2026-09-20T03:00:00+08:00",
           "fair": {"home": 0.5, "draw": 0.28, "away": 0.22}, "hhad_line": -1}
    b = render_brief(code="周五001", leg=leg, profile_notes={"home": "高位逼抢", "away": ""})
    assert "周五001" in b and "50.0%" in b and "让球线 -1" in b and "高位逼抢" in b
```

- [ ] **Step 2: Run** → `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# nutmeg/decision/research_prompt.py
"""headless 深研的系统提示词 = .claude/agents/jczq-match-analyst.md 正文 + 严格 JSON 输出契约。"""
from __future__ import annotations

from pathlib import Path

_AGENT_MD = Path(__file__).resolve().parents[2] / ".claude" / "agents" / "jczq-match-analyst.md"

RESEARCH_JSON_CONTRACT = """
## 输出契约（硬约束）
只输出 JSON，不要任何前后缀文字。字段与足彩研究 JSON 完全一致：
{"name": str, "summary": str, "confidence": 1-5, "anchor_side": "home|away|none",
 "anchor_integrity": "pass|fail|symmetric_damage", "hole_location": {...},
 "license_questions": {"q1_spine": bool, "q2_route": bool, "q3a_opponent_scores": bool,
                       "q3b_opponent_takes_points": bool, "q4_no_context_flag": bool},
 "death_three_proofs": {"home"|"draw"|"away": {"a_no_scoring_mechanism": bool,
     "b_precedent_carrier_gone": bool, "c_anchor_pass": bool, "proof_count": "n/3",
     "verdict": "alive|dead", "detail": str}},
 "directional_flags": [[flag, "3|1|0"]], "nondirectional_flags": [str], "crash_markers": [str],
 "precedents": [["3|1|0", str, "alive|dead|none"]], "schedule": {...}, "market_snapshot": {...}}
宣告 dead 必须三证 3/3；查无先例记 none，不得当 dead。数字只许引用简报给你的或你查到的实盘。
"""


def system_prompt() -> str:
    body = _AGENT_MD.read_text("utf-8").split("---", 2)[-1]   # 去掉 frontmatter
    return body.strip() + "\n" + RESEARCH_JSON_CONTRACT


def render_brief(*, code: str, leg: dict, profile_notes: dict) -> str:
    f = leg["fair"]
    lines = [f"# 竞彩 {code} · {leg['name']}（{leg.get('competition')}）",
             f"开球（北京）{leg['kickoff_bj']}",
             f"去水 fair 主/平/客 = {f['home']*100:.1f}% / {f['draw']*100:.1f}% / {f['away']*100:.1f}%",
             f"让球线 {leg.get('hhad_line')}" if leg.get("hhad_line") is not None else "让球线 无",
             f"主队画像：{profile_notes.get('home') or '（无）'}",
             f"客队画像：{profile_notes.get('away') or '（无）'}",
             "只研究这一场；按输出契约只回 JSON。"]
    return "\n".join(lines)
```

- [ ] **Step 4: Run** → 2 passed
- [ ] **Step 5: Commit** `git add nutmeg/decision/research_prompt.py tests/decision/test_research_prompt.py && git commit -m "feat(research): headless 深研提示词=agent 正文+JSON 契约"`

---

### Task 3: 运行器（队列 / 预算 / 幂等 / 泄漏闸 / rejected / R0 fulfill）

**Files:** Create `nutmeg/decision/research_runner.py`; Test `tests/decision/test_research_runner.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_research_runner.py
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from nutmeg.decision.research_runner import RESEARCH_DAILY_BUDGET, run_day

BJ = ZoneInfo("Asia/Shanghai")
GOOD = json.dumps({"name": "A-B", "summary": "s", "confidence": 3, "anchor_integrity": "pass",
                   "license_questions": {"q1_spine": True, "q2_route": True, "q3a_opponent_scores": False,
                                         "q3b_opponent_takes_points": False, "q4_no_context_flag": True},
                   "death_three_proofs": {}, "directional_flags": [], "nondirectional_flags": [],
                   "crash_markers": [], "precedents": []}, ensure_ascii=False)


def _board(tmp_path, n=3, hours_ahead=5):
    d = tmp_path / "daily" / "2026-09-19"; d.mkdir(parents=True)
    ko = (datetime.now(BJ) + timedelta(hours=hours_ahead)).isoformat(timespec="seconds")
    legs = {f"周五00{i}": {"match_id": f"m-{i}", "name": f"T{i}-U{i}", "competition": "x", "kickoff_bj": ko,
                          "fair": {"home": .5, "draw": .3, "away": .2}, "hhad_line": None,
                          "judgment_tier": "price_only", "faces": "310"} for i in range(1, n + 1)}
    (d / "jczq-legs-base.json").write_text(json.dumps({"day": "2026-09-19", "legs": legs}), "utf-8")
    return tmp_path


def test_runs_each_match_once_and_writes_products_and_fulfills(tmp_path):
    root = _board(tmp_path); calls, fulfills = [], []
    rep = run_day(day="2026-09-19", jczq_dir=root, data_dir=tmp_path,
                  claude=lambda sys_prompt, brief: (calls.append(brief) or (0, GOOD)),
                  fulfill=lambda argv: fulfills.append(argv) or (0, ""), profile=lambda mid: {}, budget=10)
    assert [r["status"] for r in rep["matches"]] == ["done"] * 3 and len(calls) == 3
    assert (root / "daily" / "2026-09-19" / "research-周五001.json").exists()
    assert all(a[:4] == ["rsi", "fulfill", "--exp", "R0"] and "--match" in a for a in fulfills)
    rep2 = run_day(day="2026-09-19", jczq_dir=root, data_dir=tmp_path, claude=lambda s, b: (0, GOOD),
                   fulfill=lambda a: (0, ""), profile=lambda m: {}, budget=10)
    assert [r["status"] for r in rep2["matches"]] == ["skipped_done"] * 3       # 幂等


def test_budget_and_past_kickoff_are_recorded_not_faked(tmp_path):
    root = _board(tmp_path, n=3)
    rep = run_day(day="2026-09-19", jczq_dir=root, data_dir=tmp_path, claude=lambda s, b: (0, GOOD),
                  fulfill=lambda a: (0, ""), profile=lambda m: {}, budget=2)
    assert [r["status"] for r in rep["matches"]] == ["done", "done", "skipped_budget"]
    legs = json.loads((root / "daily" / "2026-09-19" / "jczq-legs-base.json").read_text("utf-8"))["legs"]
    assert legs["周五003"]["judgment_tier"] == "price_only"
    root2 = _board(tmp_path / "late", n=1, hours_ahead=-1)
    rep = run_day(day="2026-09-19", jczq_dir=root2, data_dir=tmp_path / "late", claude=lambda s, b: (0, GOOD),
                  fulfill=lambda a: (0, ""), profile=lambda m: {}, budget=10)
    assert rep["matches"][0]["status"] == "skipped_past_kickoff"
    assert RESEARCH_DAILY_BUDGET == 40


def test_invalid_json_is_rejected_once_and_leg_stays_price_only(tmp_path):
    root = _board(tmp_path, n=1); n = {"k": 0}
    def bad(s, b):
        n["k"] += 1; return (0, "not json")
    rep = run_day(day="2026-09-19", jczq_dir=root, data_dir=tmp_path, claude=bad, fulfill=lambda a: (0, ""),
                  profile=lambda m: {}, budget=10)
    assert rep["matches"][0]["status"] == "rejected" and n["k"] == 2                 # 只重试 1 次
    d = root / "daily" / "2026-09-19"
    assert (d / "research-周五001.rejected.json").exists() and not (d / "research-周五001.json").exists()
```

- [ ] **Step 2: Run** → `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# nutmeg/decision/research_runner.py
"""headless 深研运行器。三道保险丝：预算常量、按开球排队+开球后不启动、幂等跳过。
任何一道触发都如实记录，不降级成假判读。"""
from __future__ import annotations

import json
import subprocess
import tempfile
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from nutmeg.decision.research_prompt import render_brief, system_prompt

BJ = ZoneInfo("Asia/Shanghai")
RESEARCH_DAILY_BUDGET = 40          # RULEBOOK 常量：改动走 rsi deploy
MAX_ATTEMPTS = 2
Claude = Callable[[str, str], tuple[int, str]]
Fulfill = Callable[[list[str]], tuple[int, str]]
Profile = Callable[[str], dict]

_REQUIRED = ("name", "summary", "confidence", "anchor_integrity", "license_questions",
             "death_three_proofs", "directional_flags", "nondirectional_flags", "crash_markers", "precedents")


def _claude_cli(sys_prompt: str, brief: str) -> tuple[int, str]:
    argv = ["claude", "-p", "--system-prompt", sys_prompt, "--allowedTools", "WebSearch,WebFetch",
            "--max-turns", "12", "--output-format", "text"]
    with tempfile.TemporaryDirectory() as neutral:
        p = subprocess.run(argv, input=brief, capture_output=True, text=True, timeout=900, cwd=neutral, check=False)
    return p.returncode, p.stdout


def _cli_fulfill(argv: list[str]) -> tuple[int, str]:
    from nutmeg.decision.rsi_wiring import _cli_invoke
    return _cli_invoke(argv)


def _validate(text: str) -> dict:
    doc = json.loads(text)
    missing = [k for k in _REQUIRED if k not in doc]
    if missing:
        raise ValueError(f"缺字段 {missing}")
    if not 1 <= int(doc["confidence"]) <= 5:
        raise ValueError("confidence 不在 1-5")
    for face, d3 in (doc.get("death_three_proofs") or {}).items():
        if str(d3.get("verdict", "alive")).lower() == "dead":
            cnt = sum(bool(d3.get(k)) for k in ("a_no_scoring_mechanism", "b_precedent_carrier_gone", "c_anchor_pass"))
            if cnt < 3:
                raise ValueError(f"{face} 宣告 dead 但三证 {cnt}/3")
    return doc


def run_day(*, day: str, jczq_dir: Path, data_dir: Path, claude: Claude = _claude_cli,
            fulfill: Fulfill = _cli_fulfill, profile: Profile = lambda mid: {},
            budget: int = RESEARCH_DAILY_BUDGET, code: str | None = None) -> dict:
    d = Path(jczq_dir) / "daily" / day
    board_path = d / "jczq-legs-base.json"
    board = json.loads(board_path.read_text("utf-8"))
    legs = board["legs"]
    order = sorted(legs, key=lambda c: legs[c]["kickoff_bj"])
    if code:
        order = [c for c in order if c == code]
    sp = system_prompt()
    now = datetime.now(BJ)
    used = 0
    rows = []
    for c in order:
        leg = legs[c]
        out = d / f"research-{c}.json"
        if out.exists():
            rows.append({"code": c, "status": "skipped_done"}); continue
        if datetime.fromisoformat(leg["kickoff_bj"]) <= now:
            rows.append({"code": c, "status": "skipped_past_kickoff"}); continue
        if used >= budget:
            rows.append({"code": c, "status": "skipped_budget"}); continue
        used += 1
        brief = render_brief(code=c, leg=leg, profile_notes=profile(leg["match_id"]))
        t0 = time.time(); status = "rejected"; last = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            rc, text = claude(sp, brief)
            last = text
            try:
                if rc != 0:
                    raise ValueError(f"claude 退出码 {rc}")
                doc = _validate(text)
            except (ValueError, json.JSONDecodeError):
                continue
            doc["captured_at"] = datetime.now(BJ).isoformat(timespec="seconds")
            out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), "utf-8")
            leg["judgment_tier"] = "deep_research"
            status = "done"
            fulfill(["rsi", "fulfill", "--exp", "R0", "--duty", "match-research", "--day", day,
                     "--match", leg["match_id"], "--artifact", str(out), "--n-rows", "1",
                     "--stratum", "jczq", "--data-dir", str(data_dir)])
            break
        if status == "rejected":
            (d / f"research-{c}.rejected.json").write_text(last, "utf-8")
        rows.append({"code": c, "status": status, "seconds": round(time.time() - t0, 1), "attempts": attempt})
    board_path.write_text(json.dumps(board, ensure_ascii=False, indent=1), "utf-8")
    report = {"day": day, "budget": budget, "matches": rows}
    (d / f"research-run-{day}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
    return report
```
（`rsi fulfill` 目前无 `--match` / `--stratum` 选项：在 `nutmeg/interfaces/cli/rsi.py::fulfill` 加 `match: str = typer.Option("", "--match")` 并透传 `match_id=match`；`--stratum` 已有。`rsi fulfill` 的 `earliest_kickoff` 解析依赖 `--issue`：竞彩没有期，加分支——当 `--match` 给定时，从 `jczq-legs-base.json` 取该场 `kickoff_bj` 作截止。）

- [ ] **Step 4: Run** → 3 passed
- [ ] **Step 5: Commit** `git add nutmeg/decision/research_runner.py nutmeg/interfaces/cli/rsi.py tests/decision/test_research_runner.py tests/test_cli_rsi.py && git commit -m "feat(research): headless 深研运行器——预算/排队/幂等/泄漏闸/拒收，R0 逐场登记"`

---

### Task 4: intake by code + `face_status`；`jczq-build-reads`

**Files:** Modify `nutmeg/decision/research_intake.py`（暴露每场函数）；Create `nutmeg/decision/jczq_reads.py`；Test `tests/decision/test_jczq_reads.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_jczq_reads.py
import json

from nutmeg.decision.jczq_reads import build_jczq_reads, intake_board

RESEARCH = {"name": "A-B", "summary": "s", "confidence": 3, "anchor_integrity": "pass", "anchor_side": "home",
            "license_questions": {"q1_spine": True, "q2_route": True, "q3a_opponent_scores": False,
                                  "q3b_opponent_takes_points": False, "q4_no_context_flag": True},
            "death_three_proofs": {"away": {"a_no_scoring_mechanism": True, "b_precedent_carrier_gone": True,
                                            "c_anchor_pass": True, "proof_count": "3/3", "verdict": "dead", "detail": "…"}},
            "directional_flags": [], "nondirectional_flags": [], "crash_markers": [], "precedents": []}


def _day(tmp_path):
    d = tmp_path / "daily" / "2026-09-19"; d.mkdir(parents=True)
    legs = {"周五001": {"match_id": "m-1", "name": "A-B", "competition": "x", "kickoff_bj": "2026-09-20T03:00:00+08:00",
                       "fair": {"home": .6, "draw": .25, "away": .15}, "hhad_line": None,
                       "judgment_tier": "deep_research", "faces": "310"}}
    (d / "jczq-legs-base.json").write_text(json.dumps({"day": "2026-09-19", "legs": legs}), "utf-8")
    (d / "research-周五001.json").write_text(json.dumps(RESEARCH, ensure_ascii=False), "utf-8")
    return tmp_path


def test_intake_backfills_labels_and_face_status_by_code(tmp_path):
    root = _day(tmp_path)
    rep = intake_board(day="2026-09-19", jczq_dir=root, write=True)
    legs = json.loads((root / "daily" / "2026-09-19" / "jczq-legs-base.json").read_text("utf-8"))["legs"]
    leg = legs["周五001"]
    assert rep["ok"] == ["周五001"] and leg["confidence"] == 3 and leg["anchor_integrity"] == "pass"
    assert leg["face_status"]["away"]["state"] == "dead" and leg["faces"] == "31"


def test_build_reads_marks_ai_judge_and_deep_tier(tmp_path):
    root = _day(tmp_path); intake_board(day="2026-09-19", jczq_dir=root, write=True)
    reads = build_jczq_reads(day="2026-09-19", jczq_dir=root, made_at="2026-09-19T12:00:00+08:00")
    assert len(reads) == 1 and reads[0]["judge"] == "ai:jczq-analyst"
    assert reads[0]["match_id"] == "m-1" and reads[0]["judgment_tier"] == "deep_research"
    assert abs(sum(reads[0]["belief"].values()) - 1) < 1e-9 and reads[0]["belief"]["away"] == 0.0
```

- [ ] **Step 2: Run** → `ModuleNotFoundError`

- [ ] **Step 3: Implement**

先在 `research_intake.py` 找到「对一场做校验并回填 leg」的函数（`grep -n "^def " nutmeg/decision/research_intake.py`；它以 `match_no` 与 `leg` 为参数、返回 issues 列表并就地写 `confidence/anchor_integrity/flags/_d3/…`）。若它耦合了 `<期>-research-m<N>.json` 的读取，把「读文件」与「校验+回填」拆开，导出 `intake_leg(leg: dict, research: dict, *, key: str) -> list[IntakeIssue]`，原命令改调它（行为不变，已有测试守）。

```python
# nutmeg/decision/jczq_reads.py
"""竞彩板：研究 JSON → legs-base 回填（含 face_status）→ 草稿 Read（judge=ai:jczq-analyst）。"""
from __future__ import annotations

import json
from pathlib import Path

from nutmeg.decision.face_status import FaceStatusError, attach_face_status
from nutmeg.decision.research_intake import intake_leg

FACES = ("home", "draw", "away")


def intake_board(*, day: str, jczq_dir: Path, write: bool) -> dict:
    d = Path(jczq_dir) / "daily" / day
    board_path = d / "jczq-legs-base.json"
    board = json.loads(board_path.read_text("utf-8"))
    ok, failed = [], {}
    for code, leg in board["legs"].items():
        rp = d / f"research-{code}.json"
        if not rp.exists():
            continue
        research = json.loads(rp.read_text("utf-8"))
        issues = [i for i in intake_leg(leg, research, key=code) if i.severity == "ERROR"]
        if issues:
            failed[code] = [i.message for i in issues]; continue
        try:
            attach_face_status(leg, research, source=rp.name)
        except FaceStatusError as exc:
            failed[code] = [str(exc)]; continue
        ok.append(code)
    if write:
        board_path.write_text(json.dumps(board, ensure_ascii=False, indent=1), "utf-8")
    return {"ok": ok, "failed": failed}


def build_jczq_reads(*, day: str, jczq_dir: Path, made_at: str) -> list[dict]:
    d = Path(jczq_dir) / "daily" / day
    board = json.loads((d / "jczq-legs-base.json").read_text("utf-8"))
    reads = []
    for code, leg in board["legs"].items():
        if leg.get("judgment_tier") != "deep_research" or "face_status" not in leg:
            continue
        alive = [f for f in FACES if leg["face_status"][f]["state"] == "alive"]
        mass = sum(float(leg["fair"][f]) for f in alive)
        belief = {f: (float(leg["fair"][f]) / mass if f in alive else 0.0) for f in FACES}
        reads.append({"match_id": leg["match_id"], "market": "had", "judge": "ai:jczq-analyst",
                      "made_at": made_at, "prior": dict(leg["fair"]), "belief": belief,
                      "confidence": leg.get("confidence"), "judgment_tier": "deep_research",
                      "status": "draft", "note": f"{code} {leg['name']}",
                      "flags": {"directional": leg.get("directional_flags", []),
                                "nondirectional": leg.get("nondirectional_flags", [])}})
    (d / "reads.json").write_text(json.dumps(reads, ensure_ascii=False, indent=1), "utf-8")
    return reads
```
（belief = 活面按 fair 归一——这是**第一序的机械后果**，不是新判断：死面质量归零，其余按价格比例。`decision-read --reads-file` 期望的 Read 字段以 `nutmeg/decision/read_builder.py` 产出的 reads.json 为准：`python -c "import json;print(json.load(open('.nutmeg-data/zucai/26129-reads.json'))[0].keys())"` 看真键名并对齐——键名不同就改这里，不改 decision-read。）

- [ ] **Step 4: Run** → 2 passed（+ 既有 `tests/decision/test_research_intake.py` 仍绿）
- [ ] **Step 5: Commit** `git add nutmeg/decision/research_intake.py nutmeg/decision/jczq_reads.py tests/decision/test_jczq_reads.py && git commit -m "feat(research): 按板面代码 intake + face_status；竞彩草稿 Read（ai:jczq-analyst）"`

---

### Task 5: CLI `research board|run|intake` + `jczq-build-reads` + R0 登记 + 备料链接线

**Files:** Create `nutmeg/interfaces/cli/research.py`；Modify `cli/__init__.py`；Create `experiments/registry/R0.json`；Modify `nutmeg/decision/rsi_wiring.py`（`after_am`）与 `cli/decision.py::decision_am`；Test `tests/test_cli_research.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_research.py
import json

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app


def test_research_board_run_intake_build_reads_pipeline(tmp_path, monkeypatch):
    root = tmp_path / "jczq"; d = root / "daily" / "2026-09-19"; d.mkdir(parents=True)
    (d / "bold_odds.json").write_text(json.dumps({"周五001": {"match_winner": {"odds": {"home": 2.0, "draw": 3.5, "away": 4.0}}}}), "utf-8")
    import nutmeg.interfaces.cli.research as mod
    monkeypatch.setattr(mod, "_board_matches", lambda day, data_dir: [
        {"match_id": "m-1", "home_team": "A", "away_team": "B", "competition": "x",
         "scheduled_at": "2099-01-01T19:00:00+00:00", "board_code": "周五001"}])
    good = json.dumps({"name": "A-B", "summary": "s", "confidence": 3, "anchor_integrity": "pass",
                       "license_questions": {"q1_spine": True, "q2_route": True, "q3a_opponent_scores": False,
                                             "q3b_opponent_takes_points": False, "q4_no_context_flag": True},
                       "death_three_proofs": {}, "directional_flags": [], "nondirectional_flags": [],
                       "crash_markers": [], "precedents": []})
    monkeypatch.setattr(mod, "_claude", lambda s, b: (0, good))
    monkeypatch.setattr(mod, "_fulfill", lambda argv: (0, ""))
    r = CliRunner()
    assert r.invoke(app, ["research", "board", "--day", "2026-09-19", "--jczq-dir", str(root), "--data-dir", str(tmp_path)]).exit_code == 0
    out = r.invoke(app, ["research", "run", "--day", "2026-09-19", "--jczq-dir", str(root), "--data-dir", str(tmp_path)])
    assert out.exit_code == 0 and "done" in out.output
    out = r.invoke(app, ["research", "intake", "--day", "2026-09-19", "--jczq-dir", str(root), "--write"])
    assert out.exit_code == 0 and "周五001" in out.output
    out = r.invoke(app, ["jczq-build-reads", "--day", "2026-09-19", "--jczq-dir", str(root)])
    assert out.exit_code == 0 and (d / "reads.json").exists()


def test_r0_registry_doc_declares_a_per_match_duty():
    from nutmeg.decision.rsi_prereg import load_registry_doc
    doc = load_registry_doc("experiments/registry/R0.json")
    assert doc["population"] == "jczq" and doc["tier"] == "observation" and doc["layer"] == "judgment"
    d = doc["duties"][0]
    assert d["scope"] == "match" and d["deadline_rule"] == "match_kickoff" and "{day}" in " ".join(d["instrument"])
```

- [ ] **Step 2: Run** → `No such command 'research'`

- [ ] **Step 3: Implement**

```python
# nutmeg/interfaces/cli/research.py
"""`nutmeg research board|run|intake` + `jczq-build-reads`：竞彩全板深研桥。"""
from __future__ import annotations

from pathlib import Path

import typer

import nutmeg.interfaces.cli as _cli
from nutmeg.decision.research_runner import _claude_cli as _claude
from nutmeg.decision.research_runner import _cli_fulfill as _fulfill

research_app = typer.Typer(help="竞彩全板深研桥（headless）")
_cli.app.add_typer(research_app, name="research")
_DAY = typer.Option(..., "--day")
_JCZQ = typer.Option(Path(".nutmeg-data/jczq"), "--jczq-dir")
_DATA = typer.Option(Path(".nutmeg-data"), "--data-dir")


def _board_matches(day: str, data_dir: Path) -> list[dict]:
    """内核当日板 + sporttery_markets 的 match_id→板面代码映射。"""
    import json
    from datetime import UTC, datetime, timedelta
    from nutmeg.config.settings import AppSettings
    from nutmeg.ontology import build_ontology_kernel
    from nutmeg.product.repository import ProductReadRepository

    k = build_ontology_kernel(AppSettings(data_dir=Path(data_dir).resolve())); k.initialize()
    repo = ProductReadRepository(k.engine, k.paths.analytics)
    start = datetime.fromisoformat(f"{day}T00:00:00+08:00").astimezone(UTC)
    rows = repo.board_matches(start.isoformat(), (start + timedelta(days=1)).isoformat(),
                              as_of=datetime.now(UTC).isoformat())
    mp = Path(data_dir) / "jczq" / "daily" / day / "sporttery_markets.json"
    codes = {}
    if mp.exists():
        for it in json.loads(mp.read_text("utf-8")) if isinstance(json.loads(mp.read_text("utf-8")), list) else []:
            if it.get("match_id") and it.get("code"):
                codes[it["match_id"]] = it["code"]
    return [{**r, "board_code": codes.get(r["match_id"])} for r in rows]


@research_app.command("board")
def board(day: str = _DAY, jczq_dir: Path = _JCZQ, data_dir: Path = _DATA) -> None:
    from nutmeg.decision.jczq_board import build_board_legs
    doc = build_board_legs(day=day, matches=_board_matches(day, data_dir), jczq_dir=jczq_dir)
    typer.echo(f"{day} 板面 {len(doc['legs'])} 场 → jczq-legs-base.json（price_only）")


@research_app.command("run")
def run(day: str = _DAY, jczq_dir: Path = _JCZQ, data_dir: Path = _DATA,
        code: str | None = typer.Option(None, "--code"), budget: int | None = typer.Option(None, "--budget")) -> None:
    from nutmeg.decision.research_runner import RESEARCH_DAILY_BUDGET, run_day
    rep = run_day(day=day, jczq_dir=jczq_dir, data_dir=data_dir, claude=_claude, fulfill=_fulfill,
                  budget=budget or RESEARCH_DAILY_BUDGET, code=code)
    for r in rep["matches"]:
        typer.echo(f"  {r['code']} {r['status']}" + (f" {r.get('seconds')}s" if r.get("seconds") else ""))


@research_app.command("intake")
def intake(day: str = _DAY, jczq_dir: Path = _JCZQ, write: bool = typer.Option(False, "--write")) -> None:
    from nutmeg.decision.jczq_reads import intake_board
    rep = intake_board(day=day, jczq_dir=jczq_dir, write=write)
    typer.echo(f"入库 {len(rep['ok'])} 场: {' '.join(rep['ok'])}" + ("" if write else "（预演，未写）"))
    for c, msgs in rep["failed"].items():
        typer.echo(f"  ✗ {c}: {'; '.join(msgs)}")


@_cli.app.command("jczq-build-reads")
def jczq_build_reads(day: str = _DAY, jczq_dir: Path = _JCZQ,
                     made_at: str | None = typer.Option(None, "--made-at")) -> None:
    from datetime import datetime
    from nutmeg.decision.jczq_reads import build_jczq_reads
    reads = build_jczq_reads(day=day, jczq_dir=jczq_dir,
                             made_at=made_at or datetime.now().astimezone().isoformat(timespec="seconds"))
    typer.echo(f"{day} 草稿 Read {len(reads)} 条 → daily/{day}/reads.json（下一步 decision-read --reads-file）")
```
（`sporttery_markets.json` 的真形状要先看：`python -c "import json;d=json.load(open('.nutmeg-data/jczq/daily/2026-09-18/sporttery_markets.json'));print(type(d), (d[0] if isinstance(d,list) else list(d.items())[:1]))"`，映射键名按真形状改。）

`experiments/registry/R0.json`：
```json
{"exp_id": "R0", "claim": "竞彩全板每场都有前瞻深研（覆盖率）；未研场如实为 gap。",
 "mechanism": "覆盖率不是假设，是义务账；它让 U10 有账可查。",
 "tier": "observation", "layer": "judgment", "population": "jczq", "min_tier": "price_only",
 "window": {"date_from": "2026-09-20", "n_min": 200},
 "falsifier": {"metric": "coverage_pct", "stratum": "jczq", "n_min": 200, "bound": "ci_lower",
               "threshold_pp": 80.0, "direction": "lt_means_falsified"},
 "stop_rule": "累计 200 场结账；覆盖率 CI 下界 < 80% 即证伪（说明预算/流程不够）。", "quota_slot": false,
 "buckets": [], "rule_ids": [], "source_doc": "docs/superpowers/specs/2026-09-19-jczq-board-research-bridge-design.md",
 "registered_at": "2026-09-19",
 "duties": [{"name": "match-research", "scope": "match", "deadline_rule": "match_kickoff",
             "instrument": ["uv", "run", "nutmeg", "research", "run", "--day", "{day}"],
             "artifact_glob": ".nutmeg-data/jczq/daily/{day}/research-*.json",
             "description": "每场 headless 深研；开球前落"}]}
```

`rsi_wiring.py` 加 `after_am(*, day, data_dir, invoke=_cli_invoke)`：`invoke(["research","board","--day",day,"--data-dir",str(data_dir)])` 然后 `invoke(["rsi","schedule","--day",day,"--data-dir",str(data_dir)])`（`rsi schedule` 需扩展：`--issue` 缺省时从 `jczq-legs-base.json` 取当日各场 `kickoff_bj` 作 `match_kickoffs`，最早者作 `earliest_kickoff`）。`decision_am` 成功（非 dry-run）后加一行调用。测试与 `after_settle` 同型（假 invoke 记 argv）。

- [ ] **Step 4: Run** `uv run pytest tests/test_cli_research.py tests/decision/test_rsi_wiring.py tests/test_cli_rsi.py -v` → 全绿
- [ ] **Step 5: Commit** `git add nutmeg/interfaces/cli/research.py nutmeg/interfaces/cli/__init__.py nutmeg/interfaces/cli/rsi.py nutmeg/interfaces/cli/decision.py nutmeg/decision/rsi_wiring.py experiments/registry/R0.json tests/test_cli_research.py tests/decision/test_rsi_wiring.py && git commit -m "feat(research): CLI research board/run/intake + jczq-build-reads + R0 覆盖率义务 + 备料链接线"`

---

### Task 6: 真库登记 R0 + RUNBOOK 泳道 A 入册 + 一次真运行（--budget 2）

- [ ] `uv run nutmeg rsi register experiments/registry/R0.json` → 已登记
- [ ] RUNBOOK 泳道 A：A1 行末加「`decision-am` 后自动 `research board` + `rsi schedule`」；A3 行加「`research run --day`（headless，预算 40 场/日，研不到记 price_only）→ `research intake --write` → `jczq-build-reads` → `decision-read`」；非决策附录加「R0 覆盖率义务」一段
- [ ] 真运行验证（**唯一允许的真调用，且限 2 场**）：`uv run nutmeg research board --day <今天>` → `uv run nutmeg research run --day <今天> --budget 2` → 贴运行报告；`uv run nutmeg research intake --day <今天>`（先不 `--write`）看校验结果
- [ ] Commit `git add docs/sop/RUNBOOK.md && git commit -m "docs(runbook): 泳道 A 深研桥入册"`

## Self-review
spec §3 对象（板面 legs-base / 研究产物 / 草稿 Read / R0）→ Task 1/3/4/5；§4 运行器六条 → Task 3；§5 命令面与接线 → Task 5；§6 保险丝 → Task 3 常量与状态；§7 测试逐条有；§8 出口 → Task 6。类型：`run_day` 的 `claude/fulfill/profile` 签名在 Task 3 定义、Task 5 注入；`intake_leg(leg, research, key=)` 在 Task 4 定义并被 `intake_board` 调用。留白：`board_code` 映射与 reads.json 真键名要按真文件核对（步骤里写明了看什么）。
