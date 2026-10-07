# 传统足彩·人群偏离笔记本（Crowd Notebook）· 设计

日期：2026-10-07 ｜ 状态：路线 A、第一/二段已批；**r2（同日）数据源修订已批：逐场人群比例拿不到 → 改为官方奖金反推人群** ｜ 后续：`docs/superpowers/plans/2026-10-07-zucai-crowd-notebook.md`
依赖：`2026-09-18-rsi-experiment-persistence-design.md`（RSI 实验对象，已落地）、
`2026-09-19-zucai-structure-lane-design.md`（face_status / tiers / 枚举器；本文是它的前置数据层）、
`scripts/zucai_prize_model.py`（奖金模型 `log(奖金)=a+b·S`，本文在它上面加人群特征）

## 0. 一句话

足彩是奖池均分游戏：edge 不来自「我比真相准」，只能来自「我和人群分开的地方人群是错的」。
本设计给系统一本**老彩民的笔记本**：每条人群偏离假说用人话写、用谓词触发、按 RSI 结账；
人群偏离不靠任何网站的投注比例，而是**从全国官方奖金里反推**——某类面开出时奖池比市场预期多付，
说明全国人群少买了它。机器从历史奖金残差里提名，人签字后才登记；线索（Clue）进初稿为 advisory，
人 `deploy` 后才成为枚举约束。**逐场本体继续做底料，但对足彩只交市场 P 与事实层否决。**

## 1. 为什么改（记分牌证据）

| 期 | 逐场处方 | 票面 | 死因层 |
|---|---|---|---|
| 26103 | 14/14 | 8/9 | 结构（第五个更好的理由） |
| 26104 | 13/14 | 全版本同死 | 结构（牌照单选） |
| 26098 | 12/13 | 钱票全灭 | 结构（先砍全包后砍裸单） |
| 26123 | 14/14 | 8/9 | 结构（全包名额换一格即 +29,255） |
| 26133 | — | 两票全灭 | 结构（两票共享两裸单，联合同死≈60%） |

逐场判断力相对市场 ≈ 0：F14 训练行 −1.4pp≈市场；F9 belief≡prior；403 天 gym 无策略族 ROI 为正。
奖金由板面冷热决定：现行奖金模型任九 n=41、b=1.007（CI 0.91–1.11）、corr 0.949、残差 sd 0.62——
**b≈1 说明全国人群整体按市场概率买；残差 0.62 就是人群与市场不一致的全部空间**。

## 2. 用户裁定

| # | 裁定 |
|---|---|
| N1 | 「人性的偏离」= **投注人群（奖池对手）**的系统性偏爱 |
| N2 | 运行方式 = **老彩民的笔记本**：假说人话可读、每期找实例、赛后自动记账、假说有生死 |
| N3 | 假说来源 = **机器提名，人签字**；机器自主生成/淘汰（Dream 路线）不做 |
| N4 | 实现路线 = **A**：挂在 RSI 实验层，不另起账本 |
| N5′ | 基准概率 = **市场去水概率，全部期次统一取 zgzcw `europeSp`**（单一源）；校准不硬编码——热门带若有偏，自己就是一条可提名的特征 |
| N6′ | falsifier = **假说特征在奖金残差回归里的系数 γ**（每多开一个触发面，任九奖金变化 %）的 CI；方向由假说声明 |
| N7 | 数据路线 = **反推人群**（r2）：观测源不可得，不留观测源接口（YAGNI） |

**r2 数据源勘察（2026-10-07）**：500「本站用户投注比例」列被 CSS 隐藏、`/static/public/jczq/json/popularity/{sfc,rj}/<期>.json` 当期与历史全 404；zgzcw `renqiInfo` 26050–26135 全空；okooo 405。zgzcw `zcplayvs.action?lotteryId=13&issue=<期>` 的 `europeSp` 可回取 26035 起全部期次（与 500 14:00 快照逐场差最多 8pp，故不混源）。

## 3. 范围

本 spec：zgzcw 市场底座采集与回填、trigger DSL、奖金残差模型与 γ 结账、`CR` 前缀 RSI 实验、
Clue 事件流、`crowd` 命令面、泳道 B 接线、提名器、首条种子 CR1。
不在本 spec：竞彩人群、热板空仓新规则、枚举器本身（09-19 spec）、宪法措辞、把人群特征接进审票 V1 奖金模型（等首条假说 `deploy` 后另立）。

## 4. 模型

对第 t 期、场 i、实际赛果 ω_i，市场去水概率 p_i(ω)，全国人群份额 c_i(ω)。任九奖金 ∝ 1/中奖注数 ∝ 1/∏c_i(ω_i)。
设人群 = 市场 × 特征偏移：`ln c_i(ω) = ln p_i(ω) − Σ_k β_k x_ik(ω) + 归一项`。一阶展开后：

```
log 奖金_t = a + b·S_t + Σ_k γ_k·X_kt
S_t   = −Σ_i ln p_i(ω_i)                                  （现行意外度，非作废场）
X_kt  = Σ_i [ x_ik(ω_i) − Σ_ω p_i(ω)·x_ik(ω) ]            （触发面「实开数 − 市场期望数」）
```

- `x_ik(ω)=1` ⇔ 假说 k 的 trigger 在 (场 i, 面 ω) 上成立。X 按市场期望中心化，与 S 近似正交。
- **γ_k > 0**：触发面开出时奖池多付 → 全国人群**少买**它（`crowd_bias=under`，role `cover`：把覆盖花在这类面上更值）。
- **γ_k < 0**：人群**多买**它（`crowd_bias=over`，role `fade`：这类面中了也分得少，别把全包名额花在它上面）。
- 估计：Frisch–Waugh 两步 OLS（log 奖金与 X 各自对 S 回归取残差，再残差对残差），按期 bootstrap 2,000 次取 2.5/97.5 分位。单位：`γ×100` = 每多开一个触发面奖金变化 %。
- 观测单位是**期**（每期一个奖金），n 增长约 2–3 期/周；残差 sd 0.62 下，n≈100 时可分辨 |γ|≳0.10。

**可行性预检（2026-10-07，500 快照口径，26090–26134，n=42）**：残差对「开出平局数」斜率 −0.119，95% CI [−0.219, −0.005]——全国人群在平局上**多买**（与「人群厌恶平局」的直觉相反）。CI 勉强不含 0、未做多重比较校正、且用的是 500 口径，只作 CR1 的事前依据；**这一块 26090–26134 因已被看过，不再给 CR1 当验证集**。

## 5. 对象

### 5.1 市场底座 `<issue>-zgzcw.json`（`.nutmeg-data/zucai/`，快照追加）

```
{"issue": "26136", "source": "https://cp.zgzcw.com/lottery/zcplayvs.action?lotteryId=13&issue=26136",
 "snapshots": [{"fetched_at": "2026-10-08T09:05:12+08:00", "raw": {<zgzcw 原文 JSON>}}]}
```
解析（`crowd_source.parse_zgzcw`）→ 每场 `CrowdMatch{no, league, home, away, p{"3","1","0"}, asian}`；
`league_group ∈ {national, top5, other}`；`europeSp` 缺/坏的场跳过；不足 14 场的期不进模型。

### 5.2 假说 = RSI 实验，`exp_id` 前缀 **`CR`**

`H` 前缀已被未登记草稿 `_draft_H1.json`（开盘位移人性面）占用，`C` 与审计码 C0–C19 冲突，故用 `CR`。
在 09-18 登记原件之上新增字段；`label_cn`、`trigger`、`crowd_bias`、`replay_window` **仅当存在时**进冻结哈希（旧实验哈希不变）：

```
{
 "exp_id": "CR1", "tier": "deploy_eligible", "layer": "structural", "population": "zucai", "min_tier": "price_only",
 "label_cn": "全国人群多买平局",
 "claim": "平局开出时任九奖金低于市场意外度所预期（γ<0）",
 "mechanism": "复式习惯拿平局做保险……",            ← 进哈希（原有字段）
 "psychology": "怕「差一场平」……",                   ← 不进哈希，人可随时改
 "trigger": {"field": "face", "op": "==", "v": "1"},
 "crowd_bias": "over",                               ← under → role cover；over → role fade
 "falsifier": {"metric": "crowd_prize_pct_per_face", "stratum": "zucai", "n_min": 30,
               "bound": "ci_lower", "threshold_pp": 0.0, "direction": "lt_means_falsified"},
 "window": {"issue_from": "26136", "issue_to": "26999"},       ← 前瞻（判决只认这个）
 "replay_window": {"issue_from": "26035", "issue_to": "26089"},← 回放（只给读数，进不了判决）
 "stop_rule": "前瞻满 30 期判；60 期仍跨线则提 retire",
 "quota_slot": false, "buckets": [], "rule_ids": [], "examples": {"pos": [], "neg": []},
 "source_doc": "docs/superpowers/specs/2026-10-07-zucai-crowd-notebook-design.md", "registered_at": "2026-10-07"
}
```
结账 metric = `sign × γ × 100`，sign = +1（under）/ −1（over）——**正数 = 假说方向成立**。
RSI 判据：CI 下界 ≥ 0 → survived；CI 上界 < 0 → falsified（反方向显著）；否则 inconclusive。
判决只认 `prospective` 档（现行 `record_verdict` 已如此）；`replay` 档在初稿里给读数。

**trigger DSL（封闭集合）**——粒度 (场, 面)：
- 组合：`all` / `any`（列表）、`not`（单节点）；最多嵌套 2 层。
- 叶子：`{"field": F, "op": OP, "v": V}`，`OP ∈ {>=, <=, ==, in, not_in}`。
- `F ∈ {face, p_face, p_home, p_draw, p_away, fav_face, is_fav, league, league_group, board_hot_count}`；
  概率字段单位为 %（0–100）；`board_hot_count` = 本期最大面 ≥65% 的场数。未知字段/运算符 → 登记时 ValueError。

### 5.3 `Clue`（`<issue>-clues.jsonl`，只追加，不进内核）

```
{"kind":"clue","issue":"26136","snapshot_at":"…","exp_id":"CR1","label_cn":"全国人群多买平局","match_no":7,
 "face":"1","p_face":27.4,"crowd_bias":"over","role":"fade","advisory":true}
{"kind":"settle","issue":"26136","exp_id":"CR1","match_no":7,"face":"1","outcome":"hit|miss|void","acted":"followed|ignored|null"}
```
- 每次 scan 以当前最后一张快照为准追加；同 (exp_id, match_no, face, snapshot_at) 不重复写。
- `advisory = 该实验最近一次 deployment 不是 deploy`。
- `acted` 由 settle 时读 `betslips.jsonl` 本期票推出：cover 线索——任一张票盖了该面 = followed；fade 线索——没有任何票盖该面 = followed；本期无票 = null。**不改 betslip register**（永不拦登记）。

### 5.4 候选 `experiments/candidates/CR-cand-<n>.json`

提名器产出：登记原件草稿 + `evidence{window, n, gamma_pct, ci, buckets_scanned}`；`psychology` 留空给人写。
**候选不触发 Clue、不进内核**；签字 = `nutmeg crowd sign <候选> --as CR<k> --by Jun` → 写 `experiments/registry/CR<k>.json` 并 `rsi register`。

## 6. 每期流程（泳道 B 接点；不新增 plist）

| 时点 | 现有步 | 新动作 |
|---|---|---|
| 早/14:00/18:30 | `zucai-prep` → `after_prep` | 追加 `crowd fetch` + `crowd scan`（接线层，失败只告警） |
| B5 | `judgment draft` | 初稿末尾追加「**人群地图**」节：每条线索的场/面/市场 P/假说/方向/advisory 或约束/代价；附各 CR 的 replay 与 prospective 读数 |
| 赛后 | `day run --job settle` | 追加 `crowd settle --issue <最新期>`：刷官方奖金缓存、写 settle 行 |
| 夜 | `rsi loop` 结账步 | 所有 `experiments/registry/CR*.json` 并入 `grade --mode prospective` 与 `verdict` |
| 按需 | — | `crowd nominate`（人在对话里跑，产出候选） |

**边界**：线索在字典序第三序以内——事实层否决 → 帽内结构 → 人群分开；不能判死 alive 面，不能越过刹车/止损/日帽。证实前「看得见线索，不被牵着走」。

**提名器（`crowd nominate --from --to`）**：桶 = 面(3/1/0) × p_face 档([0,20),[20,35),[35,50),[50,65),[65,100]) × league_group，另加 3 个纯面桶，共 48 个；每桶拟 γ；保留 CI 不含 0 的，按 |γ| 取前 3；与已登记 CR 在窗口内触发集合重叠 ≥50% 的不提。候选里写明 `buckets_scanned=48`（多重比较：48 桶期望约 2.4 个假阳性）。
**首轮分块**：提名只扫 26090–26135；签字后 `replay_window` 默认取 26035–26089（未参与提名）。之后的提名扫全部已结期，验证只靠前瞻。

## 7. 首条种子 CR1（计划最后一步交 Jun 签字，不自动登记）

平局多买（§4 预检）。trigger `face == "1"`，`crowd_bias=over`，`replay_window` 26035–26089，前瞻自 26136。
回填后先在 zgzcw 口径的 26090–26135 上重跑一次斜率（与 500 口径对照，只报告），再出 replay 读数，交签。

## 8. 命令面

```
nutmeg crowd fetch    --issue <期>                 # zgzcw 快照追加
nutmeg crowd backfill --from 26035 --to 26135      # 官方奖金有记录的期逐期回取（已有快照跳过，间隔 1s）
nutmeg crowd scan     --issue <期>                 # 已登记 CR 的 trigger → Clue
nutmeg crowd map      --issue <期>                 # 人群地图 markdown
nutmeg crowd settle   --issue <期>                 # 刷奖金缓存 + settle 行
nutmeg crowd nominate --from <期> --to <期> [--write]
nutmeg crowd sign     <候选.json> --as CR<k> --by <人>
nutmeg rsi grade --exp CR<k> --mode replay|prospective
```
全部幂等、只追加；Telegram 不推（advisory 线索不需要 Jun 动作；deploy 级线索推送等首条 deploy 时再加）。

## 9. 失败处理

| 情形 | 处理 |
|---|---|
| zgzcw 超时/非 JSON/`matchInfo` 空 | fetch 非零退出、不写文件；接线层只告警；初稿「人群地图」写「本期无市场底座」 |
| 某场 `europeSp` 缺/坏 | 跳过该场；该期不足 14 场 → 不进模型（scan 仍对有数据的场出线索） |
| 官方奖金缺该期 / 任九无人中奖 | 该期不进模型；settle 只写 outcome |
| 赛果 `*` 作废 | 该场不计入 S 与 X；Clue `outcome=void` |
| registry 原件与内核 frozen_hash 不符 | `rsi grade` 拒绝（防止改了 trigger 不走 amend） |
| 窗口内有效期 < 3 | grade 返回 n=实际数、γ=0、CI=[0,0]（RSI 按 n<n_min 不判） |

## 10. 测试

- 单元：`parse_zgzcw`（去水、坏行、league_group）；DSL 校验与求值（嵌套、`not`、未知字段）；X 中心化；γ 在合成数据上恢复已知系数；bootstrap 稳定（固定 seed）；`grade_crowd` 的方向 sign 与窗口过滤；提名重叠剔除；Clue 去重、advisory、acted 推导；人群地图渲染。
- 契约：CR 原件过 `load_registry_doc`；旧 F/G/K 原件 `frozen_hash` 不变（对 registry 现有文件逐个回归）。
- 接线：`after_prep` 末尾多两条 crowd 调用且前三条不变；`planned_commands(settle)` 含 `crowd settle`；`rsi_loop` 计划含 CR 实验。
- 集成（`/verify`）：沙盒副本上跑 backfill(小范围)→scan→map→settle→nominate→`rsi grade --mode replay`。

## 11. 与现有文件的关系

- `docs/sop/RUNBOOK.md` 泳道 B：B0/B5/赛后各一行指针；`docs/sop/RULEBOOK.md` 新增「十、人群偏离假说（CR）」：模型、DSL 字段集、role 语义、advisory/约束切换、提名多重比较说明。
- `docs/ARCHITECTURE.md`：新增「人群层」一节 + 一张 Mermaid 图；`scripts/build_architecture_docx.py` 重建 docx。
- `2026-09-19-zucai-structure-lane-design.md`：枚举器读 Clue（deploy 后为约束）在那边实现。
