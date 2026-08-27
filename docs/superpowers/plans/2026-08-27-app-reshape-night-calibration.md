# Nutmeg 应用成型方案 + Package 1（夜间校准链）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

日期：2026-08-27 ｜ 状态：成型方案待用户批准分包；Package 1 任务已可执行
上位设计：`docs/superpowers/specs/2026-08-24-nutmeg-intelligence-os-design.md`（M1-M6 已并入 main，发布卡四门）
本文关系：对上位设计的**应用层修订提案**（八工作区 → 三表面），不改架构层（本体内核/typed Actions/发布门全部沿用）。

**Goal:** 把应用层从"八工作区工作站"改造成"期次生命周期流水线 × 三表面"，并先落地第一个可执行包：`nutmeg zucai-night-calibrate`——夜间结果自动抓取 + 90 分钟口径彩果 + 票面存活报告。

**Architecture:** 判断层继续住在 Claude Code 对话主循环（宪法元原则一）；本包只做确定性算术（取数、口径拆分、命中计算、渲染报告），产物是供主循环写 rx 夜账的报告与快照文件，**不自动改 rx / scoreboard**。身份映射走每期显式 `{issue}-af-map.json`，禁止按队名猜测回退（OS 不变量：identity 不静默回退）。

**Tech Stack:** Python 3.12 / typer CLI（`@_cli.app.command` 仿 `interfaces/cli/decision.py` 既有模式）/ httpx / pytest（`uv run pytest`）。数据源 API-Football（env：`NUTMEG_API_FOOTBALL_BASE_URL`、`NUTMEG_API_FOOTBALL_KEY`），okooo 因 WAF 405 降为人工核对源。

---

## §1 使用习惯证据（设计地基，六条）

1. **对话是主战场**：判读/构票/裁决/复盘全在会话完成（26111 一期 11 条 ADJ、12+ 票版本）。宪法钦定：判断永不入脚本。
2. **节奏 = 期次生命周期，一天两峰**：午后备料判读构票（14:00→18:30→22:00），清晨结果校准（跨三夜期次要做三次）。
3. **用户是重度版本探索者**：自提票版、同价变体、知情行权（user_naked_wheels 一等公民）。系统要支持"被推翻并记账"。
4. **战绩驱动**：规则生死看记分牌 tally，复盘必立法。
5. **异步确认是真实短板**：26111 两票至今未入账——确认动作缺一个离开电脑也能完成的表面。
6. **数据源沉默失败**：okooo 405 靠现场撞见（2026-08-27 晨），应是告警。

## §2 工作区裁决（对上位设计 §8 的修订）

| 上位设计工作区 | 裁决 | 理由 |
|---|---|---|
| 8.3 调查室 web 版 AI 线程 | 砍 | 对话主循环已覆盖；只留只读证据时间轴 |
| 8.2 数据运维中心 | 缩为健康条+告警栏 | 日常只需"prep 跑没跑、源断没断" |
| 8.7 本体浏览器 | 降为开发工具 | 非日常动作 |
| 8.1 指挥台 + 8.4 票面工作台 + 8.5 结算复盘 | 合并为**期次驾驶舱**一屏 | 注意力单位是"这一期" |
| 8.6 规则校准中心 | 瘦身为记分牌页 | 立法动作留在对话 |
| 8.8 告警流 | 保留，主出口改 telegram | 告警要追到手机 |

## §3 业务框架 = 期次状态机（产品骨架）

| 状态 | 责任方 | 表面 | 门 |
|---|---|---|---|
| 备料 | 脚本（prep 链，已活） | 后台 | 源健康告警 |
| 判读→构票→裁决 | AI+用户 | 对话主循环 | 判决表/RULEBOOK |
| 审计→部署门 | 脚本 | CLI→驾驶舱 | ERROR 退出码 1；中位倍数门槛 |
| 出票→入账 | 用户 | Telegram 一键确认 | 没入账=没打；超时自动标 shadow |
| 在场（夜 1..n） | 脚本（**本计划 Package 1**） | 晨间校准报告 | 90' 口径；三源制 |
| 结算→复盘→立法 | 脚本结算 + AI/用户复盘 | 对话；scoreboard 投影 | falsifier 预注册执行 |

## §4 分包与对齐（Package 2-4 各立独立 plan，不在本文件内展开任务）

| 包 | 内容 | 依赖/对齐 |
|---|---|---|
| **P1 夜间校准链（本计划 §5）** | 结果抓取+口径拆分+票面存活报告 | 26111 期中校准手工流程的代码化；三源制；26095 口径纪律 |
| P2 确认闭环 | Telegram 出票两段确认 + 入账 Action + 超时 shadow 标记 | M4 保护确认流；26111 未入账事故；RULEBOOK 部署门条 |
| P3 ADJ 对象化 | rx pending_adjudications → 本体 Adjudication 对象 + 队列 | 08-23 重构 P1 四新对象；26111 待办 3（audit override 通道）；偏离登记条 |
| P4 期次驾驶舱 | 合并三工作区的一屏 web + 记分牌投影页 | M5 记分牌切换（发布门之一）；先关四门再动工 |

其余 26111 待办对齐：待办 4（优化器 CLI）并入 P4 前置；待办 7-8（C8/部署门代码化）走 RULEBOOK probation 攒样本后独立小包。

---

## §5 Package 1 实施任务

### 数据契约（先于代码锁定）

- **输入 1** `{issue}-issue.json`：已有（matches: match_no/home_team/away_team/kickoff_bj/match_date）。
- **输入 2** `{issue}-af-map.json`（新，备料时由主循环生成、人可查验）：
  ```json
  {"issue": "26111", "fixtures": {"3": 1234501, "4": 1234502, "5": 1234503}}
  ```
  match_no → API-Football fixture_id 显式映射。缺条目=该场显式跳过，绝不按队名模糊回退。
- **输入 3** `{issue}-final-tickets.json`（新，B9 出票时由主循环落，顺带修复"票面 faces 住在散文里"的问题）：
  ```json
  {"issue": "26111", "tickets": [
    {"id": "SFC192", "kind": "胜负彩", "faces": {"1": "30", "2": "3", "3": "1", "4": "31", "5": "31", "6": "31", "7": "3", "8": "31", "9": "0", "10": "3", "11": "310", "12": "3", "13": "1", "14": "3"}}
  ]}
  ```
  （SFC192 的 faces 逐场取自 26111-rx.json 的已知 code 串；R9 等复式票的双选第二面若散文未记全，须先核回再录——见 Task 8。）
- **输出** `{issue}-night-{date}-af.json` 快照（source/fetched_at/results/skipped）+ stdout 人读报告。
- **90' 口径铁律**：一律取 `score.fulltime`；status ∈ {FT, AET, PEN} 才算完赛；AET/PEN 的加时/点球不进彩果。

### Task 1: 彩果编码纯函数

**Files:**
- Create: `nutmeg/decision/zucai_night.py`
- Test: `tests/decision/test_zucai_night.py`

- [ ] **Step 1: 写失败测试**

```python
from nutmeg.decision.zucai_night import result_code


def test_result_code_home_win():
    assert result_code(4, 1) == "3"


def test_result_code_draw():
    assert result_code(1, 1) == "1"


def test_result_code_away_win():
    assert result_code(1, 2) == "0"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/decision/test_zucai_night.py -v`
Expected: FAIL（ImportError: cannot import name 'result_code'）

- [ ] **Step 3: 最小实现**

```python
"""夜间结果校准（确定性算术层）。

胜负彩 90 分钟口径：AET/PEN 一律取 score.fulltime（26095/26111 场5 口径纪律）。
身份纪律：match_no → fixture_id 必须来自 {issue}-af-map.json 显式映射，
缺失即显式跳过，禁止按队名猜测回退（Intelligence OS 不变量）。
本模块不写 rx、不写 scoreboard——判断与复盘留在主循环。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_FINISHED = {"FT", "AET", "PEN"}


def result_code(ft_home: int, ft_away: int) -> str:
    """90 分钟比分 → 彩果 3/1/0。"""
    if ft_home > ft_away:
        return "3"
    if ft_home == ft_away:
        return "1"
    return "0"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/decision/test_zucai_night.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/zucai_night.py tests/decision/test_zucai_night.py
git commit -m "feat(decision): 夜间校准 90' 彩果编码纯函数"
```

### Task 2: 每期 af-map 加载

**Files:**
- Modify: `nutmeg/decision/zucai_night.py`
- Test: `tests/decision/test_zucai_night.py`

- [ ] **Step 1: 写失败测试**

```python
import json

from nutmeg.decision.zucai_night import load_af_map


def test_load_af_map(tmp_path):
    (tmp_path / "26111-af-map.json").write_text(json.dumps(
        {"issue": "26111", "fixtures": {"3": 1234501, "4": 1234502}}), "utf-8")
    assert load_af_map(tmp_path, "26111") == {"3": 1234501, "4": 1234502}


def test_load_af_map_missing_file_is_empty(tmp_path):
    assert load_af_map(tmp_path, "26111") == {}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/decision/test_zucai_night.py -v -k af_map`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现**

```python
def load_af_map(zucai_dir, issue: str) -> dict[str, int]:
    """{issue}-af-map.json → {match_no(str): fixture_id(int)}。缺文件=空映射（全场显式跳过）。"""
    path = Path(zucai_dir) / f"{issue}-af-map.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text("utf-8"))
    return {str(k): int(v) for k, v in (data.get("fixtures") or {}).items()}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/decision/test_zucai_night.py -v -k af_map`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/zucai_night.py tests/decision/test_zucai_night.py
git commit -m "feat(decision): af-map 显式身份映射加载"
```

### Task 3: API-Football 当日抓取（可注入 fetcher）

**Files:**
- Modify: `nutmeg/decision/zucai_night.py`
- Test: `tests/decision/test_zucai_night.py`

- [ ] **Step 1: 写失败测试**

```python
from nutmeg.decision.zucai_night import fetch_af_day


def _af_payload():
    return {"response": [
        {"fixture": {"id": 1234503, "status": {"short": "AET"}},
         "teams": {"home": {"name": "Celje"}, "away": {"name": "Slovan Bratislava"}},
         "score": {"fulltime": {"home": 1, "away": 1}}},
        {"fixture": {"id": 1234501, "status": {"short": "FT"}},
         "teams": {"home": {"name": "AEK Athens FC"}, "away": {"name": "Levski Sofia"}},
         "score": {"fulltime": {"home": 4, "away": 0}}},
    ]}


def test_fetch_af_day_uses_fulltime_and_status(monkeypatch):
    monkeypatch.setenv("NUTMEG_API_FOOTBALL_BASE_URL", "https://af.example")
    monkeypatch.setenv("NUTMEG_API_FOOTBALL_KEY", "k")
    seen = {}

    def fake_fetcher(url, headers):
        seen["url"], seen["headers"] = url, headers
        return _af_payload()

    fixtures = fetch_af_day("2026-08-26", fetcher=fake_fetcher)
    assert seen["url"] == "https://af.example/fixtures?date=2026-08-26"
    assert seen["headers"] == {"x-apisports-key": "k"}
    assert fixtures[1234503] == {"status": "AET", "ft_home": 1, "ft_away": 1,
                                 "home": "Celje", "away": "Slovan Bratislava"}
    assert fixtures[1234501]["ft_home"] == 4
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/decision/test_zucai_night.py -v -k fetch_af`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现**

```python
def fetch_af_day(date: str, *, fetcher=None) -> dict[int, dict]:
    """API-Football /fixtures?date= → {fixture_id: {status, ft_home, ft_away, home, away}}。

    ft_* 取 score.fulltime（90' 口径）；加时/点球比分被刻意丢弃。
    """
    if fetcher is None:
        def fetcher(url, headers):
            import httpx
            resp = httpx.get(url, headers=headers, timeout=25.0)
            resp.raise_for_status()
            return resp.json()
    base = os.environ["NUTMEG_API_FOOTBALL_BASE_URL"].rstrip("/")
    headers = {"x-apisports-key": os.environ["NUTMEG_API_FOOTBALL_KEY"]}
    payload = fetcher(f"{base}/fixtures?date={date}", headers)
    out: dict[int, dict] = {}
    for f in payload.get("response") or []:
        ft = (f.get("score") or {}).get("fulltime") or {}
        out[int(f["fixture"]["id"])] = {
            "status": f["fixture"]["status"]["short"],
            "ft_home": ft.get("home"),
            "ft_away": ft.get("away"),
            "home": f["teams"]["home"]["name"],
            "away": f["teams"]["away"]["name"],
        }
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/decision/test_zucai_night.py -v -k fetch_af`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/zucai_night.py tests/decision/test_zucai_night.py
git commit -m "feat(decision): API-Football 当日 fixtures 抓取(fulltime 口径)"
```

### Task 4: 夜间彩果解析（映射/完赛/缺失三重显式跳过）

**Files:**
- Modify: `nutmeg/decision/zucai_night.py`
- Test: `tests/decision/test_zucai_night.py`

- [ ] **Step 1: 写失败测试**

```python
from nutmeg.decision.zucai_night import night_results

_MATCHES = [
    {"match_no": 3, "home_team": "雅典", "away_team": "索斯基"},
    {"match_no": 5, "home_team": "采列", "away_team": "布拉迪"},
    {"match_no": 7, "home_team": "萨茨堡", "away_team": "米亚尔"},
    {"match_no": 8, "home_team": "比尔森", "away_team": "红星"},
]
_FIXTURES = {
    1234501: {"status": "FT", "ft_home": 4, "ft_away": 0, "home": "AEK Athens FC", "away": "Levski Sofia"},
    1234503: {"status": "AET", "ft_home": 1, "ft_away": 1, "home": "Celje", "away": "Slovan Bratislava"},
    1234507: {"status": "NS", "ft_home": None, "ft_away": None, "home": "Salzburg", "away": "Brann"},
}


def test_night_results_codes_and_skips():
    af_map = {"3": 1234501, "5": 1234503, "7": 1234507}
    results, skipped = night_results(_MATCHES, af_map, _FIXTURES)
    assert results["3"]["code"] == "3" and results["3"]["ft"] == "4-0"
    assert results["5"]["code"] == "1"          # AET 取 90' 1-1 = 平
    assert "7" not in results                    # 未完赛
    assert any("场7" in s and "NS" in s for s in skipped)
    assert any("场8" in s and "无映射" in s for s in skipped)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/decision/test_zucai_night.py -v -k night_results`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现**

```python
def night_results(matches: list[dict], af_map: dict[str, int],
                  fixtures: dict[int, dict]) -> tuple[dict[str, dict], list[str]]:
    """逐场解析当夜彩果。返回 (results, skipped)。

    results = {match_no: {code, ft, home, away, status}}；
    skipped 逐条给出机器可读理由——缺失不静默变确定性。
    """
    results: dict[str, dict] = {}
    skipped: list[str] = []
    for m in matches:
        no = str(m["match_no"])
        fid = af_map.get(no)
        if fid is None:
            skipped.append(f"场{no}: af-map 无映射")
            continue
        fx = fixtures.get(fid)
        if fx is None:
            skipped.append(f"场{no}: fixture {fid} 该日未返回(未开赛或非本夜)")
            continue
        if fx["status"] not in _FINISHED:
            skipped.append(f"场{no}: 状态 {fx['status']} 未完赛")
            continue
        if fx["ft_home"] is None or fx["ft_away"] is None:
            skipped.append(f"场{no}: fulltime 缺失")
            continue
        results[no] = {
            "code": result_code(fx["ft_home"], fx["ft_away"]),
            "ft": f"{fx['ft_home']}-{fx['ft_away']}",
            "home": fx["home"], "away": fx["away"], "status": fx["status"],
        }
    return results, skipped
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/decision/test_zucai_night.py -v -k night_results`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/zucai_night.py tests/decision/test_zucai_night.py
git commit -m "feat(decision): 夜间彩果解析+三重显式跳过"
```

### Task 5: 票面期中存活计算

**Files:**
- Modify: `nutmeg/decision/zucai_night.py`
- Test: `tests/decision/test_zucai_night.py`

- [ ] **Step 1: 写失败测试**

```python
from nutmeg.decision.zucai_night import ticket_partial_status


def test_ticket_partial_status_alive_and_dead():
    faces = {"3": "31", "4": "31", "5": "310", "7": "3"}
    codes = {"3": "3", "4": "0", "5": "1"}      # 场7 未赛
    st = ticket_partial_status(faces, codes)
    assert st["dead"] == ["4"]                   # 双31 漏客胜
    assert st["hit"] == ["3", "5"]
    assert st["undecided"] == ["7"]
    assert st["alive"] is False


def test_ticket_partial_status_all_alive():
    st = ticket_partial_status({"3": "31", "12": "31"}, {"3": "3", "12": "3"})
    assert st["alive"] is True and st["dead"] == [] and st["undecided"] == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/decision/test_zucai_night.py -v -k partial_status`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现**

```python
def ticket_partial_status(faces: dict, codes: dict[str, str]) -> dict:
    """期中口径的复式票状态。faces={场次: "31"...}, codes={场次: 彩果}。

    与 zucai_official.ticket_hits 的区别：hits 是终局全量口径，
    这里区分 已中/已死/未决 三态，供夜间报告与在场监控使用。
    """
    faces = {str(k): str(v) for k, v in faces.items()}
    hit = sorted((no for no, f in faces.items()
                  if no in codes and codes[no] in set(f)), key=int)
    dead = sorted((no for no, f in faces.items()
                   if no in codes and codes[no] not in set(f)), key=int)
    undecided = sorted((no for no in faces if no not in codes), key=int)
    return {"alive": not dead, "hit": hit, "dead": dead, "undecided": undecided}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/decision/test_zucai_night.py -v -k partial_status`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/zucai_night.py tests/decision/test_zucai_night.py
git commit -m "feat(decision): 票面期中存活三态计算"
```

### Task 6: 报告渲染

**Files:**
- Modify: `nutmeg/decision/zucai_night.py`
- Test: `tests/decision/test_zucai_night.py`

- [ ] **Step 1: 写失败测试**

```python
from nutmeg.decision.zucai_night import render_report


def test_render_report_lines():
    results = {"3": {"code": "3", "ft": "4-0", "home": "AEK Athens FC",
                     "away": "Levski Sofia", "status": "FT"},
               "5": {"code": "1", "ft": "1-1", "home": "Celje",
                     "away": "Slovan Bratislava", "status": "AET"}}
    tickets = [{"id": "R9", "faces": {"3": "31", "5": "310", "7": "3"}}]
    text = render_report("26111", "2026-08-26", results, ["场8: af-map 无映射"], tickets)
    assert "场3 AEK Athens FC vs Levski Sofia: 4-0(90') → 3" in text
    assert "AET" in text                        # 加时场标注口径来源
    assert "R9: 存活 | 已中 3,5 | 未决 7" in text
    assert "场8: af-map 无映射" in text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/decision/test_zucai_night.py -v -k render`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现**

```python
def render_report(issue: str, date: str, results: dict[str, dict],
                  skipped: list[str], tickets: list[dict]) -> str:
    lines = [f"== {issue} 夜间校准 {date} (API-Football, 90' 口径) =="]
    for no in sorted(results, key=int):
        r = results[no]
        tag = f" [{r['status']}→取90']" if r["status"] != "FT" else ""
        lines.append(f"场{no} {r['home']} vs {r['away']}: {r['ft']}(90') → {r['code']}{tag}")
    codes = {no: r["code"] for no, r in results.items()}
    for t in tickets:
        st = ticket_partial_status(t["faces"], codes)
        state = "存活" if st["alive"] else f"已死(断腿 {','.join(st['dead'])})"
        lines.append(f"{t['id']}: {state} | 已中 {','.join(st['hit']) or '-'}"
                     f" | 未决 {','.join(st['undecided']) or '-'}")
    lines.extend(skipped)
    return "\n".join(lines)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/decision/test_zucai_night.py -v -k render`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/zucai_night.py tests/decision/test_zucai_night.py
git commit -m "feat(decision): 夜间校准报告渲染"
```

### Task 7: CLI 命令 + 快照落盘（集成）

**Files:**
- Modify: `nutmeg/decision/zucai_night.py`（新增 `run_night_calibrate`）
- Modify: `nutmeg/interfaces/cli/decision.py`（新增命令，仿既有 `@_cli.app.command` 模式）
- Test: `tests/decision/test_zucai_night.py`

- [ ] **Step 1: 写失败测试（集成，全部注入不出网）**

```python
from nutmeg.decision.zucai_night import run_night_calibrate


def test_run_night_calibrate_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("NUTMEG_API_FOOTBALL_BASE_URL", "https://af.example")
    monkeypatch.setenv("NUTMEG_API_FOOTBALL_KEY", "k")
    (tmp_path / "26111-issue.json").write_text(json.dumps({"issue_id": "26111", "matches": [
        {"match_no": 3, "home_team": "雅典", "away_team": "索斯基"},
        {"match_no": 5, "home_team": "采列", "away_team": "布拉迪"}]}), "utf-8")
    (tmp_path / "26111-af-map.json").write_text(json.dumps(
        {"issue": "26111", "fixtures": {"3": 1234501, "5": 1234503}}), "utf-8")
    (tmp_path / "26111-final-tickets.json").write_text(json.dumps({"issue": "26111", "tickets": [
        {"id": "R9", "kind": "任九", "faces": {"3": "31", "5": "310"}}]}), "utf-8")

    report = run_night_calibrate("26111", "2026-08-26", tmp_path,
                                 fetcher=lambda url, headers: _af_payload())
    assert "R9: 存活" in report
    snap = json.loads((tmp_path / "26111-night-2026-08-26-af.json").read_text("utf-8"))
    assert snap["results"]["3"]["code"] == "3"
    assert snap["source"].startswith("API-Football")


def test_run_night_calibrate_no_tickets_file(tmp_path, monkeypatch):
    monkeypatch.setenv("NUTMEG_API_FOOTBALL_BASE_URL", "https://af.example")
    monkeypatch.setenv("NUTMEG_API_FOOTBALL_KEY", "k")
    (tmp_path / "26111-issue.json").write_text(json.dumps({"issue_id": "26111", "matches": [
        {"match_no": 3, "home_team": "雅典", "away_team": "索斯基"}]}), "utf-8")
    (tmp_path / "26111-af-map.json").write_text(json.dumps(
        {"issue": "26111", "fixtures": {"3": 1234501}}), "utf-8")
    report = run_night_calibrate("26111", "2026-08-26", tmp_path,
                                 fetcher=lambda url, headers: _af_payload())
    assert "场3" in report            # 无票文件仍出彩果，不报错
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/decision/test_zucai_night.py -v -k end_to_end`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现 orchestrator**

在 `nutmeg/decision/zucai_night.py` 追加：

```python
def run_night_calibrate(issue: str, date: str, zucai_dir, *, fetcher=None) -> str:
    """一次夜间校准：抓取→解析→存活→快照→报告。只读 zucai 文件+写快照，不碰 rx/scoreboard。"""
    from datetime import datetime, timezone

    zucai_dir = Path(zucai_dir)
    issue_doc = json.loads((zucai_dir / f"{issue}-issue.json").read_text("utf-8"))
    af_map = load_af_map(zucai_dir, issue)
    fixtures = fetch_af_day(date, fetcher=fetcher)
    results, skipped = night_results(issue_doc["matches"], af_map, fixtures)

    tickets_path = zucai_dir / f"{issue}-final-tickets.json"
    tickets = (json.loads(tickets_path.read_text("utf-8"))["tickets"]
               if tickets_path.exists() else [])

    snap_path = zucai_dir / f"{issue}-night-{date}-af.json"
    snap_path.write_text(json.dumps({
        "issue": issue,
        "source": f"API-Football fixtures?date={date} (score.fulltime 90' 口径)",
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "results": results,
        "skipped": skipped,
    }, ensure_ascii=False, indent=1), "utf-8")

    return render_report(issue, date, results, skipped, tickets)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/decision/test_zucai_night.py -v -k end_to_end`
Expected: 2 passed

- [ ] **Step 5: 注册 CLI 命令**

在 `nutmeg/interfaces/cli/decision.py` 追加（import 区加 `from nutmeg.decision.zucai_night import run_night_calibrate`）：

```python
@_cli.app.command("zucai-night-calibrate")
def zucai_night_calibrate(
    issue: str = _cli.typer.Option(..., "--issue", help="期号 如 26111"),
    date: str = _cli.typer.Option(..., "--date",
                                  help="欧洲比赛日 YYYY-MM-DD(API-Football date 口径,北京凌晨场取前一天)"),
    zucai_dir: Path = _ZUCAI_DIR_OPTION,
):
    """夜间结果校准:抓当日完赛→90'彩果→票面存活报告(不写 rx/scoreboard)。"""
    _cli.typer.echo(run_night_calibrate(issue, date, zucai_dir))
```

- [ ] **Step 6: 全量测试**

Run: `uv run pytest tests/decision/test_zucai_night.py -v && uv run nutmeg zucai-night-calibrate --help`
Expected: 全部 passed；help 正常输出

- [ ] **Step 7: Commit**

```bash
git add nutmeg/decision/zucai_night.py nutmeg/interfaces/cli/decision.py tests/decision/test_zucai_night.py
git commit -m "feat(decision): zucai-night-calibrate 夜间校准 CLI"
```

### Task 8: RUNBOOK 挂接 + 26111 回填试运行

**Files:**
- Modify: `docs/sop/RUNBOOK.md`（B9 与 B10 之间）
- Create: `.nutmeg-data/zucai/26111-af-map.json`、`.nutmeg-data/zucai/26111-final-tickets.json`

- [ ] **Step 1: RUNBOOK 加 B9b 行**

在 B9 行之后插入：

```markdown
| B9b | 晨间夜账校准（多夜期次每夜一次） | `uv run nutmeg zucai-night-calibrate --issue <issue> --date <欧洲比赛日>`；报告供主循环写 rx night 块；af-map 与 final-tickets 两文件在 B2/B9 时由主循环落 |
```

同时在 B9 行动作列追加一句：`；同时落 <issue>-final-tickets.json 结构化票面（faces 不再只住散文）`。

- [ ] **Step 2: 回填 26111 两输入文件并试运行**

回填规则：SFC192 faces 直接抄 rx `ticket_versions.SFC192已落` 的 code 串；R9 的单（7/14）与全包（5/8/13=310）确定，**双选第二面（场3/9/10/12）从 500 方案号 20260825…1948 虚拟单页核回，录入前请用户过目**（场3=31、场12=31 已由 rx 夜二块证实，9/10 待核）。af-map 的 fixture id 用 `fixtures?date=` 返回的 `fixture.id` 按队名人工对号入座。完成后：

Run: `uv run nutmeg zucai-night-calibrate --issue 26111 --date 2026-08-26`
Expected: 场3/4/5/6/12 彩果与 rx night2 块一致（3/0/1/3/3），SFC192 报"已死(断腿 3,4)"，R9 报"存活"

- [ ] **Step 3: Commit**

```bash
git add docs/sop/RUNBOOK.md .nutmeg-data/zucai/26111-af-map.json .nutmeg-data/zucai/26111-final-tickets.json
git commit -m "docs(sop): RUNBOOK B9b 夜间校准挂接 + 26111 输入回填"
```

---

## §6 显式排除（本包不做）

- 不自动改 rx / scoreboard（判断与复盘留在主循环）；
- 不做队名→fixture 的自动模糊匹配（af-map 显式映射，缺失即跳过）；
- 不做 launchd 定时（decision 链 launchd 仍是发布门议题，先手动/`/loop` 调用）；
- 不做 okooo 抓取（WAF 405；okooo 降为人工核对源，官方 gameNo=90 终核走既有 `zucai_official.py`）；
- 不做 Telegram 推送（Package 2 范围）。
