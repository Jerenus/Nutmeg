# JCZQ Tiered Plan v2 — codex-style 4-tier replacement of bold-combos

**Date**: 2026-05-25
**Status**: design
**Replaces**: `nutmeg/services/jczq_bold_combos.py` (bold-combos v1, 5/18 起的
"5 同名大胆票" 引擎)
**Trigger**: 用户 5/25 反馈"大胆票老是 4 场比赛排列组合、没有创造力、没有
选择逻辑支撑"，要求参考 `daily/<date>/debate/gpt-analysis.md` 里 codex 的
A/B/D/E 4 档分层方案重写。

---

## §0 焊死硬约束（不变）

沿用 bold-combos v1 的三条焊死硬约束，加一条 v2 专属：

1. 每张票头部含金额（`stake_yuan`）— **金额是日常娱乐预算的分配建议、不是
   "正期望"声明**；总金额行加诚实标 `💰 今日方案 · 总建议金额 ¥X · 仅用
   娱乐预算`
2. 输出 banned 词不变：`胜率 / edge / +EV / 正期望 / 推荐下注 / 重仓`
3. 引擎不 import `dixon_coles` / `ValueBoardService` / `nutmeg.models`
4. **新**：D 档不得读 brief 里的 Poisson +EV 信号 —— v2 的"反大众"靠引擎
   原生 boldness/contrarian 信号，不借用已退役的 Poisson 残余证据

---

## §1 命名 + CLI + 文件位置

- **新命令**：`nutmeg jczq-tiered`（live 模式默认，`--replay YYYY-MM-DD`
  复现，`--dispatch-telegram --no-dry-run` 推送）
- **金额缩放 flag**：`--stake-multiplier <float>`（默认 1.0；0.25 = 9/9/5/3
  接近日常 25 元/日）
- **模块**：`nutmeg/services/jczq_tiered.py`（新建，不动 `jczq_bold_combos.py`）
- **每日输出位置**：
  - `.nutmeg-data/jczq/daily/<date>/tiered-plan.md`
  - `.nutmeg-data/jczq/daily/<date>/tiered-plan.json`
- **复盘命令**：`nutmeg jczq-tiered-review`，输出 `tiered-plan-review.md` +
  `tiered-plan-review.json`，append-only `tiered-plan-history.json`
- **launchd**：
  - `com.nutmeg.jczq.daily-bold` → 改名 **`daily-tiered`**，12:00 跑
    `jczq-tiered --date today --dispatch-telegram --no-dry-run`
  - `com.nutmeg.jczq.bold-review-8am` → 改名 **`tiered-review-8am`**，次日
    08:00 跑 `jczq-tiered-review`
- **v1 退役流程**：
  - `jczq-bold-combos` / `jczq-bold-review` CLI 保留 2 周作为对照参考
    （**手动可调 `--replay`，不再上 launchd**），2 周后从 CLI 注册表清退
  - bold-combos / bold-review 的 source 模块**保留**（archive 用途），单元
    测试继续维护，但 daily 自动管线不再调用。**v1 输出目录不归档**
    （`bold-combos.md` / `bold-review.json` 等仍写到 `daily/<date>/`，但只在
    人手动跑 v1 CLI 时生成；自动跑只生成 v2 `tiered-plan.*`）
  - **§24 retired_themes 累计跨版本读取**（合并旧 `bold-review-history.json`
    + 新 `tiered-plan-history.json`），不丢平局收割 23 张的历史汰留判定

---

## §2 数据流 + 候选池加宽

### §2.1 数据流

```
Sporttery snapshot ─┐
500.com 欧赔 snap ──┼─→ bold_matches_from_sporttery(...)   [复用 v1]
                    │     ↓ [BoldMatch × N 场]
                    │   v2_candidate_pool(matches)         [新写]
                    │     ↓ [BoldLeg × 每场 ≤2 / 总 8-15]
bold-review-history ┴─→ select_tiered_plan(pool, history, stake_multiplier)
                          ↓ [TieredPlan(A, B, D, E)]
                       render_tiered_plan(plan)
                          ↓ tiered-plan.md
```

### §2.2 `v2_candidate_pool(matches)` — 根治 §18 退化

| 维度 | v1 `_balanced_pool` | **v2 `v2_candidate_pool`** |
|---|---|---|
| 每场腿数 | 1 条（最高 boldness） | **最多 2 条**（不同市场） |
| 池子总大小 | `chaos_pool_size(chaos)`（chaos=8 → ~4-5） | **无 chaos 控制**：每场 ≤2 条直接全收 → chaos=8 极静日也有 8-10 腿 |
| 市场上限 | `pool_n // 2`（任一市场 ≤ 池一半） | **沿用** — 防比分腿垄断；总池 N 时上限 = `⌈N × 0.5⌉` |
| Rule O | 每条腿不同 match_no | 不变 — 每张票内每场 ≤1 腿（v2 跨档共享允许，档内不允许） |

**实现**：
- pass 1：每场所有 4 市场 leg 按 boldness 排序，取前 2 条满足"互为不同
  market"约束
- pass 2：全局市场计数 > `⌈N × 0.5⌉` 时，砍该市场内最低 boldness 的过量者
- 返回 `list[BoldLeg]`，按全局 boldness 倒序

### §2.3 chaos 角色

v2 让 chaos **彻底退出选票路径**。剩余角色：
- 顶部公示行：`混乱值 X/100（{band}）` — 纯展示
- §22 翻面读法的触发条件之一（不变）
- §18 退化通知触发：只在 **N 场池 ≤ 5** 时仍可能触发，极少数日

---

## §3 4 档 TierProfile + selection callable

### §3.1 数据结构

```python
ExcludedMatches = frozenset[str]  # match_no 集合

Strategy = Callable[
    [list[BoldLeg], ExcludedMatches, "PlanContext"],
    Optional["Tier"]
]

@dataclass(frozen=True, slots=True)
class TierProfile:
    code: str                        # "A" / "B" / "D" / "E"
    name: str                        # "稳健底仓" / "主方案" / "反大众" / "极限娱乐"
    fold_range: tuple[int, int]      # (min, max) inclusive
    total_odds_band: tuple[float, float]
    base_stake_yuan: int             # 1.0×multiplier 时的金额
    max_crs_legs: int                # 比分腿上限（防全 crs 失真）
    strategy: Strategy

@dataclass(frozen=True, slots=True)
class Tier:
    profile: TierProfile
    legs: list[BoldLeg]              # 每腿带 leg.reason: LegReason（§4）
    total_odds: float
    stake_yuan: int                  # = base_stake × multiplier，四舍五入
    confidence_tag: str              # "⭐⭐⭐⭐" / "⭐⭐⭐" / "⭐⭐" / "⭐"
    bullets: list[str]               # 票级 narrative（≤ 2 行）

@dataclass(frozen=True, slots=True)
class PlanContext:
    """传给 strategy callable 的只读上下文。"""
    pool_signals: PoolSignals        # 沿用 v1
    retired_themes: frozenset[str]   # §24 累计汰留集（跨版本读）
    history_by_tier: dict[str, dict] # tiered-plan-history.json 的每档累计
    multiplier: float                # stake_multiplier

@dataclass(frozen=True, slots=True)
class TieredPlan:
    run_date: str
    day_chaos: int
    chaos_band: str
    tiers: list[Optional[Tier]]      # [A, B, D, E] 顺序固定；缺档为 None
    recommended_single: Optional[str]  # "A" / "B" / None
    retired_themes: tuple[RetiredTheme, ...]  # §24 沿用，渲染顶部
    pool_signals: PoolSignals
    multiplier: float
```

### §3.2 四档 profile 默认参数

| 档 | code | name | folds | 赔率档 | 金额 (1.0×) | crs ≤ |
|---|---|---|---|---|---|---|
| A | A | 稳健底仓 | 2-3 | 2.5-8× | ¥35 | 0 |
| B | B | 主方案 | 3-5 | 30-150× | ¥35 | 0 |
| D | D | 反大众 | 3-4 | 80-300× | ¥20 | 1 |
| E | E | 极限娱乐 | 4-5 | 800-5000× | ¥10 | 1 |

总金额 1.0× = ¥100；`--stake-multiplier 0.25` → ¥9/9/5/3 ≈ ¥26 接近日常。

**confidence_tag 规则**（固定映射，非算法）：
- A → ⭐⭐⭐⭐（最稳）
- B → ⭐⭐⭐
- D → ⭐⭐
- E → ⭐（最娱乐）

### §3.3 四个 strategy

#### `pick_anchor_tier(pool, excluded={}, ctx)` — A 稳健底仓

1. 候选 = pool 中 had 或 hhad 腿（不收 ttg / crs）
2. **§17.1 gap-guard**：对每条候选，若体彩 implied vs 欧赔 fair_prob ≥ 8pp
   gap → drop
3. **hhad cover 倾向**（codex 5/25 风格，默认 ON）：当某场 had 主胜或客胜
   ≤ **1.50** 时，优先用该场 hhad 让球对侧 cover（"超热门小胜" → 让分 cover
   避主胜紧逼）；门槛 ≥ 1.50 时仍用 had
4. 取赔率最低的前 5 场（去重后 ≥3 → fold=3；2 场 → fold=2；<2 → 返回 None）
5. 组合总赔率必须落 [2.5, 8.0] 区间；超过则去掉最高赔的一条再算
6. **失败容错**：gap-guard 全砍 / 场不够 / 总赔率超档 → 返回 None

#### `pick_main_tier(pool, excluded=A.matches, ctx)` — B 主方案

1. 候选 = pool 中**排除 A 用过的 match_no**
2. boldness 中段（按全局百分位 30%-70%）— "不要最冷、也不要最热"
3. 优先 hhad / ttg 腿（structural picks，非 had 杠杆）
4. fold ∈ {3, 4, 5}：候选 ≥4 → fold=4；候选 = 3 → fold=3；<3 → None
5. 总赔率必须落 [30, 150]；不满足 → 调 fold 或 None
6. 排序按 `_band_fit × avg_boldness`（沿用 v1 §13 评分）

#### `pick_contra_tier(pool, excluded=A.matches | B.matches, ctx)` — D 反大众

1. 候选 = pool 中**排除 A ∪ B 用过的 match_no**
2. **跳过 §24 retired themes**：构造 candidate 组合时，若该组合
   `ticket_theme(combo_legs)[0] in ctx.retired_themes` 直接丢弃
3. 按腿的 boldness 倒序（boldness 已综合 contrarian/conflict/dispersion
   信号；不重新计算 contrarian_score）取前 50%
4. 在剩余腿里再优先 boldness 主导信号 = "反直觉冷门" 的腿（leg.reason
   旧字段或新 LegReason.why_pick 的 keyword 含"反直觉/contrarian"）
5. fold ∈ {3, 4}；crs ≤ 1
6. 总赔率 [80, 300]；不满足 → 调 fold 或 None

#### `pick_lottery_tier(pool, excluded={}, ctx)` — E 极限娱乐

1. 候选 = pool **全部**（不排斥前面用过的场 — E 是娱乐尾巴）
2. **允许 §24 retired themes 回归**（E 档作为装饰性 long tail）
3. 按全局 boldness × band_fit 排序取最长尾组合
4. fold ∈ {4, 5}；crs ≤ 1
5. 总赔率 [800, 5000]；不满足 → 调 fold（先减不增）或 None

### §3.4 recommended_single 决策

- A 存在 → `"A"`
- A=None 且 B 存在 → `"B"`
- 全 None → `None`（顶部公示"今日无可用方案"）

**决策硬编码、不算法化** — codex 5/25 的"若只玩一张选 A"是常识不是 EV
计算。首推一张**只标 A 或 B**，绝不标 D/E（防误导）。

### §3.5 strategy 失败容错

每个 strategy 都可能返回 None。渲染时显式说：

```markdown
### D 反大众
> 今日 D 档：候选不足（A∪B 用过 6/9 场，剩 3 场不满足 3-4 串 + 80× 下限）
```

不静默跳过 — 用户要看到引擎尝试了但放弃。

---

## §4 选腿理由结构化 — `LegReason`

```python
@dataclass(frozen=True, slots=True)
class LegReason:
    why_match: str       # 这场入选的引擎理由（≤ 60 字）
    why_market: str      # 这个市场被选的理由（≤ 60 字）
    why_pick: str        # 这个 pick 的盘面解读（≤ 60 字）
    why_not_alt: str     # 没选 alt 的简短交代（≤ 60 字；可为 ""）
```

### §4.1 生成器

每档 strategy 在选完腿后调 `build_leg_reason(leg, tier_code, ctx)` 填充：

- `why_match` 从 PoolSignals 反向取：min_had_odds / draw_implied / 标签
- `why_market` 从档位 selection_strategy 反向：A 档触发 hhad cover 时 →
  `"主胜紧逼下让球是更宽 cover"`；D 档高 contrarian → `"contrarian 分前 20%
  反盘面"`
- `why_pick` 从 leg.pick_label + market 类型反向：had/hhad 用方向语；crs/ttg
  用比分/进球叙事
- `why_not_alt` 从同场其它候选反向：选 hhad 时 → `"没选 had 主胜：1.76 已
  implied 56.8%，加深不增信息"`；信号不足 → ""

### §4.2 模板库

4 个 strategy × 4 段 = 16 个模板字符串，集中放 `_LEG_REASON_TEMPLATES`
模块常量。模板用 Python f-string，参数化 boldness / odds / direction /
gap_pp 等。

"alt" 的定义：同 `match_no` 的其他候选腿（同场不同 market 的 BoldLeg）。
只在 strategy 主动放弃 alt 时（如 A 档 hhad cover vs had 主胜的二选一）才
填 why_not_alt；信号不足或没有 alt 候选 → 空字符串。

### §4.3 兼容

`BoldLeg.reason: str` 字段保留（v1 模块仍用）；v2 在 BoldLeg subclass 或
`@dataclass(frozen=True)` 加 `structured_reason: Optional[LegReason] = None`
字段（默认 None 不破坏 v1 测试）。

---

## §5 渲染层 — `render_tiered_plan(plan)`

### §5.1 顶部公示（沿用 + 新增）

沿用 v1 全套顶部公示行：
- HARD_LABEL（v1 焊死标）
- chaos 行 + 等效独立行 + §17.4 / §18 退化 / §19 同场反向 / §20 盘面共识 /
  §21 主题失谐 / §22 翻面读法 / §24 主题汰留

**v2 新增顶部行（按顺序）**：
1. **金额合计行**（顶部第一行，在 HARD_LABEL 下）：
   `💰 今日方案 · 总建议金额 ¥{stake_total}（multiplier={x}×） · 首推一张 = {recommended_single or "—"}`

### §5.2 每张票渲染

```markdown
### {code} {name}（{folds}串1 · 合计赔率 {odds:.2f} · ¥{stake} · {confidence_tag}）
{以下行 if recommended_single == code:}
> 首推一张（若只玩一张选这张）

- {match_no} {home} vs {away} ｜ [{market_label}] **{pick_label}** @ {tc_odds:.2f}
  > 场理由：{why_match}
  > 选法：{why_market}
  > pick：{why_pick}
  {以下行 if why_not_alt:}
  > 不选 {alt}：{why_not_alt}

  - 后续腿同上 -

{以下行 if bullets:}
> {bullet}
```

### §5.3 缺档渲染

```markdown
### {code} {name}
> {解释失败原因的一行}
```

不显示 ⭐ / 金额 — 缺档就是缺档，诚实展示。

### §5.4 底部脚注（沿用 v1）

```markdown
_「大胆分」是盘面启发式显著性分，不是命中概率；本引擎不预测胜负、长期为负，
仅供娱乐。注金请只用娱乐预算的小额。_
_注金提示：上面多张票相互独立 ≠ 风险分散 —— 它们常共享同几场、会一起赢一起输。
你完全可以只挑一张、或一张都不买。_
```

外加 v2 新增脚注（仅在 recommended_single 非空时）：

```markdown
_首推一张标记只是引擎依据档位优先级给出的常识建议，不是命中概率断言。_
```

---

## §6 复盘 + history schema

### §6.1 `tiered-plan-review.json`

```json
{
  "run_date": "2026-05-25",
  "status": "reviewed",
  "day_chaos": 8,
  "multiplier": 1.0,
  "recommended_single": "A",
  "tiers": {
    "A": {
      "name": "稳健底仓",
      "fold": 2,
      "total_odds": 3.05,
      "stake": 35,
      "legs": [
        {"match_no": "周一008", "market": "hhad", "pick_label": "让负",
         "tc_odds": 1.84, "actual": "让负", "hit": true},
        ...
      ],
      "hits": 2, "graded": 2, "all_hit": true, "pending": false
    },
    "B": {...}, "D": {...}, "E": {...}
  },
  "by_tier_cumulative": {
    "A": {"tickets": N, "ticket_hits": N, "legs": N, "leg_hits": N,
          "stake_total": N, "stake_returned": N},
    ...
  },
  "by_theme_cumulative": {...}  // 沿用 §24 平局收割等主题累计
}
```

### §6.2 `tiered-plan-history.json`

append-only，schema 同上 record 数组。

### §6.3 §24 跨版本累计

`retired_themes_from_history(by_theme)` 接收的 by_theme **合并自**：
- 旧 `bold-review-history.json` 的 cumulative.by_theme
- 新 `tiered-plan-history.json` 的 by_theme_cumulative

合并逻辑：同 theme 的 `tickets / ticket_hits / legs / leg_hits` 字段加和。
平局收割的 23 张 / 63 腿历史汰留判定**不丢**。

### §6.4 stake_returned 字段（新）

每档 review 时计算：

- `all_hit=True` → `stake_returned = stake × total_odds`
- `all_hit=False` 且 `pending=False`（结清失败）→ `stake_returned = 0`
- `pending=True`（跨日待定）→ `stake_returned = None`（不计入累计）

累计 `stake_returned_total - stake_total`（仅算已结清票）给出每档"娱乐
预算消耗速度"（仍非 +EV 声明，只是事实统计）。

### §6.5 review.json 顶层字段（保留 v1）

新 schema 顶层除 §6.1 列出的字段外，**保留 v1** 的：

- `message: str` — 渲染好的 markdown，dispatch 直接喂给 Telegram
- `results: dict[str, dict[str, str]]` — okooo 抓到的赛果（per-match per-market）

这两个字段是 dispatch / Telegram 推送层依赖的契约，不能丢。

---

## §7 验收 + 测试

### §7.1 TDD 覆盖（每条都是一个 fixture-driven 测试）

#### 候选池
- T1: 5/24 退化池 4 场 → v2_candidate_pool 给出 ≥ 6 腿（每场 ≥1.5 腿）
- T2: 5/25 9 场 → v2_candidate_pool 给出 ≥ 14 腿（每场 ~2 腿）
- T3: 单一市场（had-only context）→ pool 退化为每场 1 腿、不崩
- T4: 市场上限：crs 占 > 50% → 砍最低 boldness 的 crs 过量者

#### 4 个 strategy
- T5-T7 A: 正常 / gap-guard 砍光 / 候选不足 < 2 场
- T8-T10 B: 正常 / 全部被 A 排斥 / 赔率档超出
- T11-T13 D: 正常 / 全部被 A∪B 排斥 / 全 contrarian 在 retired theme 里
- T14-T16 E: 正常 / 赔率档命不中 / fold 范围迭代

#### 跨档排斥
- T17: A 用 [008, 009] → B legs 全部不含这两场
- T18: A 用 [008, 009] + B 用 [001, 002, 003] → D legs 全部不含这 5 场
- T19: E 不受排斥约束

#### recommended_single
- T20: A 存在 → "A"
- T21: A=None B 存在 → "B"
- T22: A=None B=None → None
- T23: 渲染顶部金额行包含 "首推一张 = A"

#### LegReason
- T24-T28: 每个 strategy fixture → leg.structured_reason 四段全填 / 模板
  参数对、不空 why_match / why_market / why_pick
- T29: 模板库 banned 词检查（编译期）

#### 渲染
- T30: 完整 5/25 fixture → 渲染含 4 档 + 顶部金额行 + recommended 标
- T31: D=None → 缺档渲染 "今日 D 档：..."
- T32: banned 词检查（全文不含 §0 banned 词）
- T33: --stake-multiplier 0.25 → 35→9, 35→9, 20→5, 10→3（四舍五入）

#### review schema
- T34: tiered-plan-review.json 每档独立 hits / graded / all_hit
- T35: by_tier_cumulative 累加跨日
- T36: §24 跨版本累计：合并 bold-review-history + tiered-plan-history

### §7.2 集成测试

- T37: `jczq-tiered --date today` live 跑、写文件、不崩
- T38: `jczq-tiered --replay 2026-05-24` 重现 5/24 → 4 档输出
- T39: `jczq-tiered --replay 2026-05-25` → recommended_single 非 None

### §7.3 v1 兼容性

- T40: `bold_combos(legs, chaos)` 仍正常工作（v1 模块完整保留）
- T41: §24 retired_themes_from_history 仍接受旧 by_theme 格式

### §7.4 退役步骤

按顺序、可逆：

1. 落码 + 测试绿（不动 launchd / dispatch）
2. 手动跑 `jczq-tiered --date today` 验收输出
3. 跑 `jczq-tiered-review --date 2026-05-24` 验收复盘
4. launchd plist 切换：**新建** `com.nutmeg.jczq.daily-tiered.plist` 和
   `com.nutmeg.jczq.tiered-review-8am.plist`，`launchctl load`；同时
   **unload** 旧 `daily-bold` / `bold-review-8am`（保留 plist 文件 1 周
   作为 rollback），1 周后删除旧 plist 文件
5. 观察 3 天（5/26、5/27、5/28）
6. 3 天若稳定 → memory 标 bold-combos archive、CLI 改 deprecated 提示
7. 2 周后从 CLI 注册表移除 bold-combos / bold-review entry，模块代码保留

### §7.5 不在 v2 范围内

- **不**改信号层（5 信号 / boldness / chaos / pool_signals 不动）
- **不**改 §17.1 anchor gap-guard 阈值
- **不**改 §18-§24 任何公示文字（仅在 v2 顶部新增 §5.1 金额行）
- **不**做可配置档位（X2 方案被拒）
- **不**做模型 import（D 档不接 Poisson）
- **不**改 bold-combos v1 源码

---

## §8 成功标准

- 5/25 重跑：4 档输出，A 档 hhad cover 触发（008/009 让球替代 had 主胜），
  B/D 主腿不含 A 用过的场
- 5/24 重跑（退化池）：v2 给出 4 档输出（≥3 档非空），不再 5 张同主题换皮
- recommended_single 行清楚标 A 或 B
- 顶部 §24 平局收割汰留通知保留触发
- 每张票每条腿至少 3 行 narrative（why_match / why_market / why_pick）
- 全量 `pytest` 绿；新增 ~40 测试全过
- launchd 2 周稳定运行无 crash

---

## §25 v2.1 — 5/25 复盘后增量（2026-05-26 落地）

### §25.0 背景
5/25 v2 首日 4 张全输（0/4 票、2/14 腿、−¥100）。诊断（见 memory
[[jczq_5_26_v2_1_landed]]）：

1. A 档"压舱"假象：008/009/002 had 全 1.76+，无 ≤1.50 触发 hhad cover；
   3 串 6.86× ≈ 大胆票
2. BDE 高度耦合：`pick_lottery_tier` 显式 `_ = excluded` 让 E 与 BD 同场
   同向押注；B/D 之间又无"同场反向 hhad 禁止"
3. D "反大众"=押让球反面 / 无 contrarian 有效性门控；今天大众站对 6/9，
   contrarian 反咬

§25 三条规则全部为公示 + 选腿硬约束，**不**改信号层、**不**改 §17/§18-§24
任何既有条款（与之并存）。

---

### §25.1 方向 1 · A 档真稳健化

**触发条件 + 行为**：
- `pick_anchor_tier` 候选池中**必须**存在至少 1 条 `had ≤ ANCHOR_REQUIRE_HOT_THRESHOLD`（默认 **1.65**）
  的"真热门"场次（不需要这条腿必须被选中，只是池子里要有，证明今晚有真信号）
- 若 A 三串总赔率 > **5.5**，自动降级到 2 串组合（在 fold_range 内允许 2-3）
- 同时新增上限：A 2 串总赔率必须 ≤ **4.0**；3 串总赔率必须 ≤ **5.5**
- 若上述两条任一不满足 → `pick_anchor_tier` 返回 `None`，**A 档不出**

**首推降级**（Q1a）：A 不出时 `recommended_single` 优先级链
**A → D → B → None**（注意 D 提到 B 前，因为 D 的 contrarian 启发式比 B 的纯
boldness 主方案更有"为什么选这场"的逻辑骨架；同时 D 也跟着方向 3 的门控）

**渲染文案**：
- A 不出时 brief 顶部加一行：`⚠️ A 档因无 ≤1.65 真热门、或总赔率超 5.5 上限，今晚不出`
- 首推改成 D 时：`> 首推一张（A 档不出，本档为今晚最高优先级娱乐票）`

**默认常量**：
```
ANCHOR_REQUIRE_HOT_THRESHOLD = 1.65
A_3FOLD_TOTAL_ODDS_HARD_CAP   = 5.5
A_2FOLD_TOTAL_ODDS_HARD_CAP   = 4.0
```

---

### §25.2 方向 2 · BDE 跨档去重升级

**§25.2.a · E 不再忽略 excluded**
- `pick_lottery_tier(...)` 删除 `_ = excluded`，改为 `excluded = a∪b∪d_match_nos`
- 候选池过滤同 B/D
- 若过滤后腿数 < `fold_range[0]`（即 4）→ E 返回 `None`，¥10 转 ¥0（Q2a）

**§25.2.b · B↔D 同场反向 hhad 禁止**
- 在 D `pick_contra_tier` 选 hhad 腿时，**额外**约束：
  - 若该场已在 B 选 hhad 让 X，则 D 不可选同场 hhad 让 Y（Y ≠ X）
  - 这条约束**不**适用 had/ttg/crs/其它市场（仅约束 hhad 同场反向）
- 实现：传入 `b_hhad_picks: dict[match_no, pick_label]`，在 D 候选过滤阶段剔除

**§25.2.c · 渲染文案**
- E 不出时 brief 加：`⚠️ E 档因跨档去重后剩余腿 < 4，今晚不出`
- D 因 §25.2.b 跳过某腿时 debug 日志记录（不写到用户面）

---

### §25.3 方向 3 · hhad 健康度门控

**滚动窗口 + 累计读取**：
- 读最近 **14 天** review 历史中所有"已 graded、市场=hhad"腿
- 按 `actual` 方向聚合：`让胜 hit_rate / 让平 hit_rate / 让负 hit_rate`
- 样本量阈值：**总 hhad 腿数 ≥ 30** 才启用门控；否则 disabled-state（contrarian 正常开）

**门控规则**：
- 若 `让胜 hit_rate ≥ 55%` → D / E 候选池**剔除** pick∈{让平, 让负} 的所有 hhad 腿
- 若 `让负 hit_rate ≥ 55%` → D / E 候选池**剔除** pick∈{让平, 让胜} 的所有 hhad 腿
- 若 `让平 hit_rate ≥ 55%` → D / E 候选池**剔除** pick∈{让胜, 让负} 的所有 hhad 腿
- 三者都 < 55% → 不剔除（contrarian 正常开）

**B 不受门控影响**（B 是 boldness 主方案，不是 contrarian；门控仅约束"反大众"
和"长尾娱乐"两档）

**渲染文案**（顶部摘要）：
- 启用时：`📊 hhad 健康度 14d：让胜 X.X% / 让平 Y.Y% / 让负 Z.Z%（N 腿）— D/E 已剔除 W 条反向腿`
- 未启用：`📊 hhad 健康度样本不足（N<30 腿），D/E contrarian 正常开`

**累计数据来源**：
- 复用 `cumulative.by_tier` / `tiered-plan-history.json` 的 graded leg 数据
- 新增 reader：`recent_hhad_market_health(history, days=14)` → dict

---

### §25.4 验收标准

- 5/25 数据重跑：
  - A 档**不出**（008/009/002 had 全 ≥1.76 > 1.65；2/3 串总赔率均 > 上限）
  - `recommended_single = "D"`（B 因 §25.2.b 检查仍能出；D 排在 B 前是 §25.1 强制顺序）
  - E 档**不出**（BDE 互斥后剩余场次不足 4）
  - 整票数 4 → ≤ 2（B + D）
  - 当日"建议总注金"从 ¥100 → ¥(B 35 + D 20) = ¥55，多出 ¥45 公示为"今晚不下"
- 5/24 数据重跑：v2.1 仍能给出至少 1 档非空
- 全量 `pytest` 绿；新增 ≥15 测试覆盖三条规则

### §25.5 不在 v2.1 范围内
- 不改信号层 / 5 信号 / boldness / chaos
- 不动 §17-§24 任何既有条款
- 不引入 Poisson / 模型层
- 不改 launchd 频率（仍 12:00 出方案、次日 08:00 复盘）
- 不动 stake_multiplier 行为

---

## §26 v2.2 — 5/26 复盘后增量（2026-05-27 落地）

### §26.0 背景

5/26 是 v2.1 首日正式生产。派发：A 2 串 @3.31 ¥35 + B 3 串 @59.42 ¥35
（全 hhad）+ D/E 不出。截至 5/27 复盘已知：001 ✅（A 第 1 腿）/ 002 让负 ❌
（B 第 2 腿坐实，B ¥35 输）/ 004 ✅（B 第 1 腿）；007 / 005 / 006 待 okooo
刷新。

诊断（见 memory [[jczq-5-25-retro-debate]] + [[2026-05-26]]）：

1. **B 又是全 hhad** — 5/25 retro 分歧 4 已经诊断「B 应允许 ttg 中线腿混搭」，
   §25 没动 B → 5/26 重复犯（5/25 B 87.55× 全 hhad → 5/26 B 59.42× 全 hhad）
2. **005 弗拉门戈 had None 仍进 B 候选池** — A 因 has_real_favourite 把
   它过滤，但 v2_candidate_pool 没有同等"是否真有这个市场"的源头过滤。
   这是 v1 generator 退役同源的"未开盘场误报"
3. **D 在 calm 日若退化成 over-leveraged contrarian 仍会被首推** — 5/25 retro
   分歧 5 的 D 4 串 177.27× 即此例；5/26 没出 D 没触发，但仍是潜在风险

§26 五条规则保持 §25 风格：公示 + 选腿硬约束 / 渲染层，**不**改信号层、
**不**改 §17-§25 任何既有条款（与之并存）。

---

### §26.1 方向 1 · v2_candidate_pool had 可用性过滤

**触发条件 + 行为**：

- `v2_candidate_pool` 入口先过滤：`match.tc_odds` 中无任何 `v > 1.0` → 整场剔除
- 该过滤**只**影响 B/D/E 的候选池（A 走 `matches` 直链，已有 has_real_favourite）
- 渲染时不公示（透明降级，和 §17 gap-guard 风格一致）

**默认常量**：无（硬约束）

**实现**：`_match_has_usable_had(match) → bool` 复用 `bold_leg_for_market`
内部判据 `v and v > 1.0`。

---

### §26.2 方向 2 · pick_main_tier · ttg 必含 + hhad 集中度

**§26.2.a · sort key 升级**

`pick_main_tier` 候选排序：`ttg < hhad < had < 其它`（数字越小越靠前）。
让 `candidates[: fold + 4]` 搜索窗口在 ttg 存在时一定看到 ttg 腿。

**§26.2.b · B 强制 ≥1 ttg 腿**

候选池里**存在**至少 1 条 ttg → B 的每个组合必须包含 ≥1 条 ttg 腿。
ttg 候选**不存在** → 约束 disabled（graceful degrade，A 池里若全是 had/hhad
仍能出 B）。

**§26.2.c · B/D ≤2 hhad legs 硬上限**

`MAIN_MAX_HHAD_LEGS = 2`、`CONTRA_MAX_HHAD_LEGS = 2`。3 串 B / 3-4 串 D
都不允许全 hhad；至少有 1 条非 hhad 腿（B 通常是 ttg, D 可能是 had/ttg/crs）。

**§26.2.d · B 候选池排除 hhad odds ≥ 5**

`MAIN_HHAD_HIGH_ODDS_CUTOFF = 5.0` — 主方案不该被 hhad 超长尾腿托高赔率。
仅作用于 B，D 不动（D 是娱乐档可接受高赔率 hhad）。

**默认常量**：
```
MAIN_MAX_HHAD_LEGS         = 2
CONTRA_MAX_HHAD_LEGS       = 2
MAIN_HHAD_HIGH_ODDS_CUTOFF = 5.0
```

---

### §26.3 方向 3 · 首推 D 安全网（calm 日 over-leveraged 不首推）

**触发条件 + 行为**：

A=None 且 D 存在 + 大盘面 `chaos < SINGLE_RECOMMEND_CALM_CHAOS_MAX`（默认 20）：

- D 票 fold > `D_SINGLE_RECOMMEND_MAX_FOLD_CALM`（默认 3）→ D 不首推
- D 总赔率 > `D_SINGLE_RECOMMEND_MAX_ODDS_CALM`（默认 180）→ D 不首推
- D 全 hhad（hhad_count == len(legs)）→ D 不首推
- 其余情况（B 存在）→ 不再继续降级到 B；`recommended_single = None`，公示"今晚不首推"

**渲染文案**：D 仍正常渲染为娱乐票，但顶部"首推一张 = —"。

**默认常量**：
```
SINGLE_RECOMMEND_CALM_CHAOS_MAX     = 20
D_SINGLE_RECOMMEND_MAX_FOLD_CALM    = 3
D_SINGLE_RECOMMEND_MAX_ODDS_CALM    = 180.0
```

---

### §26.4 方向 4 · review 从派发 markdown 还原

**问题**：复盘要打的是"昨晚实际派发的票"，但 `replay_tiered_plan` 默认会从
当日 sporttery snapshot + 当前最新规则**重跑**。规则一迭代，replay 结果就
和实际派发不一致 → 复盘把"今天的规则"硬套到"昨天的数据"上，等于自证清白。

**行为**：

- `replay_tiered_plan(run_date, output_dir)` 优先读 `daily/<date>/tiered-plan.md`
- 解析出 4 档票面 + 首推标记 + multiplier + chaos → 还原 `TieredPlan` 对象
- 若 markdown 不存在或解析失败 → fallback 原 replay 通路（首日 / 历史数据无 dispatch 记录的情况）
- review schema 不变（grading 仍走原 `grade_leg`）

**实现**：`_load_saved_markdown_plan(run_date, output_dir)` 用 regex 解析
4 档表头、腿行、顶部 chaos+multiplier+首推；构造 BoldLeg / TieredLeg / Tier。

---

### §26.5 方向 5 · v1 generator 退役标记

- `jczq-daily-advisor` + `jczq-daily-review` 顶部打 `⚠️ DEPRECATED` banner
- banner 引用 5/25 retro 分歧 2（005 弗拉门戈 v1 仍出票）+ 指向 `jczq-tiered`
- **不**删代码、**不**动测试、**不**改 launchd（launchd 早已切到 tiered）
- 后续若 14 天观察 jczq-tiered 稳定 → §27 可考虑完全移除 v1

---

### §26.6 验收标准

- 5/26 数据重跑（用旧 markdown 还原）：
  - review 结果 = 实际派发票（A 2串 @3.31 / B 3串 @59.42 / D-E 不出）
  - 累计 `by_hhad_actual` 正确填充（5/26 已观察到 让平+1、让负+1）
- 全量 `pytest` 绿；新增 ≥3 测试覆盖 §26.1 + §26.2.a/b
- 用 5/26 当天 BoldMatch 数据跑 select_tiered_plan（5/27 live 数据）：
  - had None 场不出现在 B/D/E 腿中
  - B 若出且 ttg 池非空 → B 含 ≥1 ttg 腿
- `jczq-daily-advisor --dry-run` 顶部打出 deprecated banner（人工肉眼验证）

### §26.7 不在 v2.2 范围内

- 不动 §25.4 候选「hhad 让球反面通道」（仍按 5/25 retro 说的"等 10+ 天追踪"）
- 不删 v1 generator 代码（仅打 banner）
- 不动信号层 / boldness / chaos
- 不改 launchd 频率
- 不引入"每天 shadow 看一下假如允许 hhad 反面通道 A 会选什么"的追踪（next iteration backlog）

---

## §27 v2.3 — 5/27 复盘后增量（2026-05-28 落地）

### §27.0 背景

5/27 是 v2.2 落地后首个完整 loop 复盘。三个版本全军覆没：

- **v2.2 自动票（launchd 12:00 派发）**：B 3 串 @71.40 全 hhad+had / D 3 串 @129.03。
  已结算 3 场，**腿 0/3 命中**、B+D 两张整票已死。
- **Claude finalize**（debate 立场）：B 3 串 @18.62 / D 3 串 @62.77。已结算 1/2 graded
  腿命中（003 让负 ✅），B 也已死，D 全待定。
- **GPT 立场**：A 2 串 @3.19 全 hhad 让负预启用 §25.4 → 0/2 全错；B/D 待定、E 已死。

诊断（见 [[2026-05-28]] / [[jczq-5-25-retro-debate]]）：

1. **v2.2 D 选了 002 让胜（GPT direct Poisson edge = -22%）** — D 候选层完全没有
   Poisson edge 检查；contrarian 选腿本来就容易选低 edge 腿
2. **003 强胆主胜 1.30，v2.2 B 选 hhad 让平@3.30（boldness 0.35）而非让负@2.93** —
   按 boldness 排序选了更"大胆"的让平；但 0:1 客胜 → 让负命中。Claude finalize 选的是
   让负（命中）
3. **ttg 池空时 B 退化到 had 5.40 单点冷腿** — 5/27 没有 ttg 候选，v2.2 §26.2 ttg-min
   约束自动 disabled 优雅降级。退化的 B 是结构性隐患
4. **review 累计混算了 v2/v2.1/v2.2 三个版本的腿命中率** — 迭代分析时混淆基线
5. **001/002 都是 1:0 → hhad 让平**：让球 -1 + 主队最小胜的 hhad 标准结果，
   三个版本都没押让平。需要 14d 追踪才能判断是否结构性

§27 五条规则：硬证据驱动 + 渲染层补足 + 数据卫生 + shadow 追踪，**不**改 §17-§26
任何既有条款（与之并存）。

---

### §27.1 方向 1 · D 候选直 Poisson edge 硬过滤

**触发条件 + 行为**：

- 新常量 `D_LEG_EDGE_HARD_FLOOR = -0.15`
- 新公开函数 `compute_d_poisson_edge_index(matches, dc_rho=0.0)` 返回 dict
  `(match_no, market, pick_label) -> edge`
- `select_tiered_plan(..., poisson_edge_index=...)` 新增可选参数，None 时维持
  v2.2 行为（向后兼容）
- `pick_contra_tier(..., poisson_edge_index=...)` 在候选过滤阶段剔除 edge ≤
  `D_LEG_EDGE_HARD_FLOOR` 的腿
- 实现策略：**raw** Poisson edge（不带 R25/F2/F3 偏差），mirror GPT 的 direct check
- CLI 层（`nutmeg jczq-tiered`）在 fetch matches 后调用一次，传入 select_tiered_plan

**默认常量**：
```
D_LEG_EDGE_HARD_FLOOR = -0.15
```

---

### §27.2 方向 2 · 强胆场 hhad 让球反方向优先

**触发条件 + 行为**：

- 新常量 `STRONG_FAV_HAD_THRESHOLD = 1.50`
- 新内部函数 `_strong_fav_reverse_hhad(matches)` 返回 dict
  `match_no -> "让负"|"让胜"` for strong-fav 场（main fav 是主队 → 让负反向；
  main fav 是客队 → 让胜反向；平局 fav 罕见跳过）
- `pick_main_tier` sort key 升级：在 §26.2 排序的基础上，hhad 候选里
  "强胆场反方向 pick" 优先级 > 其它 hhad pick
- 不动 D 档（D 是 contrarian、思路本就反向）

**5/27 验证**：003 had 1.30 主胜场 → 反向 = 让负。v2.2 自动 B 选了 hhad 让平（错），
Claude finalize 选了 hhad 让负（命中）。§27.2 落地后 v2.2 自动 B 在 003 上会自动
选让负。

---

### §27.3 方向 3 · ttg 池空 + B 出票时的渲染层警示

**触发条件 + 行为**：

- `TieredPlan` 新增字段 `ttg_pool_empty: bool` (default False)
- `select_tiered_plan` 计算 `ttg_pool_empty = not any(lg.market == "ttg" for lg in pool)`
- `render_tiered_plan` 在顶部公示区加：当 `ttg_pool_empty AND b_tier is not None` →
  `⚠️ ttg 池空，B 已退化为 hhad+had 混搭（无中线腿稀释让球反向）`
- 不动选腿逻辑、不动 §26.2 ttg-min 约束 disabled 的优雅降级行为

---

### §27.4 方向 4 · review 累计 by_version 分组

**触发条件 + 行为**：

- `TieredPlan` 新增字段 `version: str` (default "v2.3")
- `_load_saved_markdown_plan` 把 version 设为 "v2.x"（派发时引擎版本未知）
- `_day_record` 把 `plan.version` 写入 day record
- `_cumulative` 新增 `by_version` 字段：`{version: {tier_code: {tickets, leg_hits, ...}}}`
- `render_tiered_review` 当 history 含 ≥2 个版本时，加"按引擎版本分组"块
- 老 history 记录缺 version → 自动归到 "v2.x"（degrade gracefully）

---

### §27.5 方向 5 · 让 -1 盘面 hhad 让平 shadow 字段

**触发条件 + 行为**（仅累计、不用于决策）：

- `_day_record` 新增字段 `by_hhad_actual_let_neg_one: dict[str, int]`，counts
  actual hhad direction restricted to graded legs whose match has `hhad_line == -1.0`
- 数据来源：`_try_load_match_hhad_lines(run_date, output_dir)` 从 sporttery
  snapshot 复用 `bold_matches_from_sporttery` 拿 hhad_line 映射
- 当 snapshot 缺失（历史回填）→ 跳过 shadow 字段（不写到 day record）
- 14 天后人工分析：让 -1 盘面下 hhad 让平 实际命中率 → 决定是否启用"让 -1 让平
  通道" backlog

---

### §27.6 验收标准

- 5/26 数据 markdown 还原后复盘：B 仍展示原 3 串 @59.42 hhad（不被新规则改写）
- 5/27 数据 replay（v2.3 规则）：D 候选层会拒掉 002 让胜（edge -22%），B 在 003
  上会选让负而非让平
- 全量 `pytest` 绿；新增 ≥6 测试覆盖 §27.1 + §27.2 + §27.3 + §27.6
- `nutmeg jczq-tiered` live 跑 5/28 盘面验证：D 票面不再含 edge < -15% 的腿
- review markdown 展示 by_version 块（已含 v2.x + v2.3 ≥2 个版本时）

### §27.7 不在 v2.3 范围内

- 不动 §25.4 候选「hhad 让球反面通道」（仍守"等 10+ 天追踪"纪律；GPT 5/27 A 失手
  也支撑了这个纪律）
- 不动信号层 / boldness / chaos
- 不引入 Poisson 主信号回归（§27.1 只是把 Poisson edge 作过滤层，不是当选腿主信号）
- 不改 launchd 频率
- 不删 v1 generator（v2.2 §26.5 已加 banner）

---

## §28 v2.4 — R25 双向化（2026-05-28 落地）

### §28.0 背景

5/27 复盘后用户提出对瑞超/挪超/芬超做联赛级校准。调研发现的反直觉数据
（`.nutmeg-data/jczq/memory/strategy-memory.json` 200 条 Poisson residuals）：

| 联赛 | ttg n | ttg avg residual | 解释 |
|---|---|---|---|
| 瑞超 | 4 | +0.40 | 实际进球 > 预期（符合"北欧高进球"直觉，待 5 样本） |
| 挪超 | 8 | **-0.31** | 实际进球 < 预期（模型**高估**进球） |
| 芬超 | 5 | **-0.96** | 实际进球远低于预期（严重高估） |

诊断：大众认知"北欧高进球"已经被 Poisson 模型**过度 calibrate** —— 从 had odds
反推 lambda 时把"北欧高进球先验"放进去，导致预测进球数本身偏高、实际反而偏低。

**R25 原版的盲点**：单向（只触发 `avg > 0 → -0.10` 衰减低球 alpha）。挪超 n=8
avg=-0.31、芬超 n=5 avg=-0.96 都达到样本门槛但触发不了任何 bias —— 模型高估
进球的联赛缺补偿机制。

### §28.1 R25 双向化

**触发条件 + 行为**：

- 保留原 R25 单向逻辑：`avg residual > 0 AND n ≥ 5 → delta = -0.10`（衰减低球
  alpha for 模型低估进球的联赛）
- 新增反向：`avg residual ≤ POISSON_LEAGUE_BIAS_NEG_THRESHOLD AND n ≥ 5 → delta
  = +POISSON_LEAGUE_BIAS_NEG_DELTA`（加强低球 alpha for 模型高估进球的联赛）
- 中性区间 `avg ∈ (-0.30, 0]` 不触发任何 bias（避免噪声驱动）
- 仅作用 ttg/crs 池；had/hhad/hafu 不受影响（同 R25 原版）

**默认常量**：
```
POISSON_LEAGUE_BIAS_MIN_SAMPLES = 5    # 原值
POISSON_LEAGUE_BIAS_DELTA       = -0.10 # 原值（model under-prices goals）
POISSON_LEAGUE_BIAS_NEG_THRESHOLD = -0.30  # 新增
POISSON_LEAGUE_BIAS_NEG_DELTA   = +0.05    # 新增（更温和，因新方向证据较弱）
```

**5/28 实测触发结果**（200 条 residual 样本上）：
- 负 delta（衰减低球）：解放者杯 / 意甲 / 德甲 / 西甲 / **瑞超**
- 正 delta（加强低球）：**芬超 / 挪超** + 惊喜两项 **日职 / 法甲**

**法甲反转的意义**：5/13 R25 当时是 `-0.10`（low估进球），数据更新后转为 `+0.05`
（高估进球）—— 验证了 R25 设计为 **rolling** 而非一次性的优势。

### §28.2 验收标准

- 现有 R25 单向测试（≥4 条）继续绿
- 新增 ≥2 测试覆盖反向触发 + 中性区间不触发
- 真实 strategy-memory.json 数据上跑出至少 1 个反向 delta 联赛（实际跑出 4 个）
- compute_poisson_edges 调用方（jczq_brief / jczq_daily）无需改动 — 双向 delta
  天然兼容现有 `edge = edge + bias_map[league]` 加法语义

### §28.3 不在 v2.4 范围内

- 不动 had/hhad/hafu 联赛级偏差（独立 v2.5 backlog）
- 不加 hardcoded 联赛 prior（纯数据驱动，瑞超 n=4 等 1 个样本就会自动触发）
- 不引入 league-pair 交互（pool×league 的更细粒度 bias）
- 不动 hi-vol 联赛清单（HIGH_VOL_LEAGUE_OVERRIDE）

---

## §29 v2.5 — A 档 gap-guard「欧赔同认热门」豁免（2026-05-29 落地）

### §29.0 背景

5/28 是一个**满盘热门兑现日**：5 场全是主胜热门，已赛 4 场全部主胜
（001 1:0 / 002 2:0 / 003 2:0 / 004 4:1，005 强胆主胜待定）。但 tiered 引擎
**A/B/D 三档全空票**，只出了 E 极限娱乐（反着打黑马让球）2/4。引擎在全年
对底仓最友好的一天，反而只出了反热门的娱乐票。

诊断（`.nutmeg-data/jczq/daily/2026-05-28` 真实盘面重放，见
[[jczq_5_29_v2_5_landed]]）—— **§17.1 anchor gap-guard 把 5 场里 4 场真热门
误杀**：

| 场 | 体彩主胜 | 体彩 implied | 欧赔 fair | gap (体彩−欧赔) | gap-guard | 赛果 |
|---|---|---|---|---|---|---|
| 001 | 1.51 | 0.662 | 0.570 | **+0.092** | ❌ 误杀 | 1:0 主胜 ✅ |
| 002 | 2.10 | 0.476 | 0.399 | +0.077 | 保留 | 2:0 主胜 ✅ |
| 003 | 1.52 | 0.658 | 0.572 | **+0.086** | ❌ 误杀 | 2:0 主胜 ✅ |
| 004 | 1.13 | 0.885 | 0.750 | +0.135 | ❌ 误杀 | 4:1 主胜 ✅ |
| 005 | 1.27 | 0.787 | 0.654 | +0.133 | ❌ 误杀 | 强胆待定 |

被误杀的 4 场**全部主胜兑现**。A 档候选只剩 002 一条 → 无法组 2-3 串 →
A=None；B/D 池只有 hhad+crs（had 全被挤出、ttg 池空）→ 也空。

**问题本质**：`_favourite_had_leg` 的 §17.1 gap-guard 在
`体彩 implied − 欧赔 fair ≥ ANCHOR_GAP_THRESHOLD (0.08)` 时丢热门，本意是抓
"体彩凭空造热门、欧赔不认"的**分歧盘**。但对**短赔真热门**，体彩在短赔上的
抽水 + 主队溢价天然就 >8pp —— 这是结构性 margin，不是分歧。结果 gap-guard
把 A 档赖以生存的真热门系统性清空。gap-guard 对中赔（1.7-2.5）"公众造的假
热门"仍有效，但对短赔 sharp-confirmed 热门是误杀。

### §29.1 A 档 gap-guard 欧赔同认热门豁免

**触发条件 + 行为**：

- 在 `_favourite_had_leg` 的 gap-guard 命中分支里加豁免：当
  `gap ≥ ANCHOR_GAP_THRESHOLD` 时，若**欧赔也认这是明确热门**
  （`fair ≥ EURO_CONFIRM_FAVOURITE_PROB`，默认 0.55，即欧赔 ≤ ~1.82）**且**
  体彩溢价不离谱（`gap < EURO_CONFIRM_MAX_GAP`，默认 0.20）→ **保留腿**
  （sharp-confirmed，gap 是短赔 margin 非分歧）
- 否则维持原 §17.1 行为：丢腿
- 仅作用 A 档 had 腿（`_favourite_had_leg` 只被 `pick_anchor_tier` 调用）；
  B/D/E 走 `v2_candidate_pool` 不受影响
- 欧赔快照缺失（`fair` 为 None / 0.0）→ 整体跳过 gap-guard（同 §17.1 既有
  行为，不变）

**默认常量**：
```
EURO_CONFIRM_FAVOURITE_PROB = 0.55   # 欧赔认热门概率门槛
EURO_CONFIRM_MAX_GAP        = 0.20   # 体彩溢价上限（超过仍视为陷阱）
```

**gap-guard 三类行为（落地后）**：
- 中赔热门（fair < 0.55）+ gap ≥ 0.08 → **仍丢**（公众造假热门，§17.1 原意）
- 任意热门 + gap ≥ 0.20 → **仍丢**（体彩真造大陷阱）
- sharp-confirmed 短赔热门（fair ≥ 0.55 且 gap ∈ [0.08, 0.20)）→ **保留**（新）

### §29.2 验收标准

- 5/28 数据重放（live 规则）：A 档恢复出票 = 3 串主胜
  `001胜@1.51 × 003胜@1.52 × 002胜@2.10` @4.82（落 [2.5, 5.5] cap）；
  首推 = A；B/D/E 仍 None（满盘热门日不出反热门票，正确）
- 三条 gap-guard 行为各有测试覆盖（保留 sharp-confirmed / 仍丢中赔假热门 /
  仍丢离谱溢价 / 无欧赔跳过）
- 全量 `pytest` 绿；新增 ≥5 测试

### §29.3 不在 v2.5 范围内

- 不动 B/D/E 的 `v2_candidate_pool` 路径（had 被挤出是 boldness 排序结果，
  满盘热门日 B/D 不出反热门票本身合理）
- 不动 §17.1 ANCHOR_GAP_THRESHOLD (0.08) 本身、不动中赔区间行为
- 不动 A 档 §25.1 per-fold cap (4.0/5.5) 与 has_real_favourite 门槛
- 不动 hhad cover swap（短赔 ≤1.50 仍走 §3.3 让球 cover；004/005 不在最低 3
  腿组合里，未受影响）
- 不动信号层 / boldness / chaos

---

## §30 v2.6 — 校准驱动迭代（元规则，2026-05-30 落地）

### §30.0 背景

5/29 回测（见 [[jczq_5_30_calibration_landed]]）：9 场打出 **5 平**（平局基准
~25%、期望 ~2.4 场，实际 5 = 约 2σ 扎堆）。竞彩 A（008 波黑主 × 007 布兰主）
0/2 全灭——008 国际赛 0:0 平、007 主场 1:2 负；当日净 −¥45。tiered v2 累计
**5 天 0/9 整票、净 −¥225**。

两条诊断，都不是"再加一条选腿规则"能解的：

1. **resulting 谬误 + 校准沟通错**：把 56–59% 的腿叫"铁胆/最稳"。从 6 天
   24 条已结算腿的真实校准表看，**implied 0.50–0.60 桶实际只命中 40%**
   （hhad 让球腿 3/16=18.8%、had 胜平负 4/7=57%）。59% 不是 lock，是"十把
   输四把"。判断对错要看过程与概率口径，不看单次结果。
2. **规则 churn = 对单日噪声过拟合**：review.md 当天自动写"策略记忆已更新：
   舒服盘防平防冷"。这正是 R1–R29 一天一条堆出来的老毛病——5 平就加"防平"，
   下周对攻又得加"防冷"，左右挨打。5 天样本无法支撑任何选腿规则的统计显著性。

§30 是**元规则**：用累计校准取代单日加规则，并校正概率沟通口径。**不改选腿
逻辑**（v2.5 及以前全部保留），只改"如何迭代"和"如何表述"。

### §30.1 校准日志（calibration log）

- 工具：`scripts/jczq_calibration.py`（5/19 §17 留的空壳，5/30 填实）
- 数据：读所有 `daily/<date>/tiered-plan-review.json` 的已结算腿
  （`hit` 非 None），每腿一行 `(date, tier, match_no, market, pick, odds,
  implied=1/odds, hit)`
- 产物：`.nutmeg-data/jczq/calibration-log.json`（数据，gitignore）+
  按 implied 概率桶 / market / tier 的实际命中率表
- 概率桶：`[0,.40) [.40,.50) [.50,.60) [.60,.70) [.70,1]`

### §30.2 迭代纪律（核心元规则）

1. **桶 n < `MIN_BUCKET_N`（默认 30）→ 标 `thin`，不据此改任何东西。**
   5 天只有 24 腿、桶全是个位数，远不到改模型的统计门槛。
2. **单日结果只入账（写进 review/calibration-log），不触发新规则。**
   冻结/回滚"当日 review.md 自动写入"的规则记忆（含 5/29 那条"舒服盘防平
   防冷"）——它们是噪声驱动。
3. **只有桶 n ≥ 30 且实际命中偏离桶中点 ≥ `CALIB_TOLERANCE`（默认 0.12）
   才允许改模型**，且改的是概率映射/市场权重，不是再加 if-then 选腿规则。
4. **承认非 edge**：引擎自标"−13% 抽水、长期为负"。5 天 0/9 整票符合纯娱乐
   工具的方差，不是"规则不够多"。停止为追整票命中而堆规则。

### §30.3 概率沟通口径（表述规则）

- **禁用"铁胆/最稳/稳胆"等确定性词**描述 < 0.75 implied 的腿。
- 输出一律附**显式概率 + 反面**：如"约 6 成、会输 4 成"，而非"胆"。
- "首推一张"保留（档位优先级常识），但不得升级为命中断言（§5.4 已有脚注）。

### §30.4 唯一允许严肃追踪的两个结构 edge

其余信号停止迭代。只对这两个"我方概率 vs 市场概率的系统性偏差"追踪校准：
- **§29 体彩−欧赔 gap**（sharp-confirmed 豁免阈值 fair≥0.55 / gap<0.20 的
  实际表现；样本够了再决定收紧到 0.58 / 0.15）
- **§28 R25 联赛进球偏差**（挪超/芬超高估进球的反向 delta 是否兑现）

### §30.5 不在 v2.6 范围内

- 不改任何选腿逻辑（A/B/D/E strategy、§17–§29 全部保留）
- 不加新的 if-then 选腿规则（这正是 §30 要停止的行为）
- 不把 calibration-log 接进 launchd 自动管线（手动跑 `scripts/jczq_calibration.py`
  审阅即可；样本到 30+ 再考虑自动化）
- 不动信号层 / boldness / chaos

---

## §31 软热视角 —— 读盘决策因子（2026-05-30 落地；定位修订）

> **本节是"读盘视角/创作因子"，不是"待验证的 portfolio 策略"。** 这个游戏
> 引擎 spec §0 焊死无 edge、长期 −13% 抽水——**正 EV 在这里不存在也无意义**。
> 所以 §31 的目的不是"找一个长期正收益的打法"，而是给单场决策**多一个可调用的
> 视角**：让我看一场具体比赛时，有能力识别出"这场的正确打开方式也许是平/冷/
> 反面"，把它作为丰富方案的**因子**纳入候选——服务**单场创作的丰富度与命中**，
> 不是组合的长期期望。
>
> ⚠️ **定位修订（2026-05-30）**：早版（§31.6 原文）把软热反面做成"用 30 样本
> ROI 判生死"的策略评测，结论"反面 ROI −0.257 被证伪"。**这是用错了尺子**——
> 在 −13% 抽水的游戏里任何打法 ROI 都为负，用 ROI 否决一个因子，等于因为"它不
> 是印钞机"就扔掉一把创作工具。**撤回那个"证伪"判决**：softchalk 数据不是 ROI
> 裁决器，是**读盘参考**（见 §31.6 重定位）。

### §31.0 读盘锚 — 大热未必兑现（context，非"溢价"论证）

`scripts/jczq_draw_analysis.py`（6 天 62 场）：

| 读盘事实 | 数值 |
|---|---|
| 正路低赔热门直接赢 | 37%（23/62）|
| 平/冷（任一非正路结果发生） | 63% |
| 平局率 | 27%，且**成块**：5/27、5/28 各 0 平；5/24、5/25、5/29 各 5 平 |

**怎么用**：这是**读盘 context**——"跟着每个大热押正路，多数场次会被某个意外
打断"。它提醒我**别默认大热=稳**，要在每场问"这场的意外剧本是什么"。它**不是**
"反面有溢价、押反面赚钱"的论证（那个用 ROI 想问题，错）。布兰 5/29：1.66 主热
三方共识 1:2 输——它教的不是"该押反面赚钱"，是"软热不配当 A 底仓稳腿、它的今晚
剧本值得我多想一层"。

### §31.1 热门三分层（读盘标签）

看每个大热时贴一个标签，决定**用什么视角读它**：

| 标签 | 判据 | 读盘视角 |
|---|---|---|
| **硬热** | had ≤ ~1.50 **且** 欧赔 fair ≥ 0.55 **且** 有逻辑（实力差/赛意/主客场）| 可正路做胆 |
| **软热** | had 1.55–2.10、或体彩强欧赔半信（fair < 0.52）、或舒服盘标签 | **不默认正路稳腿**；这一场的剧本值得多想：平？冷？还是有独立理由仍站正路？|
| **coinflip** | vig 高 + 三方接近 | 无明确热门，最便宜方式表达或跳过 |

### §31.2 软热作为因子的用法（核心：因子，不是机械动作）

软热标签**只是把这场标记为"值得多想一层"**，具体怎么打由**这一场的单场逻辑**
决定，三选一，由创作判断不由统计：

1. **有独立基本面/盘口理由倒向反面**（客场无力被高估、赛意低、体彩 implied 远高
   于欧赔 fair 的假热）→ 把平/冷作为这场的表达，吃它的高赔；
2. **有理由仍站正路**（硬实力差、主场绝对优势）→ 正路，但知道它只是软热不是 lock；
3. **两边都没有过硬单场理由** → 这场不做胆/少碰/极小注，把预算让给更有把握的场。

**和 D 档盲反的区别**：D 档机械反"大众站哪边"、还串大票；§31 是**针对某一场、有
单场逻辑、作为众多因子之一**地考虑反面——是创作，不是规则。**不要把软热反面变成
"逢软热必反"的机械动作**（早版错误），也不要"逢软热必跳过"（更早的过度保守）。

### §31.3 表述口径（接 §30.3）

- 每个大热**显式标层**（硬热/软热/coinflip）+ 显式概率（"约6成、会输4成"），
  禁用"铁胆/最稳"。
- 多轮争议中**默认给"多想一层"的勇气**：软热不要因为"三方共识"就缩回正路
  （布兰=决策疲劳回归大众的反面教材）；但倒向反面要有这一场的具体理由。
- 守 [[jczq_advice_style]]：不默认"完全不打/跳过"，给"有逻辑的大胆落点"。

### §31.4 softchalk-track 的定位 —— 读盘参考，不是 ROI 裁决器

`scripts/jczq_softchalk_track.py` + `softchalk-track.json` **保留**，但定位修订：

- **它是什么**：决策时可快速调出"这类盘面（某赔率带/某联赛的软热）历史上都怎么
  走了"——平/冷分布、哪个方向常爆——作为**读这一场盘的 context**，帮我把软热
  因子**用得更准**。
- **它不是什么**：不是"软热反面 ROI 是正是负 → 决定这个因子生死"的评测器。在
  −13% 抽水的游戏里 ROI 永远负，那个判决无意义（早版 §31.6 的错）。
- **怎么读**：看分布与条件（例如"挪超软热里客胜爆得多/瑞超软热平多"），作为单场
  剧本的灵感来源，不看汇总 ROI。

### §31.5 不在范围内

- 不改 A/B/D/E strategy 代码（因子/视角层，非代码层）
- **不用 ROI / 正 EV 评判任何因子的生死**（这个游戏里正 EV 无意义——这是 §31
  定位修订的核心）
- 不把软热反面变成机械动作（逢软热必反 / 必跳过都错）
- 不动信号层 / boldness / chaos

### §31.6 softchalk-track 首次回填（读盘参考数据，非 ROI 判决）

`scripts/jczq_softchalk_track.py` 回填 5/24–5/29 全部软热场（fav_odds 1.50–2.10），
每场记录软热的反面方向 + 实际 had。**这些数字是读盘参考，不是给方向判生死的 ROI。**

首批读盘事实（30 场软热）：
- 软热**正路**实际兑现 53%、软热**单一反面方向**兑现 23%（其余是另一个反面方向）。
- 读法：软热正路兑现率（53%）确实明显低于硬热，**印证"软热不配当稳腿"**；但单押
  一个反面方向命中也低（23%）——**说明软热的价值不在"机械押反面"，而在"逐场判断
  这一场的意外往哪边走"**。这正是把它当**因子**（逐场判断）而非**策略**（统一押
  反面）的实证理由。
- `softchalk-track.json` 每日复盘累积，**用于读盘时查分布**，不计算/不展示汇总 ROI
  作为决策依据。

### §31.7 后续（仍是因子库扩充，非收益评测）

软热是读盘因子库的第一把。后续可加的**读盘因子**（都按"丰富单场创作"用，不按
ROI 评判）：
- **§29 体彩−欧赔 gap**：体彩 implied 远高于欧赔 fair 的"假热"——读盘时一个强
  信号（欧赔是独立 sharp 基准），提示这场正路可能被资金灌水，值得多想反面。
- **§28 R25 联赛进球偏差**：特定联赛进球高/低估，读 ttg/比分剧本时的 context。
- 每个都进 softchalk-track 式的**读盘参考表**（查分布、找剧本），不做 ROI 裁决。

## §32 单一决策入口 `jczq-today` —— agent 编排层系统化（2026-06-04 落地）

> 背景见 `docs/jczq-decision-chain-critique.md`。根因：用户工作流是"让 agent（GPT/Claude）
> 跑 jczq 分析组合任务"，但**没有钉死的确定性入口**——每个 agent 自行即兴挑命令/引擎/Poisson，
> 导致 GPT 与 Claude 路径分叉（"每次跳出系统、隔离决策"）。§32 用一个入口 + 一份共读指令根治。

### §32.0 目标函数按档分配（定性，驱动文案）
- **A 稳健底仓** = 唯一可能有结构 edge 的桶，只追 §29 gap + §28 R25 两个假设；证不出就是低方差锚。
- **B/D/E** = **明确零 edge、纯方差塑形/娱乐**。**停止给 B/D/E 套任何"正 EV/edge"叙事**
  （§31.5 已定调：−13% 抽水里正 EV 无意义）。Poisson 地板（§27.1）保留**只作"别买明显被
  dominated 的腿"的卫生过滤**，不作 edge 主张。
- **整套 brief/packet** = 决策卫生 + 盘面阅读记录；过程价值 > 单日输赢。

### §32.1 命令
`nutmeg jczq-today [--date|--replay] [--stake-multiplier] [--write] [--dispatch-telegram]`
内部复用 `jczq-tiered` 的抓盘→`select_tiered_plan`，再产出**决策包**（不重造票面）。
落盘 `daily/<date>/today-packet.md`，**并同时写 `tiered-plan.md`**（=§A 的 `render_tiered_plan`），
让 `jczq-tiered-review` 次晨能 grade 派发原样（§26.4），从而 jczq-today 可作唯一每日 launchd 任务。
replay 不覆盖（守 §26.4）。

**launchd 整合（2026-06-04）**：每日只留 `com.nutmeg.jczq.daily-today`（12:00 跑 jczq-today），
复盘留 `tiered-review-8am`；卸载 daily-bold / daily-tiered / daily-review-8am / bold-review-8am。

### §32.2 决策包结构（`render_today_packet`）
1. **钉死指令头**（给任何 agent）：① 这是今天唯一决策源，别在退役 generator/旧 brief/各 spec
   间即兴；② §A 是引擎已定票面，照单或整张不买，**勿改腿**；③ 只在 §C 裁量问题上动判断，按
   schema 作答；④ 你与别的 agent 在某 q_id 答案不同 = 该场高不确定 → **减注/剔除**，非二选一赌运气。
2. **§A 引擎票面**：原样嵌入 `render_tiered_plan(plan)`。
3. **§B 盘面底座（引擎口径，无 generator 偏差）**：
   - B1 热度分层表（引擎原生分类，见 §32.3）。
   - B2 Poisson +EV 列表：来自 `compute_d_poisson_edge_index`（raw，无 R25/F2/F3），edge ≥ +5%。
4. **§C 裁量问题 + 作答 schema**：见 §32.4。无触发则显式写"今日无裁量问题，照 §A 执行"。

### §32.3 引擎原生热度分类（`classify_heat`，不碰 generator analytics）
对每场取最低主胜/客胜 had（favourite）：
- `≤ 1.50` → **硬热(短赔)**（仅赔率口径；§31.1 完整硬热还需欧赔 fair≥0.55+逻辑，packet 标"短赔"诚实降级）
- `1.55–2.10` → **软热**
- favourite `> 2.10` 且三方接近 → **coinflip**
- 其余 → **普通**

### §32.4 裁量问题派生（`derive_judgment_questions(plan, matches)` — 确定性、有界）
只枚举引擎触发的真裁量点，**不让 agent 重审全盘**：
- **Q_A_EMPTY**：`tiers[0] is None` → "今晚无稳健底仓(A=None,原因…)；接受空底仓 / 有理由强做一注？"（default=接受）
- **Q_ALL_EMPTY**：所有 tier 为 None → "今日盘面无任一档；空仓？"（default=空仓）
- **Q_B_DEGRADED**：`ttg_pool_empty and tiers[1] is not None` → "B 退化为 hhad/had 混搭；仍出 B？"（default=仍出）
- **Q_SOFTHOT_<match>**：每场 favourite∈[1.55,2.10] **且出现在已出票的某档** → "<对阵> 软热@<odds>，引擎默认<pick>；§31.2 这场剧本：平 / 冷 / 还是有独立理由仍站正路？"（default=引擎默认 pick）
作答 schema：`| q_id | 你的决定 | confidence(1-5) | 一行理由 |`

### §32.5 共读指令（§33 收尾时落地，本节先建命令）
`CLAUDE.md` + `AGENTS.md` 加同一段："被要求跑 jczq 每日分析组合时，只跑 `nutmeg jczq-today`，
把输出当决策；不要即兴；只在 §C 按 schema 作答。"

### §32.6 不在范围（本次）
- 不动 A/B/D/E 选腿逻辑、不动 boldness/chaos、不动 §1-§31 任何选腿规则。
- 不删退役 generator（§33 大裁剪再做归档）；本次只新增入口，不破坏现有命令。
- 决策包是**渲染层 + 派生层**，纯确定性，无 LLM 调用。

### §32.7 验收
- `derive_judgment_questions` 单测覆盖：A 空 / 全空 / B 退化 / 软热腿出现在票中才问 / 软热不在票中不问。
- `classify_heat` 单测覆盖四档边界（1.50 / 1.55 / 2.10）。
- `render_today_packet` 结构测试：含指令头、§A 嵌入、§B Poisson 列表（有/无 +EV 两路）、§C schema；无裁量问题时显式公示。
- CLI `jczq-today` 冒烟：replay 一个已存快照能出包、落盘 today-packet.md、replay 不覆盖。

## §34 反面引擎 —— 补足大胆度/多样性（2026-06-07 落地）

> 背景：用户质疑"系统缺多样性与大胆度、不稳定场给不出犀利反面"。06-06 实证：鹿岛vs神户
> pick'em，旧系统/Claude 选了"平"，实际**神户客场 5-0**——该站的犀利反面（神户客胜 @2.92）
> 被系统结构性错过。根因（决策链 critique §4/§5）：A 档"热门焊死"(had≤1.65)，pick'em 混战
> 不够格进 A 直接撤退；唯一反面档 D 被 loss-churn 阉割且只能当零 edge 小注 → 反面读永远升不了正格。

### §34.0 定位
**非 edge、非概率断言**（−13% 抽水无正期望），是**读盘视角**：系统性挑出"该站反面"的不稳定场、
允许高信心当一等候选，而不是跳过或降格成彩票。`nutmeg/services/jczq_contrarian.py`。

### §34.1 `compute_contrarian_reads(matches)` — 三个可计算结构信号（不嘴算）
热门 = 主/客胜里 had 更低者。
- **euro_inflated（最强·触发器）**：体彩 de-vig implied(热门) − 欧赔 fair(热门) ≥ `EURO_FADE_GAP=0.05`
  → 欧赔(独立 sharp)不认、体彩灌水 → 站反面（§29 gap 反向用法）。
- **pickem（触发器）**：|implied(主)−implied(客)| < `PICKEM_SPREAD=0.12` → 真混战、热门光环虚。
- **soft_fav（仅信心加成·不触发）**：热门 had ∈ [1.55,2.10]（§31）。单独不触发——否则几乎每个
  中等主队热门都被标反面，糊成 monochrome 噪声（06-06 demo 实测教训）。
- 反面落点：有欧赔→取非热门里 euro−体彩 value 最高边；否则 pickem→冷门胜。
- 信心：euro_inflated×2 + pickem + soft_fav → 强反(≥3)/中反(2)/弱反(1)；按信心+灌水幅度排序。

### §34.2 并进决策包
`render_contrarian_section` 渲染「§D 反面视角」，`render_today_packet` 在 §C 后追加。每个
jczq-today 决策包现在都带 §D。06-06 回放：§D 唯一喊出「周六201 站客胜」= 神户 5-0 实际命中。

### §34.3 不在范围 / 验收
不改 A/B/D/E 选腿、不声称 edge、soft_fav 不当触发器。纯确定性、无 LLM、无 I/O。
11 测试 `tests/test_jczq_contrarian.py`：pickem/euro_inflated 触发、soft_fav 单独不触发、
信心分级、排序、渲染、神户 pick'em 命中。

## §35 机会雷达底座 —— 多视角持续增强（2026-06-07 落地）

> 背景：用户要"持续增强决策系统的多元化与创造力、挖不被注意的机会、作为未来决策的底座"。
> 关键洞察：系统**已经在算却没用上**的信号还有好几类（drift/dispersion/大小球价值）；缺的不是
> 再加规则，是一个**可插拔的"读盘透镜"底座**——每个透镜从不同角度扫盘喊一类机会。

### §35.0 底座结构（`nutmeg/services/jczq_opportunity.py`）
- 统一 `Opportunity`(lens/match/pick/confidence/reason) + 透镜协议 `(matches)->list[Opportunity]`。
- `LENSES` 注册表：**加未来透镜 = 追加一行 (名, 函数)**，不动调用点。这就是"持续增强多样性"的扩展点。
- `scan_opportunities` 跑全部透镜分组排序；`render_opportunity_radar` 渲染「§D 机会雷达」。

### §35.1 已落地透镜
- **反面**（§34 适配）：pickem / euro_inflated 找被高估热门、站反面。
- **异动**：欧赔 opening→live de-vig 移动 ≥ `STEAM_MIN=0.04`（sharp money 流向）；叠加体彩
  lag（欧赔 live − 体彩 implied ≥ `LAG_MIN=0.04` = 体彩没跟上 = 价值窗口）。强/中/弱。
- **大小球**（§35.4，全新进球维度）：体彩 ttg 聚合到欧赔大小球线比 P(over)，
  |欧赔−体彩| ≥ `TOTALS_MIN=0.06` → 价值在大球/小球（与胜平负正交，最大化多样性）。

### §35.2 跨透镜共振
同一场被 ≥2 透镜指向**同一边** → 🔆 头条标"今晚最值得注意"。多视角独立同意 = 信号最强。

### §35.3 并进决策包 + 验收
`render_today_packet` §D 改用 `render_opportunity_radar(scan_opportunities(matches))`
（替代单一反面段）。05-30 回放渲染反面 6 条；合成 demo 反面+异动共振头条触发。
后续可挂透镜：分歧盘 dispersion / 平局价值 / R25 联赛偏差 —— 各注册一行。
14 测试 `tests/test_jczq_opportunity.py`。非 edge/非概率、纯确定性、无 LLM、无 I/O。

### §35.4 launchd 全迁移（2026-06-07）
自动化彻底切到新系统：unload daily-bold/daily-tiered/daily-review-8am/bold-review-8am，
留 `daily-today`（12:00 jczq-today）+ `tiered-review-8am`。老命令(jczq-daily-*/bold-*)仅手动可跑。
