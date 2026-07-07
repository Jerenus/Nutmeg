# 决策本体 · 实体层增补提案（对 §2/§3/§5 的修订，未采纳）

> 2026-07-07 起草。**状态：Tier 1+2 已落地（2026-07-07，10 个 commit 见 git log
> `实体层 Task 1-10`；schema 已折进主 spec §2/§5）；Tier 3（Appearance）判"过早、不建"；
> `Match.joint` / `Factor.scope_key` 字段同判不做（配对知识走 Read.factors 的
> scope=pairing 引用表达）。实现计划：`docs/superpowers/plans/2026-07-07-ontology-entity-layer.md`。**
> 缘起：一次本体论追问——"一场独立比赛，该把**对阵双方**当研究对象，还是把**整场比赛**
> 当一个研究对象？" 用 Palantir Ontology 的判据回答后，发现现本体在**实体侧建模不足**。
> 本提案不推翻五动词/七对象，只**补持久实体层 + 给 Factor 加 scope**，并给出分级采纳。
> M2 已于 2026-07-07 切换完成、系统 live，故这是**上线后增强**，不属原 §9 迁移。

---

## §P0 精确诊断（先说什么已经对，再说什么在漏血）

**已经对、不要动的两件事：**

- `Match` 作**决策与结算对象**是对的——五动词（read/express/reconcile/calibrate）全附着于此，
  且已有 canonical 跨通道身份（`channel_refs`）。Palantir 判据里"动作附着 + 跨源身份"两关全过。
- `MarketSnapshot.fair`（三路/比分矩阵去水）**本身就是一个配对级的联合对象**。市场的
  联合分布（含 Dixon-Coles 相关、低分耦合）已经被正确建模在 Snapshot 上，**不存在
  "联合分布无家可归"的问题**——它天然是 match 级的。

**正在漏血的两处（本提案要修的）：**

- **漏点 1 · 边缘实体不是对象 → 学习在错误海拔上空转。**
  `Match {home, away, competition}` 三者皆字符串。可你 §5 种子词典里**已经有**
  `league_bias`（极端联赛画像，瑞超实证）这类**联赛级**因子、以及隐含的球队状态类因子，
  它们**没有持久节点可挂**。后果：calibrate 的 `n<30 只积累不判决` 想学"瑞超主客分裂""法甲
  ttg 残差""挪超/芬超高估进球"这类**跨场结构偏差**，却找不到一个跨场存在的 League/Team
  对象来累积 n。这些知识今天只活在 memory 文件（`allsvenskan-2026-league-profile`、
  `jczq-5-28-v2-4` 的 R25 反向联赛表）和你脑子里，**没进本体**——这正是"实体侧建模不足"的体征。

- **漏点 2 · Factor 无 scope → 联合/边缘/联赛因子在同一张扁平词典里混判生死。**
  现 `Factor` 是一条不带海拔的词典项。可种子词典本身**已经是隐性多尺度**的：

  | 种子因子 | 真实海拔 | 说明 |
  |---|---|---|
  | `seeding_incentive`（071 签位激励） | **pairing（配对/情境）** | 双方共同最优是平——不可还原到任一队 |
  | `bunker_profile`（087 铁桶压缩净胜） | **pairing** | 是"强攻 vs 铁桶"的相性，不是单队属性 |
  | `lineup_news_gap`（实名伤停/轮换） | **appearance（单队本场态）** | 属某一支球队今晚的出场态 |
  | `league_bias`（瑞超画像） | **league** | 跨该联赛全部场次的结构偏差 |
  | `market_line_error`（3 路口径错觉） | **match** | 属这一场的盘口口径 |
  | `fatigue_discount`（7/04 反向登记） | **appearance** | 单队疲劳态 |

  一张扁平词典把这六条混在一起判生死，≤12 active 上限和双轴 Verdict **分不清**"这条因子
  是关于本场这对、还是这支队永远、还是这个联赛永远"。`direction_hit_rate` 把
  `league_bias`（该联赛几十场累积）和 `seeding_incentive`（个别配对情境）按同一口径平均，
  是**统计口径错误**，不只是不优雅。

**一句话诊断**：市场联合层已经是对象（Snapshot），但**边缘实体不是对象**（学习漏血）、
**因子没有海拔**（生死误判）。这两点恰好对应你原始问题的两半——"双方"该是**持久节点**、
"比赛"该是**承载动作与联合的链接对象**。

---

## §P1 本体判据（Palantir 理念，判"谁该是对象"）

一个东西够格当 object，过三关：**(a) 动作附着**（有 verb 作用其上）· **(b) 跨源同一身份**
（多通道解析到同一个它）· **(c) 状态沉淀**（时间推移状态累积其上）。

| 候选 | (a) 动作 | (b) 跨源身份 | (c) 状态沉淀 | 结论 |
|---|---|---|---|---|
| Match | ✅ 五动词 | ✅ 已有 channel_refs | ⚠️ 一次性（赛后成史） | **决策/结算对象**（已是） |
| Team | ❌ 不对球队下注 | ✅ 你已在做别名解析（Czechia/国家队别名表） | ✅ 状态/伤停/战意跨场累积 | **信念/学习对象**（缺） |
| League | ❌ | ✅ | ✅ 联赛画像跨季累积 | **学习对象**（缺） |

**Palantir 的干净构造**：关系可提升为一等对象（带属性、挂动作的 link）。据此，

> **两支球队是持久节点，是信念输入与跨场学习的沉淀处；一场比赛是这两个节点之间
> 承载属性与全部动作的链接对象。比赛必须一等，不是因为它"比两队大"，而是因为它的
> 那些产生 edge 的属性（战意博弈、克制、盘口错定价）根本不落在任一支球队上。**

"对阵双方 vs 整场比赛"因此**不是二选一**——它们是本体不同层、被不同动词作用的对象。

---

## §P2 提案对象（新增/修订的 schema）

沿用 §2 约定：append-only JSONL、幂等 upsert-by-id、语义 id（同 Factor 用可读 slug）。

```
Team          持久实体节点（信念输入 + 跨场学习的沉淀处）—— 新增
  {team_id: "swe-hammarby",          # 稳定 slug（非每场新生）
   name_zh, name_en,
   aliases: ["Hammarby","哈马比","Hammarby IF"],   # 跨源身份：种子=国家队别名表+Czechia映射
   competition_ids: ["swe-allsvenskan"],           # 主属联赛（可多个）
   profile_notes?: [{key, note, evidence, at}]}     # 画像沉淀(如"主强客弱";证据式,非分数,非规则

League        持久实体节点（联赛级结构偏差的沉淀处）—— 新增
  {league_id: "swe-allsvenskan",
   name_zh, name_en, country,
   season?: "2026",
   profile_notes?: [{key, note, evidence, at}]}      # 如"法甲 ttg 残差""挪超高估进球"

Appearance    出场态 = 某队在某场的情境化状态（桥接层）—— 新增（Tier 3，可缓）
  {appearance_id: "AP-<match_id>-home",
   match_id, team_id, side: home|away,
   rest_days?, rotation_note?, motivation_note?,     # 状态≠战意在此天然分层
   lineup_evidence?: [{url,quote,at}]}
```

**Match 修订**（字符串升引用；补显式联合槽；旧字段保留作 back-compat）：

```
Match  {match_id, kickoff_at,
        home, away, competition,                      # 保留：显示用 & 未 resolve 的兜底
        home_team_id?, away_team_id?, competition_id?, # 新增：resolve 后的持久节点引用
        joint?: {                                     # 新增：不可还原到任一队的配对属性(证据式)
          matchup_note?: {note, evidence:[{url,quote,at}]},        # 克制/战术相性
          game_theoretic?: {kind: seeding_lock|dead_rubber|
            must_win_asymmetry|none, note, evidence:[{url,quote,at}]}
        },
        channel_refs}
```

**Factor 修订**（加一个 `scope` 字段——本提案的**最小、最高杠杆**改动）：

```
Factor  {factor_id, name_zh, definition,
         scope: match|pairing|appearance|team|league,  # 新增：因子作用海拔
         scope_key?,          # team/league scope 下=team_id/league_id；pairing 下可空(靠 Read 关联)
         born_at, born_from, status, retire_reason?}
```

**Read 修订**（因子引用带上 scope_key，让 calibrate 能按海拔聚合）：

```
factors: [{factor_id, scope_key?, direction, weight_pp, evidence:[...]}]
         # scope_key 例：league_bias 引用时 scope_key="swe-allsvenskan"
```

---

## §P3 对血缘与五动词的改动（最小面）

- **血缘补一条**：`Match → home_team_id/away_team_id/competition_id`；`Appearance → Match + Team`；
  `Read.factors[].scope_key → Team/League`。任何对象仍能回答"你从哪来"。
- **sense（纯代码，+resolve 步）**：存 Match 时对 `home/away/competition` 跑
  **resolve**（查**策展式** Team/League 别名表 → 命中填 `*_id`；未命中 → `*_id=null` + log，
  **不自动新建对象**——每天几十场自动造 Team 会让几百支我们毫无知识的球队污染 store；
  Team/League 对象只为"我们对它有知识"的实体而生，正好与 Tier 2 迁移 memory 画像同一批。
  2026-07-07 复核修正）。这与现有"Czechia 改名走显式映射""国家队别名表"是**同一件事的
  一等化**，不是新判断——纯取数/解析/校验，**不违反 §7"判断永不进代码"**。
  顺手修一个读码发现的既有数据丢失：`sense.py` 现硬编码 `competition=""`，sporttery
  原始数据的联赛名被丢弃——league scope_key 落地的直接障碍，Tier 1 一并补上。
- **read（Claude 判断不变）**：偏移引用 `league_bias` 时带 `scope_key="swe-allsvenskan"`；
  `joint` 槽（战意博弈/克制）由 Claude 以证据式填写，**不烤进代码**。
- **express / reconcile**：**零改动**（Ticket.legs 仍按 match_id 组合；结算仍按 match 赛果）。
- **calibrate（纯代码，两级聚合，2026-07-07 复核修正）**：**生死判决仍在 factor 级**
  （n≥30 反 churn 门槛不变——per-scope_key 判生死会让 `league_bias@瑞超` 一季攒不满 30
  而永悬 probation，实为倒退；而"引用极端联赛画像作为偏移理由"作为**方法**在 factor 级
  判生死是自洽的问题）。scope_key 级增**诊断性子判决**：verdict id = `factor_id@scope_key`
  （复合 id 亦避免 store upsert-by-id 互相 clobber），面板分行显示
  "league_bias@瑞超 7/9 · @法甲 2/6"，供 read 时判断"这条画像在这个联赛还灵不灵"。
  修掉漏点 2 的方式是**证据分辨率**，不是多台生死状态机。

---

## §P4 §7 反积累宪法自检（提案必须过这关，否则不该采纳）

| §7 条款 | 本提案是否合规 | 说明 |
|---|---|---|
| 1 判断永不进代码 | ✅ | Team/League/Appearance 是**数据对象**；`joint`/`profile_notes` 是**证据式数据**，非 if 规则；resolve 是取数/解析 |
| 2 政策即数据 | ✅ | scope、别名表、画像全是数据/本体对象，非代码 PR 携带的规则 |
| 3 词典上限+强制退休 | ✅ 增强 | scope 让 ≤12 上限**更**可控（分海拔配额，防 league 类挤爆 pairing 类） |
| 4 每条教训入库必答"替代哪条旧规则" | ✅ | 本提案替代**"联赛/球队知识只活在 memory 文件"这一非本体旧态**——把 `allsvenskan-2026-league-profile`、R25 反向联赛表从散记升为 League.profile_notes + league scope 因子 |
| 5 shadow 基线永远在跑 | ✅ | 不动 shadow 机制 |

**关键**：本提案**只增数据结构与数据，不增任何判断代码**。这是它能被你自己的宪法接纳的前提。

---

## §P5 分级采纳（按 YAGNI，从最低成本入场；北极星是全三层，先建 Tier 1）

| 级 | 内容 | 成本 | 解决 | 建议 |
|---|---|---|---|---|
| **Tier 1** | 只加 `Factor.scope` + `scope_key` + sense 里对 `home/away/competition` resolve 出稳定 `*_id`（**不建完整 Team/League 对象，先只要稳定 id**） | 最低（1 字段 + 1 resolve 表，种子=现有别名表） | **漏点 2 全解 + 漏点 1 的地基**（因子有正确海拔可挂，calibrate 能分桶） | **✅ 先做这个** |
| **Tier 2** | 把 Team/League 升为完整对象带 `profile_notes`，迁入现有 memory 里的联赛/球队画像 | 中（2 对象 + 一次性迁移） | 漏点 1 全解（跨场结构偏差有本体家、可复盘、可被 calibrate 读） | calibrate 真要读跨场画像时做 |
| **Tier 3** | Appearance 出场态对象（状态≠战意结构化分层） | 高（新对象 + 每场两条 + read 流程改动） | "状态≠战意"从 Read 的自由文本升为结构化双槽 | **只在 Read 的 factors 自由文本被证明不够用时才做**（当前存疑，见 §P6） |

Tier 1 已经拿到本提案**大部分价值**（修好因子生死的统计口径），且几乎零表面积。
Tier 3 是否值得，诚实存疑——现在 Read 的 `factors[]` + `note` 已能表达单队状态/战意，
Appearance 可能是过早结构化（违背反 churn 精神）。**不建议现在建。**

---

## §P6 需要你拍板的决策点

1. **是否采纳 Tier 1（`Factor.scope`）并现在动代码？** 这是修漏点 2 的最小改动，我判断
   收益/成本比最高。若采纳，起手式按 §B.3：`writing-plans` 出实现计划 → TDD → verify skill。
2. **Team/League（Tier 2）现在建还是挂 backlog？** 取决于 calibrate 近期是否真要读跨场画像；
   若否，可只留 Tier 1 的稳定 `*_id` 作地基，Team/League 对象延后。
3. **Appearance（Tier 3）是否直接判"过早、不建"？** 我倾向不建，把"状态≠战意"继续留在
   Read 的 factors/note 里，等它被证明不够用再说。
4. **本提案折进 §2 spec，还是留作独立提案直到 Tier 1 落地？** 建议 Tier 1 落地后再把
   `scope` 字段正式写进 §2/§5，保持"最终设计"文档与 live 系统一致。

---

> 关联：`2026-07-06-decision-ontology-design.md` §2/§3/§5/§7（被修订/自检对象）·
> memory `decision-ontology-design`（原设计）· `allsvenskan-2026-league-profile` /
> `jczq-5-28-v2-4`（Tier 2 待迁入的联赛画像证据）· `jczq-7-06-system-retro`（因子生死证据出处）。
