# 实验本体对象扩采样设计（2026-09-20）

> 用户 2026-09-20 裁定：把前瞻实验的采样对象从「足彩当期 14 场」扩到「竞彩全板 ∪ 足彩当期」。
> 本文只做设计，实施计划见 `docs/superpowers/plans/2026-09-20-experiment-population-expansion.md`。

## 1. 出发点：今天的实际集合关系

2026-09-20 实测：竞彩板面 **30 场**，足彩 26131 **14 场**，且 **14/14 全在竞彩板面上**。
⇒ **足彩 ⊂ 竞彩板面**，并集 = 竞彩板面 = 30 场，交集 = 14 场。

但实验对象**不是并集**：

| 实验 | population | falsifier.stratum | 窗口 | duties | 今天实际覆盖 |
|---|---|---|---|---|---|
| R0 | jczq | jczq | date_from 2026-09-20, n≥200 | `match-research` **scope=match** | **30/30** |
| F9 | **both** | **pooled** | date_from **2026-09-20**, n≥60 | `balance-ledger` scope=day `--issue {issue}` | 14（实现所限） |
| F5 | **both** | **pooled** | date_from 2026-09-19, n≥120 | **无 duty** | 0 |
| F2 | zucai | zucai | issue 26126–26137, n≥140 | `f2-observation` scope=day | 14 |
| F1c | zucai | zucai | issue 26129–26140, n≥140 | `dispersion-observation` scope=day | 14 |
| F3 | zucai | zucai | issue 26125–26136, n≥120 | 无 duty | 0 |
| F8 | zucai | zucai | date_from 2026-09-20, n≥120 | 无 duty | 0 |

**缺口**：今天为 16 场竞彩独有比赛付出的深研成本，只被 R0 的覆盖率计数与赛后语料吃到，
没有进入任何一条**前瞻**实验样本。

## 2. 边界裁定：什么能改，什么必须另立

⛔**`population` 与 `falsifier.stratum` 是注册表冻结字段，不是 duty 字段。**
RSI 纪律「原件全冻结，改判据＝另立新 exp_id」覆盖它们。窗口内改口径＝已累计样本作废。

因此分三类，**不得混做**：

### A 类 · 注册表已写 both/pooled，只是 duty 实现没跟上 → 扩实现，不动原件
- **F9**：`population=both` / `stratum=pooled` / 窗口 date_from 2026-09-20（今天起）/ **n=0**。
  其 duty `balance-ledger` 的 instrument 写死 `--issue {issue}`，**这是实现缺陷不是判据**。
  ⇒ 合法扩到竞彩全板。
- **F5**：`population=both` / `stratum=pooled` / **duties 为空**。
  ⇒ 首次定义 duty 时直接按并集定义，不存在"改"的问题。

### B 类 · 注册表冻结为 zucai 且窗口已开 → 一律不动，到期结账
- **F2**（已 n=11）、**F1c**、**F3**、**F8**。
  若要竞彩样本，**另立姊妹实验**（建议 `F2j` / `F1cj` / `F3j` / `F8j`），
  `population=jczq`、`stratum=jczq`、新窗口、判据文本原样复制。
  ⛔不得把姊妹实验的样本并进原实验的 n。

### C 类 · 已经是 match 级 → 无需改
- **R0**。它是现成的参照实现（`scope=match` + `deadline_rule=match_kickoff`）。

## 2.5 板面规模与日期口径（2026-09-20 追加）

**板面场数是变量，设计不得依赖它。** 仓内只有 2026-09-19 / 09-20 两天的 `jczq-legs-base.json`
（深研桥 09-19 才落地），均为 30 场——**这是 n=2 的观察不是常态**。
`matches_for_population` 一律读文件返回实际长度，任何位置不得出现常数 30。

⚠️**`day` 指业务日，不是自然日。** 实测 26131 的比赛日为 `['2026-09-20','2026-09-21']`，
但 14 场**全部**落在 `daily/2026-09-20/` 一个板面文件内（场9 尤文 09-21 00:00、
场10 米兰 09-21 02:45 都在其中）。按自然日切分会把跨零点开球的比赛整批分错桶——
26131 有 6 场在 09-21 凌晨。**实现必须以板面文件所在目录名为准，不得用 kickoff 的日期重新分桶。**

⚠️**`issue` 可能为 None。** 传统足彩不保证每天开期（实测 26126–26131 恰好逐日连续，
但这不是保证）。`population="both"` 在 `issue is None` 时**必须静默降级为 `jczq`**，不得抛错——
这正是 T4b 那个 bug 的同型。

📌**已知限制（写进结账报告，不在本次修）**：F9/R0 的 `n_min` 按**场**计数，
板面大的日子贡献样本多，故结账样本系统性偏向大板日，而大板日的联赛构成与小板日不同。
这影响的是样本代表性，不影响本次实现；是否分层由用户在结账前裁定。

## 3. 改造内容

### 3.1 `rsi schedule` 支持按 population 展开 match 级 duty
现状：`scope=match` 的 duty 只有 R0 在用，由 `after_am` 触发、按竞彩板面逐场生成。
改造：让 `schedule` 对任何 `scope=match` 的 duty 都按其 `population` 决定对象集合——
`jczq`→竞彩板面全场；`zucai`→当期 14 场；`both`→并集（今天等于竞彩板面，但**必须按并集算而非假设包含关系**，
因为体彩板面与足彩选场并非恒定包含，见 26130 有 2 场未对齐、26131 有 6 场未对齐）。

### 3.2 F9 的 duty 由 day 改为 match，instrument 去掉 `--issue` 硬绑
`rsi balance` 已支持 `--day`（见 `rsi_wiring.py:134`）。
改造后 F9 逐场记 belief/prior 拨动，竞彩场的 belief 取 `daily/<day>/reads.json`，足彩场取 `<issue>-reads.json`。
**口径统一**：两边都用 `balance_ledger.balance_row()`，不新增算法。

### 3.3 F5 首次定义 duty（并集，match 级）
F5 题目已写「足彩 −6.2 / 竞彩 −9.7」，设计上就吃两边。按并集定义 `scope=match` duty。

### 3.4 姊妹实验登记器
`rsi register` 增加 `--fork-from <exp_id> --population <p> --window-from <x>`：
复制原件的 claim/mechanism/falsifier 文本，只换 `exp_id`/`population`/`stratum`/`window`，
并在新件里写 `forked_from`。**拒绝 fork 已结账的实验**。

## 4. 不做什么

- ⛔不动 F2/F1c/F3/F8 的任何冻结字段
- ⛔不把竞彩样本并进 zucai 的 n
- ⛔不改任何 falsifier 阈值、分档、stop_rule
- ⛔不改判读或票面逻辑——本次改造只碰采样范围

## 5. 验收

1. `uv run nutmeg rsi status` 里 F9 的 n 按**竞彩全板场数**增长，不再等于足彩 14
2. F2/F1c/F3/F8 的 `population`/`stratum`/`window`/`falsifier` 与本文表格**逐字节一致**（未被改动）
3. `rsi schedule --day <今天>` 为 F9/F5 生成 match 级 duty，数量 = 并集场数
4. 新增测试：`population=both` 且足彩有场次不在竞彩板面时，并集计算正确（用 26130 的 2 场未对齐做夹具）
