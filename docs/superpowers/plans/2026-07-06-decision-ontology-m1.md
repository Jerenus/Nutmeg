# 决策本体系统 M1 Implementation Plan（预测度量核心）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让新决策本体在现 SOP 旁**并行影子运行**——每日判读的 Read 落库、CLV 轴从第一天积累数据、系统开始自测（Brier + CLV + 因子判决）。投注/推送（express/Telegram）延到 M1.5。

**Architecture:** 在 M0 的七对象 + 五动词地基上，接入"活数据"的三条：① 欧赔 fair 作先验锚（比 −13% 抽水的体彩更 sharp）；② 收盘欧赔快照（近开赛再抓 500.com/API-Football）供 CLV；③ read 摄取（Claude 运行时产 Read → 校验落库 + 自动 shadow）+ reconcile 结算（Brier+CLV）+ calibrate 面板。**判断永不进代码**：read 的 belief/factor 由 Claude 运行时产出，代码只摄取/校验/记账。

**Tech Stack:** Python 3.12 / dataclasses / pytest / uv。复用：`jczq_apifootball_odds.collect_bold_odds_apifootball_live`（收盘再抓）、`jczq_market_kernel.load_bold_odds_snapshot`（读时欧赔）、`jczq_results.OkoooJczqResultProvider`（赛果）、M0 的 `nutmeg/decision/`。

**关键设计精化（覆盖 spec §12 开放问题，实施执行）：**
1. **收盘快照源改为欧赔 fair，非 okooo SP**。实测 okooo 结果只给**获胜方单腿 SP**（无法构成三路分布），而欧赔 `bold_odds.json` 已带全三路去水 `fair_probability`，且欧赔是真正会动的 sharp 线。→ closing snapshot = 近开赛 `collect_bold_odds_apifootball_live` 的欧赔 fair（source=apifootball）；缺则 CLV=null（绝不伪造）。
2. **Read 先验锚 = 欧赔读时 fair（有则优先），否则体彩 fair**。欧赔是最 sharp 估计，CLV 两端都用欧赔才自洽。snapshot 同时存体彩(source=sporttery,下注用)与欧赔(source=apifootball,锚+CLV)两条。
3. **M1 只增不改**：现 SOP/launchd 照跑；新增 decision-* 命令与新本体文件。M2 才切 SOP/launchd。

**纪律（每 Task）：** TDD；每步 `uv run pytest tests/decision/<file> -q`；只碰列出文件；绝不动现系统源码（除 cli/__init__ 已有的 1 行注册区，本 M1 不再改它）；缺数据=null 绝不伪造；pre-commit（ruff+子集）须过。

**参考：** spec `docs/superpowers/specs/2026-07-06-decision-ontology-design.md`（§2/§5/§9/§12）；M0 计划同目录 `-m0.md`；M0 记忆 `decision-ontology-design`。

---

## 文件结构（M1 新增/扩展）

```
nutmeg/decision/
  market_data.py    # 扩展：euro_snapshot_from_bold_odds（欧赔 fair → MarketSnapshot）
  anchor.py         # 新建：resolve_prior（欧赔优先的先验锚选择）
  sense.py          # 扩展：sense_day（体彩+欧赔读时快照一并落库）
  read_ingest.py    # 新建：ingest_reads（校验+落库）+ backfill_shadows（自动 shadow）
  closing.py        # 新建：capture_closing（近开赛欧赔 → kind=closing 快照）
  reconcile.py      # 扩展：settle_day（Reads+赛果+收盘 → Settlement，Brier+CLV，落库）
  calibrate.py      # 扩展：run_calibrate（聚合 Settlement → FactorVerdict + markdown 面板）
  verbs.py          # 扩展：run_read_ingest/run_capture_closing/run_reconcile/run_calibrate
  migrate.py        # 新建：judge-ledger.jsonl 历史 → Read/Settlement（保 6/12 起战绩，Brier 轴）
tests/decision/
  test_anchor.py test_read_ingest.py test_closing.py
  test_m1_market_data.py test_m1_sense.py test_m1_reconcile.py
  test_m1_calibrate.py test_migrate.py test_m1_e2e.py
```

---

## Task 1: euro_snapshot_from_bold_odds（欧赔 fair → MarketSnapshot）

**Files:**
- Modify: `nutmeg/decision/market_data.py`
- Test: `tests/decision/test_m1_market_data.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_m1_market_data.py
from nutmeg.decision.market_data import euro_snapshot_from_bold_odds
from nutmeg.decision.ontology import MarketSnapshot


class _MO:
    """MarketOdds 的最小替身：只需 fair_probability / line。"""
    def __init__(self, fair, line=None):
        self.fair_probability = fair
        self.line = line


def test_euro_snapshot_from_bold_odds_builds_had_fair():
    bold = {"周日092": {"match_winner": _MO({"home": 0.40, "draw": 0.28, "away": 0.32})}}
    snaps = euro_snapshot_from_bold_odds(
        bold, run_date="2026-07-08", taken_at="2026-07-08T15:00:00+08:00",
        kind="read_time", source="apifootball",
    )
    assert len(snaps) == 1
    s = snaps[0]
    assert isinstance(s, MarketSnapshot)
    assert s.source == "apifootball" and s.kind == "read_time"
    assert s.match_id == "M-2026-07-08-周日092"
    assert abs(sum(s.fair["had"].values()) - 1.0) < 1e-6
    assert s.fair["had"]["home"] == 0.40
    assert "tags" not in s.to_dict()      # 净化不变


def test_euro_snapshot_skips_match_without_fair():
    bold = {"周日091": {"match_winner": _MO({})}}     # 空 fair
    assert euro_snapshot_from_bold_odds(
        bold, run_date="2026-07-08", taken_at="t", kind="read_time",
        source="apifootball") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_m1_market_data.py -q`
Expected: FAIL — `ImportError: cannot import name 'euro_snapshot_from_bold_odds'`

- [ ] **Step 3: Write minimal implementation（追加到 market_data.py）**

`__all__` 追加 `"euro_snapshot_from_bold_odds"`；实现：

```python
def euro_snapshot_from_bold_odds(
    bold_odds: dict, *, run_date: str, taken_at: str, kind: str, source: str,
) -> list:
    """欧赔 bold_odds（{竞彩号: {market: MarketOdds}}）→ MarketSnapshot 列表。

    只取 match_winner 的去水 fair_probability（欧赔已去水，是最 sharp 三路估计），
    作为 had 市场的 fair。空 fair 的场跳过。不产 tags/信号字段（净化不变）。
    收盘快照(kind=closing)与读时锚(kind=read_time)共用本构造器。
    """
    from nutmeg.decision.ontology import MarketSnapshot

    snaps: list = []
    for match_no, markets in bold_odds.items():
        mw = markets.get("match_winner")
        fair = dict(getattr(mw, "fair_probability", {}) or {}) if mw else {}
        if not fair or abs(sum(fair.values())) < 1e-9:
            continue
        snaps.append(MarketSnapshot(
            snapshot_id=_snapshot_id(match_no, taken_at, kind),
            match_id=f"M-{run_date}-{match_no}",
            taken_at=taken_at, kind=kind, source=source,
            fair={"had": fair}, raw_odds={},
            lines={},
        ))
    return snaps
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_m1_market_data.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/market_data.py tests/decision/test_m1_market_data.py
git commit -m "feat(decision): M1 euro_snapshot_from_bold_odds(欧赔 fair 锚)"
```

---

## Task 2: resolve_prior（欧赔优先的先验锚）

**Files:**
- Create: `nutmeg/decision/anchor.py`
- Test: `tests/decision/test_anchor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_anchor.py
from nutmeg.decision.anchor import resolve_prior
from nutmeg.decision.ontology import MarketSnapshot


def _snap(source, had):
    return MarketSnapshot(snapshot_id=f"S-{source}", match_id="M-1", taken_at="t",
                          kind="read_time", source=source, fair={"had": had})


def test_prefers_euro_over_sporttery():
    euro = _snap("apifootball", {"home": 0.40, "draw": 0.30, "away": 0.30})
    tc = _snap("sporttery", {"home": 0.46, "draw": 0.27, "away": 0.27})
    prior, anchor = resolve_prior([tc, euro], market="had")
    assert prior == euro.fair["had"] and anchor.source == "apifootball"


def test_falls_back_to_sporttery_when_no_euro():
    tc = _snap("sporttery", {"home": 0.46, "draw": 0.27, "away": 0.27})
    prior, anchor = resolve_prior([tc], market="had")
    assert prior == tc.fair["had"] and anchor.source == "sporttery"


def test_none_when_no_read_time_snapshot_has_market():
    closing = MarketSnapshot(snapshot_id="S-c", match_id="M-1", taken_at="t",
                             kind="closing", source="apifootball",
                             fair={"had": {"home": 0.5, "draw": 0.3, "away": 0.2}})
    assert resolve_prior([closing], market="had") == (None, None)  # 只认 read_time
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_anchor.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nutmeg.decision.anchor'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/anchor.py
"""先验锚选择——欧赔读时 fair 优先(最 sharp),否则体彩 fair(spec §9 精化 2)。

CLV 两端都用欧赔才自洽:prior=欧赔读时 fair,closing=欧赔收盘 fair。
只认 kind=read_time 快照(收盘快照不作先验)。
"""
from __future__ import annotations

_SOURCE_PRIORITY = ("apifootball", "fcom500", "sporttery")


def resolve_prior(snapshots: list, *, market: str):
    """→ (prior_dict, anchor_snapshot)。无可用 read_time 快照带该市场 → (None, None)。"""
    candidates = [
        s for s in snapshots
        if s.kind == "read_time" and (s.fair or {}).get(market)
    ]
    if not candidates:
        return None, None
    candidates.sort(key=lambda s: _SOURCE_PRIORITY.index(s.source)
                    if s.source in _SOURCE_PRIORITY else len(_SOURCE_PRIORITY))
    anchor = candidates[0]
    return anchor.fair[market], anchor
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_anchor.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/anchor.py tests/decision/test_anchor.py
git commit -m "feat(decision): M1 resolve_prior(欧赔优先先验锚)"
```

---

## Task 3: sense_day（体彩+欧赔读时快照一并落库）

**Files:**
- Modify: `nutmeg/decision/sense.py`
- Test: `tests/decision/test_m1_sense.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_m1_sense.py
import json
from nutmeg.decision.sense import sense_day
from nutmeg.decision.ontology import MarketSnapshot
from nutmeg.decision.store import DecisionStore

_BOARD = {"matchInfoList": [{"businessDate": "2026-07-08", "subMatchList": [{
    "matchStatus": "Selling", "businessDate": "2026-07-08", "matchNumStr": "周日092",
    "homeTeamAbbName": "墨西哥", "awayTeamAbbName": "英格兰",
    "had": {"h": "2.03", "d": "3.30", "a": "3.55"}, "hhad": {}, "ttg": {}, "crs": {}}]}]}


class _MO:
    def __init__(self, fair): self.fair_probability = fair; self.line = None


def test_sense_day_persists_both_sporttery_and_euro(tmp_path, monkeypatch):
    daily = tmp_path / "daily" / "2026-07-08"
    daily.mkdir(parents=True)
    (daily / "sporttery_markets.json").write_text(json.dumps(_BOARD), encoding="utf-8")
    # monkeypatch 欧赔读取为一份内存 bold_odds（避免打网/依赖 MarketOdds 反序列化）
    import nutmeg.decision.sense as sense_mod
    monkeypatch.setattr(sense_mod, "_load_euro_bold_odds",
                        lambda rd, od: {"周日092": {"match_winner":
                                                    _MO({"home": 0.42, "draw": 0.28, "away": 0.30})}})
    store = DecisionStore(tmp_path / "decision")
    n = sense_day("2026-07-08", output_dir=tmp_path,
                  taken_at="2026-07-08T15:00:00+08:00", store=store)
    assert n == 1                                    # 1 场
    snaps = store.load(MarketSnapshot)
    sources = {s.source for s in snaps}
    assert sources == {"sporttery", "apifootball"}   # 两条读时快照
    euro = next(s for s in snaps if s.source == "apifootball")
    assert abs(sum(euro.fair["had"].values()) - 1.0) < 1e-6


def test_sense_day_without_euro_still_persists_sporttery(tmp_path, monkeypatch):
    daily = tmp_path / "daily" / "2026-07-08"
    daily.mkdir(parents=True)
    (daily / "sporttery_markets.json").write_text(json.dumps(_BOARD), encoding="utf-8")
    import nutmeg.decision.sense as sense_mod
    monkeypatch.setattr(sense_mod, "_load_euro_bold_odds", lambda rd, od: {})
    store = DecisionStore(tmp_path / "decision")
    sense_day("2026-07-08", output_dir=tmp_path, taken_at="t", store=store)
    sources = {s.source for s in store.load(MarketSnapshot)}
    assert sources == {"sporttery"}                  # 欧赔缺→只体彩,不崩
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_m1_sense.py -q`
Expected: FAIL — `ImportError: cannot import name 'sense_day'`

- [ ] **Step 3: Write minimal implementation（追加到 sense.py）**

```python
def _load_euro_bold_odds(run_date: str, output_dir) -> dict:
    """读时欧赔 bold_odds（现 SOP 已抓的 bold_odds.json，含去水 fair_probability）。
    缺文件/坏结构 → {}（优雅降级，只落体彩快照）。"""
    from nutmeg.services.jczq_market_kernel import load_bold_odds_snapshot
    try:
        return load_bold_odds_snapshot(run_date, output_dir) or {}
    except Exception:  # noqa: BLE001 — 欧赔缺不阻塞体彩落库
        return {}


def sense_day(run_date: str, *, output_dir, taken_at: str, store) -> int:
    """一天的读时感知：体彩快照(下注用) + 欧赔快照(先验锚+CLV) 一并落库。

    体彩从 sporttery_markets.json；欧赔从 bold_odds.json（现 SOP 已抓）。
    返回入库场数（以体彩为准）。M1 用已存快照 replay，不新增打网。
    """
    from nutmeg.decision.market_data import (
        euro_snapshot_from_bold_odds,
        snapshots_from_sporttery,
    )
    from nutmeg.services.jczq_market_kernel import load_sporttery_snapshot

    value = load_sporttery_snapshot(run_date, output_dir)
    if value is None:
        return 0
    tc_snaps = snapshots_from_sporttery(
        value, run_date=run_date, taken_at=taken_at,
        source="sporttery", kind="read_time",
    )
    for s in tc_snaps:
        store.upsert(_match_for_snapshot(s, value, run_date))
        store.upsert(s)
    bold = _load_euro_bold_odds(run_date, output_dir)
    for s in euro_snapshot_from_bold_odds(
        bold, run_date=run_date, taken_at=taken_at,
        kind="read_time", source="apifootball",
    ):
        store.upsert(s)
    return len(tc_snaps)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_m1_sense.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/sense.py tests/decision/test_m1_sense.py
git commit -m "feat(decision): M1 sense_day(体彩+欧赔读时快照)"
```

---

## Task 4: read_ingest — 摄取 Read + 自动 shadow

**Files:**
- Create: `nutmeg/decision/read_ingest.py`
- Test: `tests/decision/test_read_ingest.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_read_ingest.py
from nutmeg.decision.ontology import Factor, MarketSnapshot, Read
from nutmeg.decision.read_ingest import backfill_shadows, ingest_reads
from nutmeg.decision.store import DecisionStore


def _factors():
    return [Factor("seeding_incentive", "签位", "d", "2026-06-27", "071", status="probation")]


def _valid_read_payload():
    return {
        "read_id": "R-1", "match_id": "M-2026-07-08-周日092", "snapshot_id": "S-1",
        "made_at": "t", "judge": "claude", "market": "had",
        "prior": {"home": 0.42, "draw": 0.28, "away": 0.30},
        "belief": {"home": 0.36, "draw": 0.34, "away": 0.30},
        "factors": [{"factor_id": "seeding_incentive", "direction": "draw",
                     "weight_pp": 6, "evidence": [{"url": "u", "quote": "q", "at": "a"}]}],
        "confidence": 3, "shadow": False,
    }


def test_ingest_valid_read_persists(tmp_path):
    store = DecisionStore(tmp_path)
    errs = ingest_reads([_valid_read_payload()], store=store, factors=_factors())
    assert errs == []
    assert store.get(Read, "R-1") is not None


def test_ingest_rejects_invalid_read_no_persist(tmp_path):
    store = DecisionStore(tmp_path)
    bad = _valid_read_payload()
    bad["belief"] = {"home": 0.5, "draw": 0.3, "away": 0.3}   # sum 1.1
    errs = ingest_reads([bad], store=store, factors=_factors())
    assert errs and "R-1" in errs[0]
    assert store.get(Read, "R-1") is None                    # 未落库


def test_backfill_shadows_creates_shadow_for_unjudged(tmp_path):
    store = DecisionStore(tmp_path)
    # 两场读时欧赔快照,只有第一场有非 shadow Read
    for mno in ("周日092", "周日091"):
        store.upsert(MarketSnapshot(
            snapshot_id=f"S-{mno}", match_id=f"M-2026-07-08-{mno}",
            taken_at="2026-07-08T15:00:00+08:00", kind="read_time", source="apifootball",
            fair={"had": {"home": 0.45, "draw": 0.28, "away": 0.27}}))
    ingest_reads([_valid_read_payload()], store=store, factors=_factors())  # 092 已判
    n = backfill_shadows(store, run_date="2026-07-08",
                         made_at="2026-07-08T15:30:00+08:00")
    assert n == 1                                            # 只给 091 补 shadow
    shadows = [r for r in store.load(Read) if r.shadow]
    assert len(shadows) == 1 and shadows[0].match_id.endswith("周日091")
    assert shadows[0].belief == shadows[0].prior            # shadow: belief==prior


def test_backfill_shadows_idempotent(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(MarketSnapshot(
        snapshot_id="S-091", match_id="M-2026-07-08-周日091", taken_at="t",
        kind="read_time", source="apifootball",
        fair={"had": {"home": 0.45, "draw": 0.28, "away": 0.27}}))
    backfill_shadows(store, run_date="2026-07-08", made_at="t2")
    n2 = backfill_shadows(store, run_date="2026-07-08", made_at="t3")
    assert n2 == 0                                           # 重跑不重复
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_read_ingest.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nutmeg.decision.read_ingest'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/read_ingest.py
"""read 动词的代码侧：摄取 Claude 运行时产出的 Read（校验+落库）+ 自动 shadow。

判断（belief/factor/幅度）由 Claude 产出,本模块只校验 schema + 落库。
无命名因子的在售场由 backfill_shadows 自动补 belief=prior 的影子 Read
（免费攒市场基线校准样本,spec §2/§7 shadow 基线永远在跑）。
"""
from __future__ import annotations

from nutmeg.decision.anchor import resolve_prior
from nutmeg.decision.factors import allowed_factor_ids
from nutmeg.decision.ontology import MarketSnapshot, Read
from nutmeg.decision.read_validate import validate_read


def ingest_reads(payloads: list[dict], *, store, factors: list) -> list[str]:
    """校验并落库 Claude 产出的 Read。返回错误串列表（空=全部落库）。"""
    allowed = allowed_factor_ids(factors)
    errors: list[str] = []
    for payload in payloads:
        read = Read.from_dict(payload)
        errs = validate_read(read, allowed_factors=allowed)
        if errs:
            errors.append(f"{read.read_id}: {'; '.join(errs)}")
            continue
        store.upsert(read)
    return errors


def backfill_shadows(store, *, run_date: str, made_at: str) -> int:
    """对当日有读时快照但无非 shadow Read 的场,补 belief=prior 的影子 Read。

    幂等:已有任何 Read（含 shadow）的 match_id 跳过。返回新建 shadow 数。
    """
    prefix = f"M-{run_date}-"
    snaps_by_match: dict[str, list] = {}
    for s in store.load(MarketSnapshot):
        if s.match_id.startswith(prefix) and s.kind == "read_time":
            snaps_by_match.setdefault(s.match_id, []).append(s)
    judged = {r.match_id for r in store.load(Read)}
    made = 0
    for match_id, snaps in sorted(snaps_by_match.items()):
        if match_id in judged:
            continue
        prior, anchor = resolve_prior(snaps, market="had")
        if prior is None:
            continue
        store.upsert(Read(
            read_id=f"R-shadow-{match_id}", match_id=match_id,
            snapshot_id=anchor.snapshot_id, made_at=made_at, judge="shadow",
            market="had", prior=dict(prior), belief=dict(prior),
            factors=[], confidence=1, shadow=True, note="市场基线影子",
        ))
        made += 1
    return made
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_read_ingest.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/read_ingest.py tests/decision/test_read_ingest.py
git commit -m "feat(decision): M1 read_ingest(摄取 Read + 自动 shadow)"
```

---

## Task 5: capture_closing（近开赛欧赔 → 收盘快照）

**Files:**
- Create: `nutmeg/decision/closing.py`
- Test: `tests/decision/test_closing.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_closing.py
import json
from nutmeg.decision.closing import capture_closing
from nutmeg.decision.ontology import MarketSnapshot
from nutmeg.decision.store import DecisionStore

_BOARD = {"matchInfoList": [{"businessDate": "2026-07-08", "subMatchList": [{
    "matchStatus": "Selling", "businessDate": "2026-07-08", "matchNumStr": "周日092",
    "homeTeamAbbName": "墨", "awayTeamAbbName": "英",
    "had": {"h": "2.03", "d": "3.30", "a": "3.55"}}]}]}


class _MO:
    def __init__(self, fair): self.fair_probability = fair; self.line = None


def test_capture_closing_persists_closing_euro_snapshot(tmp_path):
    daily = tmp_path / "daily" / "2026-07-08"
    daily.mkdir(parents=True)
    (daily / "sporttery_markets.json").write_text(json.dumps(_BOARD), encoding="utf-8")
    store = DecisionStore(tmp_path / "decision")
    # 注入 live 欧赔抓取替身（避免打网）
    fake_live = lambda value, *, run_date, settings=None: {
        "周日092": {"match_winner": _MO({"home": 0.38, "draw": 0.29, "away": 0.33})}}
    n = capture_closing("2026-07-08", output_dir=tmp_path,
                        taken_at="2026-07-08T20:00:00+08:00", store=store,
                        live_fetcher=fake_live)
    assert n == 1
    closing = [s for s in store.load(MarketSnapshot) if s.kind == "closing"]
    assert len(closing) == 1
    assert closing[0].source == "apifootball"
    assert abs(sum(closing[0].fair["had"].values()) - 1.0) < 1e-6


def test_capture_closing_no_board_returns_zero(tmp_path):
    store = DecisionStore(tmp_path / "decision")
    assert capture_closing("2026-07-08", output_dir=tmp_path, taken_at="t",
                           store=store, live_fetcher=lambda *a, **k: {}) == 0


def test_capture_closing_empty_euro_persists_nothing(tmp_path):
    daily = tmp_path / "daily" / "2026-07-08"
    daily.mkdir(parents=True)
    (daily / "sporttery_markets.json").write_text(json.dumps(_BOARD), encoding="utf-8")
    store = DecisionStore(tmp_path / "decision")
    n = capture_closing("2026-07-08", output_dir=tmp_path, taken_at="t",
                        store=store, live_fetcher=lambda *a, **k: {})
    assert n == 0                                # 欧赔空→无收盘快照(CLV 将 null)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_closing.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nutmeg.decision.closing'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/closing.py
"""收盘快照捕获——近开赛再抓欧赔 live 价 → kind=closing 快照(CLV 参照,spec §9 精化 1)。

closing = collect_bold_odds_apifootball_live 的欧赔去水 fair。欧赔缺 → 不落
（reconcile 遇缺则 CLV=null,绝不伪造）。live_fetcher 可注入替身供测试。
"""
from __future__ import annotations

from nutmeg.decision.market_data import euro_snapshot_from_bold_odds
from nutmeg.services.jczq_market_kernel import load_sporttery_snapshot


def capture_closing(run_date: str, *, output_dir, taken_at: str, store,
                    live_fetcher=None) -> int:
    """再抓 live 欧赔 → 收盘欧赔快照入库。返回入库收盘快照数。"""
    value = load_sporttery_snapshot(run_date, output_dir)
    if value is None:
        return 0
    if live_fetcher is None:
        from nutmeg.services.jczq_apifootball_odds import (
            collect_bold_odds_apifootball_live,
        )
        live_fetcher = collect_bold_odds_apifootball_live
    bold = live_fetcher(value, run_date=run_date) or {}
    snaps = euro_snapshot_from_bold_odds(
        bold, run_date=run_date, taken_at=taken_at,
        kind="closing", source="apifootball",
    )
    for s in snaps:
        store.upsert(s)
    return len(snaps)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_closing.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/closing.py tests/decision/test_closing.py
git commit -m "feat(decision): M1 capture_closing(近开赛欧赔收盘快照)"
```

---

## Task 6: settle_day（Reads+赛果+收盘 → Settlement 落库，Brier+CLV）

**Files:**
- Modify: `nutmeg/decision/reconcile.py`
- Test: `tests/decision/test_m1_reconcile.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_m1_reconcile.py
from nutmeg.decision.ontology import MarketSnapshot, Read, Settlement
from nutmeg.decision.reconcile import settle_day
from nutmeg.decision.store import DecisionStore


def _seed(store, *, with_closing):
    store.upsert(Read(read_id="R-1", match_id="M-2026-07-08-周日092",
                      snapshot_id="S-r", made_at="t", judge="claude", market="had",
                      prior={"home": 0.42, "draw": 0.28, "away": 0.30},
                      belief={"home": 0.36, "draw": 0.34, "away": 0.30}))
    if with_closing:
        store.upsert(MarketSnapshot(
            snapshot_id="S-c", match_id="M-2026-07-08-周日092", taken_at="t2",
            kind="closing", source="apifootball",
            fair={"had": {"home": 0.34, "draw": 0.37, "away": 0.29}}))


def _results():
    # okooo 赛果口径:{竞彩号: {score, had, ...}}
    return {"周日092": {"score": "1:1", "had": "平"}}


def test_settle_day_scores_brier_and_clv(tmp_path):
    store = DecisionStore(tmp_path)
    _seed(store, with_closing=True)
    n = settle_day(store, run_date="2026-07-08", results=_results(),
                   settled_at="2026-07-09T08:00:00+08:00")
    assert n == 1
    s = store.settlement_for("read", "R-1")
    assert s is not None and s.outcome_90 == "draw"
    assert s.brier is not None and s.clv_pp is not None    # 双轴齐
    assert s.closing_snapshot_id == "S-c"


def test_settle_day_clv_null_without_closing(tmp_path):
    store = DecisionStore(tmp_path)
    _seed(store, with_closing=False)
    settle_day(store, run_date="2026-07-08", results=_results(), settled_at="t")
    s = store.settlement_for("read", "R-1")
    assert s.brier is not None and s.clv_pp is None        # 无收盘→CLV null


def test_settle_day_pending_when_no_result(tmp_path):
    store = DecisionStore(tmp_path)
    _seed(store, with_closing=True)
    settle_day(store, run_date="2026-07-08", results={}, settled_at="t")
    s = store.settlement_for("read", "R-1")
    assert s.brier is None and s.outcome_90 is None        # 赛果缺→pending


def test_settle_day_idempotent(tmp_path):
    store = DecisionStore(tmp_path)
    _seed(store, with_closing=True)
    settle_day(store, run_date="2026-07-08", results=_results(), settled_at="t")
    settle_day(store, run_date="2026-07-08", results=_results(), settled_at="t")
    assert len([s for s in store.load(Settlement) if s.ref_id == "R-1"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_m1_reconcile.py -q`
Expected: FAIL — `ImportError: cannot import name 'settle_day'`

- [ ] **Step 3: Write minimal implementation（追加到 reconcile.py）**

顶部 import 追加 `from dataclasses import replace`（若未有）；实现：

```python
_HAD_OUTCOME = {"胜": "home", "平": "draw", "负": "away"}


def _result_outcome(result: dict) -> tuple[str | None, str | None, int | None, int | None]:
    """okooo 赛果行 → (outcome_90, score, goals_h, goals_a)。缺 → (None,...)。"""
    had = _HAD_OUTCOME.get(result.get("had", ""))
    score = result.get("score") or None
    gh = ga = None
    if score:
        try:
            gh, ga = (int(x) for x in score.replace("：", ":").split(":"))
        except ValueError:
            gh = ga = None
        if had is None and gh is not None:
            had = "home" if gh > ga else "away" if gh < ga else "draw"
    return had, score, gh, ga


def settle_day(store, *, run_date: str, results: dict, settled_at: str) -> int:
    """当日所有 Read → Settlement(Brier+CLV)落库。幂等(upsert-by-id)。返回结算的 Read 数。

    赛果按 okooo 口径 {竞彩号: {score, had}};收盘欧赔快照(kind=closing)供 CLV。
    match_id 形如 M-<date>-<竞彩号>,回捞竞彩号取赛果。
    """
    from nutmeg.decision.ontology import MarketSnapshot, Read

    prefix = f"M-{run_date}-"
    # 收盘欧赔快照按 match_id 索引(只认 kind=closing;供 settle_read 算 CLV)
    closing_by_match = {
        s.match_id: s for s in store.load(MarketSnapshot) if s.kind == "closing"
    }
    n = 0
    for read in store.load(Read):
        if not read.match_id.startswith(prefix):
            continue
        match_no = read.match_id[len(prefix):]
        outcome, score, _gh, _ga = _result_outcome(results.get(match_no, {}))
        closing = closing_by_match.get(read.match_id)
        s = settle_read(read, outcome_90=outcome, score=score, closing=closing)
        s = replace(s, settlement_id=f"SET-read-{read.read_id}",
                    settled_at=settled_at)
        store.upsert(s)
        n += 1
    return n
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_m1_reconcile.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/reconcile.py tests/decision/test_m1_reconcile.py
git commit -m "feat(decision): M1 settle_day(Reads+赛果+收盘→Settlement 落库)"
```

---

## Task 7: run_calibrate（聚合 → FactorVerdict + markdown 面板）

**Files:**
- Modify: `nutmeg/decision/calibrate.py`
- Test: `tests/decision/test_m1_calibrate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_m1_calibrate.py
from nutmeg.decision.ontology import FactorVerdict, Read, Settlement
from nutmeg.decision.calibrate import run_calibrate, render_panel
from nutmeg.decision.store import DecisionStore


def _seed(store, n, factor_id, clv_hit_rate, brier_delta):
    hits = int(round(n * clv_hit_rate))
    for i in range(n):
        rid = f"R-{factor_id}-{i}"
        store.upsert(Read(read_id=rid, match_id=f"M-x-{i}", snapshot_id="s",
                          made_at="t", judge="claude", market="had",
                          prior={"home": 0.4, "draw": 0.3, "away": 0.3},
                          belief={"home": 0.5, "draw": 0.25, "away": 0.25},
                          factors=[{"factor_id": factor_id}]))
        # 预置 Settlement 携带 brier/clv（clv_hit 由 clv_pp>0 表征）
        store.upsert(Settlement(settlement_id=f"SET-read-{rid}", ref_type="read",
                                ref_id=rid, settled_at="t",
                                brier=0.2 + brier_delta, clv_pp=(1.0 if i < hits else -1.0)))


def test_run_calibrate_produces_verdicts(tmp_path):
    store = DecisionStore(tmp_path)
    _seed(store, 31, "seeding_incentive", clv_hit_rate=0.58, brier_delta=-0.01)
    verdicts = run_calibrate(store, as_of="2026-07-20")
    v = next(v for v in verdicts if v.factor_id == "seeding_incentive")
    assert v.n_reads == 31
    assert store.get(FactorVerdict, "seeding_incentive") is not None  # 落库


def test_render_panel_contains_factor_and_rates(tmp_path):
    store = DecisionStore(tmp_path)
    _seed(store, 31, "seeding_incentive", clv_hit_rate=0.58, brier_delta=-0.01)
    verdicts = run_calibrate(store, as_of="2026-07-20")
    panel = render_panel(verdicts)
    assert "seeding_incentive" in panel
    assert "CLV" in panel and "Brier" in panel
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_m1_calibrate.py -q`
Expected: FAIL — `ImportError: cannot import name 'run_calibrate'`

- [ ] **Step 3: Write minimal implementation（追加到 calibrate.py）**

顶部需要 `brier_delta` 的先验对照——Settlement 已存 `brier`（belief 的），但 factor_verdict 需要 `brier_delta`（belief−prior）。M1 简化：用 Read 的 prior/belief + Settlement 的 outcome 重算 delta。为最小实现，settle 时应已可得；此处从 Settlement 的 `brier` 与按 prior 重算的 brier 差得 delta。实现：

```python
def run_calibrate(store, *, as_of: str) -> list:
    """聚合所有已结 Settlement → 每因子 FactorVerdict,落库并返回。

    每 Read 的 (brier_delta, clv_hit) 由其 Settlement + prior/belief 得出:
    - clv_hit = 1 if settlement.clv_pp > 0 else 0（clv_pp is None → 该条不计入 CLV）。
    - brier_delta = settlement.brier − brier(prior, outcome);outcome 由 settlement.outcome_90。
      settlement.brier is None(pending)→ 该条不计入。
    """
    from nutmeg.decision.ontology import Read, Settlement
    from nutmeg.decision.scoring import brier

    reads = {r.read_id: r for r in store.load(Read)}
    per_factor: dict[str, list[dict]] = {}
    for st in store.load(Settlement):
        if st.ref_type != "read" or st.brier is None or st.outcome_90 is None:
            continue
        read = reads.get(st.ref_id)
        if read is None or read.shadow or not read.factors:
            continue
        prior_brier = brier(read.prior, st.outcome_90)
        entry = {
            "brier_delta": st.brier - prior_brier,
            "clv_hit": 1 if (st.clv_pp is not None and st.clv_pp > 0) else 0,
        }
        for f in read.factors:
            fid = f.get("factor_id")
            if fid:
                per_factor.setdefault(fid, []).append(entry)

    verdicts = [factor_verdict(fid, entries, as_of=as_of)
                for fid, entries in sorted(per_factor.items())]
    for v in verdicts:
        store.upsert(v)
    return verdicts


def render_panel(verdicts: list) -> str:
    """校准面板 markdown——逐因子双轴 + 建议。参与精度/曲线留 M1.5 扩展。"""
    lines = ["# 决策校准面板", "", "| 因子 | n | Brier Δ | CLV 命中 | 建议 |", "|---|---|---|---|---|"]
    for v in verdicts:
        bd = "—" if v.brier_delta_vs_prior is None else f"{v.brier_delta_vs_prior:+.3f}"
        clv = "—" if v.clv_hit_rate is None else f"{v.clv_hit_rate:.0%}"
        lines.append(f"| {v.factor_id} | {v.n_reads} | {bd} | {clv} | {v.recommendation} |")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_m1_calibrate.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/calibrate.py tests/decision/test_m1_calibrate.py
git commit -m "feat(decision): M1 run_calibrate + markdown 校准面板"
```

---

## Task 8: 历史 judge-ledger 迁移（保 6/12 起战绩，Brier 轴）

**Files:**
- Create: `nutmeg/decision/migrate.py`
- Test: `tests/decision/test_migrate.py`

spec §12 #3。历史 pick 无欧赔先验/收盘 → 只迁 Read(prior=belief 的 one-hot 近似不可取；改：prior=belief 均设为市场未知则跳过)。**M1 只迁能算 Brier 的**：历史 pick 的 judgment(方向)作 belief one-hot、无 prior 则 brier_delta 无意义 → 只入 Read+Settlement 的 outcome/hit，供因子历史与方向命中率，CLV/brier_delta 标 null。

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_migrate.py
from nutmeg.decision.migrate import migrate_ledger_entries
from nutmeg.decision.ontology import Read, Settlement
from nutmeg.decision.store import DecisionStore


def _ledger():
    return [
        {"date": "2026-06-27", "kind": "pick", "match_id": "M02", "fixture": "阿 vs 奥",
         "judgment": "draw", "confidence": 4, "pending": False,
         "judgment_hit": True, "score_hit": False},
        {"date": "2026-06-27", "kind": "pick", "match_id": "M03", "fixture": "X vs Y",
         "judgment": "home", "confidence": 3, "pending": True},   # pending → 跳过 settlement
        {"date": "2026-06-27", "kind": "absent"},                 # 忽略
    ]


def test_migrate_creates_reads_and_settlements(tmp_path):
    store = DecisionStore(tmp_path)
    n = migrate_ledger_entries(_ledger(), store=store, source_tag="legacy-judge")
    reads = store.load(Read)
    assert len(reads) == 2                       # 两个 pick(absent 忽略)
    # 已结的入 Settlement(hit),pending 的不入
    setts = store.load(Settlement)
    assert len(setts) == 1 and setts[0].hit is True
    assert setts[0].clv_pp is None               # 历史无收盘→CLV null
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_migrate.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nutmeg.decision.migrate'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/migrate.py
"""历史 judge-ledger.jsonl → Read/Settlement 一次性迁移(spec §8/§12 #3)。

历史 pick 无欧赔先验/收盘快照:只迁方向判定与命中,供因子历史与方向命中率;
brier_delta/clv 标 null(绝不伪造)。pending/absent 条目不产 Settlement。
"""
from __future__ import annotations

from nutmeg.decision.ontology import Read, Settlement

_DIRS = ("home", "draw", "away")


def migrate_ledger_entries(entries: list[dict], *, store, source_tag: str) -> int:
    """迁移 pick 条目 → Read(+已结的 Settlement)。返回迁移的 pick 数。"""
    n = 0
    for e in entries:
        if e.get("kind") != "pick":
            continue
        judgment = e.get("judgment")
        if judgment not in _DIRS:
            continue
        date = e.get("date", "")
        mid = f"M-legacy-{date}-{e.get('match_id', '')}"
        belief = {d: (1.0 if d == judgment else 0.0) for d in _DIRS}
        rid = f"R-legacy-{date}-{e.get('match_id', '')}"
        store.upsert(Read(
            read_id=rid, match_id=mid, snapshot_id="", made_at=date,
            judge=source_tag, market="had", prior={}, belief=belief,
            factors=[], confidence=int(e.get("confidence", 3) or 3),
            shadow=False, note=f"legacy migrate: {e.get('fixture', '')}",
        ))
        n += 1
        if not e.get("pending") and e.get("judgment_hit") is not None:
            store.upsert(Settlement(
                settlement_id=f"SET-read-{rid}", ref_type="read", ref_id=rid,
                settled_at=date, hit=bool(e.get("judgment_hit")),
                brier=None, clv_pp=None,       # 历史无 prior/收盘 → 双轴 null
            ))
    return n
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_migrate.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/migrate.py tests/decision/test_migrate.py
git commit -m "feat(decision): M1 历史 judge-ledger 迁移(方向+命中,双轴 null)"
```

---

## Task 9: 动词接线（read/capture-closing/reconcile/calibrate 从骨架转实）

**Files:**
- Modify: `nutmeg/decision/verbs.py`
- Modify: `nutmeg/interfaces/cli/decision.py`
- Test: `tests/decision/test_m1_verbs.py`

M0 的 decision-read/reconcile/calibrate 是骨架 echo。M1 让它们真跑（read 读一个 Read JSON 文件摄取；reconcile 抓 okooo 赛果结算；calibrate 出面板）。capture-closing 新增命令。**只碰 decision.py + verbs.py，不动 cli/__init__。**

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_m1_verbs.py
import json
from typer.testing import CliRunner
from nutmeg.interfaces.cli import app

runner = CliRunner()


def test_decision_read_ingests_from_json_file(tmp_path):
    reads_file = tmp_path / "reads.json"
    reads_file.write_text(json.dumps([{
        "read_id": "R-1", "match_id": "M-2026-07-08-周日092", "snapshot_id": "S-1",
        "made_at": "t", "judge": "claude", "market": "had",
        "prior": {"home": 0.42, "draw": 0.28, "away": 0.30},
        "belief": {"home": 0.42, "draw": 0.28, "away": 0.30},
        "factors": [], "confidence": 1, "shadow": True}]), encoding="utf-8")
    result = runner.invoke(app, [
        "decision-read", "--reads-file", str(reads_file),
        "--output-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "摄取" in result.output or "ingest" in result.output.lower()
    from nutmeg.decision.store import DecisionStore
    from nutmeg.decision.ontology import Read
    assert DecisionStore(tmp_path / "decision").get(Read, "R-1") is not None


def test_decision_capture_closing_registered():
    result = runner.invoke(app, ["decision-capture-closing", "--help"])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_m1_verbs.py -q`
Expected: FAIL — decision-read 无 --reads-file / decision-capture-closing 未注册

- [ ] **Step 3: Write minimal implementation**

`nutmeg/decision/verbs.py` 追加：

```python
def run_read_ingest(reads_file: Path, output_dir: Path) -> str:
    import json
    from nutmeg.decision.factors import load_seed_factors
    from nutmeg.decision.read_ingest import ingest_reads
    from nutmeg.decision.store import DecisionStore

    payloads = json.loads(Path(reads_file).read_text(encoding="utf-8"))
    store = DecisionStore(Path(output_dir) / "decision")
    # 词典：已落库 Factor 优先,否则种子
    factors = store.load(_factor_cls()) or load_seed_factors()
    errs = ingest_reads(payloads, store=store, factors=factors)
    ok = len(payloads) - len(errs)
    msg = f"decision-read: 摄取 {ok}/{len(payloads)} 条 Read"
    if errs:
        msg += " | 拒绝: " + "; ".join(errs)
    return msg


def _factor_cls():
    from nutmeg.decision.ontology import Factor
    return Factor


def run_capture_closing(run_date: str, output_dir: Path, taken_at: str) -> str:
    from nutmeg.decision.closing import capture_closing
    from nutmeg.decision.store import DecisionStore

    store = DecisionStore(Path(output_dir) / "decision")
    n = capture_closing(run_date, output_dir=output_dir, taken_at=taken_at, store=store)
    return f"decision-capture-closing {run_date}: 收盘欧赔快照 {n} 条"


def run_reconcile(run_date: str, output_dir: Path, settled_at: str) -> str:
    from nutmeg.decision.reconcile import settle_day
    from nutmeg.decision.store import DecisionStore
    from nutmeg.services.jczq_results import OkoooJczqResultProvider

    store = DecisionStore(Path(output_dir) / "decision")
    try:
        results = OkoooJczqResultProvider().fetch_results(run_date)
    except Exception:  # noqa: BLE001 — 抓不到赛果 → 全 pending
        results = {}
    n = settle_day(store, run_date=run_date, results=results, settled_at=settled_at)
    return f"decision-reconcile {run_date}: 结算 {n} 条 Read"


def run_calibrate_panel(output_dir: Path, as_of: str) -> str:
    from nutmeg.decision.calibrate import render_panel, run_calibrate
    from nutmeg.decision.store import DecisionStore

    store = DecisionStore(Path(output_dir) / "decision")
    verdicts = run_calibrate(store, as_of=as_of)
    panel = render_panel(verdicts)
    out = Path(output_dir) / "decision" / f"calibration-panel-{as_of}.md"
    out.write_text(panel, encoding="utf-8")
    return f"decision-calibrate: {len(verdicts)} 因子判决 → {out}"
```

`nutmeg/interfaces/cli/decision.py` 把四个骨架命令改为真调用（保留 decision-express 骨架），并加 decision-capture-closing。示例（decision-read）：

```python
_READS_FILE_OPTION = _cli.typer.Option(..., "--reads-file", help="Read JSON 数组文件")


@_cli.app.command("decision-read")
def decision_read(
    reads_file: Path = _READS_FILE_OPTION,
    output_dir: Path = _OUTPUT_DIR_OPTION,
) -> None:
    """决策本体 · 动词二:摄取 Claude 运行时产出的 Read(校验+落库)。"""
    from nutmeg.decision.verbs import run_read_ingest
    _cli.typer.echo(run_read_ingest(reads_file, output_dir))


@_cli.app.command("decision-capture-closing")
def decision_capture_closing(
    run_date: str = _cli.typer.Option(..., "--run-date"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
    taken_at: str = _cli.typer.Option(..., "--taken-at"),
) -> None:
    """决策本体 · 收盘捕获:近开赛欧赔 → CLV 参照快照。"""
    from nutmeg.decision.verbs import run_capture_closing
    _cli.typer.echo(run_capture_closing(run_date, output_dir, taken_at))
```

decision-reconcile / decision-calibrate 同样改真调用（run_reconcile 需 --run-date/--settled-at；run_calibrate 需 --as-of）。**保持 decision-sense（Task 14 M0）与 decision-express（骨架）不变。**

- [ ] **Step 4: Run test to verify it passes + CLI 回归**

Run: `uv run pytest tests/decision/test_m1_verbs.py -q`
Expected: PASS (2 passed)

Run: `uv run pytest tests/test_cli.py -q`
Expected: 全 passed（现有 CLI 未破坏）

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/verbs.py nutmeg/interfaces/cli/decision.py tests/decision/test_m1_verbs.py
git commit -m "feat(decision): M1 动词接线(read 摄取/capture-closing/reconcile/calibrate)"
```

---

## Task 10: M1 端到端冒烟 + 全套回归

**Files:**
- Test: `tests/decision/test_m1_e2e.py`

完整 CLV 环:sense_day(体彩+欧赔) → 手造 Read → 校验落库 → 补 shadow → capture_closing → settle_day(Brier+CLV) → run_calibrate。

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_m1_e2e.py
"""M1 端到端:一天走完 感知→判读→收盘→结算→校准,CLV 真实算出。"""
import json
from nutmeg.decision.store import DecisionStore
from nutmeg.decision.sense import sense_day
from nutmeg.decision.read_ingest import backfill_shadows, ingest_reads
from nutmeg.decision.closing import capture_closing
from nutmeg.decision.reconcile import settle_day
from nutmeg.decision.calibrate import run_calibrate
from nutmeg.decision.factors import load_seed_factors
from nutmeg.decision.ontology import Settlement

_BOARD = {"matchInfoList": [{"businessDate": "2026-07-08", "subMatchList": [{
    "matchStatus": "Selling", "businessDate": "2026-07-08", "matchNumStr": "周日092",
    "homeTeamAbbName": "墨", "awayTeamAbbName": "英",
    "had": {"h": "2.03", "d": "3.30", "a": "3.55"}}]}]}


class _MO:
    def __init__(self, fair): self.fair_probability = fair; self.line = None


def test_m1_full_clv_loop(tmp_path, monkeypatch):
    daily = tmp_path / "daily" / "2026-07-08"
    daily.mkdir(parents=True)
    (daily / "sporttery_markets.json").write_text(json.dumps(_BOARD), encoding="utf-8")
    store = DecisionStore(tmp_path / "decision")

    import nutmeg.decision.sense as sense_mod
    monkeypatch.setattr(sense_mod, "_load_euro_bold_odds",
                        lambda rd, od: {"周日092": {"match_winner":
                                                    _MO({"home": 0.42, "draw": 0.28, "away": 0.30})}})
    assert sense_day("2026-07-08", output_dir=tmp_path,
                     taken_at="2026-07-08T15:00:00+08:00", store=store) == 1

    # 手造一个签位激励偏平的 Read(锚欧赔 fair)
    ingest_reads([{
        "read_id": "R-092", "match_id": "M-2026-07-08-周日092", "snapshot_id": "S-x",
        "made_at": "2026-07-08T15:00:00+08:00", "judge": "claude", "market": "had",
        "prior": {"home": 0.42, "draw": 0.28, "away": 0.30},
        "belief": {"home": 0.36, "draw": 0.34, "away": 0.30},
        "factors": [{"factor_id": "seeding_incentive", "direction": "draw",
                     "weight_pp": 6, "evidence": [{"url": "u", "quote": "q", "at": "a"}]}],
        "confidence": 3, "shadow": False}], store=store, factors=load_seed_factors())

    backfill_shadows(store, run_date="2026-07-08", made_at="2026-07-08T15:30:00+08:00")

    # 收盘欧赔朝平移动(与 belief 同向)
    capture_closing("2026-07-08", output_dir=tmp_path,
                    taken_at="2026-07-08T20:00:00+08:00", store=store,
                    live_fetcher=lambda v, *, run_date, settings=None: {
                        "周日092": {"match_winner": _MO({"home": 0.36, "draw": 0.35, "away": 0.29})}})

    settle_day(store, run_date="2026-07-08",
               results={"周日092": {"score": "1:1", "had": "平"}},
               settled_at="2026-07-09T08:00:00+08:00")

    s = store.settlement_for("read", "R-092")
    assert s.outcome_90 == "draw"
    assert s.brier is not None and s.clv_pp is not None
    assert s.clv_pp > 0            # belief 朝平偏、收盘也朝平 → CLV 正(信息含量)

    verdicts = run_calibrate(store, as_of="2026-07-08")
    assert any(v.factor_id == "seeding_incentive" for v in verdicts)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_m1_e2e.py -q`
Expected: FAIL（若某签名不符在此暴露）→ 修到 PASS

- [ ] **Step 3: 联调（本任务无新实现，仅暴露签名不符时回改）**

各模块已在 Task 1-9 实现；此步仅在联调暴露不一致时回改，重跑至 PASS。

- [ ] **Step 4: 收尾门（全套回归 + ruff）**

Run: `uv run ruff check nutmeg/decision tests/decision`
Expected: All checks passed

Run: `uv run pytest -q`
Expected: 全绿（M0 后 1106 基线 + M1 新增测试，零回归）

- [ ] **Step 5: Commit**

```bash
git add tests/decision/test_m1_e2e.py
git commit -m "test(decision): M1 端到端 CLV 环冒烟 + 全套回归绿"
```

---

## 自查（fresh-eyes 检查）

**Spec 覆盖（§9 M1 + §12 精化）：**
- §9「每日判读并行落新本体」→ read_ingest(Task 4) + 动词接线(Task 9) ✓
- §9「CLV 轴从第一天积累」→ euro 锚(Task 1) + resolve_prior(Task 2) + capture_closing(Task 5) + settle_day CLV(Task 6) ✓
- §12 #1「收盘快照源」→ 精化为欧赔 fair(Task 1/5),已在计划头声明 ✓
- §12 #3「历史迁移」→ migrate(Task 8) ✓
- §7「shadow 基线永远在跑」→ backfill_shadows(Task 4) ✓
- 自测面板 → run_calibrate/render_panel(Task 7) ✓
- 范围外(§12 #2 GPT 二评委 / express / Telegram)→ 用户选"只建核心",不在 M1 ✓

**占位符扫描：** 无 TBD/TODO/占位（Task 6 已清理为正式索引写法）。每步含完整代码或确切命令。

**类型一致性：** `euro_snapshot_from_bold_odds`(Task 1)签名与 sense_day(Task 3)/capture_closing(Task 5)调用一致；`resolve_prior→(prior,anchor)`(Task 2)与 backfill_shadows(Task 4)一致；`settle_day`(Task 6)与 verbs run_reconcile(Task 9)/e2e(Task 10)一致；`run_calibrate/render_panel`(Task 7)与 verbs(Task 9)/e2e 一致；`_load_euro_bold_odds` 为 monkeypatch 点,sense(Task 3)定义、test/e2e 替换。

**范围边界：** M1 = 预测度量核心(感知欧赔锚 + read 摄取 + 收盘 CLV + 结算 + 校准面板 + 历史迁移)；express 组合票 / Telegram 推送 / launchd 自动化 = M1.5/M2。

---

## Execution Handoff

计划已保存到 `docs/superpowers/plans/2026-07-06-decision-ontology-m1.md`。两种执行方式：

1. **Subagent-Driven（推荐，同 M0）** — 每 Task 派新 subagent，任务间审查。
2. **Inline 执行** — 本 session 用 executing-plans。

选哪种？
