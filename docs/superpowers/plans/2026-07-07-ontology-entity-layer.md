# 决策本体实体层（Tier 1 + Tier 2）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给决策本体补实体层——`Factor.scope`（因子海拔）+ Read 引用带 `scope_key` + sense 策展式 resolve 出稳定 `*_id` + Team/League 持久对象与联赛画像迁移，并修掉 sense 两处 `competition` 丢失。

**Architecture:** 全部是**数据结构与数据**的增补，零判断代码（§7 反积累宪法自检见提案 §P4）。生死判决留 factor 级不变；scope_key 级只出**诊断性子判决**（复合 id `factor_id@scope_key`）。resolve 策展式：别名表命中填 id，未命中 `null`+log，**绝不自动造对象、绝不模糊匹配**。所有 schema 演进靠 `_from_dict` 的容忍性向后兼容（旧 JSONL 行加载自动落默认值）。

**Tech Stack:** Python 3.12 / frozen dataclass + JSONL store（现有模式）/ pytest / uv。无新依赖。

**Spec:** `docs/superpowers/specs/2026-07-07-ontology-entity-layer-proposal.md`（含 2026-07-07 复核修正）。

**用户已拍板：** Tier 1 + Tier 2 现在做；Tier 3（Appearance）**不建**；提案 §P2 的 `Match.joint` 槽与 `Factor.scope_key` 字段**均不做**（配对知识走 Read.factors 的 scope=pairing 引用表达，scope_key 属于引用不属于词典项——YAGNI）。

**不可破坏约束：**
- live 系统 decision-am/close/settle（launchd 08:00/19:00/08:10）不得中断——所有改动向后兼容，新字段全带默认值。
- 旧 `.nutmeg-data/jczq/decision/factors.jsonl` 的行无 scope 字段 → `from_dict` 默认 `match`，对 `league_bias` 是**错的**——Task 9 的 `sync_factor_scopes`（幂等，挂进 calibrate 动词）负责纠正。
- 测试基线 1051 passed / ruff 全绿 / pre-commit 已装。每个 Task 收尾 `uv run pytest -q tests/decision/` 必须全绿再 commit。

**分支：** 直接在当前分支 `research/tunisia-japan-2026-06-20`（M2 落地分支，工作树干净）工作。

---

## File Structure（先锁边界）

| 文件 | 动作 | 职责 |
|---|---|---|
| `nutmeg/decision/ontology.py` | Modify | `Factor` +`scope`；`Match` +`home_team_id/away_team_id/competition_id`；新增 `Team`/`League` dataclass |
| `nutmeg/data/decision_factors_seed.json` | Modify | 六因子补 `scope` |
| `nutmeg/decision/factors.py` | Modify | +`factor_scopes()`、`sync_factor_scopes()` |
| `nutmeg/decision/store.py` | Modify | `_FILENAMES` +Team/League |
| `nutmeg/data/decision_entities_seed.json` | Create | 策展 Team/League 种子（memory 联赛画像迁入，Tier 2） |
| `nutmeg/decision/entities.py` | Create | slugify / 别名表加载（复用国家队表+实体种子）/ resolve / seed_entities_if_empty |
| `nutmeg/decision/sense.py` | Modify | `_match_for_snapshot` 补 competition+resolve；`upsert_match_merged` 不 clobber 已解析 id |
| `nutmeg/decision/sense_zucai.py` | Modify | 同上（zucai 路径） |
| `nutmeg/decision/read_validate.py` | Modify | team/league scope 因子引用必带 `scope_key` |
| `nutmeg/decision/read_ingest.py` | Modify | 传 factor_scopes 给校验 |
| `nutmeg/decision/calibrate.py` | Modify | scope_key 诊断性子判决 + `apply_verdicts` 守卫 |
| `nutmeg/decision/verbs.py` | Modify | `run_sense` 挂 seed_entities；`run_calibrate_panel` 挂 sync_factor_scopes |
| `tests/decision/test_entities.py` | Create | 实体解析全套 |
| `tests/decision/{test_factors,test_ontology,test_store,test_sense,test_zucai_sense,test_read_validate,test_read_ingest,test_calibrate,test_verbs}.py` | Modify | 各 Task 的 TDD 测试 |

**别名表设计（DRY，不新建第三个文件）**：team 别名 = `jczq_national_team_aliases.json`（中文→API-Football 英文，id=slugify(英文)）⊕ `decision_entities_seed.json` 里 Team 的 `aliases+name_zh+name_en`；league 别名 = 种子 League 的 `name_zh+name_en`。归一化复用 `identity.norm_team`。

---

### Task 1: Factor.scope（词典项的海拔）

**Files:**
- Modify: `nutmeg/decision/ontology.py:91-110`（Factor）
- Modify: `nutmeg/data/decision_factors_seed.json`
- Modify: `nutmeg/decision/factors.py`
- Test: `tests/decision/test_factors.py`

- [x] **Step 1: Write the failing tests**

在 `tests/decision/test_factors.py` 末尾追加：

```python
def test_seed_factors_carry_scope():
    """种子词典的隐性多尺度显式化(提案 §P0 漏点2)。"""
    scopes = {f.factor_id: f.scope for f in load_seed_factors()}
    assert scopes == {
        "seeding_incentive": "pairing",
        "bunker_profile": "pairing",
        "lineup_news_gap": "appearance",
        "league_bias": "league",
        "market_line_error": "match",
        "fatigue_discount": "appearance",
    }


def test_factor_scope_defaults_to_match_for_legacy_rows():
    """旧 factors.jsonl 行无 scope → 加载默认 match(向后兼容,不炸 live store)。"""
    from nutmeg.decision.ontology import Factor
    f = Factor.from_dict({"factor_id": "x", "name_zh": "X", "definition": "d",
                          "born_at": "2026-07-07", "born_from": "test"})
    assert f.scope == "match"


def test_factor_scopes_map():
    from nutmeg.decision.factors import factor_scopes
    assert factor_scopes(load_seed_factors())["league_bias"] == "league"
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/decision/test_factors.py -v`
Expected: 3 FAIL（`AttributeError: scope` / `ImportError: factor_scopes` / seed 无 scope 键）

- [x] **Step 3: Implement**

`nutmeg/decision/ontology.py` — `Factor` 追加字段（放在 `retire_reason` 之后，带默认值，不破坏位置参构造）：

```python
@dataclass(frozen=True, slots=True)
class Factor:
    factor_id: str
    name_zh: str
    definition: str
    born_at: str
    born_from: str
    status: str = "probation"           # probation | active | retired
    retire_reason: str = ""
    scope: str = "match"                # match|pairing|appearance|team|league(提案§P2 因子海拔)
```

`nutmeg/data/decision_factors_seed.json` — 每因子补 `"scope"` 键（完整新内容）：

```json
[
  {"factor_id": "seeding_incentive", "name_zh": "签位激励", "scope": "pairing",
   "definition": "MD3/淘汰赛前高名次碰强签→赢反而更糟,平/小负成双方最优",
   "born_at": "2026-06-27", "born_from": "071 阿vs奥 实证,信心4"},
  {"factor_id": "bunker_profile", "name_zh": "铁桶压缩净胜", "scope": "pairing",
   "definition": "强弱悬殊+弱队铁桶画像→净胜被压缩,让球档需重算3路",
   "born_at": "2026-07-03", "born_from": "087 让球双选对冲实证"},
  {"factor_id": "lineup_news_gap", "name_zh": "阵容情报时间差", "scope": "appearance",
   "definition": "实名伤停/轮换与市场定价存在时间差=可用信息",
   "born_at": "2026-07-04", "born_from": "拉赫蒂回血2主力 fade 唯一命中"},
  {"factor_id": "league_bias", "name_zh": "极端联赛画像", "scope": "league",
   "definition": "极端主客分裂/xG背离联赛禁用通用主场加成",
   "born_at": "2026-07-05", "born_from": "瑞超联赛画像 allsvenskan-2026"},
  {"factor_id": "market_line_error", "name_zh": "3路口径错觉", "scope": "match",
   "definition": "体彩让球是3路非亚盘,整数盘热门胜1球落让平档,亚盘直觉高估~28pp",
   "born_at": "2026-07-06", "born_from": "hhad-3way-vs-asian-handicap 教训"},
  {"factor_id": "fatigue_discount", "name_zh": "疲劳折扣(反向登记)", "scope": "appearance",
   "definition": "疲劳≠变弱只推迟破门,破门后崩的是追赶方;试用其否定式",
   "born_at": "2026-07-04", "born_from": "7/04 摩洛哥120min后0:3血洗 证伪方向"}
]
```

`nutmeg/decision/factors.py` — 追加（`allowed_factor_ids` 之后）：

```python
def factor_scopes(factors: list[Factor]) -> dict[str, str]:
    """{factor_id: scope} — read 校验用(team/league scope 引用必带 scope_key)。"""
    return {f.factor_id: f.scope for f in factors}
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/decision/test_factors.py -v`
Expected: 全 PASS

- [x] **Step 5: Run decision suite + commit**

```bash
uv run pytest -q tests/decision/
git add nutmeg/decision/ontology.py nutmeg/data/decision_factors_seed.json \
        nutmeg/decision/factors.py tests/decision/test_factors.py
git commit -m "feat(decision): Factor.scope 因子海拔字段 + 种子词典显式多尺度(实体层 Task 1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XfSkXib7b5rf4aocCqbG8M"
```

---

### Task 2: Match 实体引用字段 + merge 不 clobber

**Files:**
- Modify: `nutmeg/decision/ontology.py:18-36`（Match）
- Modify: `nutmeg/decision/sense.py:48-57`（upsert_match_merged）
- Test: `tests/decision/test_ontology.py`, `tests/decision/test_sense.py`

- [x] **Step 1: Write the failing tests**

`tests/decision/test_ontology.py` 末尾追加：

```python
def test_match_entity_refs_roundtrip_and_legacy_default():
    from nutmeg.decision.ontology import Match
    m = Match(match_id="M-x", kickoff_at="t", home="哈马比", away="卡尔马",
              competition="瑞超", home_team_id="swe-hammarby",
              away_team_id="swe-kalmar", competition_id="swe-allsvenskan")
    m2 = Match.from_dict(m.to_dict())
    assert (m2.home_team_id, m2.away_team_id, m2.competition_id) == (
        "swe-hammarby", "swe-kalmar", "swe-allsvenskan")
    # 旧 matches.jsonl 行(无新字段)→ None 默认,不炸
    legacy = Match.from_dict({"match_id": "M-y", "kickoff_at": "t",
                              "home": "a", "away": "b"})
    assert legacy.home_team_id is None and legacy.competition_id is None
```

`tests/decision/test_sense.py` 末尾追加：

```python
def test_upsert_match_merged_preserves_resolved_ids_and_competition(tmp_path):
    """第二通道(zucai)的未解析 Match 不得抹掉第一通道已解析的 id/联赛名。"""
    from nutmeg.decision.ontology import Match
    from nutmeg.decision.sense import upsert_match_merged
    from nutmeg.decision.store import DecisionStore
    store = DecisionStore(tmp_path)
    upsert_match_merged(store, Match(
        match_id="M-1", kickoff_at="t", home="h", away="a", competition="瑞超",
        home_team_id="swe-hammarby", away_team_id="swe-kalmar",
        competition_id="swe-allsvenskan",
        channel_refs={"jczq_match_no": "周三001"}))
    upsert_match_merged(store, Match(
        match_id="M-1", kickoff_at="t", home="h", away="a", competition="",
        channel_refs={"zucai": {"issue": "26100", "index": 3}}))
    merged = store.get(Match, "M-1")
    assert merged.competition == "瑞超"
    assert merged.home_team_id == "swe-hammarby"
    assert merged.competition_id == "swe-allsvenskan"
    assert merged.channel_refs["jczq_match_no"] == "周三001"
    assert merged.channel_refs["zucai"]["issue"] == "26100"
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/decision/test_ontology.py tests/decision/test_sense.py -v`
Expected: 2 FAIL（`Match` 无 `home_team_id`）

- [x] **Step 3: Implement**

`nutmeg/decision/ontology.py` — `Match` 在 `channel_refs` 之后追加三个可空引用（位置参兼容）：

```python
@dataclass(frozen=True, slots=True)
class Match:
    match_id: str
    kickoff_at: str
    home: str
    away: str
    competition: str = ""
    channel_refs: dict[str, Any] = field(default_factory=dict)
    home_team_id: str | None = None      # 策展 resolve 命中才填;未命中 None 绝不伪造
    away_team_id: str | None = None
    competition_id: str | None = None
```

`nutmeg/decision/sense.py` — `upsert_match_merged` 改为（merge 语义扩展到实体引用与联赛名）：

```python
def upsert_match_merged(store, match) -> None:
    """落 Match 前合并 channel_refs——同一 canonical 比赛被第二通道 sense 时,
    不覆盖对方通道号(spec §2 一场多通道);已解析的实体 id/联赛名同理不被
    未解析通道的空值 clobber(实体层提案 §P3)。"""
    from dataclasses import replace

    existing = store.get(Match, match.match_id)
    if existing is not None:
        match = replace(
            match,
            channel_refs={**existing.channel_refs, **match.channel_refs},
            competition=match.competition or existing.competition,
            home_team_id=match.home_team_id or existing.home_team_id,
            away_team_id=match.away_team_id or existing.away_team_id,
            competition_id=match.competition_id or existing.competition_id,
        )
    store.upsert(match)
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/decision/test_ontology.py tests/decision/test_sense.py -v`
Expected: 全 PASS

- [x] **Step 5: Run decision suite + commit**

```bash
uv run pytest -q tests/decision/
git add nutmeg/decision/ontology.py nutmeg/decision/sense.py \
        tests/decision/test_ontology.py tests/decision/test_sense.py
git commit -m "feat(decision): Match 实体引用字段 + merge 不 clobber 已解析 id(实体层 Task 2)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XfSkXib7b5rf4aocCqbG8M"
```

---

### Task 3: Team/League 持久对象 + store 文件名

**Files:**
- Modify: `nutmeg/decision/ontology.py`（文件末尾追加两类）
- Modify: `nutmeg/decision/store.py:14-22`（_FILENAMES）
- Test: `tests/decision/test_store.py`

- [x] **Step 1: Write the failing test**

`tests/decision/test_store.py` 末尾追加：

```python
def test_team_league_objects_roundtrip_via_store(tmp_path):
    from nutmeg.decision.ontology import League, Team
    from nutmeg.decision.store import DecisionStore
    store = DecisionStore(tmp_path)
    store.upsert(Team(
        team_id="swe-hammarby", name_zh="哈马比", name_en="Hammarby",
        aliases=["Hammarby IF"], competition_ids=["swe-allsvenskan"],
        profile_notes=[{"key": "home_fortress", "note": "主场20-5",
                        "evidence": "memory allsvenskan-2026-league-profile",
                        "at": "2026-07-07"}]))
    store.upsert(League(league_id="swe-allsvenskan", name_zh="瑞超",
                        name_en="Allsvenskan", country="Sweden", season="2026"))
    t = store.get(Team, "swe-hammarby")
    assert t.profile_notes[0]["key"] == "home_fortress"
    assert store.get(League, "swe-allsvenskan").name_zh == "瑞超"
    assert (tmp_path / "teams.jsonl").exists()
    assert (tmp_path / "leagues.jsonl").exists()
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_store.py -v`
Expected: FAIL（`ImportError: Team`）

- [x] **Step 3: Implement**

`nutmeg/decision/ontology.py` — 文件末尾追加（模块 docstring 首行的"七对象"改为"九对象（2026-07-07 实体层增补 Team/League）"）：

```python
@dataclass(frozen=True, slots=True)
class Team:
    """持久实体节点——信念输入与跨场学习的沉淀处(实体层提案 §P2)。
    只为"我们对它有知识"的实体而生:策展式创建,绝不由 sense 自动造。"""
    team_id: str
    name_zh: str = ""
    name_en: str = ""
    aliases: list[str] = field(default_factory=list)
    competition_ids: list[str] = field(default_factory=list)
    profile_notes: list[dict] = field(default_factory=list)  # {key,note,evidence,at}

    @property
    def id(self) -> str:
        return self.team_id

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "Team":
        return _from_dict(cls, payload)


@dataclass(frozen=True, slots=True)
class League:
    """持久实体节点——联赛级结构偏差(league scope 因子)的沉淀处。"""
    league_id: str
    name_zh: str = ""
    name_en: str = ""
    country: str = ""
    season: str = ""
    profile_notes: list[dict] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.league_id

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "League":
        return _from_dict(cls, payload)
```

`nutmeg/decision/store.py` — `_FILENAMES` 追加两行：

```python
_FILENAMES = {
    "Match": "matches.jsonl",
    "MarketSnapshot": "snapshots.jsonl",
    "Read": "reads.jsonl",
    "Factor": "factors.jsonl",
    "Ticket": "tickets.jsonl",
    "Settlement": "settlements.jsonl",
    "FactorVerdict": "verdicts.jsonl",
    "Team": "teams.jsonl",
    "League": "leagues.jsonl",
}
```

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_store.py -v`
Expected: 全 PASS

- [x] **Step 5: Run decision suite + commit**

```bash
uv run pytest -q tests/decision/
git add nutmeg/decision/ontology.py nutmeg/decision/store.py tests/decision/test_store.py
git commit -m "feat(decision): Team/League 持久实体对象 + store 文件名(实体层 Task 3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XfSkXib7b5rf4aocCqbG8M"
```

---

### Task 4: 实体种子（Tier 2 画像迁移）+ 策展式 resolve

**Files:**
- Create: `nutmeg/data/decision_entities_seed.json`
- Create: `nutmeg/decision/entities.py`
- Test: `tests/decision/test_entities.py`（新建）

- [x] **Step 1: Write the failing tests**

新建 `tests/decision/test_entities.py`：

```python
# tests/decision/test_entities.py
from nutmeg.decision.entities import (
    load_league_alias_table,
    load_seed_entities,
    load_team_alias_table,
    resolve_league,
    resolve_team,
    seed_entities_if_empty,
    slugify,
)
from nutmeg.decision.identity import norm_team


def test_slugify_stable_and_unicode_safe():
    assert slugify("Bosnia & Herzegovina") == "bosnia-herzegovina"
    assert slugify("Türkiye") == "türkiye"          # 重音保留(与 API-Football 拼写对齐)
    assert slugify("USA") == "usa"
    assert slugify("South Korea") == "south-korea"


def test_national_aliases_fold_into_team_table():
    """复用 jczq_national_team_aliases.json:中文/英文都解析到 slug(英文)。"""
    table = load_team_alias_table()
    assert table[norm_team("荷兰")] == "netherlands"
    assert table[norm_team("Netherlands")] == "netherlands"
    assert "_comment" not in table                   # 注释键跳过


def test_seed_entities_feed_alias_tables():
    """种子实体的 aliases/name_zh/name_en 自动进别名表(DRY,无第三个文件)。"""
    team_table = load_team_alias_table()
    assert resolve_team("哈马比", team_table) == "swe-hammarby"
    assert resolve_team("Hammarby", team_table) == "swe-hammarby"
    league_table = load_league_alias_table()
    assert resolve_league("瑞超", league_table) == "swe-allsvenskan"
    assert resolve_league("法甲", league_table) == "fra-ligue1"


def test_resolve_miss_returns_none_never_fuzzy():
    assert resolve_team("不存在的队", load_team_alias_table()) is None
    assert resolve_team("", load_team_alias_table()) is None
    assert resolve_league("不存在联赛", load_league_alias_table()) is None


def test_seed_entities_have_evidence_notes():
    """Tier 2 验收:memory 联赛画像已迁入本体(profile_notes 证据式)。"""
    teams, leagues = load_seed_entities()
    by_id = {lg.league_id: lg for lg in leagues}
    assert "swe-allsvenskan" in by_id
    assert any("主客分裂" in n["note"] for n in by_id["swe-allsvenskan"].profile_notes)
    assert all(n.get("evidence") for lg in leagues for n in lg.profile_notes)
    assert all(n.get("evidence") for t in teams for n in t.profile_notes)


def test_seed_entities_if_empty_idempotent(tmp_path):
    from nutmeg.decision.ontology import League
    from nutmeg.decision.store import DecisionStore
    store = DecisionStore(tmp_path)
    n1 = seed_entities_if_empty(store)
    n2 = seed_entities_if_empty(store)
    assert n1 > 0 and n2 == 0
    assert store.get(League, "swe-allsvenskan") is not None
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/decision/test_entities.py -v`
Expected: 全 FAIL（`ModuleNotFoundError: nutmeg.decision.entities`）

- [x] **Step 3: Create the seed resource**

新建 `nutmeg/data/decision_entities_seed.json`（策展内容 = memory `allsvenskan-2026-league-profile` + `jczq-5-28-v2-4` R25 反向联赛的**证据式迁移**；R25 数字是引擎时代统计，作 note 供参考、非规则）：

```json
{
  "_comment": "策展实体种子(实体层提案 Tier 2)。Team/League 只为'我们对它有知识'的实体而生;aliases/name_* 自动进 resolve 别名表。profile_notes 是证据式笔记(evidence 必填),不是规则——判断永不进代码。",
  "leagues": [
    {"league_id": "swe-allsvenskan", "name_zh": "瑞超", "name_en": "Allsvenskan",
     "country": "Sweden", "season": "2026",
     "profile_notes": [
       {"key": "home_away_split", "note": "极端主客分裂:卡尔马客场0分/哥德堡主场0胜/哈马比主场20-5,禁用通用主场加成",
        "evidence": "memory allsvenskan-2026-league-profile", "at": "2026-07-05"},
       {"key": "xg_divergence", "note": "xG背离榜:哈马比被积分榜低估(xG第2强);米亚尔比战绩虚高",
        "evidence": "memory allsvenskan-2026-league-profile", "at": "2026-07-05"},
       {"key": "summer_window", "note": "夏窗7/8后才开=复赛首轮新援不能上",
        "evidence": "memory allsvenskan-2026-league-profile", "at": "2026-07-05"}]},
    {"league_id": "fra-ligue1", "name_zh": "法甲", "name_en": "Ligue 1",
     "country": "France", "season": "",
     "profile_notes": [
       {"key": "goal_residual_drift", "note": "泊松残差历史双向漂移(5/13 -0.10→5/28 +0.05),联赛画像必须 rolling 复核不可静态引用",
        "evidence": "memory jczq-5-28-v2-4 R25", "at": "2026-05-28"}]},
    {"league_id": "nor-eliteserien", "name_zh": "挪超", "name_en": "Eliteserien",
     "country": "Norway", "season": "",
     "profile_notes": [
       {"key": "goals_overestimated", "note": "反直觉:模型历史高估进球(R25 avg≤-0.30 触发反向 delta),引擎时代统计仅供参考",
        "evidence": "memory jczq-5-28-v2-4 R25", "at": "2026-05-28"}]},
    {"league_id": "fin-veikkausliiga", "name_zh": "芬超", "name_en": "Veikkausliiga",
     "country": "Finland", "season": "",
     "profile_notes": [
       {"key": "goals_overestimated", "note": "反直觉:模型历史高估进球(R25 反向联赛),引擎时代统计仅供参考",
        "evidence": "memory jczq-5-28-v2-4 R25", "at": "2026-05-28"}]},
    {"league_id": "jpn-j1", "name_zh": "日职", "name_en": "J1 League",
     "country": "Japan", "season": "",
     "profile_notes": [
       {"key": "goals_overestimated", "note": "反直觉:模型历史高估进球(R25 反向联赛),引擎时代统计仅供参考",
        "evidence": "memory jczq-5-28-v2-4 R25", "at": "2026-05-28"}]}
  ],
  "teams": [
    {"team_id": "swe-hammarby", "name_zh": "哈马比", "name_en": "Hammarby",
     "aliases": ["Hammarby IF"], "competition_ids": ["swe-allsvenskan"],
     "profile_notes": [
       {"key": "underrated_xg", "note": "xG第2强被积分榜低估;主场20-5;6/5换帅Rydström",
        "evidence": "memory allsvenskan-2026-league-profile", "at": "2026-07-05"}]},
    {"team_id": "swe-kalmar", "name_zh": "卡尔马", "name_en": "Kalmar FF",
     "aliases": ["Kalmar"], "competition_ids": ["swe-allsvenskan"],
     "profile_notes": [
       {"key": "away_zero", "note": "客场0分——客场腿禁用通用画像",
        "evidence": "memory allsvenskan-2026-league-profile", "at": "2026-07-05"}]},
    {"team_id": "swe-goteborg", "name_zh": "哥德堡", "name_en": "IFK Goteborg",
     "aliases": ["IFK Göteborg", "Goteborg"], "competition_ids": ["swe-allsvenskan"],
     "profile_notes": [
       {"key": "home_zero_wins", "note": "主场0胜——主场腿禁用通用主场加成",
        "evidence": "memory allsvenskan-2026-league-profile", "at": "2026-07-05"}]},
    {"team_id": "swe-mjallby", "name_zh": "米亚尔比", "name_en": "Mjallby AIF",
     "aliases": ["Mjällby", "Mjallby"], "competition_ids": ["swe-allsvenskan"],
     "profile_notes": [
       {"key": "overrated_results", "note": "战绩虚高于 xG——正路信心需打折",
        "evidence": "memory allsvenskan-2026-league-profile", "at": "2026-07-05"}]}
  ]
}
```

- [x] **Step 4: Create the module**

新建 `nutmeg/decision/entities.py`：

```python
"""实体解析(策展式)+ 实体种子——队名/联赛名 → 稳定 *_id(实体层提案 §P2/§P3)。

别名来源(政策即数据,DRY 不新建第三个文件):
- jczq_national_team_aliases.json(复用): 中文名 → API-Football 英文名;id=slugify(英文)。
- decision_entities_seed.json: 策展 Team/League;aliases+name_zh+name_en 自动进表。
未命中 → None(调用方记 log,*_id=null 照常入库)。绝不模糊匹配、绝不自动造对象
——防几百支无知识球队污染 store;Team/League 只为"我们对它有知识"的实体而生。
"""
from __future__ import annotations

import json
import re
from importlib import resources

from nutmeg.decision.identity import norm_team
from nutmeg.decision.ontology import League, Team

_ENTITIES_RESOURCE = "decision_entities_seed.json"
_NATIONAL_RESOURCE = "jczq_national_team_aliases.json"


def slugify(name: str) -> str:
    """稳定 id 片段:casefold + 非词字符折叠成 '-'。重音保留(对齐 API-Football 拼写)。"""
    return re.sub(r"[\W_]+", "-", (name or "").casefold(), flags=re.UNICODE).strip("-")


def _load_json(resource: str) -> dict:
    return json.loads(
        resources.files("nutmeg.data").joinpath(resource).read_text(encoding="utf-8")
    )


def load_seed_entities() -> tuple[list[Team], list[League]]:
    data = _load_json(_ENTITIES_RESOURCE)
    teams = [Team.from_dict(t) for t in data.get("teams") or []]
    leagues = [League.from_dict(lg) for lg in data.get("leagues") or []]
    return teams, leagues


def load_team_alias_table() -> dict[str, str]:
    """{norm_team(alias): team_id}。国家队表 ⊕ 种子实体,种子优先(setdefault 序)。"""
    table: dict[str, str] = {}
    teams, _ = load_seed_entities()
    for t in teams:
        for alias in [t.name_zh, t.name_en, *t.aliases]:
            if alias:
                table.setdefault(norm_team(alias), t.team_id)
    for zh, en in _load_json(_NATIONAL_RESOURCE).items():
        if zh.startswith("_"):
            continue                                 # "_comment" 注释键
        table.setdefault(norm_team(zh), slugify(en))
        table.setdefault(norm_team(en), slugify(en))
    return table


def load_league_alias_table() -> dict[str, str]:
    table: dict[str, str] = {}
    _, leagues = load_seed_entities()
    for lg in leagues:
        for alias in [lg.name_zh, lg.name_en]:
            if alias:
                table.setdefault(norm_team(alias), lg.league_id)
    return table


def resolve_team(name: str, table: dict[str, str]) -> str | None:
    return table.get(norm_team(name)) if name else None


def resolve_league(name: str, table: dict[str, str]) -> str | None:
    return table.get(norm_team(name)) if name else None


def seed_entities_if_empty(store) -> int:
    """store 无 Team 且无 League 时落种子(幂等,同 seed_factors_if_empty 模式)。"""
    if store.load(Team) or store.load(League):
        return 0
    teams, leagues = load_seed_entities()
    store.upsert_many(teams)
    store.upsert_many(leagues)
    return len(teams) + len(leagues)
```

- [x] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/decision/test_entities.py -v`
Expected: 全 PASS

- [x] **Step 6: Run decision suite + commit**

```bash
uv run pytest -q tests/decision/
git add nutmeg/data/decision_entities_seed.json nutmeg/decision/entities.py \
        tests/decision/test_entities.py
git commit -m "feat(decision): 策展式实体 resolve + Team/League 种子(memory 画像迁入,实体层 Task 4)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XfSkXib7b5rf4aocCqbG8M"
```

---

### Task 5: sense 竞彩路径——competition 补上 + resolve

**Files:**
- Modify: `nutmeg/decision/sense.py:31-45`（_match_for_snapshot）、`sense.py:14-28`（sense_from_snapshot）、`sense.py:70-116`（sense_day）
- Test: `tests/decision/test_sense.py`

- [x] **Step 1: Write the failing test**

`tests/decision/test_sense.py` 末尾追加：

```python
def test_match_for_snapshot_fills_competition_and_resolved_ids():
    """修 sense 丢 competition 的既有数据丢失 + 策展 resolve(未命中 None 不伪造)。"""
    from nutmeg.decision.identity import canonical_match_id
    from nutmeg.decision.ontology import MarketSnapshot
    from nutmeg.decision.sense import _match_for_snapshot
    run_date = "2026-07-08"
    mid = canonical_match_id("荷兰", "法国", run_date)
    snap = MarketSnapshot(snapshot_id="S-1", match_id=mid, taken_at="t",
                          kind="read_time", source="sporttery")
    value = {"matchInfoList": [{"subMatchList": [{
        "matchNumStr": "周三001", "leagueAbbName": "世界杯",
        "homeTeamAbbName": "荷兰", "awayTeamAbbName": "法国"}]}]}
    m = _match_for_snapshot(snap, value, run_date)
    assert m.competition == "世界杯"                  # 之前被硬编码 "" 丢掉
    assert m.home_team_id == "netherlands"           # 国家队别名表命中
    assert m.away_team_id == "france"
    assert m.competition_id is None                  # 世界杯无联赛实体:未命中→None+log
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_sense.py -v`
Expected: 新测试 FAIL（`m.competition == ""`）

- [x] **Step 3: Implement**

`nutmeg/decision/sense.py`：

顶部 import 区追加：

```python
import logging

logger = logging.getLogger(__name__)
```

`_match_for_snapshot` 整体替换为：

```python
def _match_for_snapshot(snapshot, value: dict, run_date: str, *,
                        team_table=None, league_table=None) -> Match:
    """按 canonical 反查队名/竞彩号/联赛名(snapshot.match_id 现为 canonical),
    并策展式 resolve 实体 id(命中填,未命中 None——绝不伪造/模糊匹配)。"""
    from nutmeg.decision.entities import (
        load_league_alias_table,
        load_team_alias_table,
        resolve_league,
        resolve_team,
    )

    if team_table is None:
        team_table = load_team_alias_table()
    if league_table is None:
        league_table = load_league_alias_table()
    home = away = match_no = league = ""
    for day in value.get("matchInfoList") or []:
        for raw in day.get("subMatchList") or []:
            h = str(raw.get("homeTeamAbbName") or "")
            a = str(raw.get("awayTeamAbbName") or "")
            if canonical_match_id(h, a, run_date) == snapshot.match_id:
                home, away = h, a
                match_no = str(raw.get("matchNumStr") or "")
                league = str(raw.get("leagueAbbName") or "")
    return Match(
        match_id=snapshot.match_id, kickoff_at=snapshot.taken_at,
        home=home, away=away, competition=league,
        channel_refs={"jczq_match_no": match_no},
        home_team_id=resolve_team(home, team_table),
        away_team_id=resolve_team(away, team_table),
        competition_id=resolve_league(league, league_table),
    )
```

`sense_from_snapshot` 与 `sense_day` 的落库循环改为**表加载一次 + 聚合记 miss**（两处同构；以 sense_day 为例，sense_from_snapshot 同样处理）：

```python
    from nutmeg.decision.entities import load_league_alias_table, load_team_alias_table

    team_table = load_team_alias_table()
    league_table = load_league_alias_table()
    misses: set[str] = set()
    for s in tc_snaps:
        m = _match_for_snapshot(s, value, run_date,
                                team_table=team_table, league_table=league_table)
        if m.home and m.home_team_id is None:
            misses.add(m.home)
        if m.away and m.away_team_id is None:
            misses.add(m.away)
        upsert_match_merged(store, m)
        store.upsert(s)
    if misses:   # 绝不静默:未命中照常入库(*_id=null),聚合一行可见
        logger.info("sense resolve 未命中别名表(照常入库,*_id=null): %s",
                    "、".join(sorted(misses)))
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/decision/test_sense.py tests/decision/test_m1_sense.py tests/decision/test_m1_verbs_sense.py -v`
Expected: 全 PASS（既有 sense 测试不回归——新字段全可空）

- [x] **Step 5: Run decision suite + commit**

```bash
uv run pytest -q tests/decision/
git add nutmeg/decision/sense.py tests/decision/test_sense.py
git commit -m "fix(decision): sense 竞彩路径补 competition(原被丢弃)+ 策展 resolve 实体 id(实体层 Task 5)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XfSkXib7b5rf4aocCqbG8M"
```

---

### Task 6: sense zucai 路径——同样补 competition + resolve

**Files:**
- Modify: `nutmeg/decision/sense_zucai.py:99-122`（sense_zucai）
- Test: `tests/decision/test_zucai_sense.py`

- [x] **Step 1: Write the failing test**

`tests/decision/test_zucai_sense.py` 末尾追加：

```python
def test_sense_zucai_fills_competition_and_resolved_ids(tmp_path):
    """zucai 路径同样修 competition 丢失 + resolve(loader 注入,不打网)。"""
    from nutmeg.decision.ontology import Match
    from nutmeg.decision.sense_zucai import sense_zucai
    from nutmeg.decision.store import DecisionStore
    from nutmeg.domain.zucai import ZucaiMatch

    def loader(issue, output_dir):
        matches = [ZucaiMatch(match_no=1, competition="瑞超", home_team="哈马比",
                              away_team="卡尔马", match_date="2026-07-12")]
        odds = {1: {"home": 2.0, "draw": 3.2, "away": 3.4}}
        return matches, odds, {1: "2026-07-12"}

    store = DecisionStore(tmp_path)
    n = sense_zucai("26100", output_dir=tmp_path, taken_at="t",
                    store=store, loader=loader)
    assert n == 1
    m = store.load(Match)[0]
    assert m.competition == "瑞超"                    # 之前被硬编码 "" 丢掉
    assert m.home_team_id == "swe-hammarby"          # 种子实体别名命中
    assert m.away_team_id == "swe-kalmar"
    assert m.competition_id == "swe-allsvenskan"
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_zucai_sense.py -v`
Expected: 新测试 FAIL（`m.competition == ""`）

- [x] **Step 3: Implement**

`nutmeg/decision/sense_zucai.py` — `sense_zucai` 的落库循环改为：

```python
def sense_zucai(issue: str, *, output_dir, taken_at: str, store, loader=None) -> int:
    """一期传统足彩 14 场 → Match(canonical,merge refs)+Snapshot 入库。返回入库场数。"""
    import logging

    from nutmeg.decision.entities import (
        load_league_alias_table,
        load_team_alias_table,
        resolve_league,
        resolve_team,
    )
    from nutmeg.decision.identity import canonical_match_id
    from nutmeg.decision.ontology import Match
    from nutmeg.decision.sense import upsert_match_merged

    logger = logging.getLogger(__name__)
    loader = loader or _default_loader
    matches, odds, dates = loader(issue, output_dir)
    snaps = zucai_snapshots(matches, odds, issue=issue, dates=dates,
                            taken_at=taken_at)
    canonical_to_no = {
        canonical_match_id(m.home_team, m.away_team, dates[m.match_no]): m.match_no
        for m in matches if m.match_no in dates
    }
    by_no = {m.match_no: m for m in matches}
    team_table = load_team_alias_table()
    league_table = load_league_alias_table()
    misses: set[str] = set()
    for s in snaps:
        no = canonical_to_no.get(s.match_id)
        m = by_no.get(no)
        home_id = resolve_team(m.home_team, team_table)
        away_id = resolve_team(m.away_team, team_table)
        for name, rid in ((m.home_team, home_id), (m.away_team, away_id)):
            if name and rid is None:
                misses.add(name)
        upsert_match_merged(store, Match(
            match_id=s.match_id, kickoff_at=taken_at, home=m.home_team,
            away=m.away_team, competition=m.competition,
            channel_refs={"zucai": {"issue": issue, "index": no}},
            home_team_id=home_id, away_team_id=away_id,
            competition_id=resolve_league(m.competition, league_table)))
        store.upsert(s)
    if misses:
        logger.info("sense-zucai resolve 未命中别名表(照常入库,*_id=null): %s",
                    "、".join(sorted(misses)))
    return len(snaps)
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/decision/test_zucai_sense.py tests/decision/test_zucai_e2e.py -v`
Expected: 全 PASS

- [x] **Step 5: Run decision suite + commit**

```bash
uv run pytest -q tests/decision/
git add nutmeg/decision/sense_zucai.py tests/decision/test_zucai_sense.py
git commit -m "fix(decision): sense-zucai 补 competition + resolve 实体 id(实体层 Task 6)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XfSkXib7b5rf4aocCqbG8M"
```

---

### Task 7: Read 校验——team/league scope 因子引用必带 scope_key

**Files:**
- Modify: `nutmeg/decision/read_validate.py`
- Modify: `nutmeg/decision/read_ingest.py:15-22`
- Test: `tests/decision/test_read_validate.py`, `tests/decision/test_read_ingest.py`

- [x] **Step 1: Write the failing tests**

`tests/decision/test_read_validate.py` 末尾追加：

```python
def _mk_scoped_read(factors):
    """weight_pp=4 与 belief−prior 偏移 4pp 一致(校验既有规则)。"""
    from nutmeg.decision.ontology import Read
    return Read(
        read_id="R-scope", match_id="M-1", snapshot_id="S-1",
        made_at="t", judge="claude", market="had",
        prior={"home": 0.46, "draw": 0.27, "away": 0.27},
        belief={"home": 0.42, "draw": 0.31, "away": 0.27},
        factors=factors, confidence=3, shadow=False)


def test_league_scope_factor_requires_scope_key():
    from nutmeg.decision.read_validate import validate_read
    read = _mk_scoped_read([{"factor_id": "league_bias", "direction": "draw",
                             "weight_pp": 4, "evidence": [{"url": "u"}]}])
    errs = validate_read(read, allowed_factors={"league_bias"},
                         factor_scopes={"league_bias": "league"})
    assert any("scope_key" in e for e in errs)


def test_league_scope_factor_with_scope_key_passes():
    from nutmeg.decision.read_validate import validate_read
    read = _mk_scoped_read([{"factor_id": "league_bias", "direction": "draw",
                             "weight_pp": 4, "scope_key": "swe-allsvenskan",
                             "evidence": [{"url": "u"}]}])
    assert validate_read(read, allowed_factors={"league_bias"},
                         factor_scopes={"league_bias": "league"}) == []


def test_factor_scopes_omitted_keeps_backward_compat():
    """不传 factor_scopes(旧调用面)→ 不做 scope 校验,行为不变。"""
    from nutmeg.decision.read_validate import validate_read
    read = _mk_scoped_read([{"factor_id": "league_bias", "direction": "draw",
                             "weight_pp": 4, "evidence": [{"url": "u"}]}])
    assert validate_read(read, allowed_factors={"league_bias"}) == []
```

`tests/decision/test_read_ingest.py` 末尾追加：

```python
def test_ingest_rejects_league_factor_without_scope_key(tmp_path):
    """ingest 用词典 scope 自动强制 scope_key(种子 league_bias=league scope)。"""
    from nutmeg.decision.factors import load_seed_factors
    from nutmeg.decision.read_ingest import ingest_reads
    from nutmeg.decision.store import DecisionStore
    payload = {
        "read_id": "R-x", "match_id": "M-1", "snapshot_id": "S-1",
        "made_at": "t", "judge": "claude", "market": "had",
        "prior": {"home": 0.46, "draw": 0.27, "away": 0.27},
        "belief": {"home": 0.42, "draw": 0.31, "away": 0.27},
        "factors": [{"factor_id": "league_bias", "direction": "draw",
                     "weight_pp": 4, "evidence": [{"url": "u"}]}],
        "confidence": 3, "shadow": False}
    store = DecisionStore(tmp_path)
    errors = ingest_reads([payload], store=store, factors=load_seed_factors())
    assert errors and "scope_key" in errors[0]
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/decision/test_read_validate.py tests/decision/test_read_ingest.py -v`
Expected: 前两个新测试 FAIL（`validate_read` 无 `factor_scopes` 参数 → TypeError）；backward-compat 测试 PASS（本来就该过）

- [x] **Step 3: Implement**

`nutmeg/decision/read_validate.py` — 签名与因子循环改为：

```python
def validate_read(read, *, allowed_factors: set[str],
                  factor_scopes: dict[str, str] | None = None) -> list[str]:
```

因子循环内（`证据非空` 检查之后）追加：

```python
            # team/league scope 因子引用必带 scope_key(实体层提案 §P3:
            # calibrate 据此出 factor_id@scope_key 诊断性子判决)
            scope = (factor_scopes or {}).get(fid)
            if scope in ("team", "league") and not f.get("scope_key"):
                errs.append(f"因子 {fid!r} scope={scope} 引用必须带 scope_key")
```

`nutmeg/decision/read_ingest.py` — `ingest_reads` 改为传 scopes：

```python
from nutmeg.decision.factors import allowed_factor_ids, factor_scopes
```

```python
def ingest_reads(payloads: list[dict], *, store, factors: list) -> list[str]:
    """校验并落库 Claude 产出的 Read。返回错误串列表（空=全部落库）。"""
    allowed = allowed_factor_ids(factors)
    scopes = factor_scopes(factors)
    errors: list[str] = []
    for payload in payloads:
        read = Read.from_dict(payload)
        errs = validate_read(read, allowed_factors=allowed, factor_scopes=scopes)
```

（其余不变。）

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/decision/test_read_validate.py tests/decision/test_read_ingest.py -v`
Expected: 全 PASS

- [x] **Step 5: Run decision suite + commit**

```bash
uv run pytest -q tests/decision/
git add nutmeg/decision/read_validate.py nutmeg/decision/read_ingest.py \
        tests/decision/test_read_validate.py tests/decision/test_read_ingest.py
git commit -m "feat(decision): team/league scope 因子引用强制 scope_key(实体层 Task 7)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XfSkXib7b5rf4aocCqbG8M"
```

---

### Task 8: calibrate——scope_key 诊断性子判决（生死仍在 factor 级）

**Files:**
- Modify: `nutmeg/decision/calibrate.py:55-88`（run_calibrate）、`calibrate.py:157-196`（apply_verdicts）
- Test: `tests/decision/test_calibrate.py`

- [x] **Step 1: Write the failing tests**

`tests/decision/test_calibrate.py` 末尾追加：

```python
def test_run_calibrate_emits_diagnostic_subverdicts_per_scope_key(tmp_path):
    """带 scope_key 的引用 → 额外产 factor_id@scope_key 诊断子判决(证据分辨率,
    非生死状态机——提案 2026-07-07 复核修正)。复合 id 亦防 store clobber。"""
    from nutmeg.decision.calibrate import run_calibrate
    from nutmeg.decision.ontology import Read, Settlement
    from nutmeg.decision.store import DecisionStore
    store = DecisionStore(tmp_path)
    store.upsert(Read(
        read_id="R-1", match_id="M-1", snapshot_id="S-1", made_at="t",
        judge="claude", market="had",
        prior={"home": 0.5, "draw": 0.3, "away": 0.2},
        belief={"home": 0.44, "draw": 0.36, "away": 0.2},
        factors=[{"factor_id": "league_bias", "scope_key": "swe-allsvenskan",
                  "direction": "draw", "weight_pp": 6,
                  "evidence": [{"url": "u"}]}]))
    store.upsert(Settlement(
        settlement_id="SET-read-R-1", ref_type="read", ref_id="R-1",
        settled_at="t", outcome_90="draw", brier=0.6, clv_pp=0.01))
    verdicts = {v.factor_id: v for v in run_calibrate(store, as_of="2026-07-07")}
    assert "league_bias" in verdicts                       # 生死判决主体不变
    assert "league_bias@swe-allsvenskan" in verdicts       # 诊断子判决
    assert verdicts["league_bias@swe-allsvenskan"].recommendation == "diagnostic"
    assert verdicts["league_bias"].recommendation == "keep"   # n=1<30 只积累
    assert verdicts["league_bias@swe-allsvenskan"].n_reads == 1


def test_apply_verdicts_ignores_diagnostic_subverdicts(tmp_path):
    """子判决永不驱动转正/退休——生死留在 factor 级(反 churn n≥30 不变)。"""
    from nutmeg.decision.calibrate import apply_verdicts, seed_factors_if_empty
    from nutmeg.decision.ontology import Factor, FactorVerdict
    from nutmeg.decision.store import DecisionStore
    store = DecisionStore(tmp_path)
    seed_factors_if_empty(store)
    sub = FactorVerdict(
        factor_id="league_bias@swe-allsvenskan", as_of="2026-07-07",
        n_reads=40, brier_delta_vs_prior=-0.1, clv_hit_rate=0.9,
        direction_hit_rate=None, recommendation="diagnostic")
    changes = apply_verdicts(store, [sub])
    assert changes == {"promoted": [], "retired": []}
    fac = {f.factor_id: f for f in store.load(Factor)}["league_bias"]
    assert fac.status == "probation"                       # 不受子判决影响
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/decision/test_calibrate.py -v`
Expected: 第一个新测试 FAIL（无 `@` 子判决）；第二个可能已 PASS（`factors.get` miss 天然跳过）——仍要显式守卫（防未来 factor_id 撞 `@`）

- [x] **Step 3: Implement**

`nutmeg/decision/calibrate.py` — `run_calibrate` 的因子归集与判决构建改为：

```python
        for f in read.factors:
            fid = f.get("factor_id")
            if not fid:
                continue
            per_factor.setdefault(fid, []).append(entry)
            # scope_key 引用 → 追加 factor_id@scope_key 诊断桶(实体层提案 §P3:
            # 证据分辨率,非生死状态机;复合 id 防 store upsert-by-id clobber)
            sk = f.get("scope_key")
            if sk:
                per_factor.setdefault(f"{fid}@{sk}", []).append(entry)

    from dataclasses import replace as _replace
    verdicts = []
    for fid, entries in sorted(per_factor.items()):
        v = factor_verdict(fid, entries, as_of=as_of)
        if "@" in fid:                       # 子判决只做诊断,永不 retire/keep
            v = _replace(v, recommendation="diagnostic")
        verdicts.append(v)
    for v in verdicts:
        store.upsert(v)
    return verdicts
```

`apply_verdicts` — 循环顶部加显式守卫（`factors.get` miss 已天然跳过，此守卫防御未来撞名）：

```python
    for fid, v in vmap.items():
        if "@" in fid or v.recommendation == "diagnostic":
            continue                          # 诊断子判决永不驱动生死(提案复核修正)
        f = factors.get(fid)
```

（`render_panel` 无需改动：`run_calibrate` 输出已按 id 字典序，`league_bias` 后紧跟 `league_bias@...` 子行，面板天然分组显示。）

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/decision/test_calibrate.py tests/decision/test_m1_calibrate.py tests/decision/test_factor_lifecycle.py -v`
Expected: 全 PASS

- [x] **Step 5: Run decision suite + commit**

```bash
uv run pytest -q tests/decision/
git add nutmeg/decision/calibrate.py tests/decision/test_calibrate.py
git commit -m "feat(decision): calibrate 按 scope_key 出诊断性子判决,生死留 factor 级(实体层 Task 8)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XfSkXib7b5rf4aocCqbG8M"
```

---

### Task 9: sync_factor_scopes（live store 纠偏）+ 动词挂钩

**Files:**
- Modify: `nutmeg/decision/factors.py`
- Modify: `nutmeg/decision/verbs.py:21-29`（run_sense）、`verbs.py:165-183`（run_calibrate_panel）
- Test: `tests/decision/test_factors.py`, `tests/decision/test_verbs.py`

- [x] **Step 1: Write the failing tests**

`tests/decision/test_factors.py` 末尾追加：

```python
def test_sync_factor_scopes_fixes_legacy_rows_and_is_idempotent(tmp_path):
    """M2 已落库的旧行无 scope → 默认 match 对 league_bias 是错的;sync 按种子纠偏,
    只改 scope 保留 status。幂等:第二次跑 0 变更。"""
    from nutmeg.decision.factors import sync_factor_scopes
    from nutmeg.decision.ontology import Factor
    from nutmeg.decision.store import DecisionStore
    store = DecisionStore(tmp_path)
    store.upsert(Factor.from_dict({
        "factor_id": "league_bias", "name_zh": "极端联赛画像", "definition": "d",
        "born_at": "2026-07-05", "born_from": "x", "status": "active"}))
    assert store.get(Factor, "league_bias").scope == "match"   # 旧行错误默认
    assert sync_factor_scopes(store) == 1
    fixed = store.get(Factor, "league_bias")
    assert fixed.scope == "league"
    assert fixed.status == "active"                            # 状态保留
    assert sync_factor_scopes(store) == 0                      # 幂等
```

`tests/decision/test_verbs.py` 末尾追加：

```python
def test_run_sense_seeds_entities_even_without_snapshot(tmp_path):
    """run_sense 幂等落实体种子——read 时 Claude 能从 store 读联赛/球队画像。"""
    from nutmeg.decision.ontology import League
    from nutmeg.decision.store import DecisionStore
    from nutmeg.decision.verbs import run_sense
    run_sense("2026-07-08", tmp_path, "2026-07-08T08:00:00+08:00")
    store = DecisionStore(tmp_path / "decision")
    assert store.get(League, "swe-allsvenskan") is not None


def test_run_calibrate_panel_syncs_factor_scopes(tmp_path):
    """settle 的 calibrate 步自动纠偏 live store 的旧 scope 行(幂等挂钩)。"""
    from nutmeg.decision.ontology import Factor
    from nutmeg.decision.store import DecisionStore
    from nutmeg.decision.verbs import run_calibrate_panel
    store = DecisionStore(tmp_path / "decision")
    store.upsert(Factor.from_dict({
        "factor_id": "league_bias", "name_zh": "极端联赛画像", "definition": "d",
        "born_at": "2026-07-05", "born_from": "x", "status": "probation"}))
    run_calibrate_panel(tmp_path, "2026-07-07")
    assert store.get(Factor, "league_bias").scope == "league"
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/decision/test_factors.py tests/decision/test_verbs.py -v`
Expected: 3 FAIL（`ImportError: sync_factor_scopes` / run_sense 未落种子 / panel 未 sync）

- [x] **Step 3: Implement**

`nutmeg/decision/factors.py` — 追加：

```python
def sync_factor_scopes(store) -> int:
    """store 的 Factor scope 与种子对齐(幂等,只改 scope,状态/其余字段保留)。

    背景:M2 已落库的行无 scope 字段 → from_dict 默认 match,对 league_bias 等是错的。
    只对齐种子里存在的 factor_id;未来非种子出生的因子不受影响。返回纠偏条数。
    """
    from dataclasses import replace

    seed_scope = {f.factor_id: f.scope for f in load_seed_factors()}
    stored = store.load(Factor)
    changed = 0
    for f in stored:
        want = seed_scope.get(f.factor_id)
        if want and f.scope != want:
            store.upsert(replace(f, scope=want))
            changed += 1
    return changed
```

`nutmeg/decision/verbs.py` — `run_sense` 在 return 前追加两行：

```python
    store = DecisionStore(Path(output_dir) / "decision")
    n = sense_day(run_date, output_dir=output_dir,
                  taken_at=taken_at, store=store)
    # 实体种子幂等落库(Tier 2):read 时 Claude 从 store 读联赛/球队画像
    from nutmeg.decision.entities import seed_entities_if_empty
    seeded = seed_entities_if_empty(store)
    msg = f"decision-sense {run_date}: 入库 {n} 场 Match+体彩/欧赔 Snapshot"
    if seeded:
        msg += f" | 实体种子落库 {seeded} 条"
    return msg
```

`run_calibrate_panel` 在 `run_calibrate` 之前追加：

```python
    store = DecisionStore(Path(output_dir) / "decision")
    # 幂等纠偏:旧 factors.jsonl 行无 scope(默认 match)→ 按种子对齐(实体层 Task 9)
    from nutmeg.decision.factors import sync_factor_scopes
    sync_factor_scopes(store)
    verdicts = run_calibrate(store, as_of=as_of)
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/decision/test_factors.py tests/decision/test_verbs.py tests/decision/test_m1_verbs.py -v`
Expected: 全 PASS

- [x] **Step 5: Run decision suite + commit**

```bash
uv run pytest -q tests/decision/
git add nutmeg/decision/factors.py nutmeg/decision/verbs.py \
        tests/decision/test_factors.py tests/decision/test_verbs.py
git commit -m "feat(decision): sync_factor_scopes 纠偏挂 calibrate + 实体种子挂 sense(实体层 Task 9)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XfSkXib7b5rf4aocCqbG8M"
```

---

### Task 10: 全量验证 + live store 纠偏 + 文档收尾

**Files:**
- Modify: `docs/superpowers/specs/2026-07-06-decision-ontology-design.md`（§2 折进 scope/实体对象）
- Modify: `docs/superpowers/specs/2026-07-07-ontology-entity-layer-proposal.md`（状态行）
- Modify: `CLAUDE.md` + `AGENTS.md`（Read schema 行加 `scope_key?`——两份必须同步改）

- [x] **Step 1: 全量测试 + lint**

```bash
uv run pytest -q
uv run ruff check nutmeg/decision/ tests/decision/
```
Expected: 全绿（基线 1051 + 本计划新增 ≈17 条）

- [x] **Step 2: live store 一次性纠偏（谨慎:动真数据前先看一眼）**

```bash
# 先看 live factors.jsonl 现状(应无 scope 字段)
cat .nutmeg-data/jczq/decision/factors.jsonl
# 幂等纠偏(与 settle 挂钩逻辑同一函数;提前手动跑一次让 read 层立刻可用)
uv run python -c "
from pathlib import Path
from nutmeg.decision.factors import sync_factor_scopes
from nutmeg.decision.store import DecisionStore
store = DecisionStore(Path('.nutmeg-data/jczq/decision'))
print('纠偏条数:', sync_factor_scopes(store))
"
# 复查:league_bias 行应带 "scope": "league"
grep league_bias .nutmeg-data/jczq/decision/factors.jsonl
```
Expected: 纠偏条数 = live store 中 scope 不符的种子因子数（首跑 >0，再跑 0）

- [x] **Step 3: verify skill 端到端（按 §B.3 收尾纪律）**

调用项目 `verify` skill，重点配方：
1. **sense replay**：拷贝一个近期有快照的日期目录到 scratchpad，跑 `uv run nutmeg decision-am --run-date <该日期> --output-dir <拷贝>`（fetch 失败 best-effort 继续、sense 从已存快照 replay）；检查 `matches.jsonl` 新行带 `competition`、国家队场带 `home_team_id`；`teams.jsonl`/`leagues.jsonl` 种子已落。
2. **settle replay**：同拷贝跑 `decision-settle`；检查 calibrate 面板正常渲染、factors.jsonl scope 已纠偏、无回归。

- [x] **Step 4: 文档收尾（三处）**

1. `2026-07-06-decision-ontology-design.md` §2：`Factor` schema 行加 `scope`；`Match` schema 加三个 `*_id?`；对象清单加 `Team`/`League` 两行（标注"2026-07-07 实体层增补，见 proposal"）；§5 因子生死段加一句"scope_key 级诊断性子判决（`factor_id@scope_key`），生死判决仍在 factor 级"。
2. `2026-07-07-ontology-entity-layer-proposal.md` 状态行改为：`**状态：Tier 1+2 已落地（2026-07-07，commits 见 git log）；Tier 3 判"过早、不建"。**`
3. `CLAUDE.md` 与 `AGENTS.md`（同步改）：SOP 步骤 2 的 Read schema 里 `factors:[{factor_id, direction, weight_pp, evidence:[...]}]` → `factors:[{factor_id, scope_key?, direction, weight_pp, evidence:[...]}]`，并在判读硬约束后追加一行：`g. league/team 级因子引用必带 scope_key（如 league_bias → swe-allsvenskan）；联赛/球队画像读 store 的 League/Team profile_notes，不再只靠 memory。`

- [x] **Step 5: Final commit**

```bash
uv run pytest -q
git add docs/superpowers/specs/2026-07-06-decision-ontology-design.md \
        docs/superpowers/specs/2026-07-07-ontology-entity-layer-proposal.md \
        CLAUDE.md AGENTS.md
git commit -m "docs(decision): 实体层 Tier1+2 落地收尾——spec §2 折进 scope/Team/League,SOP 加约束 g(实体层 Task 10)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XfSkXib7b5rf4aocCqbG8M"
```

---

## Self-Review（已执行）

**1. Spec coverage：**
- Tier 1 `Factor.scope` → Task 1；`scope_key` 校验 → Task 7；resolve 稳定 `*_id` → Task 4/5/6；competition 修复 → Task 5/6 ✅
- Tier 2 Team/League 对象 → Task 3；profile_notes + memory 画像迁移 → Task 4 种子 ✅
- 复核修正一（生死留 factor 级 + 诊断子判决复合 id）→ Task 8 ✅
- 复核修正二（策展式 resolve、未命中 null+log、不自动造对象）→ Task 4/5/6 ✅
- 旧 factors.jsonl 纠偏 → Task 9（幂等挂钩）+ Task 10 Step 2（live 一次性）✅
- 血缘（Match→Team/League、Read.factors[].scope_key）→ Task 2/7 schema 即血缘 ✅
- Tier 3 / `Match.joint` / `Factor.scope_key` → 明确不做（header 记录）✅
- live 不中断 → 全部字段带默认值 + `_from_dict` 容忍性；launchd 命令面零变化 ✅

**2. Placeholder scan：** 无 TBD/TODO/"类似 Task N"；每个代码步骤有完整代码 ✅

**3. Type consistency：** `factor_scopes(factors)->dict[str,str]`（Task 1 定义，Task 7 使用）；`load_team_alias_table/load_league_alias_table/resolve_team/resolve_league/seed_entities_if_empty`（Task 4 定义，Task 5/6/9 使用）；`sync_factor_scopes`（Task 9 定义+使用，Task 10 复用）；`Team.team_id/League.league_id`（Task 3 定义，Task 4 种子与测试一致）✅
