# 「今日判定」评判员层 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 世界杯日报加观点层——agent 评判员每日逐场判定+比分+理由+爆冷预警+冠军 pick+¥15 评判员票,次日自动对账记分牌问责,与投注纪律完全分离。

**Architecture:** 两个新模块(`predictions.py` 落盘约定、`judge_ledger.py` 对账记分)+ 三个既有渲染模块的接入(`report_data`/`report_pdf`/`charts`)+ CLI 在 jczq-report 两条路径挂幂等对账 + SOP 双写。引擎/票面/裁量零改动。

**Tech Stack:** 纯 Python(无新依赖);复用 worldcup 子包既有模式(frozen slots dataclass、容错 load、JSONL、matplotlib Agg、NutmegCJK)。

**Spec:** `docs/superpowers/specs/2026-06-11-wc-judge-opinion-layer-design.md`

**约定:** 测试 `uv run pytest tests/<file> -v`;全量回归 `uv run pytest`(当前基线 1159 passed);commit 末尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`;PDF 自产文案禁用 emoji/Unicode 减号/•(NutmegCJK 缺字形,主工程教训)。

---

## File Structure

```
Create:
  nutmeg/services/worldcup/predictions.py    # JudgePick/OpinionTicket/Predictions + validate + 容错 load
  nutmeg/services/worldcup/judge_ledger.py   # 对账(四种命中+票盈亏)+ ledger 读写 + 累计摘要
  tests/test_wc_predictions.py
  tests/test_wc_judge_ledger.py
Modify:
  nutmeg/services/worldcup/report_data.py    # DailyReport += predictions/ledger_summary/ledger_yesterday
  nutmeg/services/worldcup/report_pdf.py     # 今日判定第 2 节 + 冠军 pick 框 + 战报记分牌 + 缺席降级
  nutmeg/services/worldcup/charts.py         # judge_trend_png 记分牌折线
  nutmeg/interfaces/cli/jczq.py              # jczq-report 两路径前挂 reconcile_recent
  CLAUDE.md / AGENTS.md                      # SOP 第 6 条插 b 步(原 b 顺延 c)
  tests/test_wc_report_data.py / test_wc_report_pdf.py / test_wc_charts.py / test_cli_jczq_report.py
运行时落盘:
  .nutmeg-data/jczq/daily/<date>/predictions.json
  .nutmeg-data/jczq/wc2026/judge-ledger.jsonl
```

---

### Task 1: predictions.py 落盘约定

**Files:**
- Create: `nutmeg/services/worldcup/predictions.py`
- Test: `tests/test_wc_predictions.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_wc_predictions.py
"""predictions.json 落盘约定(judge spec §1)。"""
from __future__ import annotations

import json
from pathlib import Path

from nutmeg.services.worldcup.predictions import (
    Predictions,
    load_predictions,
    validate_predictions_payload,
)

VALID = {
    "date": "2026-06-12",
    "judge": "claude",
    "picks": [
        {"fixture": "墨西哥 vs 南非", "match_id": "M01", "match_no": "周四001",
         "judgment": "home", "score": "2-1", "reason": "主场+对手中场弱",
         "confidence": 4, "upset_flag": False, "baseline_pick": "home"},
    ],
    "champion_pick": {"team": "Argentina", "reason": "板凳深度+淘汰赛基因"},
    "opinion_ticket": {"match_no": "周四001", "market": "had", "pick": "home",
                       "odds": 1.85, "stake_yuan": 15},
    "written_at": "2026-06-12T14:30:00+08:00",
}


def _write(tmp_path: Path, payload: dict) -> Path:
    daily = tmp_path / "2026-06-12"
    daily.mkdir(exist_ok=True)
    (daily / "predictions.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return daily


def test_roundtrip(tmp_path: Path) -> None:
    got = load_predictions(_write(tmp_path, VALID))
    assert isinstance(got, Predictions)
    assert got.picks[0].judgment == "home"
    assert got.picks[0].confidence == 4
    assert got.opinion_ticket.stake_yuan == 15
    assert got.champion_pick["team"] == "Argentina"


def test_missing_file_returns_none(tmp_path: Path) -> None:
    assert load_predictions(tmp_path) is None


def test_null_ticket_is_legal(tmp_path: Path) -> None:
    payload = json.loads(json.dumps(VALID))
    payload["opinion_ticket"] = None
    got = load_predictions(_write(tmp_path, payload))
    assert got is not None and got.opinion_ticket is None


def test_validate_catches_bad_judgment_confidence_score() -> None:
    bad = json.loads(json.dumps(VALID))
    bad["picks"][0]["judgment"] = "win"
    bad["picks"][0]["confidence"] = 0
    bad["picks"][0]["score"] = "2:1"
    errors = validate_predictions_payload(bad)
    assert any("judgment" in e for e in errors)
    assert any("confidence" in e for e in errors)
    assert any("score" in e for e in errors)


def test_corrupt_returns_none(tmp_path: Path) -> None:
    daily = tmp_path / "x"
    daily.mkdir()
    (daily / "predictions.json").write_text("{broken", encoding="utf-8")
    assert load_predictions(daily) is None
```

- [ ] **Step 2: 确认 FAIL**

Run: `uv run pytest tests/test_wc_predictions.py -v`
Expected: FAIL(ModuleNotFoundError)

- [ ] **Step 3: 实现**

```python
# nutmeg/services/worldcup/predictions.py
"""评判员判定落盘约定(judge spec §1)— agent 写,jczq-report/judge_ledger 读。

容错原则与 jczq_judgment_answers 一致:缺失/损坏 → None + 日志,报告标缺席。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

FILENAME = "predictions.json"
JUDGMENTS = ("home", "draw", "away")
_SCORE_RE = re.compile(r"^\d{1,2}-\d{1,2}$")
REQUIRED_TOP = ("date", "judge", "picks", "champion_pick", "opinion_ticket",
                "written_at")
REQUIRED_PICK = ("fixture", "judgment", "score", "reason", "confidence")
DEFAULT_STAKE_YUAN = 15


@dataclass(frozen=True, slots=True)
class JudgePick:
    fixture: str
    judgment: str
    score: str
    reason: str
    confidence: int
    upset_flag: bool = False
    baseline_pick: str = ""
    match_id: str = ""
    match_no: str = ""


@dataclass(frozen=True, slots=True)
class OpinionTicket:
    match_no: str
    market: str
    pick: str
    odds: float | None = None
    stake_yuan: int = DEFAULT_STAKE_YUAN


@dataclass(frozen=True, slots=True)
class Predictions:
    date: str
    judge: str
    picks: list[JudgePick]
    champion_pick: dict
    opinion_ticket: OpinionTicket | None
    written_at: str = ""


def validate_predictions_payload(payload: dict) -> list[str]:
    errors = [f"缺字段 {k}" for k in REQUIRED_TOP if k not in payload]
    for i, p in enumerate(payload.get("picks", [])):
        errors += [f"picks[{i}] 缺字段 {k}" for k in REQUIRED_PICK if k not in p]
        if p.get("judgment") not in JUDGMENTS:
            errors.append(f"picks[{i}] judgment 必须 home/draw/away,得到 {p.get('judgment')!r}")
        conf = p.get("confidence")
        if not (isinstance(conf, int) and 1 <= conf <= 5):
            errors.append(f"picks[{i}] confidence 必须 1-5,得到 {conf!r}")
        if not _SCORE_RE.match(str(p.get("score", ""))):
            errors.append(f"picks[{i}] score 必须 'h-a' 形式,得到 {p.get('score')!r}")
    cp = payload.get("champion_pick")
    if not (isinstance(cp, dict) and cp.get("team")):
        errors.append("champion_pick 必须含 team")
    return errors


def load_predictions(daily_dir: Path) -> Predictions | None:
    path = daily_dir / FILENAME
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        problems = validate_predictions_payload(payload)
        if problems:
            logger.warning("predictions 校验失败: %s", problems)
            return None
        ticket_raw = payload["opinion_ticket"]
        return Predictions(
            date=payload["date"], judge=payload["judge"],
            picks=[
                JudgePick(
                    fixture=p["fixture"], judgment=p["judgment"],
                    score=p["score"], reason=p["reason"],
                    confidence=p["confidence"],
                    upset_flag=bool(p.get("upset_flag", False)),
                    baseline_pick=p.get("baseline_pick", ""),
                    match_id=p.get("match_id", ""),
                    match_no=p.get("match_no", ""),
                )
                for p in payload["picks"]
            ],
            champion_pick=dict(payload["champion_pick"]),
            opinion_ticket=(
                None if ticket_raw is None
                else OpinionTicket(
                    match_no=ticket_raw["match_no"], market=ticket_raw["market"],
                    pick=ticket_raw["pick"], odds=ticket_raw.get("odds"),
                    stake_yuan=int(ticket_raw.get("stake_yuan", DEFAULT_STAKE_YUAN)),
                )
            ),
            written_at=payload.get("written_at", ""),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        logger.warning("predictions 读取失败", exc_info=True)
        return None
```

- [ ] **Step 4: 确认 PASS + 回归**

Run: `uv run pytest tests/test_wc_predictions.py -v && uv run pytest -q`
Expected: 5 PASS;全量零破坏。

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/worldcup/predictions.py tests/test_wc_predictions.py
git commit -m "feat(wc): predictions.json 评判员判定落盘约定——schema 校验+容错加载"
```

---

### Task 2: judge_ledger.py 对账记分

**Files:**
- Create: `nutmeg/services/worldcup/judge_ledger.py`
- Test: `tests/test_wc_judge_ledger.py`

记分口径(spec §2.2):judgment_hit / score_hit(AET/PEN 比分不可知记 None)/
baseline_hit / upset_hit(预警+命中+偏离基线);票盈亏 odds×stake;赛果未出 →
pending;幂等 = 重跑同一天整日替换(load → 剔除该日 → 重算 → 重写)。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_wc_judge_ledger.py
"""评判员记分(judge spec §2)。"""
from __future__ import annotations

from pathlib import Path

from nutmeg.services.worldcup.judge_ledger import (
    append_day,
    ledger_summary,
    load_ledger,
    reconcile_day,
)
from nutmeg.services.worldcup.predictions import (
    JudgePick,
    OpinionTicket,
    Predictions,
)
from nutmeg.services.worldcup.results import WcResult


def _pred(picks, ticket=None) -> Predictions:
    return Predictions(date="2026-06-12", judge="claude", picks=picks,
                       champion_pick={"team": "Argentina", "reason": "x"},
                       opinion_ticket=ticket)


def _pick(match_id, judgment, score="1-0", conf=4, upset=False,
          baseline="home", match_no="") -> JudgePick:
    return JudgePick(fixture=f"f-{match_id}", judgment=judgment, score=score,
                     reason="r", confidence=conf, upset_flag=upset,
                     baseline_pick=baseline, match_id=match_id,
                     match_no=match_no)


RESULTS = [
    WcResult("M01", "A", "B", "FT", "home", 1, 0, None),
    WcResult("M02", "C", "D", "FT", "away", 0, 2, None),
    WcResult("M03", "E", "F", "AET", "draw", None, None, "E"),
]


def test_reconcile_hits_and_misses() -> None:
    pred = _pred([
        _pick("M01", "home", score="1-0"),               # 判定中+比分中
        _pick("M02", "home", score="1-0", baseline="away"),  # 全错,基线中
        _pick("M03", "draw", score="1-1", upset=True, baseline="home"),
    ])
    entries = reconcile_day(pred, RESULTS)
    by_id = {e["match_id"]: e for e in entries if e["kind"] == "pick"}
    assert by_id["M01"]["judgment_hit"] is True
    assert by_id["M01"]["score_hit"] is True
    assert by_id["M02"]["judgment_hit"] is False
    assert by_id["M02"]["baseline_hit"] is True
    # AET:90 分钟比分不可知 → score_hit None;判平命中且偏离基线 → 爆冷命中
    assert by_id["M03"]["judgment_hit"] is True
    assert by_id["M03"]["score_hit"] is None
    assert by_id["M03"]["upset_hit"] is True


def test_reconcile_pending_when_result_missing() -> None:
    pred = _pred([_pick("M99", "home")])
    entries = reconcile_day(pred, RESULTS)
    assert entries[0]["pending"] is True


def test_ticket_pnl_win_and_loss() -> None:
    win = _pred([_pick("M01", "home", match_no="周四001")],
                ticket=OpinionTicket("周四001", "had", "home", odds=1.85))
    lose = _pred([_pick("M02", "home", match_no="周四002")],
                 ticket=OpinionTicket("周四002", "had", "home", odds=2.1))
    win_t = [e for e in reconcile_day(win, RESULTS) if e["kind"] == "ticket"][0]
    lose_t = [e for e in reconcile_day(lose, RESULTS) if e["kind"] == "ticket"][0]
    assert abs(win_t["pnl_yuan"] - 15 * 0.85) < 1e-9
    assert lose_t["pnl_yuan"] == -15


def test_ticket_missing_odds_pnl_none() -> None:
    pred = _pred([_pick("M01", "home", match_no="周四001")],
                 ticket=OpinionTicket("周四001", "had", "home", odds=None))
    t = [e for e in reconcile_day(pred, RESULTS) if e["kind"] == "ticket"][0]
    assert t["pnl_yuan"] is None


def test_append_day_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "judge-ledger.jsonl"
    pred = _pred([_pick("M01", "home")])
    append_day(path, "2026-06-12", reconcile_day(pred, RESULTS))
    append_day(path, "2026-06-12", reconcile_day(pred, RESULTS))  # 重跑
    entries = load_ledger(path)
    assert len([e for e in entries if e["kind"] == "pick"]) == 1


def test_summary_rates_and_absent() -> None:
    entries = [
        {"date": "2026-06-12", "kind": "pick", "match_id": "M01",
         "judgment_hit": True, "score_hit": True, "baseline_hit": True,
         "upset_flag": False, "upset_hit": False, "pending": False},
        {"date": "2026-06-12", "kind": "pick", "match_id": "M02",
         "judgment_hit": False, "score_hit": False, "baseline_hit": True,
         "upset_flag": True, "upset_hit": False, "pending": False},
        {"date": "2026-06-12", "kind": "ticket", "pnl_yuan": -15.0,
         "pending": False},
        {"date": "2026-06-13", "kind": "absent"},
        {"date": "2026-06-14", "kind": "pick", "match_id": "M09",
         "pending": True},
    ]
    s = ledger_summary(entries)
    assert s.n_picks == 2 and s.judgment_rate == 0.5 and s.score_rate == 0.5
    assert s.baseline_rate == 1.0
    assert s.upset_precision == 0.0
    assert s.ticket_pnl == -15.0
    assert s.absent_days == 1 and s.pending == 1
```

- [ ] **Step 2: 确认 FAIL**

Run: `uv run pytest tests/test_wc_judge_ledger.py -v`
Expected: FAIL(ModuleNotFoundError)

- [ ] **Step 3: 实现**

```python
# nutmeg/services/worldcup/judge_ledger.py
"""评判员记分牌(judge spec §2)— 对账纯函数 + JSONL 读写 + 累计摘要。

幂等:append_day 整日替换(剔除同日旧条目后重写),重跑/补结安全。
评判员的牌子是打出来的:absent 也入账公示。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .predictions import Predictions
from .results import WcResult

logger = logging.getLogger(__name__)

LEDGER_FILENAME = "judge-ledger.jsonl"


@dataclass(frozen=True, slots=True)
class LedgerSummary:
    n_picks: int
    judgment_rate: float | None
    score_rate: float | None
    baseline_rate: float | None
    upset_precision: float | None   # upset_hit / upset_flag 总数
    ticket_pnl: float
    ticket_n: int
    absent_days: int
    pending: int


def reconcile_day(pred: Predictions, results: list[WcResult]) -> list[dict]:
    """一天的判定 → ledger 条目(dict,直接可 JSONL)。赛果缺 → pending。"""
    by_id = {r.match_id: r for r in results}
    entries: list[dict] = []
    outcome_by_match_no: dict[str, str | None] = {}
    for p in pred.picks:
        r = by_id.get(p.match_id) if p.match_id else None
        e: dict = {
            "date": pred.date, "kind": "pick", "judge": pred.judge,
            "match_id": p.match_id, "fixture": p.fixture,
            "judgment": p.judgment, "confidence": p.confidence,
            "upset_flag": p.upset_flag, "pending": r is None,
        }
        if r is not None:
            jh = p.judgment == r.outcome_90
            sh = (
                None if r.goals_h_90 is None
                else p.score == f"{r.goals_h_90}-{r.goals_a_90}"
            )
            e.update({
                "judgment_hit": jh,
                "score_hit": sh,
                "baseline_hit": (
                    p.baseline_pick == r.outcome_90 if p.baseline_pick else None
                ),
                "upset_hit": bool(
                    p.upset_flag and jh and p.judgment != p.baseline_pick
                ),
            })
            if p.match_no:
                outcome_by_match_no[p.match_no] = r.outcome_90
        elif p.match_no:
            outcome_by_match_no[p.match_no] = None
        entries.append(e)

    t = pred.opinion_ticket
    if t is not None:
        outcome = outcome_by_match_no.get(t.match_no)
        te: dict = {
            "date": pred.date, "kind": "ticket", "judge": pred.judge,
            "match_no": t.match_no, "pick": t.pick, "odds": t.odds,
            "stake_yuan": t.stake_yuan, "pending": outcome is None,
        }
        if outcome is not None:
            if t.odds is None:
                te["pnl_yuan"] = None   # 赔率未存,人工补结(spec §5)
            elif t.pick == outcome:
                te["pnl_yuan"] = round(t.stake_yuan * (t.odds - 1.0), 2)
            else:
                te["pnl_yuan"] = float(-t.stake_yuan)
        entries.append(te)
    return entries


def absent_entry(date: str) -> dict:
    return {"date": date, "kind": "absent"}


def load_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning("ledger 损坏行已跳过: %r", line[:80])
    return entries


def append_day(path: Path, date: str, entries: list[dict]) -> None:
    """整日替换写入 — 重跑幂等、pending 补结安全。"""
    kept = [e for e in load_ledger(path) if e.get("date") != date]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for e in kept + entries:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")


def ledger_summary(entries: list[dict]) -> LedgerSummary:
    picks = [e for e in entries if e.get("kind") == "pick" and not e.get("pending")]
    tickets = [e for e in entries if e.get("kind") == "ticket" and not e.get("pending")]

    def _rate(key: str) -> float | None:
        vals = [e[key] for e in picks if e.get(key) is not None]
        return (sum(1 for v in vals if v) / len(vals)) if vals else None

    flagged = [e for e in picks if e.get("upset_flag")]
    return LedgerSummary(
        n_picks=len(picks),
        judgment_rate=_rate("judgment_hit"),
        score_rate=_rate("score_hit"),
        baseline_rate=_rate("baseline_hit"),
        upset_precision=(
            sum(1 for e in flagged if e.get("upset_hit")) / len(flagged)
            if flagged else None
        ),
        ticket_pnl=sum(e["pnl_yuan"] for e in tickets if e.get("pnl_yuan") is not None),
        ticket_n=len(tickets),
        absent_days=sum(1 for e in entries if e.get("kind") == "absent"),
        pending=sum(1 for e in entries if e.get("pending")),
    )


def reconcile_recent(output_dir: Path, *, today: str, days_back: int = 3) -> int:
    """对账最近 N 天(不含今天)— pending 自动补结;评判员缺席日记 absent。

    返回写入的条目数。jczq-report 两条路径(日报/复盘)都调它,幂等。
    """
    from datetime import date, timedelta

    from .predictions import load_predictions
    from .results import load_results

    wc_dir = output_dir / "wc2026"
    ledger_path = wc_dir / LEDGER_FILENAME
    results = load_results(wc_dir / "results.json")
    written = 0
    try:
        anchor = date.fromisoformat(today)
    except ValueError:
        return 0
    for back in range(1, days_back + 1):
        d = (anchor - timedelta(days=back)).isoformat()
        pred = load_predictions(output_dir / "daily" / d)
        if pred is None:
            existing_dates = {e.get("date") for e in load_ledger(ledger_path)}
            if d not in existing_dates and (output_dir / "daily" / d).exists():
                append_day(ledger_path, d, [absent_entry(d)])
                written += 1
            continue
        entries = reconcile_day(pred, results)
        append_day(ledger_path, d, entries)
        written += len(entries)
    return written
```

- [ ] **Step 4: 确认 PASS + 回归**

Run: `uv run pytest tests/test_wc_judge_ledger.py -v && uv run pytest -q`
Expected: 6 PASS;全量零破坏。

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/worldcup/judge_ledger.py tests/test_wc_judge_ledger.py
git commit -m "feat(wc): 评判员记分牌——四种命中对账/票盈亏/整日替换幂等/缺席公示"
```

---

### Task 3: 渲染接入(report_data + report_pdf + charts)

**Files:**
- Modify: `nutmeg/services/worldcup/report_data.py`(DailyReport 字段 + build 读盘)
- Modify: `nutmeg/services/worldcup/report_pdf.py`(今日判定节/冠军框/记分牌/缺席降级)
- Modify: `nutmeg/services/worldcup/charts.py`(judge_trend_png)
- Test: `tests/test_wc_report_data.py` / `tests/test_wc_report_pdf.py` / `tests/test_wc_charts.py`(均追加)

- [ ] **Step 1: 追加失败测试**

```python
# tests/test_wc_report_data.py 追加
def test_build_daily_report_loads_predictions_and_ledger(tmp_path) -> None:
    import json

    from nutmeg.services.worldcup.report_data import build_daily_report

    daily = tmp_path / "daily" / "2026-06-12"
    daily.mkdir(parents=True)
    (daily / "predictions.json").write_text(json.dumps({
        "date": "2026-06-12", "judge": "claude",
        "picks": [{"fixture": "A vs B", "judgment": "home", "score": "2-1",
                   "reason": "r", "confidence": 4}],
        "champion_pick": {"team": "Argentina", "reason": "x"},
        "opinion_ticket": None, "written_at": "t",
    }, ensure_ascii=False), encoding="utf-8")
    wc = tmp_path / "wc2026"
    wc.mkdir()
    (wc / "judge-ledger.jsonl").write_text(json.dumps({
        "date": "2026-06-11", "kind": "pick", "match_id": "M01",
        "judgment_hit": True, "score_hit": False, "baseline_hit": True,
        "upset_flag": False, "upset_hit": False, "pending": False,
    }) + "\n", encoding="utf-8")
    report = build_daily_report("2026-06-12", tmp_path)
    assert report.predictions is not None
    assert report.predictions.picks[0].judgment == "home"
    assert report.ledger_summary is not None
    assert report.ledger_summary.n_picks == 1
    assert len(report.ledger_yesterday) == 1
```

```python
# tests/test_wc_report_pdf.py 追加
def test_daily_pdf_renders_judge_section(tmp_path) -> None:
    from pathlib import Path

    from nutmeg.services.worldcup.predictions import JudgePick, Predictions
    from nutmeg.services.worldcup.report_pdf import render_daily_pdf

    r = _report(with_sim=True)
    r.predictions = Predictions(
        date="2026-06-12", judge="claude",
        picks=[JudgePick(fixture="墨西哥 vs 南非", judgment="home",
                         score="2-1", reason="主场+边路爆点", confidence=4,
                         upset_flag=True, baseline_pick="home")],
        champion_pick={"team": "Argentina", "reason": "板凳深度"},
        opinion_ticket=None)
    out = tmp_path / "with-judge.pdf"
    render_daily_pdf(r, out)
    assert out.exists() and out.read_bytes()[:5] == b"%PDF-"


def test_daily_pdf_absent_judge_still_renders(tmp_path) -> None:
    from nutmeg.services.worldcup.report_pdf import render_daily_pdf

    r = _report(with_sim=True)   # _report 不设 predictions → None
    out = tmp_path / "absent.pdf"
    render_daily_pdf(r, out)
    assert out.exists() and out.read_bytes()[:5] == b"%PDF-"
```

注:`_report` 工厂构造 `DailyReport` 的方式以 Task 3 改完的字段为准——新字段
(`predictions`/`ledger_summary`/`ledger_yesterday`)必须带默认值,旧工厂零改动
即可继续用;若现 `_report` 是位置参数构造,改成关键字构造。

```python
# tests/test_wc_charts.py 追加
def test_judge_trend_png() -> None:
    from nutmeg.services.worldcup.charts import judge_trend_png

    png = judge_trend_png(
        dates=["06-12", "06-13", "06-14"],
        judge_rates=[0.5, 0.6, 0.55],
        baseline_rates=[0.5, 0.5, 0.52],
    )
    assert png[:4] == b"\x89PNG"
```

- [ ] **Step 2: 确认 FAIL**

Run: `uv run pytest tests/test_wc_report_data.py tests/test_wc_report_pdf.py tests/test_wc_charts.py -v`
Expected: 新增测试 FAIL(字段/函数不存在)。

- [ ] **Step 3: report_data.py 改动**

`DailyReport`(:78)追加四个带默认值字段(放 `calibration_note` 之后;
`ledger_entries` 供记分牌折线逐日序列用,`ledger_yesterday` 供战报当日行用):

```python
    predictions: "Predictions | None" = None
    ledger_summary: "LedgerSummary | None" = None
    ledger_yesterday: list[dict] = field(default_factory=list)
    ledger_entries: list[dict] = field(default_factory=list)
```

文件顶部加 import:

```python
from .judge_ledger import LEDGER_FILENAME, LedgerSummary, ledger_summary, load_ledger
from .predictions import Predictions, load_predictions
```

`build_daily_report` 在 `return DailyReport(...)` 前加:

```python
    predictions = load_predictions(daily)
    ledger_entries = load_ledger(wc_dir / LEDGER_FILENAME)
    summary = ledger_summary(ledger_entries) if ledger_entries else None
    ledger_yesterday = [e for e in ledger_entries if e.get("date") == prev_day]
```

并把四个值传进构造(`predictions=predictions, ledger_summary=summary,
ledger_yesterday=ledger_yesterday, ledger_entries=ledger_entries`)。

- [ ] **Step 4: report_pdf.py 改动**

(a)`_build_daily_story` 里,把「今日主线」节(:118 附近)整体替换为「今日判定」
节——narrative 变导语,判定表为主体:

```python
    # 2 今日判定(judge spec §3)— 观点是头版;主线叙事降为导语
    story.append(Paragraph("今日判定", st["h2"]))
    story.append(Paragraph(_xml(report.narrative), st["narrative"]))
    if report.predictions is None:
        story.append(Paragraph(
            "今日评判员缺席(裁量与判定均未作答,本报告为自动兜底)。", st["body"]))
    else:
        for p in report.predictions.picks:
            stars = "★" * p.confidence + "☆" * (5 - p.confidence)
            label = {"home": "主胜", "draw": "平局", "away": "客胜"}[p.judgment]
            prefix = "[爆冷] " if p.upset_flag else ""
            story.append(Paragraph(
                _xml(f"{prefix}{p.fixture} — 本席判:{label} {p.score} {stars}"),
                st["judge"]))
            story.append(Paragraph(_xml("理由:" + p.reason), st["small"]))
        cp = report.predictions.champion_pick
        sim_top = ""
        if report.sim:
            leader, lp = max(report.sim.probs.items(),
                             key=lambda kv: kv[1]["champion"])
            sim_top = f"模拟首位:{leader} {lp['champion']:.1%};"
        story.append(Paragraph(
            _xml(f"冠军 pick:{cp.get('team')} — {cp.get('reason', '')}({sim_top}"
                 "观点与模型公开对峙)"), st["narrative"]))
        t = report.predictions.opinion_ticket
        if t is not None:
            odds_str = f"@{t.odds}" if t.odds else "(赔率未存)"
            story.append(Paragraph(
                _xml(f"评判员票:{t.match_no} {t.pick} {odds_str} 单关 "
                     f"{t.stake_yuan} 元 — 与引擎注金分开记账"), st["body"]))
```

`_styles()` 加一个判定行样式:

```python
        "judge": ParagraphStyle("WcJudge", parent=base["BodyText"],
                                fontName="NutmegCJK", fontSize=11, leading=16),
```

其中 `[爆冷]` 行如需红色,用 `textColor` 变体:实现时给 prefix 行单独
`ParagraphStyle("WcJudgeUpset", parent=judge样式, textColor=colors.HexColor("#b3261e"))`。

(b)「昨日战报」节(:174 附近)追加记分牌(在 review 行之后):

```python
    yd_picks = [e for e in report.ledger_yesterday
                if e.get("kind") == "pick" and not e.get("pending")]
    if yd_picks:
        hits = sum(1 for e in yd_picks if e.get("judgment_hit"))
        scores = sum(1 for e in yd_picks if e.get("score_hit"))
        story.append(Paragraph(
            _xml(f"昨日判定 {hits}/{len(yd_picks)} 中,比分 {scores} 中"),
            st["body"]))
    if report.ledger_summary is not None:
        s = report.ledger_summary

        def pct(v):
            return f"{v:.0%}" if v is not None else "—"

        story.append(Paragraph(
            _xml(f"记分牌(累计 {s.n_picks} 判):判定 {pct(s.judgment_rate)} vs "
                 f"基线 {pct(s.baseline_rate)} | 比分 {pct(s.score_rate)} | "
                 f"爆冷查准 {pct(s.upset_precision)} | 评判员票 "
                 f"{s.ticket_pnl:+.0f} 元/{s.ticket_n} 张 | 缺席 {s.absent_days} 天"),
            st["body"]))
        try:
            from .charts import judge_trend_png

            trend = _judge_trend_inputs(report)
            if trend is not None:
                story.append(_img(judge_trend_png(*trend), width_mm=120))
        except Exception:  # noqa: BLE001 — 图表失败降级文本(主 spec §7)
            logger.warning("PDF: 记分牌折线失败,跳过", exc_info=True)
```

模块级加输入组装(累计逐日命中率,从 ledger_yesterday 之外还需全量 entries——
为避免 DailyReport 再加字段,直接读 summary 不够,需要逐日序列;给
`report_data.py` 的 `DailyReport` 再加 `ledger_entries: list[dict] =
field(default_factory=list)`,`build_daily_report` 把 `ledger_entries` 整个传入,
`ledger_yesterday` 由它派生也可,两个字段都保留以免改既有测试):

```python
def _judge_trend_inputs(report) -> tuple[list[str], list[float], list[float]] | None:
    by_date: dict[str, list[dict]] = {}
    for e in report.ledger_entries:
        if e.get("kind") == "pick" and not e.get("pending"):
            by_date.setdefault(e["date"], []).append(e)
    if len(by_date) < 2:
        return None
    dates, judge_rates, baseline_rates = [], [], []
    jh = jt = bh = bt = 0
    for d in sorted(by_date):
        for e in by_date[d]:
            if e.get("judgment_hit") is not None:
                jt += 1
                jh += 1 if e["judgment_hit"] else 0
            if e.get("baseline_hit") is not None:
                bt += 1
                bh += 1 if e["baseline_hit"] else 0
        if jt and bt:
            dates.append(d[5:])
            judge_rates.append(jh / jt)
            baseline_rates.append(bh / bt)
    return (dates, judge_rates, baseline_rates) if len(dates) >= 2 else None
```

(c)`render_review_pdf` 在「夺冠概率变动」之前插入同样的"昨日判定 X/Y +
记分牌一行"(复用上面两段 Paragraph 逻辑;不画折线,迷你战报保持 1-2 页)。

- [ ] **Step 5: charts.py 加 judge_trend_png**

```python
def judge_trend_png(
    *, dates: list[str], judge_rates: list[float], baseline_rates: list[float]
) -> bytes:
    """记分牌累计命中率折线 — 评判员 vs 闭眼跟热门基线。"""
    prop = _cjk_prop()
    fig, ax = plt.subplots(figsize=(5.5, 2.6))
    ax.plot(dates, [v * 100 for v in judge_rates], marker="o", markersize=3,
            linewidth=1.8, color=ACCENT, label="评判员")
    ax.plot(dates, [v * 100 for v in baseline_rates], marker="s", markersize=3,
            linewidth=1.2, color="#999999", linestyle="--", label="跟市场热门")
    ax.set_ylabel("累计判定命中率 %", fontproperties=prop, fontsize=8)
    ax.legend(prop=prop, fontsize=8)
    ax.tick_params(labelsize=7)
    ax.spines[["top", "right"]].set_visible(False)
    return _to_png(fig)
```

注意测试用关键字实参调用(`dates=...`),签名 keyword-only。

- [ ] **Step 6: 确认 PASS + 回归**

Run: `uv run pytest tests/test_wc_report_data.py tests/test_wc_report_pdf.py tests/test_wc_charts.py -v && uv run pytest -q`
Expected: 全 PASS(既有渲染测试因新字段带默认值零破坏)。

- [ ] **Step 7: Commit**

```bash
git add nutmeg/services/worldcup/report_data.py nutmeg/services/worldcup/report_pdf.py \
  nutmeg/services/worldcup/charts.py tests/test_wc_report_data.py \
  tests/test_wc_report_pdf.py tests/test_wc_charts.py
git commit -m "feat(wc): 日报「今日判定」头版+冠军pick对峙+记分牌折线+缺席降级"
```

---

### Task 4: CLI 挂对账 + SOP 双写 + 端到端演练

**Files:**
- Modify: `nutmeg/interfaces/cli/jczq.py`(jczq_report 函数体)
- Modify: `CLAUDE.md` / `AGENTS.md`
- Test: `tests/test_cli_jczq_report.py`(追加)

- [ ] **Step 1: 追加失败测试**

```python
# tests/test_cli_jczq_report.py 追加
def test_jczq_report_reconciles_recent_predictions(tmp_path: Path) -> None:
    """跑 jczq-report 前自动对账最近判定 → ledger 落盘。"""
    import json

    _seed_minimal_day(tmp_path)
    prev = tmp_path / "daily" / "2026-06-11"
    prev.mkdir(parents=True)
    (prev / "predictions.json").write_text(json.dumps({
        "date": "2026-06-11", "judge": "claude",
        "picks": [{"fixture": "A vs B", "match_id": "M01", "judgment": "home",
                   "score": "2-1", "reason": "r", "confidence": 4}],
        "champion_pick": {"team": "Argentina", "reason": "x"},
        "opinion_ticket": None, "written_at": "t",
    }, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "wc2026" / "results.json").write_text(json.dumps([
        {"match_id": "M01", "home": "A", "away": "B", "status": "FT",
         "outcome_90": "home", "goals_h_90": 2, "goals_a_90": 1,
         "advanced": None}]), encoding="utf-8")
    result = runner.invoke(app, [
        "jczq-report", "--date", "2026-06-12", "--output-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    ledger = (tmp_path / "wc2026" / "judge-ledger.jsonl").read_text(
        encoding="utf-8")
    assert '"judgment_hit": true' in ledger
```

- [ ] **Step 2: 确认 FAIL**

Run: `uv run pytest tests/test_cli_jczq_report.py -v`
Expected: 新测试 FAIL(ledger 文件不存在)。

- [ ] **Step 3: CLI 改动**

`jczq_report` 函数体里,`report = build_daily_report(target_date, output_dir)`
之前插入(两条路径——日报与 `--review-pdf`——都会经过):

```python
    # judge spec §2.1 — 渲染前对账最近 3 天判定(幂等,pending 自动补结)
    try:
        from nutmeg.services.worldcup.judge_ledger import reconcile_recent

        reconcile_recent(output_dir, today=target_date)
    except Exception:  # noqa: BLE001 — 记分失败不阻塞报告(spec §5)
        import logging

        logging.getLogger(__name__).warning("judge ledger 对账失败", exc_info=True)
```

- [ ] **Step 4: SOP 双写**

CLAUDE.md 与 AGENTS.md 第 6 条,原 `a.`(judgment-answers)之后插入新 `b.`,
原 `b.`(跑 jczq-report)改为 `c.`,两文件逐字一致:

```markdown
   b. 以评判员身份写 `.nutmeg-data/jczq/daily/$(date +%Y-%m-%d)/predictions.json`
      （schema 见 judge spec §1）：当日**每场**世界杯比赛给明确判定+比分+看球
      逻辑理由+信心 1-5；**要敢偏离市场，理由写球不写概率**；当日信心最高
      （≥4）的在售场次出评判员票（单关 ¥15，与引擎注金永不合账）；冠军 pick
      明确到一支队，换 pick 要写理由。
```

验证:`diff <(grep -A 14 '世界杯窗口' CLAUDE.md) <(grep -A 14 '世界杯窗口' AGENTS.md)`
→ 无输出。

- [ ] **Step 5: 全量回归 + 端到端演练**

Run: `uv run pytest`
Expected: 全 PASS(基线 1159 + 新增约 15)。

端到端(用今天真实数据):
1. 以评判员身份给今天(或明天)的世界杯场次写一份真实 predictions.json
   (照 SOP b 步;开幕日已过则写次日)。
2. `uv run nutmeg jczq-report --date <date>` → PDF「今日判定」节呈现判定/冠军
   pick 对峙/评判员票;qlmanage 转 PNG 目检中文与 `[爆冷]` 角标。
3. 删掉 predictions.json 再跑一次 → 该节显示"今日评判员缺席",报告照出。
4. 次日(或用假 results 数据)验证 `--review-pdf` 路径:ledger 落盘、迷你战报
   出记分牌行。

- [ ] **Step 6: Commit**

```bash
git add nutmeg/interfaces/cli/jczq.py tests/test_cli_jczq_report.py CLAUDE.md AGENTS.md
git commit -m "feat(wc): jczq-report 挂判定对账 + SOP 评判员步骤双写"
```

---

## Self-Review 记录

1. **Spec coverage**:§1 predictions(Task 1)/ §2 记分含幂等与 pending(Task 2,
   `append_day` 整日替换实现 spec 的"幂等去重",偏离"追加"字面但满足语义,已在
   docstring 注明)/ §3 渲染四点(Task 3:头版判定/冠军框/记分牌+折线/缺席降级;
   迷你战报记分牌在 Task 3 Step 4c)/ §4 SOP(Task 4)/ §5 错误处理(各容错
   路径+测试)/ §6 测试(共约 15 个新测试,低于 spec 预估 25-30——spec 预估含
   渲染快照类细分,实际合并为 PDF smoke + 真值表,覆盖面一致)/ §7 切分对应
   Task 1-4。
2. **Placeholder scan**:无 TBD/TODO;Task 3 `_report` 工厂适配说明给了明确
   规则(新字段带默认值,旧构造零改动)。
3. **类型一致性**:`Predictions/JudgePick/OpinionTicket`(Task 1)在 Task 2/3
   的用法签名一致;`LedgerSummary` 字段(n_picks/judgment_rate/.../pending)
   与 Task 3 渲染引用一致;`reconcile_recent(output_dir, today=...)` 与 Task 4
   CLI 调用一致;`judge_trend_png` keyword-only 与测试调用一致。
```
