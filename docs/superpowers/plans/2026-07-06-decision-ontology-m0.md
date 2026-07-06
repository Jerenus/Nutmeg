# 决策本体系统 M0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建 `nutmeg/decision/` 包——七对象本体 + JSONL store + 净化后的 market_data + 双轴（Brier/CLV）reconcile/calibrate + 初始因子词典，全部有测试，不触动现系统。

**Architecture:** 本体中心（Palantir 式）：一切持久状态 = 七类 frozen dataclass 对象，存 `.nutmeg-data/decision/{type}.jsonl`（幂等 upsert-by-id）。五动词是作用在本体上的无状态过程。M0 建齐确定性积木 + 动词 CLI 骨架；判断（Claude 推理）永不进代码。

**Tech Stack:** Python 3.12 / dataclasses / stdlib json / pytest / typer(CLI) / uv。种子代码：`nutmeg/services/jczq_market_kernel.py`（29 数据基元）+ `nutmeg/services/worldcup/judge_ledger.py`（对账数学）。

**关键纪律（每个 Task 都遵守）：**
- 每步跑 `uv run pytest -q`；pre-commit 已装（ruff + wc/jczq 子集）会自动跑。
- 判断永不进代码：Read 的 factors/belief 幅度由 Claude 运行时产出，代码只校验 schema。
- 缺数据 = null 绝不伪造；概率归一容差 1e-6。
- M0 不动 CLAUDE.md/AGENTS.md/launchd/现有 CLI；只新增 `nutmeg/decision/` + `tests/decision/`。

**参考 spec：** `docs/superpowers/specs/2026-07-06-decision-ontology-design.md`（§2 本体 schema、§5 双轴计分、附录 A 符号清单）。

---

## 文件结构（决策锁定在此）

```
nutmeg/decision/
  __init__.py       # 包标记，导出七对象 + DecisionStore
  ontology.py       # 七 frozen dataclass + to_dict/from_dict + 校验
  store.py          # DecisionStore：JSONL 幂等 upsert-by-id + load + 血缘查询
  market_data.py    # A.1 29 基元迁入 + 净化版 snapshots_from_sporttery
  factors.py        # Factor 生命周期 + 初始词典种子加载
  scoring.py        # 双轴数学：brier / brier_delta / clv_pp（纯函数，无 I/O）
  reconcile.py      # Read/Ticket + 赛果 + 收盘快照 → Settlement
  calibrate.py      # 聚合 Settlement → FactorVerdict + 词典上限强制
  express.py        # 组合枚举 + 赔率算术 + 预算闸（骨架）
  verbs.py          # 五动词 CLI 骨架（decision-sense/read/express/reconcile/calibrate）
data/
  decision_factors_seed.json   # 6 个初始 probation 因子
tests/decision/
  test_ontology.py test_store.py test_market_data.py test_factors.py
  test_scoring.py test_reconcile.py test_calibrate.py test_express.py
.nutmeg-data/decision/         # 运行时生成：{matches,snapshots,reads,factors,tickets,settlements,verdicts}.jsonl
```

**责任边界：** `ontology` 只定义对象与校验（无 I/O）；`store` 只做持久（不懂业务）；`scoring` 是纯数学（可单测手算对照）；`reconcile`/`calibrate` 编排 store+scoring；`market_data` 是唯一外部数据形状适配点；`verbs` 只接线不含逻辑。

---

## Task 1: 包骨架 + Match/MarketSnapshot 对象

**Files:**
- Create: `nutmeg/decision/__init__.py`
- Create: `nutmeg/decision/ontology.py`
- Test: `tests/decision/test_ontology.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_ontology.py
from nutmeg.decision.ontology import Match, MarketSnapshot


def test_match_id_and_roundtrip():
    m = Match(
        match_id="M-2026-07-08-092",
        kickoff_at="2026-07-08T03:00:00+08:00",
        home="Mexico", away="England", competition="WC2026",
        channel_refs={"jczq_match_no": "周日092"},
    )
    assert m.id == "M-2026-07-08-092"
    assert Match.from_dict(m.to_dict()) == m


def test_snapshot_id_and_roundtrip():
    s = MarketSnapshot(
        snapshot_id="S-...-1", match_id="M-...", taken_at="2026-07-08T15:00:00+08:00",
        kind="read_time", source="sporttery",
        fair={"had": {"home": 0.46, "draw": 0.27, "away": 0.27}},
        raw_odds={"had": {"home": 2.03, "draw": 3.30, "away": 3.55}},
        lines={"hhad_line": -1.0, "ou_line": 2.5},
    )
    assert s.id == "S-...-1"
    assert MarketSnapshot.from_dict(s.to_dict()) == s
    assert s.kind in ("read_time", "closing")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_ontology.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nutmeg.decision'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/__init__.py
"""决策本体系统 — 第一性原理重设计(spec 2026-07-06)。"""
```

```python
# nutmeg/decision/ontology.py
"""七对象本体 — frozen dataclass + to_dict/from_dict + 校验(无 I/O)。

设计: docs/superpowers/specs/2026-07-06-decision-ontology-design.md §2。
每对象有 .id(主键,供 store 幂等 upsert)与 .to_dict/.from_dict(JSONL 往返)。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any


def _from_dict(cls, payload: dict):
    """只取 cls 声明的字段(容忍多余键),缺省字段用默认值。"""
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in payload.items() if k in known})


@dataclass(frozen=True, slots=True)
class Match:
    match_id: str
    kickoff_at: str
    home: str
    away: str
    competition: str = ""
    channel_refs: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.match_id

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "Match":
        return _from_dict(cls, payload)


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    snapshot_id: str
    match_id: str
    taken_at: str
    kind: str                  # read_time | closing
    source: str                # sporttery | fcom500 | apifootball | okooo_sp
    fair: dict[str, dict[str, float]] = field(default_factory=dict)
    raw_odds: dict[str, dict[str, float]] = field(default_factory=dict)
    lines: dict[str, float] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.snapshot_id

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "MarketSnapshot":
        return _from_dict(cls, payload)
```

Note: `slots=True` + `frozen=True` 使 `==` 按字段比较；`dict` 字段的 `asdict` 深拷贝，往返相等。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_ontology.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/__init__.py nutmeg/decision/ontology.py tests/decision/test_ontology.py
git commit -m "feat(decision): 包骨架 + Match/MarketSnapshot 本体对象"
```

---

## Task 2: Read/Factor/Ticket/Settlement/FactorVerdict 对象

**Files:**
- Modify: `nutmeg/decision/ontology.py`
- Test: `tests/decision/test_ontology.py`

- [ ] **Step 1: Write the failing test（追加到 test_ontology.py）**

```python
from nutmeg.decision.ontology import (
    Read, Factor, Ticket, Settlement, FactorVerdict,
)


def test_read_roundtrip_and_id():
    r = Read(
        read_id="R-2026-07-08-092", match_id="M-...", snapshot_id="S-...",
        made_at="2026-07-08T15:00:00+08:00", judge="claude", market="had",
        prior={"home": 0.46, "draw": 0.27, "away": 0.27},
        belief={"home": 0.40, "draw": 0.33, "away": 0.27},
        factors=[{"factor_id": "seeding_incentive", "direction": "draw",
                  "weight_pp": 6, "evidence": [{"url": "x", "quote": "y", "at": "z"}]}],
        scenarios=[{"story": "铁桶拖平", "weight": 0.33}],
        falsifier="若 X 首发则撤回", confidence=3, shadow=False, note="一句话",
    )
    assert r.id == "R-2026-07-08-092"
    assert Read.from_dict(r.to_dict()) == r


def test_factor_ticket_settlement_verdict_roundtrip():
    f = Factor(factor_id="seeding_incentive", name_zh="签位激励",
               definition="MD3 高名次碰强签→赢反而更糟", born_at="2026-06-27",
               born_from="071 实证", status="probation")
    assert f.id == "seeding_incentive" and Factor.from_dict(f.to_dict()) == f

    t = Ticket(ticket_id="T-1", channel="jczq", made_at="2026-07-08T15:00:00+08:00",
               legs=[{"match_id": "M-...", "read_id": "R-...", "market": "had",
                      "pick": "home", "line": None, "odds": 1.64}],
               structure="single", stake_yuan=15, computed_hit_prob=0.4,
               tag="had_modal", budget_bucket="had_modal")
    assert t.id == "T-1" and Ticket.from_dict(t.to_dict()) == t

    s = Settlement(settlement_id="SET-R-...", ref_type="read", ref_id="R-...",
                   settled_at="2026-07-09T08:00:00+08:00", outcome_90="draw",
                   score="1-1", closing_snapshot_id="S-close-...",
                   brier=0.18, clv_pp=0.02, hit=None, pnl_yuan=None)
    assert s.id == "SET-R-..." and Settlement.from_dict(s.to_dict()) == s

    v = FactorVerdict(factor_id="seeding_incentive", as_of="2026-07-20",
                      n_reads=31, brier_delta_vs_prior=-0.01, clv_hit_rate=0.58,
                      direction_hit_rate=0.55, recommendation="keep",
                      next_review_at="2026-08-20")
    assert v.id == "seeding_incentive" and FactorVerdict.from_dict(v.to_dict()) == v
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_ontology.py -q`
Expected: FAIL — `ImportError: cannot import name 'Read'`

- [ ] **Step 3: Write minimal implementation（追加到 ontology.py）**

```python
@dataclass(frozen=True, slots=True)
class Read:
    read_id: str
    match_id: str
    snapshot_id: str
    made_at: str
    judge: str
    market: str
    prior: dict[str, float]
    belief: dict[str, float]
    factors: list[dict] = field(default_factory=list)
    scenarios: list[dict] = field(default_factory=list)
    falsifier: str = ""
    confidence: int = 3
    shadow: bool = False
    note: str = ""

    @property
    def id(self) -> str:
        return self.read_id

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "Read":
        return _from_dict(cls, payload)


@dataclass(frozen=True, slots=True)
class Factor:
    factor_id: str
    name_zh: str
    definition: str
    born_at: str
    born_from: str
    status: str = "probation"           # probation | active | retired
    retire_reason: str = ""

    @property
    def id(self) -> str:
        return self.factor_id

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "Factor":
        return _from_dict(cls, payload)


@dataclass(frozen=True, slots=True)
class Ticket:
    ticket_id: str
    channel: str                        # jczq | shengfucai | renjiu
    made_at: str
    legs: list[dict]
    structure: str                      # single | parlay | fushi
    stake_yuan: int
    computed_hit_prob: float | None = None
    tag: str = ""
    budget_bucket: str = ""

    @property
    def id(self) -> str:
        return self.ticket_id

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "Ticket":
        return _from_dict(cls, payload)


@dataclass(frozen=True, slots=True)
class Settlement:
    settlement_id: str
    ref_type: str                       # read | ticket
    ref_id: str
    settled_at: str
    outcome_90: str | None = None
    score: str | None = None
    closing_snapshot_id: str | None = None
    brier: float | None = None
    clv_pp: float | None = None
    hit: bool | None = None
    pnl_yuan: float | None = None

    @property
    def id(self) -> str:
        return self.settlement_id

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "Settlement":
        return _from_dict(cls, payload)


@dataclass(frozen=True, slots=True)
class FactorVerdict:
    factor_id: str
    as_of: str
    n_reads: int
    brier_delta_vs_prior: float | None
    clv_hit_rate: float | None
    direction_hit_rate: float | None
    recommendation: str                 # keep | watch | retire
    next_review_at: str = ""

    @property
    def id(self) -> str:
        return self.factor_id

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "FactorVerdict":
        return _from_dict(cls, payload)
```

同时更新 `__init__.py` 导出：

```python
# nutmeg/decision/__init__.py
"""决策本体系统 — 第一性原理重设计(spec 2026-07-06)。"""
from nutmeg.decision.ontology import (
    Factor,
    FactorVerdict,
    Match,
    MarketSnapshot,
    Read,
    Settlement,
    Ticket,
)

__all__ = [
    "Match", "MarketSnapshot", "Read", "Factor",
    "Ticket", "Settlement", "FactorVerdict",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_ontology.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/ontology.py nutmeg/decision/__init__.py tests/decision/test_ontology.py
git commit -m "feat(decision): Read/Factor/Ticket/Settlement/FactorVerdict 本体对象"
```

---

## Task 3: DecisionStore — JSONL 幂等 upsert-by-id + load

**Files:**
- Create: `nutmeg/decision/store.py`
- Test: `tests/decision/test_store.py`

演进 `judge_ledger.append_day` 的"整批替换幂等"纪律为"按 id upsert"。

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_store.py
from nutmeg.decision.ontology import Match, Read
from nutmeg.decision.store import DecisionStore


def test_upsert_is_idempotent_by_id(tmp_path):
    store = DecisionStore(tmp_path)
    m = Match(match_id="M-1", kickoff_at="t", home="A", away="B")
    store.upsert(m)
    store.upsert(m)                    # 重复 upsert 同 id
    assert len(store.load(Match)) == 1


def test_upsert_replaces_same_id(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(Match(match_id="M-1", kickoff_at="t1", home="A", away="B"))
    store.upsert(Match(match_id="M-1", kickoff_at="t2", home="A", away="B"))
    loaded = store.load(Match)
    assert len(loaded) == 1 and loaded[0].kickoff_at == "t2"


def test_load_returns_typed_objects_and_get(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(Read(read_id="R-1", match_id="M-1", snapshot_id="S-1",
                      made_at="t", judge="claude", market="had",
                      prior={"home": 0.5, "draw": 0.3, "away": 0.2},
                      belief={"home": 0.5, "draw": 0.3, "away": 0.2}, shadow=True))
    got = store.get(Read, "R-1")
    assert got is not None and got.market == "had"
    assert store.get(Read, "R-nope") is None


def test_separate_file_per_type(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(Match(match_id="M-1", kickoff_at="t", home="A", away="B"))
    assert (tmp_path / "matches.jsonl").exists()
    assert not (tmp_path / "reads.jsonl").exists()


def test_corrupt_line_skipped(tmp_path):
    store = DecisionStore(tmp_path)
    (tmp_path).mkdir(exist_ok=True)
    (tmp_path / "matches.jsonl").write_text('{bad\n{"match_id":"M-1","kickoff_at":"t","home":"A","away":"B"}\n')
    assert len(store.load(Match)) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_store.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nutmeg.decision.store'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/store.py
"""DecisionStore — 本体对象的唯一持久层(append-only JSONL,幂等 upsert-by-id)。

演进 judge_ledger 的整批替换幂等纪律(load→剔除同键→重写)。每类型一个文件。
不懂业务:只认对象有 .id / .to_dict / .from_dict。规模 1 万+ 再议 SQLite。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_FILENAMES = {
    "Match": "matches.jsonl",
    "MarketSnapshot": "snapshots.jsonl",
    "Read": "reads.jsonl",
    "Factor": "factors.jsonl",
    "Ticket": "tickets.jsonl",
    "Settlement": "settlements.jsonl",
    "FactorVerdict": "verdicts.jsonl",
}


class DecisionStore:
    def __init__(self, base_dir) -> None:
        self.base = Path(base_dir)

    def _path(self, cls) -> Path:
        return self.base / _FILENAMES[cls.__name__]

    def load(self, cls) -> list:
        path = self._path(cls)
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                out.append(cls.from_dict(json.loads(line)))
            except (json.JSONDecodeError, TypeError, KeyError):
                logger.warning("decision store 损坏行已跳过: %r", line[:80])
        return out

    def get(self, cls, obj_id: str):
        for obj in self.load(cls):
            if obj.id == obj_id:
                return obj
        return None

    def upsert(self, obj) -> None:
        cls = type(obj)
        kept = [o for o in self.load(cls) if o.id != obj.id]
        kept.append(obj)
        path = self._path(cls)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for o in kept:
                fh.write(json.dumps(o.to_dict(), ensure_ascii=False) + "\n")

    def upsert_many(self, objs) -> None:
        for obj in objs:
            self.upsert(obj)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_store.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/store.py tests/decision/test_store.py
git commit -m "feat(decision): DecisionStore JSONL 幂等 upsert-by-id"
```

---

## Task 4: 血缘查询（store 的血缘助手）

**Files:**
- Modify: `nutmeg/decision/store.py`
- Test: `tests/decision/test_store.py`

- [ ] **Step 1: Write the failing test（追加）**

```python
from nutmeg.decision.ontology import Settlement


def test_lineage_reads_for_factor(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(Read(read_id="R-1", match_id="M-1", snapshot_id="S-1",
                      made_at="t", judge="claude", market="had",
                      prior={"home": 0.5, "draw": 0.3, "away": 0.2},
                      belief={"home": 0.4, "draw": 0.4, "away": 0.2},
                      factors=[{"factor_id": "seeding_incentive"}]))
    store.upsert(Read(read_id="R-2", match_id="M-2", snapshot_id="S-2",
                      made_at="t", judge="claude", market="had",
                      prior={"home": 0.5, "draw": 0.3, "away": 0.2},
                      belief={"home": 0.5, "draw": 0.3, "away": 0.2},
                      shadow=True))
    hits = store.reads_for_factor("seeding_incentive")
    assert [r.read_id for r in hits] == ["R-1"]


def test_lineage_settlement_for_ref(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(Settlement(settlement_id="SET-1", ref_type="read", ref_id="R-1",
                            settled_at="t"))
    assert store.settlement_for("read", "R-1").settlement_id == "SET-1"
    assert store.settlement_for("read", "R-9") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_store.py::test_lineage_reads_for_factor -q`
Expected: FAIL — `AttributeError: 'DecisionStore' object has no attribute 'reads_for_factor'`

- [ ] **Step 3: Write minimal implementation（追加到 store.py）**

```python
    # --- 血缘查询(spec §2) ---
    def reads_for_factor(self, factor_id: str) -> list:
        from nutmeg.decision.ontology import Read
        return [
            r for r in self.load(Read)
            if any(f.get("factor_id") == factor_id for f in r.factors)
        ]

    def settlement_for(self, ref_type: str, ref_id: str):
        from nutmeg.decision.ontology import Settlement
        for s in self.load(Settlement):
            if s.ref_type == ref_type and s.ref_id == ref_id:
                return s
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_store.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/store.py tests/decision/test_store.py
git commit -m "feat(decision): store 血缘查询 reads_for_factor / settlement_for"
```

---

## Task 5: market_data — 迁入 A.1 去水/解析基元

**Files:**
- Create: `nutmeg/decision/market_data.py`
- Test: `tests/decision/test_market_data.py`

M0 只迁**纯数学基元**（去水 + pool 解析），**不迁** BoldMatch/信号（附录 A.2/A.3）。
从 `jczq_market_kernel` import 复用（迁移期不复制；M2 删旧 kernel 时再物理搬运）。

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_market_data.py
from nutmeg.decision.market_data import devig, fair_1x2


def test_devig_normalizes_to_one():
    fair = devig({"home": 2.0, "draw": 4.0, "away": 4.0})
    assert abs(sum(fair.values()) - 1.0) < 1e-9
    assert fair["home"] > fair["draw"]          # 短赔=高概率


def test_devig_empty_input():
    assert devig({}) == {}
    assert devig({"home": 0.0}) == {}


def test_fair_1x2_hard_keyed():
    fair = fair_1x2({"home": 2.03, "draw": 3.30, "away": 3.55})
    assert set(fair) == {"home", "draw", "away"}
    assert abs(sum(fair.values()) - 1.0) < 1e-6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_market_data.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nutmeg.decision.market_data'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/market_data.py
"""market_data — 决策系统的确定性盘口数据层(唯一外部数据形状适配点)。

M0 复用 jczq_market_kernel 的纯数学基元(附录 A.1),对外用干净命名重导出;
净化版 snapshots_from_sporttery(Task 6)产 MarketSnapshot,不带 tags/信号字段。
M2 删旧 kernel 时把 A.1 基元物理搬入本文件。**结构性禁止**引入 A.3 信号打分符号。
"""
from __future__ import annotations

from nutmeg.services.jczq_market_kernel import (
    OUTCOMES,
    _devig_map,
    _fair_from_odds,
)

__all__ = ["OUTCOMES", "devig", "fair_1x2"]


def devig(odds: dict[str, float]) -> dict[str, float]:
    """任意键赔率 → 去水 fair 概率(和≈1)。空/不可用 → 空 dict。"""
    return _devig_map(odds)


def fair_1x2(had_odds: dict[str, float]) -> dict[str, float]:
    """胜平负三路赔率 → 去水 fair(home/draw/away)。"""
    return _fair_from_odds(had_odds)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_market_data.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/market_data.py tests/decision/test_market_data.py
git commit -m "feat(decision): market_data 去水基元(复用 kernel A.1)"
```

---

## Task 6: 净化版 snapshots_from_sporttery（去 tags/信号）

**Files:**
- Modify: `nutmeg/decision/market_data.py`
- Test: `tests/decision/test_market_data.py`

附录 A.2 的唯一手术点：解析 sporttery `value` → `MarketSnapshot` 列表，`fair` 逐市场
去水，**不产 tags/信号字段**。复用 kernel 的 pool 解析器（纯数据），不碰 `_strong_favorite_tags`。

- [ ] **Step 1: Write the failing test**

```python
# 追加到 tests/decision/test_market_data.py
from nutmeg.decision.market_data import snapshots_from_sporttery
from nutmeg.decision.ontology import MarketSnapshot

_SELLING = {
    "matchInfoList": [{
        "businessDate": "2026-07-08",
        "subMatchList": [{
            "matchStatus": "Selling", "businessDate": "2026-07-08",
            "matchNumStr": "周日092", "leagueAbbName": "世界杯",
            "homeTeamAbbName": "墨西哥", "awayTeamAbbName": "英格兰",
            "had": {"h": "2.03", "d": "3.30", "a": "3.55"},
            "hhad": {"h": "1.74", "d": "3.55", "a": "4.20",
                     "goalLineValue": "-1.00"},
            "ttg": {}, "crs": {},
        }],
    }]
}


def test_snapshots_from_sporttery_produces_marketsnapshot(tmp_path):
    snaps = snapshots_from_sporttery(
        _SELLING, run_date="2026-07-08", taken_at="2026-07-08T15:00:00+08:00",
        source="sporttery", kind="read_time",
    )
    assert len(snaps) == 1
    s = snaps[0]
    assert isinstance(s, MarketSnapshot)
    assert s.snapshot_id.startswith("S-")
    assert abs(sum(s.fair["had"].values()) - 1.0) < 1e-6
    assert s.lines["hhad_line"] == -1.0
    # 净化断言:结构上没有 tags / 信号字段
    assert not hasattr(s, "tags")
    assert "tags" not in s.to_dict()


def test_snapshots_skip_non_selling(tmp_path):
    board = {"matchInfoList": [{"businessDate": "2026-07-08", "subMatchList": [
        {"matchStatus": "Closed", "businessDate": "2026-07-08",
         "matchNumStr": "周日091", "had": {"h": "1.5", "d": "4", "a": "6"}}]}]}
    assert snapshots_from_sporttery(board, run_date="2026-07-08",
                                    taken_at="t", source="sporttery",
                                    kind="read_time") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_market_data.py::test_snapshots_from_sporttery_produces_marketsnapshot -q`
Expected: FAIL — `ImportError: cannot import name 'snapshots_from_sporttery'`

- [ ] **Step 3: Write minimal implementation（追加到 market_data.py）**

在文件顶部 import 追加：

```python
from nutmeg.services.jczq_market_kernel import (
    _crs_from_pool,
    _had_from_pool,
    _signed_float,
    _ttg_from_pool,
)
```

`__all__` 追加 `"snapshots_from_sporttery"`；实现：

```python
def _snapshot_id(match_no: str, taken_at: str, kind: str) -> str:
    """确定性 id:同场同时刻同 kind 只产一条(store 幂等靠它)。"""
    return f"S-{kind}-{match_no}-{taken_at}"


def snapshots_from_sporttery(
    value: dict, *, run_date: str, taken_at: str, source: str, kind: str,
) -> list:
    """sporttery getMatchCalculatorV1 的 value → MarketSnapshot 列表(净化版)。

    附录 A.2:同 bold_matches_from_sporttery 的解析逻辑,但产 MarketSnapshot、
    fair 逐市场去水、**不产 tags/信号字段**、不调 _strong_favorite_tags。
    只保留在售且 businessDate==run_date 的场;每市场有可用赔率才写 fair。
    """
    from nutmeg.decision.ontology import MarketSnapshot

    snaps: list = []
    for day in value.get("matchInfoList") or []:
        for raw in day.get("subMatchList") or []:
            if str(raw.get("matchStatus") or "").casefold() != "selling":
                continue
            business_date = str(
                raw.get("businessDate") or day.get("businessDate") or ""
            )
            if run_date and business_date and business_date != run_date:
                continue
            match_no = str(raw.get("matchNumStr") or "")
            hhad_pool = raw.get("hhad") or {}
            had_odds = _had_from_pool(raw.get("had") or {})
            hhad_odds = _had_from_pool(hhad_pool)
            ttg_odds = _ttg_from_pool(raw.get("ttg") or {})
            crs_odds = _crs_from_pool(raw.get("crs") or {})
            if not (len(had_odds) >= 3 or len(hhad_odds) >= 3 or ttg_odds or crs_odds):
                continue
            raw_odds: dict[str, dict[str, float]] = {}
            fair: dict[str, dict[str, float]] = {}
            if len(had_odds) >= 3:
                raw_odds["had"] = had_odds
                fair["had"] = fair_1x2(had_odds)
            if len(hhad_odds) >= 3:
                raw_odds["hhad"] = hhad_odds
                fair["hhad"] = fair_1x2(hhad_odds)
            if ttg_odds:
                raw_odds["ttg"] = ttg_odds
                fair["ttg"] = devig(ttg_odds)
            if crs_odds:
                raw_odds["crs"] = crs_odds
                fair["crs"] = devig(crs_odds)
            hhad_line = (
                _signed_float(hhad_pool.get("goalLineValue"))
                or _signed_float(hhad_pool.get("goalLine")) or 0.0
            )
            snaps.append(MarketSnapshot(
                snapshot_id=_snapshot_id(match_no, taken_at, kind),
                match_id=f"M-{run_date}-{match_no}",
                taken_at=taken_at, kind=kind, source=source,
                fair=fair, raw_odds=raw_odds,
                lines={"hhad_line": hhad_line},
            ))
    return snaps
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_market_data.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/market_data.py tests/decision/test_market_data.py
git commit -m "feat(decision): 净化版 snapshots_from_sporttery(去 tags/信号)"
```

---

## Task 7: 因子词典种子 + 生命周期

**Files:**
- Create: `nutmeg/data/decision_factors_seed.json`
- Create: `nutmeg/decision/factors.py`
- Test: `tests/decision/test_factors.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_factors.py
from nutmeg.decision.factors import load_seed_factors, active_factor_ids, ACTIVE_CAP


def test_seed_has_six_probation_factors():
    seed = load_seed_factors()
    assert len(seed) == 6
    assert all(f.status == "probation" for f in seed)
    ids = {f.factor_id for f in seed}
    assert {"seeding_incentive", "bunker_profile", "lineup_news_gap",
            "league_bias", "market_line_error", "fatigue_discount"} <= ids


def test_seed_factors_carry_born_from():
    assert all(f.born_from for f in load_seed_factors())   # 出生证必填


def test_active_ids_filters_status():
    from nutmeg.decision.ontology import Factor
    factors = [
        Factor("a", "A", "d", "2026-07-06", "x", status="active"),
        Factor("b", "B", "d", "2026-07-06", "x", status="probation"),
        Factor("c", "C", "d", "2026-07-06", "x", status="retired"),
    ]
    assert active_factor_ids(factors) == {"a"}


def test_active_cap_is_twelve():
    assert ACTIVE_CAP == 12
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_factors.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nutmeg.decision.factors'`

- [ ] **Step 3: Write minimal implementation**

```json
// nutmeg/data/decision_factors_seed.json
[
  {"factor_id": "seeding_incentive", "name_zh": "签位激励",
   "definition": "MD3/淘汰赛前高名次碰强签→赢反而更糟,平/小负成双方最优",
   "born_at": "2026-06-27", "born_from": "071 阿vs奥 实证,信心4"},
  {"factor_id": "bunker_profile", "name_zh": "铁桶压缩净胜",
   "definition": "强弱悬殊+弱队铁桶画像→净胜被压缩,让球档需重算3路",
   "born_at": "2026-07-03", "born_from": "087 让球双选对冲实证"},
  {"factor_id": "lineup_news_gap", "name_zh": "阵容情报时间差",
   "definition": "实名伤停/轮换与市场定价存在时间差=可用信息",
   "born_at": "2026-07-04", "born_from": "拉赫蒂回血2主力 fade 唯一命中"},
  {"factor_id": "league_bias", "name_zh": "极端联赛画像",
   "definition": "极端主客分裂/xG背离联赛禁用通用主场加成",
   "born_at": "2026-07-05", "born_from": "瑞超联赛画像 allsvenskan-2026"},
  {"factor_id": "market_line_error", "name_zh": "3路口径错觉",
   "definition": "体彩让球是3路非亚盘,整数盘热门胜1球落让平档,亚盘直觉高估~28pp",
   "born_at": "2026-07-06", "born_from": "hhad-3way-vs-asian-handicap 教训"},
  {"factor_id": "fatigue_discount", "name_zh": "疲劳折扣(反向登记)",
   "definition": "疲劳≠变弱只推迟破门,破门后崩的是追赶方;试用其否定式",
   "born_at": "2026-07-04", "born_from": "7/04 摩洛哥120min后0:3血洗 证伪方向"}
]
```

```python
# nutmeg/decision/factors.py
"""Factor 生命周期 + 初始词典种子(spec §5)。

生死机制:出生带 born_from(复盘引用)、初始 probation、n<30 只积累、
双轴达标转 active、双轴平庸退休。ACTIVE_CAP=12 结构性防规则堆积。
"""
from __future__ import annotations

import json
from importlib import resources

from nutmeg.decision.ontology import Factor

ACTIVE_CAP = 12
_SEED_RESOURCE = "decision_factors_seed.json"


def load_seed_factors() -> list[Factor]:
    raw = json.loads(
        resources.files("nutmeg.data").joinpath(_SEED_RESOURCE)
        .read_text(encoding="utf-8")
    )
    return [Factor.from_dict({**f, "status": "probation"}) for f in raw]


def active_factor_ids(factors: list[Factor]) -> set[str]:
    return {f.factor_id for f in factors if f.status == "active"}


def allowed_factor_ids(factors: list[Factor]) -> set[str]:
    """Read 校验用:probation + active 都可引用,retired 拒绝。"""
    return {f.factor_id for f in factors if f.status != "retired"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_factors.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add nutmeg/data/decision_factors_seed.json nutmeg/decision/factors.py tests/decision/test_factors.py
git commit -m "feat(decision): 初始因子词典种子 + 生命周期助手"
```

---

## Task 8: Read 校验（归一/weight_pp/因子/证据/conf5）

**Files:**
- Create: `nutmeg/decision/read_validate.py`
- Test: `tests/decision/test_read_validate.py`

spec §2 校验规则 + 判读层硬约束 a-f 继承。校验是代码；判断是 Claude(运行时)。

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_read_validate.py
from nutmeg.decision.ontology import Read
from nutmeg.decision.read_validate import validate_read


def _read(**kw):
    base = dict(read_id="R-1", match_id="M-1", snapshot_id="S-1", made_at="t",
                judge="claude", market="had",
                prior={"home": 0.46, "draw": 0.27, "away": 0.27},
                belief={"home": 0.40, "draw": 0.33, "away": 0.27},
                factors=[{"factor_id": "seeding_incentive", "direction": "draw",
                          "weight_pp": 6,
                          "evidence": [{"url": "u", "quote": "q", "at": "a"}]}],
                confidence=3, shadow=False)
    base.update(kw)
    return Read(**base)


ALLOWED = {"seeding_incentive"}


def test_valid_read_passes():
    assert validate_read(_read(), allowed_factors=ALLOWED) == []


def test_belief_must_normalize():
    bad = _read(belief={"home": 0.5, "draw": 0.3, "away": 0.3})   # sum 1.1
    errs = validate_read(bad, allowed_factors=ALLOWED)
    assert any("归一" in e for e in errs)


def test_factor_must_be_in_dictionary():
    bad = _read(factors=[{"factor_id": "made_up", "direction": "draw",
                          "weight_pp": 6, "evidence": [{"url": "u"}]}])
    errs = validate_read(bad, allowed_factors=ALLOWED)
    assert any("词典" in e for e in errs)


def test_non_shadow_factor_needs_evidence():
    bad = _read(factors=[{"factor_id": "seeding_incentive", "direction": "draw",
                          "weight_pp": 6, "evidence": []}])
    errs = validate_read(bad, allowed_factors=ALLOWED)
    assert any("证据" in e for e in errs)


def test_shadow_read_needs_belief_equals_prior_and_no_factors():
    ok = _read(shadow=True, factors=[],
               belief={"home": 0.46, "draw": 0.27, "away": 0.27})
    assert validate_read(ok, allowed_factors=ALLOWED) == []
    bad = _read(shadow=True, factors=[],
                belief={"home": 0.40, "draw": 0.33, "away": 0.27})
    assert any("shadow" in e for e in validate_read(bad, allowed_factors=ALLOWED))


def test_conf5_only_for_90min_direction():
    # conf5 允许(had 方向)
    assert validate_read(_read(confidence=5), allowed_factors=ALLOWED) == []
    # conf5 + crs(比分)非方向 → 拒绝
    bad = _read(confidence=5, market="crs",
                prior={"1-1": 0.5, "0-0": 0.5}, belief={"1-1": 0.5, "0-0": 0.5},
                factors=[])
    assert any("conf5" in e for e in validate_read(bad, allowed_factors=ALLOWED))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_read_validate.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nutmeg.decision.read_validate'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/read_validate.py
"""Read 校验(代码职责)——概率归一/weight_pp 一致/因子在词典/证据非空/conf5 限方向。

判断(因子选择/幅度/场景/falsifier)是 Claude 运行时产出,永不在此。
继承判读层硬约束 a-f(CLAUDE.md):conf5 仅限 90' 方向市场(had/hhad)。
"""
from __future__ import annotations

_DIRECTION_MARKETS = ("had", "hhad")
_TOL = 1e-6


def validate_read(read, *, allowed_factors: set[str]) -> list[str]:
    errs: list[str] = []

    # 概率归一
    for name, probs in (("prior", read.prior), ("belief", read.belief)):
        total = sum(probs.values())
        if abs(total - 1.0) > _TOL:
            errs.append(f"{name} 概率未归一(和={total:.4f})")

    if read.shadow:
        # shadow: belief 必须 == prior 且无因子
        if read.factors:
            errs.append("shadow read 不得带因子")
        if any(abs(read.belief.get(k, 0.0) - v) > _TOL
               for k, v in read.prior.items()):
            errs.append("shadow read 的 belief 必须等于 prior")
    else:
        # 因子在词典 + 证据非空
        for f in read.factors:
            fid = f.get("factor_id")
            if fid not in allowed_factors:
                errs.append(f"因子 {fid!r} 不在词典或已退休")
            if not f.get("evidence"):
                errs.append(f"因子 {fid!r} 缺证据(非 shadow 必填)")
        # weight_pp 合计 ≈ belief−prior 的总偏移量(pp)
        moved = sum(abs(read.belief.get(k, 0.0) - read.prior.get(k, 0.0))
                    for k in read.prior) * 100 / 2
        declared = sum(abs(f.get("weight_pp", 0)) for f in read.factors)
        if read.factors and abs(moved - declared) > 1.0:
            errs.append(f"weight_pp 合计({declared})≠belief−prior 偏移({moved:.1f}pp)")

    # conf5 仅限 90' 方向市场
    if read.confidence >= 5 and read.market not in _DIRECTION_MARKETS:
        errs.append(f"conf5 仅限 90' 方向市场(had/hhad),得到 {read.market}")

    return errs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_read_validate.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/read_validate.py tests/decision/test_read_validate.py
git commit -m "feat(decision): Read 校验(归一/weight_pp/因子/证据/conf5)"
```

---

## Task 9: scoring — 双轴数学（Brier + CLV，纯函数）

**Files:**
- Create: `nutmeg/decision/scoring.py`
- Test: `tests/decision/test_scoring.py`

spec §5：Brier-对-赛果 + CLV-对-收盘。纯函数，手算对照。

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_scoring.py
from nutmeg.decision.scoring import brier, brier_delta_vs_prior, clv_pp


def test_brier_perfect_and_worst():
    # 完美预测(把 1.0 给了发生的结果)→ 0
    assert brier({"home": 1.0, "draw": 0.0, "away": 0.0}, "home") == 0.0
    # 最差(把 1.0 给了没发生的)→ 2.0(两项各 1.0)
    assert brier({"home": 0.0, "draw": 0.0, "away": 1.0}, "home") == 2.0


def test_brier_uniform():
    # 均匀 1/3,结果 home:(1-1/3)^2 + (1/3)^2 + (1/3)^2 = 4/9+1/9+1/9 = 6/9
    b = brier({"home": 1/3, "draw": 1/3, "away": 1/3}, "home")
    assert abs(b - 6/9) < 1e-9


def test_brier_delta_negative_when_belief_better():
    prior = {"home": 0.33, "draw": 0.33, "away": 0.34}
    belief = {"home": 0.55, "draw": 0.25, "away": 0.20}   # 更看好 home
    # 结果 home → belief 更接近 → delta<0(改善)
    assert brier_delta_vs_prior(belief, prior, "home") < 0


def test_clv_pp_positive_when_moved_toward_closing():
    prior = {"home": 0.40, "draw": 0.30, "away": 0.30}
    belief = {"home": 0.46, "draw": 0.27, "away": 0.27}    # 朝 home 偏
    closing = {"home": 0.50, "draw": 0.28, "away": 0.22}   # 收盘也朝 home
    assert clv_pp(belief, prior, closing) > 0               # 偏移方向对


def test_clv_pp_negative_when_moved_against_closing():
    prior = {"home": 0.40, "draw": 0.30, "away": 0.30}
    belief = {"home": 0.46, "draw": 0.27, "away": 0.27}    # 朝 home 偏
    closing = {"home": 0.34, "draw": 0.33, "away": 0.33}   # 收盘反朝 away
    assert clv_pp(belief, prior, closing) < 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_scoring.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nutmeg.decision.scoring'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/scoring.py
"""双轴计分(spec §5)——纯函数,无 I/O。

轴一 Brier-对-赛果(慢,真理):Σ(belief−onehot)²,越小越好。
  brier_delta_vs_prior<0 = 你的偏移改善了市场先验(Metaculus Baseline 直译)。
轴二 CLV-对-收盘(快,信息含量):(belief−prior)·(closing−prior) 方向命中,
  >0 = 偏移朝收盘移动(含真实信息),开赛即可结,方差远小于赛果。
"""
from __future__ import annotations


def brier(probs: dict[str, float], actual: str) -> float:
    """Σ over outcomes of (prob − 1{outcome==actual})²。actual 不在键中按 0 处理。"""
    total = 0.0
    keys = set(probs) | {actual}
    for k in keys:
        p = probs.get(k, 0.0)
        target = 1.0 if k == actual else 0.0
        total += (p - target) ** 2
    return total


def brier_delta_vs_prior(belief: dict[str, float], prior: dict[str, float],
                         actual: str) -> float:
    """brier(belief) − brier(prior)。负 = 偏移改善了市场先验。"""
    return brier(belief, actual) - brier(prior, actual)


def clv_pp(belief: dict[str, float], prior: dict[str, float],
           closing: dict[str, float]) -> float:
    """(belief−prior)·(closing−prior) 点积。>0 = 偏移朝收盘方向(信息含量)。"""
    keys = set(belief) | set(prior) | set(closing)
    return sum(
        (belief.get(k, 0.0) - prior.get(k, 0.0))
        * (closing.get(k, 0.0) - prior.get(k, 0.0))
        for k in keys
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_scoring.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/scoring.py tests/decision/test_scoring.py
git commit -m "feat(decision): scoring 双轴数学(Brier + CLV 纯函数)"
```

---

## Task 10: reconcile — Read + 赛果 + 收盘快照 → Settlement

**Files:**
- Create: `nutmeg/decision/reconcile.py`
- Test: `tests/decision/test_reconcile.py`

演进 judge_ledger 的对账:Read 结算产双轴 Settlement;赛果缺 → pending(brier/clv=null)。

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_reconcile.py
from nutmeg.decision.ontology import Read, MarketSnapshot
from nutmeg.decision.reconcile import settle_read


def _read(belief):
    return Read(read_id="R-1", match_id="M-1", snapshot_id="S-1", made_at="t",
                judge="claude", market="had",
                prior={"home": 0.46, "draw": 0.27, "away": 0.27},
                belief=belief, confidence=3, shadow=False)


def _closing(fair):
    return MarketSnapshot(snapshot_id="S-close", match_id="M-1", taken_at="t2",
                          kind="closing", source="okooo_sp", fair={"had": fair})


def test_settle_read_scores_both_axes():
    read = _read({"home": 0.40, "draw": 0.33, "away": 0.27})
    closing = _closing({"home": 0.34, "draw": 0.37, "away": 0.29})
    s = settle_read(read, outcome_90="draw", score="1-1", closing=closing)
    assert s.ref_type == "read" and s.ref_id == "R-1"
    assert s.brier is not None and s.clv_pp is not None
    assert s.closing_snapshot_id == "S-close"
    assert s.outcome_90 == "draw"


def test_settle_read_pending_when_no_result():
    read = _read({"home": 0.40, "draw": 0.33, "away": 0.27})
    s = settle_read(read, outcome_90=None, score=None, closing=_closing(
        {"home": 0.34, "draw": 0.37, "away": 0.29}))
    assert s.brier is None and s.outcome_90 is None


def test_settle_read_clv_null_when_no_closing():
    read = _read({"home": 0.40, "draw": 0.33, "away": 0.27})
    s = settle_read(read, outcome_90="draw", score="1-1", closing=None)
    assert s.brier is not None       # 赛果有→Brier 有
    assert s.clv_pp is None          # 无收盘→CLV=null(绝不伪造)


def test_settle_shadow_read_still_scores_brier():
    shadow = Read(read_id="R-2", match_id="M-1", snapshot_id="S-1", made_at="t",
                  judge="claude", market="had",
                  prior={"home": 0.46, "draw": 0.27, "away": 0.27},
                  belief={"home": 0.46, "draw": 0.27, "away": 0.27}, shadow=True)
    s = settle_read(shadow, outcome_90="home", score="2-0", closing=None)
    assert s.brier is not None and s.clv_pp is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_reconcile.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nutmeg.decision.reconcile'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/reconcile.py
"""reconcile — Read/Ticket + 赛果 + 收盘快照 → Settlement(双轴)。

演进 judge_ledger 对账纪律。赛果缺 → pending(brier/outcome=None);
收盘快照缺 → clv_pp=None(缺数据绝不伪造,spec §4 多源纪律)。
"""
from __future__ import annotations

from nutmeg.decision.ontology import Settlement
from nutmeg.decision.scoring import brier, clv_pp


def settle_read(read, *, outcome_90, score, closing) -> Settlement:
    b = None if outcome_90 is None else brier(read.belief, outcome_90)
    clv = None
    if closing is not None and not read.shadow:
        closing_fair = (closing.fair or {}).get(read.market, {})
        if closing_fair:
            clv = clv_pp(read.belief, read.prior, closing_fair)
    return Settlement(
        settlement_id=f"SET-read-{read.read_id}",
        ref_type="read", ref_id=read.read_id,
        settled_at=read.made_at,          # 占位;编排层用真实结算时刻覆盖
        outcome_90=outcome_90, score=score,
        closing_snapshot_id=(closing.snapshot_id if closing else None),
        brier=b, clv_pp=clv, hit=None, pnl_yuan=None,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_reconcile.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/reconcile.py tests/decision/test_reconcile.py
git commit -m "feat(decision): reconcile settle_read 双轴 Settlement"
```

---

## Task 11: reconcile — Ticket 结算（继承 hhad 让球线数学）

**Files:**
- Modify: `nutmeg/decision/reconcile.py`
- Test: `tests/decision/test_reconcile.py`

继承 judge_ledger `_grade_ticket_outcome` 的全部 2026-07-06 修复（hhad 让球线 3 路、
AET/PEN 90'=平、未识别 pick→pending 不误判输）。

- [ ] **Step 1: Write the failing test（追加）**

```python
from nutmeg.decision.reconcile import settle_ticket_leg


def test_settle_had_leg_win_and_loss():
    win = settle_ticket_leg(market="had", pick="home", line=None,
                            outcome_90="home", goals_h=2, goals_a=0)
    assert win == "home"                      # had 直接方向
    lose = settle_ticket_leg(market="had", pick="home", line=None,
                             outcome_90="draw", goals_h=1, goals_a=1)
    assert lose == "draw"


def test_settle_hhad_leg_with_line():
    # 净胜1,让球线-1 → 1+(-1)=0 → 让平
    r = settle_ticket_leg(market="hhad", pick="home", line=-1.0,
                          outcome_90="home", goals_h=2, goals_a=1)
    assert r == "draw"


def test_settle_hhad_aet_is_draw_margin_zero():
    # AET 90' 必平,margin=0,+line
    r = settle_ticket_leg(market="hhad", pick="away", line=-2.0,
                          outcome_90="draw", goals_h=None, goals_a=None)
    assert r == "away"                        # 0+(-2)<0 → 让负


def test_settle_hhad_without_line_pending():
    assert settle_ticket_leg(market="hhad", pick="home", line=None,
                             outcome_90="home", goals_h=2, goals_a=0) is None


def test_settle_unknown_pick_pending_not_loss():
    assert settle_ticket_leg(market="hhad", pick="受让平未知", line=-1.0,
                             outcome_90="home", goals_h=2, goals_a=0) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_reconcile.py::test_settle_hhad_leg_with_line -q`
Expected: FAIL — `ImportError: cannot import name 'settle_ticket_leg'`

- [ ] **Step 3: Write minimal implementation（追加到 reconcile.py）**

```python
def settle_ticket_leg(*, market: str, pick: str, line: float | None,
                      outcome_90: str | None, goals_h: int | None,
                      goals_a: int | None) -> str | None:
    """票面口径 3 路结果(继承 judge_ledger._grade_ticket_outcome 全部 7/06 修复)。

    had=胜平负;hhad=90' 净胜球+让球线。line=None 且 hhad → None(pending)。
    AET/PEN 90'=平 margin 0。pick 无法规约成 home/draw/away → None(pending,不误判输)。
    赛果缺(outcome_90=None)→ None。
    """
    if pick not in ("home", "draw", "away"):
        return None
    if outcome_90 is None:
        return None
    if market == "had":
        return outcome_90
    if market == "hhad":
        if line is None:
            return None
        if outcome_90 == "draw":
            margin = 0
        elif goals_h is None:
            return None
        else:
            margin = goals_h - goals_a
        adj = margin + line
        return "home" if adj > 0 else "away" if adj < 0 else "draw"
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_reconcile.py -q`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/reconcile.py tests/decision/test_reconcile.py
git commit -m "feat(decision): Ticket 腿结算(继承 hhad 让球线数学)"
```

---

## Task 12: calibrate — FactorVerdict 聚合 + 词典上限强制

**Files:**
- Create: `nutmeg/decision/calibrate.py`
- Test: `tests/decision/test_calibrate.py`

spec §5 生死规则:n<30 只积累;n≥30 双轴达标 active,平庸 watch/retire;ACTIVE_CAP=12。

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_calibrate.py
from nutmeg.decision.calibrate import factor_verdict


def _settlements(n, clv_hit_rate, brier_delta):
    """构造 n 条已结 Settlement dict(简化:直接给聚合前的单条值)。"""
    out = []
    hits = int(round(n * clv_hit_rate))
    for i in range(n):
        out.append({"brier_delta": brier_delta,
                    "clv_hit": 1 if i < hits else 0})
    return out


def test_probation_when_under_30():
    v = factor_verdict("seeding_incentive", _settlements(20, 0.7, -0.02),
                       as_of="2026-07-20")
    assert v.recommendation == "keep"          # n<30 只积累不判决
    assert v.n_reads == 20


def test_active_when_double_axis_good():
    v = factor_verdict("seeding_incentive", _settlements(31, 0.58, -0.01),
                       as_of="2026-07-20")
    assert v.recommendation == "keep"          # CLV>0.55 且 brier_delta<0
    assert abs(v.clv_hit_rate - 18/31) < 0.02


def test_retire_when_double_axis_mediocre():
    v = factor_verdict("bad_factor", _settlements(31, 0.45, 0.02),
                       as_of="2026-07-20")
    assert v.recommendation == "retire"        # CLV<0.55 且 brier_delta>0


def test_watch_when_mixed():
    v = factor_verdict("mixed", _settlements(31, 0.58, 0.02),
                       as_of="2026-07-20")
    assert v.recommendation == "watch"         # 一轴好一轴差
```

追加词典上限测试：

```python
from nutmeg.decision.calibrate import enforce_active_cap
from nutmeg.decision.ontology import Factor, FactorVerdict


def test_enforce_cap_retires_weakest_when_over_limit():
    # 13 个 active,超 12 → 最弱(clv 最低)被退休
    factors = [Factor(f"f{i}", f"F{i}", "d", "2026-07-06", "x", status="active")
               for i in range(13)]
    verdicts = [FactorVerdict(f"f{i}", "2026-07-20", 31, -0.01, 0.50 + i * 0.01,
                              0.55, "keep") for i in range(13)]
    retired = enforce_active_cap(factors, verdicts)
    assert retired == ["f0"]                    # clv 最低者
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_calibrate.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nutmeg.decision.calibrate'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/calibrate.py
"""calibrate — 聚合 Settlement → FactorVerdict + 词典上限强制(spec §5)。

生死规则(继承 spec §30 反 churn):
- n<30 只积累不判决(keep)。
- n≥30:CLV 命中>0.55 且 brier_delta<0 → keep(转正/维持 active);
        双轴皆平庸(CLV≤0.55 且 brier_delta≥0) → retire;
        一轴好一轴差 → watch。
- ACTIVE_CAP=12:超限强制退休最弱(CLV 最低)。
"""
from __future__ import annotations

from nutmeg.decision.factors import ACTIVE_CAP
from nutmeg.decision.ontology import FactorVerdict

_MIN_SAMPLE = 30
_CLV_BAR = 0.55


def factor_verdict(factor_id: str, settlements: list[dict], *,
                   as_of: str) -> FactorVerdict:
    """settlements: [{brier_delta, clv_hit(0/1)}, ...](已结,非 pending)。"""
    n = len(settlements)
    clv_rate = (sum(s["clv_hit"] for s in settlements) / n) if n else None
    brier_delta = (sum(s["brier_delta"] for s in settlements) / n) if n else None

    if n < _MIN_SAMPLE:
        rec = "keep"                               # 样本不足只积累
    else:
        clv_good = clv_rate > _CLV_BAR
        brier_good = brier_delta < 0
        if clv_good and brier_good:
            rec = "keep"
        elif not clv_good and not brier_good:
            rec = "retire"
        else:
            rec = "watch"
    return FactorVerdict(
        factor_id=factor_id, as_of=as_of, n_reads=n,
        brier_delta_vs_prior=brier_delta, clv_hit_rate=clv_rate,
        direction_hit_rate=None, recommendation=rec, next_review_at="",
    )


def enforce_active_cap(factors, verdicts) -> list[str]:
    """active 因子超 ACTIVE_CAP → 退休最弱(CLV 最低)者,返回被退休的 id 列表。"""
    active = [f for f in factors if f.status == "active"]
    if len(active) <= ACTIVE_CAP:
        return []
    clv_by_id = {v.factor_id: (v.clv_hit_rate or 0.0) for v in verdicts}
    ranked = sorted(active, key=lambda f: clv_by_id.get(f.factor_id, 0.0))
    n_retire = len(active) - ACTIVE_CAP
    return [f.factor_id for f in ranked[:n_retire]]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_calibrate.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/calibrate.py tests/decision/test_calibrate.py
git commit -m "feat(decision): calibrate FactorVerdict + 词典上限强制"
```

---

## Task 13: express — 预算配置 + 组合枚举 + 预算闸（骨架）

**Files:**
- Create: `nutmeg/data/decision_budget.json`
- Create: `nutmeg/decision/express.py`
- Test: `tests/decision/test_express.py`

spec §6:¥400 硬顶,桶位是**配置数据非代码规则**。复式注数枚举 + 组合赔率算术(禁嘴算)。

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_express.py
from nutmeg.decision.express import (
    load_budget, renjiu_ticket_count, parlay_odds, within_budget,
)


def test_budget_buckets_from_config():
    b = load_budget()
    assert b["jczq"]["had_modal"] == 100
    assert b["jczq"]["draw_single"] == 40
    assert b["shengfucai_renjiu"]["fushi"] == 400


def test_renjiu_count_is_2002():
    # 任九 = 从 14 场选 9 场命中(C(14,9)) = 2002
    assert renjiu_ticket_count(14, 9) == 2002


def test_parlay_odds_multiplies():
    assert abs(parlay_odds([1.64, 2.75]) - 4.51) < 1e-9


def test_within_budget_gate():
    assert within_budget("jczq", "had_modal", 80) is True
    assert within_budget("jczq", "had_modal", 120) is False   # 超 ¥100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_express.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nutmeg.decision.express'`

- [ ] **Step 3: Write minimal implementation**

```json
// nutmeg/data/decision_budget.json
{
  "period_cap_yuan": 400,
  "jczq": {"had_modal": 100, "hhad_cover": 100, "draw_single": 40, "parlay": 60},
  "shengfucai_renjiu": {"fushi": 400}
}
```

```python
# nutmeg/decision/express.py
"""express — 组合枚举 + 赔率算术 + 预算闸(spec §6)。

预算是配置数据(decision_budget.json)非代码规则(数据>代码版本策略)。
复式注数/组合赔率一律代码算(禁嘴算)。M0 为骨架:算术 + 闸门,不含 PDF/推送。
空仓永远合法。
"""
from __future__ import annotations

import json
import math
from functools import reduce
from importlib import resources

_BUDGET_RESOURCE = "decision_budget.json"


def load_budget() -> dict:
    return json.loads(
        resources.files("nutmeg.data").joinpath(_BUDGET_RESOURCE)
        .read_text(encoding="utf-8")
    )


def renjiu_ticket_count(total: int, pick: int) -> int:
    """任九复式注数 = C(total, pick)。"""
    return math.comb(total, pick)


def parlay_odds(odds: list[float]) -> float:
    """串关组合赔率 = 各腿赔率连乘。"""
    return reduce(lambda a, b: a * b, odds, 1.0)


def within_budget(channel: str, bucket: str, stake_yuan: float) -> bool:
    budget = load_budget()
    cap = budget.get(channel, {}).get(bucket)
    return cap is not None and stake_yuan <= cap
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_express.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add nutmeg/data/decision_budget.json nutmeg/decision/express.py tests/decision/test_express.py
git commit -m "feat(decision): express 预算配置 + 组合枚举 + 预算闸"
```

---

## Task 14: sense — sporttery 快照 → Match+Snapshot 入库（编排骨架）

**Files:**
- Create: `nutmeg/decision/sense.py`
- Test: `tests/decision/test_sense.py`

编排:复用 kernel 的 `load_sporttery_snapshot`(replay) + Task 6 净化解析 + store。
M0 用已存快照 replay(不打网),对齐 verify skill 的 replay 配方。

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_sense.py
import json
from nutmeg.decision.sense import sense_from_snapshot
from nutmeg.decision.ontology import Match, MarketSnapshot
from nutmeg.decision.store import DecisionStore

_BOARD = {"matchInfoList": [{"businessDate": "2026-07-08", "subMatchList": [{
    "matchStatus": "Selling", "businessDate": "2026-07-08", "matchNumStr": "周日092",
    "leagueAbbName": "世界杯", "homeTeamAbbName": "墨西哥", "awayTeamAbbName": "英格兰",
    "had": {"h": "2.03", "d": "3.30", "a": "3.55"},
    "hhad": {"h": "1.74", "d": "3.55", "a": "4.20", "goalLineValue": "-1.00"},
    "ttg": {}, "crs": {}}]}]}


def test_sense_persists_match_and_snapshot(tmp_path):
    # 造一个已存 sporttery 快照
    daily = tmp_path / "daily" / "2026-07-08"
    daily.mkdir(parents=True)
    (daily / "sporttery_markets.json").write_text(json.dumps(_BOARD), encoding="utf-8")
    store = DecisionStore(tmp_path / "decision")
    n = sense_from_snapshot("2026-07-08", output_dir=tmp_path,
                            taken_at="2026-07-08T15:00:00+08:00", store=store)
    assert n == 1
    assert len(store.load(Match)) == 1
    assert len(store.load(MarketSnapshot)) == 1
    assert store.load(MarketSnapshot)[0].kind == "read_time"


def test_sense_idempotent_on_rerun(tmp_path):
    daily = tmp_path / "daily" / "2026-07-08"
    daily.mkdir(parents=True)
    (daily / "sporttery_markets.json").write_text(json.dumps(_BOARD), encoding="utf-8")
    store = DecisionStore(tmp_path / "decision")
    sense_from_snapshot("2026-07-08", output_dir=tmp_path,
                        taken_at="2026-07-08T15:00:00+08:00", store=store)
    sense_from_snapshot("2026-07-08", output_dir=tmp_path,
                        taken_at="2026-07-08T15:00:00+08:00", store=store)
    assert len(store.load(MarketSnapshot)) == 1     # 幂等


def test_sense_no_snapshot_returns_zero(tmp_path):
    store = DecisionStore(tmp_path / "decision")
    assert sense_from_snapshot("2026-07-08", output_dir=tmp_path,
                               taken_at="t", store=store) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_sense.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nutmeg.decision.sense'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/sense.py
"""sense — 拉盘口→去水→存 Match+Snapshot(spec §3 动词一)。

M0:从已存 sporttery 快照 replay(不打网,对齐 verify skill replay 配方)。
live 抓取(fetch_sporttery_value_with_fallback + 500.com 备源)在 M1 编排接入。
"""
from __future__ import annotations

from nutmeg.decision.market_data import snapshots_from_sporttery
from nutmeg.decision.ontology import Match
from nutmeg.services.jczq_market_kernel import load_sporttery_snapshot


def sense_from_snapshot(run_date: str, *, output_dir, taken_at: str,
                        store) -> int:
    """已存 sporttery 快照 → MarketSnapshot + Match 入库。返回入库场数。"""
    value = load_sporttery_snapshot(run_date, output_dir)
    if value is None:
        return 0
    snaps = snapshots_from_sporttery(
        value, run_date=run_date, taken_at=taken_at,
        source="sporttery", kind="read_time",
    )
    for s in snaps:
        # 从 value 里回捞队名建 Match(snapshot 已带 match_id)
        store.upsert(_match_for_snapshot(s, value, run_date))
        store.upsert(s)
    return len(snaps)


def _match_for_snapshot(snapshot, value: dict, run_date: str) -> Match:
    match_no = snapshot.match_id.rsplit("-", 1)[-1]
    home = away = ""
    for day in value.get("matchInfoList") or []:
        for raw in day.get("subMatchList") or []:
            if str(raw.get("matchNumStr") or "") == match_no:
                home = str(raw.get("homeTeamAbbName") or "")
                away = str(raw.get("awayTeamAbbName") or "")
    return Match(
        match_id=snapshot.match_id, kickoff_at=snapshot.taken_at,
        home=home, away=away, competition="",
        channel_refs={"jczq_match_no": match_no},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_sense.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/sense.py tests/decision/test_sense.py
git commit -m "feat(decision): sense_from_snapshot(replay 编排)"
```

---

## Task 15: 五动词 CLI 骨架

**Files:**
- Create: `nutmeg/decision/verbs.py`
- Create: `nutmeg/interfaces/cli/decision.py`（命令模块，仿 `cli/jczq.py` 模式）
- Modify: `nutmeg/interfaces/cli/__init__.py:1131-1137`（在命令模块 import 区追加一行）
- Test: `tests/decision/test_verbs.py`

薄接线:decision-sense 用 Task 14 编排;其余四动词 M0 打印骨架状态(read/express 需
Claude 运行时/交互,calibrate/reconcile 待 M1 全量数据)。**不动现有命令与 launchd。**

> **CLI 注册模式（codebase 实测）**：命令在**独立模块**里用 `@_cli.app.command(...)`
> 注册（见 `cli/jczq.py:530`），模块通过 `cli/__init__.py` 底部的
> `from nutmeg.interfaces.cli import <mod> as <mod>`（第 1131-1137 行）导入触发注册。
> `app = typer.Typer(...)` 在 `cli/__init__.py:120`；`from nutmeg.interfaces.cli import app`
> 可用（test_cli.py:38）。新命令照此建独立 `decision.py` 模块。

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_verbs.py
from typer.testing import CliRunner
from nutmeg.interfaces.cli import app

runner = CliRunner()


def test_decision_sense_command_registered():
    result = runner.invoke(app, ["decision-sense", "--help"])
    assert result.exit_code == 0
    assert "run-date" in result.output.lower() or "date" in result.output.lower()


def test_all_five_verbs_registered():
    result = runner.invoke(app, ["--help"])
    for verb in ["decision-sense", "decision-read", "decision-express",
                 "decision-reconcile", "decision-calibrate"]:
        assert verb in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_verbs.py -q`
Expected: FAIL — `decision-sense` not in output

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/verbs.py
"""五动词 CLI 实现(spec §3)。M0:sense 可跑(replay),余为骨架。

不动现有命令/launchd(M2 才切)。命令通过 cli/__init__ 的 @app.command 注册。
"""
from __future__ import annotations

from pathlib import Path


def run_sense(run_date: str, output_dir: Path, taken_at: str) -> str:
    from nutmeg.decision.sense import sense_from_snapshot
    from nutmeg.decision.store import DecisionStore

    store = DecisionStore(Path(output_dir) / "decision")
    n = sense_from_snapshot(run_date, output_dir=output_dir,
                            taken_at=taken_at, store=store)
    return f"decision-sense {run_date}: 入库 {n} 场 Match+Snapshot"
```

创建独立命令模块 `nutmeg/interfaces/cli/decision.py`（仿 `cli/jczq.py` 用 `_cli.app.command`）：

```python
# nutmeg/interfaces/cli/decision.py
"""决策本体系统五动词 CLI(spec §3)。M0:sense 可 replay,余为骨架。

仿 cli/jczq.py 模式:@_cli.app.command 注册,由 cli/__init__ 底部 import 触发。
"""
from __future__ import annotations

from pathlib import Path

import nutmeg.interfaces.cli as _cli


@_cli.app.command("decision-sense")
def decision_sense(
    run_date: str = _cli.typer.Option(..., "--run-date", help="YYYY-MM-DD"),
    output_dir: Path = _cli.typer.Option(Path(".nutmeg-data/jczq"), "--output-dir"),
    taken_at: str = _cli.typer.Option(..., "--taken-at", help="ISO 时刻"),
) -> None:
    """决策本体 · 动词一:盘口快照 → Match+Snapshot 入库(replay)。"""
    from nutmeg.decision.verbs import run_sense
    _cli.typer.echo(run_sense(run_date, output_dir, taken_at))


@_cli.app.command("decision-read")
def decision_read() -> None:
    """决策本体 · 动词二:产 Read(Claude 运行时推理,M1 接入)。"""
    _cli.typer.echo("decision-read: M0 骨架 — Read 由 Claude 运行时产出并经 read_validate 校验")


@_cli.app.command("decision-express")
def decision_express() -> None:
    """决策本体 · 动词三:Reads → Ticket(M1 接入)。"""
    _cli.typer.echo("decision-express: M0 骨架 — 组合枚举/预算闸见 nutmeg.decision.express")


@_cli.app.command("decision-reconcile")
def decision_reconcile() -> None:
    """决策本体 · 动词四:赛果+收盘 → Settlement(M1 接入)。"""
    _cli.typer.echo("decision-reconcile: M0 骨架 — settle_read/settle_ticket_leg 见 reconcile")


@_cli.app.command("decision-calibrate")
def decision_calibrate() -> None:
    """决策本体 · 动词五:聚合 → FactorVerdict(M1 接入)。"""
    _cli.typer.echo("decision-calibrate: M0 骨架 — factor_verdict/enforce_active_cap 见 calibrate")
```

在 `nutmeg/interfaces/cli/__init__.py` 的命令模块 import 区（第 1131-1137 行附近，与 `jczq`/`operations` 并列）追加一行：

```python
from nutmeg.interfaces.cli import decision as decision  # noqa: E402
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_verbs.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/verbs.py nutmeg/interfaces/cli/__init__.py tests/decision/test_verbs.py
git commit -m "feat(decision): 五动词 CLI 骨架(sense 可 replay,余骨架)"
```

---

## Task 16: 端到端 replay 冒烟 + 全套回归

**Files:**
- Test: `tests/decision/test_e2e_smoke.py`

验证整链在真实已存快照上跑通（sense→read 校验→settle→calibrate），且不碰现系统。

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_e2e_smoke.py
"""M0 端到端冒烟:一场比赛走完 sense→(手造 Read)→校验→结算→因子判决。"""
import json
from nutmeg.decision.store import DecisionStore
from nutmeg.decision.sense import sense_from_snapshot
from nutmeg.decision.ontology import MarketSnapshot, Read
from nutmeg.decision.read_validate import validate_read
from nutmeg.decision.reconcile import settle_read
from nutmeg.decision.scoring import brier

_BOARD = {"matchInfoList": [{"businessDate": "2026-07-08", "subMatchList": [{
    "matchStatus": "Selling", "businessDate": "2026-07-08", "matchNumStr": "周日092",
    "leagueAbbName": "世界杯", "homeTeamAbbName": "墨西哥", "awayTeamAbbName": "英格兰",
    "had": {"h": "2.03", "d": "3.30", "a": "3.55"}, "hhad": {}, "ttg": {}, "crs": {}}]}]}


def test_full_chain_on_snapshot(tmp_path):
    daily = tmp_path / "daily" / "2026-07-08"
    daily.mkdir(parents=True)
    (daily / "sporttery_markets.json").write_text(json.dumps(_BOARD), encoding="utf-8")
    store = DecisionStore(tmp_path / "decision")

    # sense
    assert sense_from_snapshot("2026-07-08", output_dir=tmp_path,
                               taken_at="2026-07-08T15:00:00+08:00", store=store) == 1
    snap = store.load(MarketSnapshot)[0]
    prior = snap.fair["had"]

    # read(手造一个市场锚定+签位激励偏移的 Read,模拟 Claude 产出)
    belief = {"home": prior["home"] - 0.06,
              "draw": prior["draw"] + 0.06, "away": prior["away"]}
    read = Read(read_id="R-092", match_id=snap.match_id, snapshot_id=snap.id,
                made_at="2026-07-08T15:00:00+08:00", judge="claude", market="had",
                prior=prior, belief=belief,
                factors=[{"factor_id": "seeding_incentive", "direction": "draw",
                          "weight_pp": 6,
                          "evidence": [{"url": "x", "quote": "y", "at": "z"}]}],
                confidence=3, shadow=False)
    assert validate_read(read, allowed_factors={"seeding_incentive"}) == []
    store.upsert(read)

    # settle(赛果 draw)
    s = settle_read(read, outcome_90="draw", score="1-1", closing=None)
    store.upsert(s)
    assert s.brier == brier(belief, "draw")
    # belief 更看好 draw → 应优于 prior
    assert s.brier < brier(prior, "draw")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_e2e_smoke.py -q`
Expected: FAIL（若某链路模块签名不符会在此暴露）→ 修到 PASS

- [ ] **Step 3: 若失败则修（本任务无新实现，仅联调）**

各模块已在前序 Task 实现；此步只在联调暴露签名不一致时回改对应模块，重跑至 PASS。

- [ ] **Step 4: 全套回归 + ruff**

Run: `uv run ruff check nutmeg/decision tests/decision`
Expected: All checks passed

Run: `uv run pytest -q`
Expected: 全绿（现系统 1051 基线 + 新增 decision 测试；无回归）

- [ ] **Step 5: Commit**

```bash
git add tests/decision/test_e2e_smoke.py
git commit -m "test(decision): M0 端到端 replay 冒烟 + 全套回归绿"
```

---

## 自查（写完计划的 fresh-eyes 检查）

**Spec 覆盖：**
- §2 七对象 → Task 1-2 ✓；血缘 → Task 4 ✓
- §3 五动词 → sense(Task 14) + CLI 骨架(Task 15)；read 校验(Task 8)；express(Task 13)；reconcile(Task 10-11)；calibrate(Task 12) ✓
- §4 三方接口：sporttery replay(Task 14) ✓；live 抓取/okooo 收盘/API-Football/Telegram = **M1 编排**（M0 骨架不含 live，spec §9 M0 范围一致）
- §5 双轴计分 → scoring(Task 9) + reconcile(Task 10) + calibrate(Task 12) ✓
- §6 ¥400 预算 → express(Task 13) ✓
- 附录 A.1 迁基元 → market_data(Task 5) ✓；A.2 净化 → Task 6 ✓；A.3 处死 = M2 不在 M0
- §7 反积累(词典上限) → calibrate enforce_active_cap(Task 12) ✓
- 初始因子词典 → Task 7 ✓
- §10 测试策略 → 每 Task TDD + e2e(Task 16) ✓

**占位符扫描：** 无 TBD/TODO；每步含完整代码或确切命令。

**类型一致性：** `Read.factors` 为 `list[dict]`（Task 2）全程一致；`settle_ticket_leg` 关键字参数（Task 11）与测试一致；`FactorVerdict` 字段（Task 2）与 calibrate 产出（Task 12）一致；`snapshots_from_sporttery` 签名（Task 6）与 sense 调用（Task 14）一致。

**范围边界：** M0 = 确定性积木 + sense replay + 动词骨架；live 抓取/Claude read 产出/Telegram 推送/历史迁移属 M1（spec §9 明确），不在本计划。

---

## Execution Handoff

计划已保存到 `docs/superpowers/plans/2026-07-06-decision-ontology-m0.md`。两种执行方式：

1. **Subagent-Driven（推荐）** — 每 Task 派新 subagent，任务间两阶段审查，快迭代。
2. **Inline 执行** — 本 session 用 executing-plans，批量执行 + 检查点。

选哪种？
