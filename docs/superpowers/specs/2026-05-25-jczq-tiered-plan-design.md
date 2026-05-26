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
