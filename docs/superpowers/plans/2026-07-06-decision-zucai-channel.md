# 决策本体 · 传统足彩通道（信念层）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 把传统足彩（胜负彩/任九）的 14 场比赛纳入决策本体的**逐场信念层**——复用同一套 Read/CLV/Brier/因子，实现 spec §3「一个逐场信念层，两个表达通道」。用户定：**规范化比赛身份**（一场真实比赛一个 Match、channel_refs 挂两通道）+ **只建信念层**（express 票构造延 M1.5）。

**Architecture:** 传统足彩不是新系统——是同一信念层作用在不同比赛来源上。核心改造 = **规范化 match_id**（队名+日期，非竞彩号），让竞彩与 zucai 重叠的同一场真实比赛（如阿根廷vs埃及）只有一个 Match、校准不双计。竞彩 sense 改用 canonical id，zucai 新增 adapter 消费现有 `ZucaiSourceSyncService`/`ZucaiOddsSyncService`/`grade_report`，Read/reconcile/calibrate 全部复用。

**Tech Stack:** Python 3.12 / pytest / uv。复用：现有 `nutmeg/services/zucai*.py`（14场+1X2赔率+赛果）、`nutmeg/decision/*`（M0/M1 信念层）、`_fair_from_odds`（去水）。

**关键设计（canonical 身份，定死）：**
- **canonical_match_id(home, away, date)** = `M-<date>-<norm(home)>-<norm(away)>`，norm=去空格+casefold（中文名保留）。同一场真实比赛，两通道算出同一 id。
- **Match.channel_refs 合并**：sense 落 Match 前 load 现有、merge channel_refs（竞彩落 jczq_match_no，zucai 落 zucai:{issue,index}），upsert 不覆盖对方通道。
- **锚**：zucai 14 场 1X2 赔率去水 fair（`_fair_from_odds`），source="zucai"。CLV/收盘同竞彩（比赛可映射 API-Football，closing 复用）。
- **降级**：两通道队名拼写不一致 → 各自建 Match（同"先不管重叠"，但仅名不齐时），绝不崩。

**纪律（每 Task）：** TDD；`uv run pytest tests/decision/<file> -q`；只碰列出文件；改竞彩 sense 后**必须重跑 tests/decision/ 全绿 + 重 sense 今天数据验证**；缺数据=null 绝不伪造；pre-commit 须过。

**参考：** spec §2（Match channel_refs）§3（双通道）；M0/M1 计划同目录；现有 zucai：`nutmeg/domain/zucai.py`(ZucaiMatch)、`nutmeg/services/zucai_source.py`、`zucai_odds_source.py`、`zucai.py`(grade_report)。

---

## 文件结构

```
nutmeg/decision/
  identity.py       # 新建:canonical_match_id + norm_team(规范化比赛身份)
  market_data.py    # 改:snapshots_from_sporttery 用 canonical id;euro_snapshot 同
  sense.py          # 改:_match_for_snapshot 用 canonical + channel_refs 合并
  sense_zucai.py    # 新建:zucai 14场+赔率 → Match+Snapshot(canonical,合并refs)
  reconcile.py      # 改:settle_day 支持 zucai 赛果口径(或新 settle_zucai_day)
  verbs.py          # 加:run_sense_zucai / run_reconcile_zucai
  interfaces/cli/decision.py  # 加:decision-sense-zucai / decision-reconcile-zucai
tests/decision/
  test_identity.py test_zucai_sense.py test_zucai_reconcile.py
  test_canonical_migration.py test_zucai_e2e.py
```

---

## Task 1: canonical_match_id + norm_team（规范化比赛身份）

**Files:** Create `nutmeg/decision/identity.py`; Test `tests/decision/test_identity.py`

- [ ] **Step 1: 失败测试**

```python
# tests/decision/test_identity.py
from nutmeg.decision.identity import canonical_match_id, norm_team


def test_norm_team_strips_and_casefolds():
    assert norm_team(" 阿根廷 ") == "阿根廷"
    assert norm_team("Real Madrid") == "realmadrid"


def test_canonical_id_same_for_same_match_across_channels():
    # 竞彩 abbrev 与 zucai 名一致时,两通道算出同一 id
    a = canonical_match_id("阿根廷", "埃及", "2026-07-06")
    b = canonical_match_id(" 阿根廷 ", "埃及", "2026-07-06")
    assert a == b == "M-2026-07-06-阿根廷-埃及"


def test_canonical_id_distinct_matches():
    assert (canonical_match_id("葡萄牙", "西班牙", "2026-07-06")
            != canonical_match_id("阿根廷", "埃及", "2026-07-06"))
```

- [ ] **Step 2: 跑测确认失败**

Run: `uv run pytest tests/decision/test_identity.py -q` → FAIL `ModuleNotFoundError`

- [ ] **Step 3: 实现**

```python
# nutmeg/decision/identity.py
"""规范化比赛身份(spec §2 Match=跨通道身份)——一场真实比赛一个 canonical id,
竞彩号/zucai期号是 channel_refs。同一场两通道算出同一 id → 校准不双计。"""
from __future__ import annotations


def norm_team(name: str) -> str:
    """去空格 + casefold(中文名原样保留;拉丁名归一大小写)。"""
    return "".join((name or "").split()).casefold()


def canonical_match_id(home: str, away: str, date: str) -> str:
    """M-<date>-<norm(home)>-<norm(away)>。确定性、跨通道稳定。"""
    return f"M-{date}-{norm_team(home)}-{norm_team(away)}"
```

- [ ] **Step 4: 跑测通过** → `3 passed`
- [ ] **Step 5: Commit** `feat(decision): canonical_match_id 规范化比赛身份`

---

## Task 2: 竞彩 sense 改用 canonical id + channel_refs

**Files:** Modify `nutmeg/decision/market_data.py`, `nutmeg/decision/sense.py`; Test `tests/decision/test_canonical_migration.py`

现 `snapshots_from_sporttery` 用 `M-{run_date}-{match_no}`；改为 canonical(home,away,date)，match_no 进 Match.channel_refs。

- [ ] **Step 1: 失败测试**

```python
# tests/decision/test_canonical_migration.py
import json

from nutmeg.decision.ontology import Match, MarketSnapshot
from nutmeg.decision.sense import sense_day
from nutmeg.decision.store import DecisionStore

_BOARD = {"matchInfoList": [{"businessDate": "2026-07-06", "subMatchList": [{
    "matchStatus": "Selling", "businessDate": "2026-07-06", "matchNumStr": "周一093",
    "homeTeamAbbName": "葡萄牙", "awayTeamAbbName": "西班牙",
    "had": {"h": "4.00", "d": "3.35", "a": "1.72"}}]}]}


def test_jczq_sense_uses_canonical_id_and_channel_ref(tmp_path, monkeypatch):
    daily = tmp_path / "daily" / "2026-07-06"
    daily.mkdir(parents=True)
    (daily / "sporttery_markets.json").write_text(json.dumps(_BOARD), encoding="utf-8")
    import nutmeg.decision.sense as sm
    monkeypatch.setattr(sm, "_load_euro_bold_odds", lambda rd, od: {})
    store = DecisionStore(tmp_path / "decision")
    sense_day("2026-07-06", output_dir=tmp_path, taken_at="t", store=store)
    m = store.load(Match)[0]
    assert m.match_id == "M-2026-07-06-葡萄牙-西班牙"           # canonical
    assert m.channel_refs.get("jczq_match_no") == "周一093"     # 竞彩号进 ref
    s = store.load(MarketSnapshot)[0]
    assert s.match_id == "M-2026-07-06-葡萄牙-西班牙"           # snapshot 同 canonical
```

- [ ] **Step 2: 跑测确认失败**（现为 `M-2026-07-06-周一093`）

Run: `uv run pytest tests/decision/test_canonical_migration.py -q` → FAIL

- [ ] **Step 3: 实现**

先读 `nutmeg/decision/market_data.py` 的 `snapshots_from_sporttery` 与 `nutmeg/decision/sense.py` 的 `_match_for_snapshot`。改：

`snapshots_from_sporttery` 里 `match_id=f"M-{run_date}-{match_no}"` 两处 → 用 canonical：

```python
from nutmeg.decision.identity import canonical_match_id
# 在解析出 home/away 后(sporttery 是 homeTeamAbbName/awayTeamAbbName):
mid = canonical_match_id(home, away, run_date)
# snapshot 的 match_id 用 mid;snapshot_id 仍可含 match_no(唯一性够)
```

⚠️ `snapshots_from_sporttery` 当前可能未取 home/away 到局部（只在末尾 raw 里）。确保在建 MarketSnapshot 前从 `raw.get("homeTeamAbbName")`/`awayTeamAbbName` 取到，传给 canonical。**保留 match_no**（snapshot_id 用 + 传给 Match.channel_refs）。为把 match_no 带到 `_match_for_snapshot`，最简：`MarketSnapshot` 不加字段，改由 `_match_for_snapshot` 从 value 按 canonical 反查 match_no（见下）。

`sense.py` 的 `_match_for_snapshot(snapshot, value, run_date)`：现按 `snapshot.match_id.rsplit("-",1)[-1]` 取 match_no——canonical 后失效。改为：遍历 value 的 subMatchList，用 canonical(home,away,run_date)==snapshot.match_id 匹配，取该场 homeTeamAbbName/awayTeamAbbName/matchNumStr：

```python
def _match_for_snapshot(snapshot, value, run_date):
    from nutmeg.decision.identity import canonical_match_id
    from nutmeg.decision.ontology import Match
    home = away = match_no = ""
    for day in value.get("matchInfoList") or []:
        for raw in day.get("subMatchList") or []:
            h = str(raw.get("homeTeamAbbName") or "")
            a = str(raw.get("awayTeamAbbName") or "")
            if canonical_match_id(h, a, run_date) == snapshot.match_id:
                home, away = h, a
                match_no = str(raw.get("matchNumStr") or "")
    return Match(match_id=snapshot.match_id, kickoff_at=snapshot.taken_at,
                 home=home, away=away, competition="",
                 channel_refs={"jczq_match_no": match_no})
```

`euro_snapshot_from_bold_odds`（Task M1）也用 `f"M-{run_date}-{match_no}"`——但欧赔快照的 match_no 是竞彩号，队名不在 bold_odds 里。**处理**：欧赔快照的 match_id 需与体彩快照 canonical 对齐。最简：sense_day 里先建体彩快照（有队名→canonical），再把欧赔快照按**竞彩号→canonical**映射（用体彩快照建的 {match_no: canonical} 表）。改 `sense_day`：

```python
# 体彩快照建 canonical + 竞彩号映射
no_to_canonical = {}
for day in value.get("matchInfoList") or []:
    for raw in day.get("subMatchList") or []:
        h=str(raw.get("homeTeamAbbName") or ""); a=str(raw.get("awayTeamAbbName") or "")
        no_to_canonical[str(raw.get("matchNumStr") or "")] = canonical_match_id(h,a,run_date)
# 欧赔快照:euro_snapshot_from_bold_odds 仍产竞彩号 match_id,sense_day 里改写为 canonical
for s in euro_snapshot_from_bold_odds(bold, run_date=run_date, taken_at=taken_at, kind="read_time", source="apifootball"):
    no = s.match_id.rsplit("-",1)[-1]
    canonical = no_to_canonical.get(no)
    if canonical and canonical in today_match_ids_canonical:
        store.upsert(replace(s, match_id=canonical))
```

（`today_match_ids_canonical` = 体彩快照的 canonical 集。用 `dataclasses.replace` 改 match_id。）

- [ ] **Step 4: 跑测通过** + 全 decision 回归

Run: `uv run pytest tests/decision/ -q` → 全 passed（M0/M1 测试中 hard-code `M-2026-07-08-周日092` 的断言会**失败**——这些需同步改为 canonical。逐个改：凡断言 `match_id` 含竞彩号的，改成对应 canonical，如 `M-2026-07-08-墨-英`。**这是预期的迁移工作，不是 bug**。）

- [ ] **Step 5: Commit** `feat(decision): 竞彩 sense 改用 canonical 身份 + channel_refs`

---

## Task 3: Match channel_refs 合并（两通道 sense 同一场不覆盖）

**Files:** Modify `nutmeg/decision/sense.py`（+ 新 helper）; Test `tests/decision/test_canonical_migration.py`

- [ ] **Step 1: 失败测试（追加）**

```python
from nutmeg.decision.sense import upsert_match_merged


def test_channel_refs_merge_across_channels(tmp_path):
    store = DecisionStore(tmp_path / "decision")
    mid = "M-2026-07-06-阿根廷-埃及"
    # 竞彩先落
    upsert_match_merged(store, Match(match_id=mid, kickoff_at="t", home="阿根廷",
                                     away="埃及", channel_refs={"jczq_match_no": "周二095"}))
    # zucai 后落同一场
    upsert_match_merged(store, Match(match_id=mid, kickoff_at="t", home="阿根廷",
                                     away="埃及", channel_refs={"zucai": {"issue": "26091", "index": 3}}))
    m = store.get(Match, mid)
    assert m.channel_refs.get("jczq_match_no") == "周二095"       # 竞彩 ref 未丢
    assert m.channel_refs.get("zucai") == {"issue": "26091", "index": 3}  # zucai ref 已加
```

- [ ] **Step 2: 跑测确认失败** → `ImportError: upsert_match_merged`

- [ ] **Step 3: 实现（sense.py 追加，两处 sense 落 Match 都改用它）**

```python
def upsert_match_merged(store, match) -> None:
    """落 Match 前合并 channel_refs——同一 canonical 比赛被第二通道 sense 时,
    不覆盖对方通道号(spec §2 一场多通道)。"""
    from nutmeg.decision.ontology import Match
    existing = store.get(Match, match.match_id)
    if existing is not None:
        merged = {**existing.channel_refs, **match.channel_refs}
        from dataclasses import replace
        match = replace(match, channel_refs=merged)
    store.upsert(match)
```

`sense_day` 里 `store.upsert(_match_for_snapshot(...))` → 改 `upsert_match_merged(store, _match_for_snapshot(...))`。

- [ ] **Step 4: 跑测通过** + decision 回归
- [ ] **Step 5: Commit** `feat(decision): Match channel_refs 跨通道合并`

---

## Task 4: zucai 比赛/赔率 → Snapshot（adapter 纯函数）

**Files:** Create `nutmeg/decision/sense_zucai.py`; Test `tests/decision/test_zucai_sense.py`

先 Read `nutmeg/domain/zucai.py`（ZucaiMatch: match_no/home_team/away_team）确认字段。

- [ ] **Step 1: 失败测试**

```python
# tests/decision/test_zucai_sense.py
from nutmeg.decision.ontology import MarketSnapshot
from nutmeg.decision.sense_zucai import zucai_snapshots


class _ZM:
    def __init__(self, no, h, a):
        self.match_no = no
        self.home_team = h
        self.away_team = a


def test_zucai_snapshots_canonical_and_fair():
    matches = [_ZM(3, "阿根廷", "埃及")]
    odds = {3: {"home": 1.30, "draw": 4.50, "away": 9.00}}    # 1X2 赔率
    snaps = zucai_snapshots(matches, odds, issue="26091", match_date="2026-07-06",
                            taken_at="2026-07-06T15:00:00+08:00")
    assert len(snaps) == 1
    s = snaps[0]
    assert isinstance(s, MarketSnapshot)
    assert s.match_id == "M-2026-07-06-阿根廷-埃及"            # canonical(与竞彩对齐)
    assert s.source == "zucai"
    assert abs(sum(s.fair["had"].values()) - 1.0) < 1e-6      # 去水
    assert s.fair["had"]["home"] > s.fair["had"]["away"]      # 短赔=高概率


def test_zucai_snapshots_skip_missing_odds():
    assert zucai_snapshots([_ZM(1, "A", "B")], {}, issue="26091",
                           match_date="2026-07-06", taken_at="t") == []
```

- [ ] **Step 2: 跑测确认失败** → `ModuleNotFoundError`

- [ ] **Step 3: 实现**

```python
# nutmeg/decision/sense_zucai.py
"""传统足彩 adapter:zucai 14场 + 1X2赔率 → MarketSnapshot(canonical 身份,去水 fair)。
复用同一信念层,不重造。express 票构造属 M1.5,本模块只到信念快照。"""
from __future__ import annotations

from nutmeg.decision.identity import canonical_match_id
from nutmeg.decision.market_data import fair_1x2


def zucai_snapshots(matches, odds: dict, *, issue: str, match_date: str,
                    taken_at: str) -> list:
    """matches: ZucaiMatch 列表(match_no/home_team/away_team);
    odds: {match_no: {home,draw,away}}。→ MarketSnapshot(source=zucai,canonical)。
    某场无 1X2 赔率 → 跳过(不伪造 fair)。"""
    from nutmeg.decision.ontology import MarketSnapshot

    snaps: list = []
    for m in matches:
        row = odds.get(m.match_no)
        if not row or not all(row.get(k) for k in ("home", "draw", "away")):
            continue
        fair = fair_1x2({"home": row["home"], "draw": row["draw"], "away": row["away"]})
        if not fair:
            continue
        mid = canonical_match_id(m.home_team, m.away_team, match_date)
        snaps.append(MarketSnapshot(
            snapshot_id=f"S-read_time-zucai-{issue}-{m.match_no}-{taken_at}",
            match_id=mid, taken_at=taken_at, kind="read_time", source="zucai",
            fair={"had": fair}, raw_odds={"had": dict(row)}, lines={},
        ))
    return snaps
```

- [ ] **Step 4: 跑测通过** → `2 passed`
- [ ] **Step 5: Commit** `feat(decision): zucai_snapshots adapter(14场→canonical 信念快照)`

---

## Task 5: sense_zucai 编排（消费现有 zucai sync + 入库）

**Files:** Modify `nutmeg/decision/sense_zucai.py`; Test `tests/decision/test_zucai_sense.py`

先 Read `nutmeg/services/zucai_source.py`(ZucaiSourceSyncService) 与 `zucai_odds_source.py` 确认如何取 14 场 + 赔率（从已存的 `<issue>.json`/`<issue>-odds.json` 读，replay 不打网）。

- [ ] **Step 1: 失败测试（注入 loader，不打网）**

```python
def test_sense_zucai_persists_matches_and_snapshots(tmp_path):
    from nutmeg.decision.ontology import Match, MarketSnapshot
    from nutmeg.decision.sense_zucai import sense_zucai
    from nutmeg.decision.store import DecisionStore

    store = DecisionStore(tmp_path / "decision")

    def _loader(issue, output_dir):
        return (
            [_ZM(3, "阿根廷", "埃及"), _ZM(4, "瑞士", "哥伦比亚")],
            {3: {"home": 1.30, "draw": 4.50, "away": 9.00},
             4: {"home": 2.10, "draw": 3.20, "away": 3.60}},
            "2026-07-06",
        )
    n = sense_zucai("26091", output_dir=tmp_path, taken_at="t", store=store,
                    loader=_loader)
    assert n == 2
    assert len(store.load(MarketSnapshot)) == 2
    m = [x for x in store.load(Match) if x.home == "阿根廷"][0]
    assert m.channel_refs.get("zucai") == {"issue": "26091", "index": 3}
```

- [ ] **Step 2: 跑测确认失败** → `ImportError: sense_zucai`

- [ ] **Step 3: 实现（追加）**

```python
def _default_loader(issue: str, output_dir):
    """从已存 zucai 快照读 (matches, odds, match_date)。replay 优先,不打网。
    真源:ZucaiSourceSyncService 出的 <issue>.json + ZucaiOddsSyncService 的
    <issue>-odds.json。实现时按其落盘结构解析(执行者 Read 两个 service 确认)。"""
    raise NotImplementedError("wire to zucai_source/zucai_odds_source 已存快照")


def sense_zucai(issue: str, *, output_dir, taken_at: str, store, loader=None) -> int:
    """一期传统足彩 14 场 → Match(canonical,merge refs)+Snapshot 入库。返回入库场数。"""
    from nutmeg.decision.identity import canonical_match_id
    from nutmeg.decision.ontology import Match
    from nutmeg.decision.sense import upsert_match_merged

    loader = loader or _default_loader
    matches, odds, match_date = loader(issue, output_dir)
    snaps = zucai_snapshots(matches, odds, issue=issue, match_date=match_date,
                            taken_at=taken_at)
    canonical_to_no = {canonical_match_id(m.home_team, m.away_team, match_date): m.match_no
                       for m in matches}
    for s in snaps:
        no = canonical_to_no.get(s.match_id)
        by_no = {m.match_no: m for m in matches}
        m = by_no.get(no)
        upsert_match_merged(store, Match(
            match_id=s.match_id, kickoff_at=taken_at, home=m.home_team,
            away=m.away_team, competition="",
            channel_refs={"zucai": {"issue": issue, "index": no}}))
        store.upsert(s)
    return len(snaps)
```

> 执行者：`_default_loader` 需 Read `zucai_source.py`/`zucai_odds_source.py` 落盘结构后实现（从 `.nutmeg-data/zucai/<issue>.json` + `<issue>-odds.json` 解析出 ZucaiMatch 列表 + {match_no:{home,draw,away}} + 开奖/比赛日期）。测试用注入 loader 不依赖它。

- [ ] **Step 4: 跑测通过** → `3 passed`
- [ ] **Step 5: Commit** `feat(decision): sense_zucai 编排(消费 zucai sync 入库)`

---

## Task 6: reconcile 支持 zucai 赛果 + CLI 接线

**Files:** Modify `nutmeg/decision/reconcile.py`, `verbs.py`, `interfaces/cli/decision.py`; Test `tests/decision/test_zucai_reconcile.py`

zucai 赛果是 14 场 1X2（胜/平/负）。`settle_day` 现按竞彩号取赛果；zucai 的 Read match_id 是 canonical，赛果需按 canonical 对。最简：`settle_day` 已遍历 Read + 用 `results` dict——只要传入的 results 键与 match_no 提取逻辑对齐即可。zucai 复用同 settle_read（Brier+CLV 与竞彩同）。

- [ ] **Step 1: 失败测试**

```python
# tests/decision/test_zucai_reconcile.py
from nutmeg.decision.ontology import MarketSnapshot, Read, Settlement
from nutmeg.decision.reconcile import settle_reads_for_matches
from nutmeg.decision.store import DecisionStore


def test_settle_reads_by_match_id_with_1x2_result(tmp_path):
    s = DecisionStore(tmp_path)
    mid = "M-2026-07-06-阿根廷-埃及"
    s.upsert(Read(read_id="R-z1", match_id=mid, snapshot_id="S", made_at="t",
                  judge="claude", market="had",
                  prior={"home": 0.7, "draw": 0.2, "away": 0.1},
                  belief={"home": 0.75, "draw": 0.18, "away": 0.07}))
    # 结果按 canonical match_id → outcome
    n = settle_reads_for_matches(s, outcomes={mid: ("home", "2-0")},
                                 settled_at="t2")
    assert n == 1
    st = s.settlement_for("read", "R-z1")
    assert st.outcome_90 == "home" and st.brier is not None
```

- [ ] **Step 2: 跑测确认失败** → `ImportError`

- [ ] **Step 3: 实现（reconcile.py 追加通用版；settle_day 可复用它）**

```python
def settle_reads_for_matches(store, *, outcomes: dict, settled_at: str) -> int:
    """通用结算:outcomes={match_id: (outcome_90, score)}。对每个有结果的 Read 产
    Settlement(Brier+CLV,复用 settle_read + 收盘快照)。canonical 身份→竞彩/zucai 通用。"""
    from dataclasses import replace

    from nutmeg.decision.ontology import MarketSnapshot, Read, Settlement  # noqa: F401
    closing = {s.match_id: s for s in store.load(MarketSnapshot) if s.kind == "closing"}
    n = 0
    for read in store.load(Read):
        oc = outcomes.get(read.match_id)
        outcome, score = (oc if oc else (None, None))
        s = settle_read(read, outcome_90=outcome, score=score,
                        closing=closing.get(read.match_id))
        s = replace(s, settlement_id=f"SET-read-{read.read_id}", settled_at=settled_at)
        store.upsert(s)
        n += 1
    return n
```

CLI（decision.py 追加 `decision-sense-zucai` + `decision-reconcile-zucai`，仿现有命令；verbs.py 加 `run_sense_zucai`/`run_reconcile_zucai` 消费 zucai grade_report 出 outcomes）。执行者 Read `zucai.py:grade_report` 取赛果口径。

- [ ] **Step 4: 跑测通过 + test_cli 回归**
- [ ] **Step 5: Commit** `feat(decision): reconcile 通用结算 + zucai CLI 接线`

---

## Task 7: 端到端 + 全套回归

**Files:** Test `tests/decision/test_zucai_e2e.py`

- [ ] **Step 1: e2e 测试** — sense_zucai(注入)→ 手造 Read → settle_reads_for_matches → run_calibrate；断言 zucai 场的 Read 进了同一因子校准（与竞彩场混在一起，canonical 无重复）。
- [ ] **Step 2-3: 跑通（联调回改）**
- [ ] **Step 4: 收尾门** `uv run ruff check nutmeg/decision tests/decision` + `uv run pytest -q`（全绿，含 M0/M1 迁移后的 canonical 断言）
- [ ] **Step 5: Commit** `test(decision): 传统足彩通道 e2e + 全套回归绿`

---

## 自查

**Spec 覆盖**：§3 双通道信念层 → Task 4-6（zucai 复用同 Read/CLV/Brier）✓；§2 Match 跨通道身份 → Task 1-3（canonical + channel_refs 合并）✓。express 票构造（14场/选9 + 奖池 P&L）= M1.5，不在本计划（用户定信念层）。

**类型一致性**：`canonical_match_id`(Task 1) 全程一致；`zucai_snapshots`→`sense_zucai`(Task 4-5)；`settle_reads_for_matches`(Task 6) 竞彩/zucai 通用；`upsert_match_merged`(Task 3) 两通道共用。

**迁移风险明示**：Task 2 改 canonical 会让 M0/M1 中 hard-code 竞彩号的 match_id 断言失败——**这是预期迁移**，逐个改为 canonical（非 bug）；改后必须 tests/decision/ 全绿 + 重 sense 今天真实数据核对（4 场 canonical id + channel_refs）。

**范围边界**：只建信念层。老 zucai 系统仍出票（影子并行）。express/奖池 P&L/launchd = M1.5/M2。

---

## Execution Handoff

计划存 `docs/superpowers/plans/2026-07-06-decision-zucai-channel.md`。Subagent-Driven（同 M0/M1，每 Task 派新 subagent + 审查）。开始执行？
