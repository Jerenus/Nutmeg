> ⚠️ **历史规划稿（M2 已于 2026-07-07 完成）**：本文的"活岛"描述与 Tier 处置均为 pre-M2 状态，旧引擎已全部下葬；现行系统见 CLAUDE.md SOP。

# JCZQ 决策系统重构路线图 —— 该删什么 / 为什么 / 什么时候

> 立于 2026-07-06 系统级复盘之后（见 memory `jczq-7-06-system-retro`）。
> 目标：让整个决策过程**可持续、可复制、有专业度与智慧**。
> 核心方法论：**做减法优先，绝不大爆炸重写**。本仓自己的历史（Rules A-J → R1-R28
> → tiered v2.1-2.6 的坟场、下注 0/38 的教训）证明了"只加不减"就是失败模式；
> 一次性重写会用新形式重犯这个病。

---

## 0. 一句话诊断

这个仓是一部**决策考古地层**：每次复盘往上叠一层，几乎从不移除下面的层。
`CLAUDE.md` 开头那句"忽略退役路径，只跑这一条 SOP"就是化石——你已经在用一条钉死的
入口**绕过**自己的历史，而不是清理它。工程投入与实际价值**完全倒挂**：26000 行引擎
实证近零 edge，而唯一有价值的判读层是最薄、最新、最缺基础设施的一层。

---

## 1. 依赖事实（2026-07-06 实测，不是猜测）

用 AST 传递闭包分析（脚本见 §6）实测：

- **活决策路径 `jczq-today` 只触及 60 个内部模块里的 26 个**。
- **`jczq_daily`（2974 行，标 DEPRECATED）不在活路径闭包内**。它有 14 个 importer，
  但那 14 个（`jczq_intelligence` / `jczq_parlay_constructor` / `jczq_baseline` /
  `jczq_diagnostics` / `jczq_brief` / `jczq_review` / `jczq_debate` …）**本身也全是退役簇**，
  互相引用成一座**可分离的孤岛**，活路径够不到。→ 这推翻了"删不掉"的初判：**能删，是孤岛不是承重墙。**
- **唯一真正的承重墙是 `jczq_bold_combos`（2284 行）里的"内核"部分**：活引擎
  `jczq_tiered` 从它 import 一批**数据类 + 常量 + 纯函数**（`BoldLeg` / `BoldMatch` /
  `PoolSignals` / `RetiredTheme` / `MARKET_LABELS` / `ticket_theme` / `chaos_band` /
  `compute_pool_signals` / `day_chaos` …）。`bold_combos` 自己**不** import `jczq_daily`。
  → 内核干净可抽取；抽走后 `bold_combos` 剩下的 v1 generator 逻辑变成可独立归档的死重。

### 结论：系统能干净切成两座岛

| 岛 | 代表模块 | 状态 | 处理 |
|---|---|---|---|
| **活岛**（~26 模块） | jczq_today → jczq_tiered → bold_combos(内核) → jczq_poisson → worldcup/* | 在跑、在产出、在记账 | 保留 + 加固 |
| **退役簇** | jczq_daily / jczq_brief / jczq_debate / jczq_review / bold_combos(v1 逻辑) / conflict_* | 无人在活路径调用 | 分阶段归档删除 |

---

## 2. 该删什么（按依赖安全度排序）

### Tier D1 — 零运行时风险，随时可删
1. **过期一次性 launchd 任务**：`wc-retro-0624` / `wc-retro-0625` / `wc-retro-1500`
   指向 6 月过期脚本，且按 Day/Hour 每月重复触发跑陈旧脚本。→ **已在 Phase 0 卸载。**
2. **退役 Rule 书文档**：`docs/jczq-decision-framework.md`（542 行，已标 LEGACY 退役
   Poisson generator）。它描述的 Rules A-J / R1-R28 是**误导 agent 的死规则源**（正是
   "决策路径不一致"根因）。→ **已在 Phase 0 加 tombstone 指向本路线图。**
3. **一次性 retro 脚本**：`scripts/wc_retro_2026062*.py` 系列（对应上面的 launchd）。

### Tier D2 — bold 引擎 ✅ 2026-07-06 已删除
- 停 3 个退役 launchd（daily-bold / bold-review-8am / daily-review-8am，plist 已备份）。
- 删 `jczq_bold_combos`(1583) + `jczq_bold_review` + `jczq_second_leg` + 3 测试 + 3 CLI 命令。
- 补全 R1：活 CLI 懒加载的快照 I/O（fetch/persist sporttery + bold_odds）补进 kernel。
- 1051 测试全绿 + jczq-today replay 逐字一致。

### Tier D3 — ⚠️ 前提被证伪：jczq_daily 簇不是可删退役码，是活工具底座
> **2026-07-06 删除执行中的实测发现（推翻本路线图初判）**：用 AST 逐命令 + 逐 CLI 文件
> 追接线后确认——所谓"退役簇"的核心**深植在 LIVE 客户端/分析工具里，不是孤岛**：
>
> | 模块 | 被谁钉住（活） |
> | --- | --- |
> | `popularity` | client-service / daily-operator / popular-matches 命令 |
> | `jczq_daily`(2974) | `build_telegram_bot_runner` → 每日 advisor 服务（telegram-bot 活命令） |
> | `jczq_conflict_*` / `jczq_intelligence` | `build_match_brief_payload` → match-brief / analyze-match 命令 |
> | `jczq_debate` | `jczq_web`（web 驾驶舱活功能）+ cli builder |
> | `jczq_review` | cli `build_jczq_daily_review_service` |
> | `jczq_final_plan_pdf` | `worldcup/report_pdf`（世界杯日报，活） |
>
> **结论**：删这些不是"清死代码"，是**删活功能**（telegram 日报 advisor / match-brief /
> analyze / web 驾驶舱 / 世界杯 PDF 字体）——那是**产品决策，不是重构**。
>
> **要真正删掉 jczq_daily 簇，前置条件是先决定"退役这些客户端/分析/telegram 功能"**，
> 或投入一次专门的解耦（把 telegram-bot / match-brief 从 jczq_daily provider 抽出、
> 把 worldcup PDF 字体助手从 final_plan_pdf 抽出）。两者都需用户拍板 + 独立一轮工作。
> **在没有这个决策前，Tier D3 不执行**——诚实优先于"删干净"的观感。

### Tier R1 — 承重墙内核抽取（真重构，非删除）✅ 2026-07-06 已完成
8. **从 `bold_combos` 抽出共享内核** → 新模块 `nutmeg/services/jczq_market_kernel.py`（943 行）：
   75 个符号 = `BoldLeg` / `BoldMatch` / `PoolSignals` / `RetiredTheme` / `GradedLeg` +
   常量 + 盘口解析/去水/信号打分纯函数（`ticket_theme` / `chaos_band` /
   `compute_pool_signals` / `day_chaos` / `bold_leg_for_market` / `grade_leg` …）。
   机械提取（脚本保留原始文本/顺序，行为不变）；`bold_combos` 2284→1583 行，反向 import 内核。
   **成果**：3 个活入口 `jczq_today` / `jczq_tiered` / `jczq_tiered_review` 传递闭包
   **全部脱离** bold_combos(v1 generator) + bold_review。双重安全网验证：1204 测试全绿 +
   `jczq-today` / `jczq-tiered-review` 端到端 replay 产出与抽取前逐字一致。
   → `bold_combos` 剩下的 v1 组合 generator 现在只被 CLI + 退役 bold_review 引用，归入 Tier D 删除。

---

## 3. 结构性改造（删除之外的三条铁律）

### R2 — 数据 > 代码 的版本策略
现状：v2.1-v2.6 以字符串 tag + `if` 分支烤进 `jczq_tiered` / `jczq_tiered_review`。
目标：引擎逻辑**无版本**，版本差异全部是**配置/参数**（`calibration-log.jsonl`
已经这么做，是全仓唯一做对的地方）。迭代 = 改一行参数 + 记一条校准，不是改代码加分支。
→ 可持续、可复制、可回测。

### R3 — 账本升为一等公民（单一真源）
现状：四本账互不相通——`tiered-plan-history`（引擎）/ `bold-review-history`（bold）/
`judge-ledger`（判读）/ `zucai-ledger`（足彩，刚约定）。
目标：**统一成一个带 `layer` 字段的 ledger**，才能回答"这套系统整体长期是赚是赔"
这个最重要的问题——当前架构**结构性地无法回答它**。
判读层的 `judge_ledger`（2026-07-06 刚修好、刚验证）是最干净的雏形，以它为基座扩展。

### R4 — 淘汰机制制度化（这才是"智慧"）
智慧不在更多规则，而在**知道哪些规则该死**。本仓已证明自己会生成规则（Rules A-J、
R1-R28），却几乎没有淘汰规则的机制。
目标：每条规则带**上线日期 + 支撑样本量**；账本定期反问"哪条规则的实证支撑已消失"，
然后删掉它。`spec §30` 反 churn 纪律是雏形，扩展成全系统元规则。

---

## 4. 什么时候（时序纪律）

**现在（世界杯窗口内，7/19 前）——只做零风险减法，不碰活路径。**
理由：系统在跑、在积累判读层数据，而那数据是唯一有价值的东西。任何活路径手术都会
打断它。已执行的 Phase 0 见 §5。

**7/19 世界杯结束后——地质清理主体。**
理由：那时判读层有完整一届样本可定论，退役代码可安全下葬，四本账可合并。
执行序：Tier R1 内核抽取（解耦活岛）→ Tier D2 逐个摘 CLI → Tier D3 整簇归档 →
R2 版本参数化 → R3 账本统一 → R4 淘汰机制。**每步一 commit、每步跑全套测试。**

**永远——每次复盘落地新规则时，同时问"这条规则替代了哪条旧规则？旧的删了吗？"**

---

## 5. Phase 0 执行记录（2026-07-06 已完成）

- [x] 卸载并删除 3 个过期一次性 launchd 任务（wc-retro-0624/0625/1500）+ 对应 plist。
- [x] `docs/jczq-decision-framework.md` 加 tombstone 顶注，明确指向本路线图（不删正文，
      保留历史可考，但 agent 一眼看到"别用"）。
- [x] 本路线图落库，作为 7/19 后执行的单一依据。

Phase 1+（Tier R1/D2/D3/R2/R3/R4）**推迟到 7/19 后**，理由见 §4。

---

## 6. 复现依赖分析的脚本

```python
# 传递闭包分析:找出哪些模块不在任何活入口可达范围内(候选归档)
import ast
from pathlib import Path
root = Path("nutmeg")
graph = {}
for p in root.rglob("*.py"):
    if "__pycache__" in str(p): continue
    mod = str(p.with_suffix("")).replace("/", ".")
    deps = set()
    try: tree = ast.parse(p.read_text(encoding="utf-8"))
    except Exception: continue
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("nutmeg"):
            deps.add(n.module)
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.startswith("nutmeg"): deps.add(a.name)
    graph[mod] = deps
def closure(start):
    seen, stack = set(), [start]
    while stack:
        m = stack.pop()
        for d in graph.get(m, ()):
            if d not in seen: seen.add(d); stack.append(d)
    return seen
# ⚠️ 关键:入口要包含所有活 CLI 命令,不只 jczq-today,否则 jczq_web /
#    jczq_apifootball_odds / jczq_judgment_answers 等会假阳性
```

> 关联：`CLAUDE.md` / `AGENTS.md` SOP · `docs/jczq-mixed-bet-judge-process.md`（判读层
> runbook）· `docs/jczq-decision-chain-critique.md`（根因复盘）· memory
> `jczq-7-06-system-retro`。