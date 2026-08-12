# 决策本体 · Tie/流量/规则三层增补提案（对实体层的第二次修订）

> 2026-08-12 起草。**状态：提案，未采纳。** 缘起：26101–26103 三期实战 + 2026-08-12 竞彩日
> 暴露的五处结构缺口。本提案不推翻九对象/五动词，只**补缺失的海拔**，并给出分级采纳。
> 前置：`2026-07-07-ontology-entity-layer-proposal.md`（实体层 Tier 1+2 已落地——League/Team
> + Factor.scope；其"Tier 3 Appearance 过早不建"的判断本提案维持）。
> ⚠️时机约束：提案 ①② 涉及身份与 schema，**应赶在 Ontology Kernel v2 Package 5 cutover
> 之前裁决**（cutover 是唯一不可逆步骤）；③④⑤ 可在现有 JSONL 上先行生长。

---

## §P0 精确诊断（先说什么已经对，再说什么在漏血）

**已被 26103 实战验证、不要动的三件事：**

- **League 画像是回报最高的一层。** `uefa-qualifiers` 画像在 26103 全周期被引用十余次且全部
  有效（`ttg_high_variance` 禁真金拦住场7 冲动；`second_leg_trailing_exact_margin` 命中里昂
  博弈结构；萨巴赫 4-0 再验右尾肥）。慢变量沉在联赛级是正确海拔。
- **Match 作为事件溯源锚点无可争议。** 约束 j 的跨渠道传导（场11 agent 挖出 26097 裁定、
  推翻主循环现场裁定）只有在"判断挂在 canonical 比赛上"时才可能发生。
- **画像写入的证据强制**（`--add-note` evidence 必填；无证据断言走 Read 进双轴）防住了
  画像变成永久化偏见。保持。

**正在漏血的五处（按代价排序）：**

1. **Tie（系列赛）不是对象** → 本周预测力最强的变量（两回合总分状态）无家可归，
   14 个 agent 各自 web 检索重复推导，还引发主循环与 26097 旧裁定的口径冲突险情。
2. **Canonical 身份在字符串层拼接** → 同一场 PSG-维拉分裂成
   `M-2026-08-13-日尔曼-维拉`（zucai）与 `M-2026-08-12-巴黎圣曼-维拉`（jczq），
   跨渠道传导靠人手写注记。
3. **画像笔记无时效/regime 元数据** → 8/07 实证：日职画像"低分高平"在揭幕轮方差窗口
   被两场各 7 球打脸；画像自己不知道自己何时失效。
4. **结构完整度判定没有持久层** → 本菲卡中轴卖空这一个事实在 26101→26102→26103→
   08-12 竞彩被独立重考证四次。
5. **规则/教训无生命周期对象** → 判决表 k-q 条与预登记证伪条件活在 CLAUDE.md 散文
   与 memory 里，靠人工复盘迭代；Factor 有 probation→active→retired，Rule 没有。

---

## §1 提案一：Tie（系列赛）对象 —— 缺失的中间海拔【价值最高】

### 证据

2026-08-11 夜 7 场欧战 Q3 次回合 **7/7 完美分型**：总分完全持平的 2 场（3-3、0-0）全部
开 90' 平（2-2、1-1，双双进加时）；有 1-2 球差的 5 场全部分出胜负（0-1、4-0、2-0、0-1、3-0）。
机理：持平 = 实力被系列赛自证对称 + 加时是合法出口 → 平是吸引子；1 球差 = 比赛是活的 →
分出胜负。这是**赛制结构级**知识——比 Team 画像更接近判断，却在 League（太粗）与
Match（太细）之间没有落点。同时每场次回合的"首回合比分/总分/赛制规则（客场进球已废、
有无加时、点球）"被每个 agent 重复考证，08-12 两场解放者杯又重复了一轮（坐实"首回合"）。

### Schema

```
Tie {
  tie_id,                        -- T-<competition>-<season>-<round>-<pairing>
  competition, season, round,    -- 欧冠Q3 / 解放者杯R16 / …
  leg1_match_id, leg2_match_id,  -- 链接两个 Match（首回合前 leg2 可空）
  aggregate: {home, away},       -- 随 leg1 结算自动更新
  rule_regime: {away_goals: abolished|active, extra_time: bool, penalties: bool,
                neutral_final: bool},
  state: pre_leg1 | level | one_goal | decided,   -- 由 aggregate 机械导出
  state_priors: {…}              -- 可选:分型先验(平/分胜负),由 calibrate 按实证累积 n
}
```

### 动作与接线

- sense 建 Match 时若识别为两回合赛制（competition 词典标注）→ upsert Tie 并链接。
- reconcile 结算 leg1 → 自动更新 aggregate/state。
- 判读时 prep/brief 直接打印 Tie.state 与对应分型先验，**agent 不再自行考证赛制**
  （仍需核实伤停等流量信息，但回合状态变成本体事实）。
- calibrate 对 `state → 90' 结果` 的分型按实证累积（当前 n：持平 2/2 平、1球差 5/5 分胜负、
  悬置夹心 3/3 未赢——三个不同口径的样本第一次可以在同一对象上记账）。

---

## §2 提案二：身份解析前置到实体层【必须赶在 Package 5 cutover 前】

### 证据

`canonical_match_id(home, away, date)` 以**中文队名字符串 + 渠道各自的日期口径**拼接：
- zucai 通道写 `日尔曼/维拉`（足彩页缩写）+ 开球自然日 → `M-2026-08-13-日尔曼-维拉`
- jczq 通道写 `巴黎圣曼/维拉`（体彩缩写）+ businessDate → `M-2026-08-12-巴黎圣曼-维拉`

同一场真实比赛两个 Match 对象，Read 传导靠 note 手写"canonical 同场,已知问题"。
26091 也曾因 match_date 口径分裂过 canonical（memory 已记）。别名表（466 条）明明已把
两种写法都映到同一英文名/team_id，却只服务采集侧，不服务身份。

### 改法

1. **match_id 由实体 ID 生成**：`M-<date>-<home_team_id>-<away_team_id>`，date 统一取
   **UTC 开球日**（消灭 businessDate/自然日分裂）。team_id 解析不了的，降级用
   `norm_team(中文名)` 并打 `identity_unresolved` 标记（进 alias-audit 日报）。
2. **别名表升级为解析器**：`resolve_team(任意写法) → team_id`，采集/感知/对齐三处共用
   （zucai_prep 的 `alias_resolver` 已是雏形，上提为本体服务）。
3. 兼容：旧 match_id 保留为 `channel_refs`；kernel v2 迁移脚本按 (team_id,team_id,±1日)
   合并历史分裂对象。

---

## §3 提案三：画像笔记加时效与 regime 元数据

### 证据

8/07 复盘（已落 memory）：J1 画像"进球最低/0-0 最肥/平局率最高"在**揭幕轮方差窗口**
连错两场（各 7 球）；瑞超画像标注"夏窗 7/8 后才开"这类时效信息只能写在 note 正文里靠人记得。
26103 判读中 agent 需要自行判断"上季数据在转会窗未关时是否可用"——每次都是口头裁量。

### 改法

`profile_note` 增加三个可选字段（存量 note 不迁移，新写入强烈建议带）：

```
{key, note, evidence[],
 as_of: date,                          -- 依据数据的截止时点
 valid_regime: [regular|season_opening|transfer_window|cup_transition|any],
 review_after: date?}                  -- 到期提醒复核(进 alias-audit 式日报)
```

判读期 `decision-profile` 输出时，当前日期落在非 valid_regime 窗口的 note 自动加
`⚠️失效窗口` 前缀——把 8/07 的教训从"人要记得"变成"系统会说"。

---

## §4 提案四：结构完整度快照（流量侧的轻量对象）

### 证据

「锚方结构完整度」自 8/08 成为胆的本体判据后，每次判读都在产出
`完整/有洞(缺口)/对称残缺 + 证据`，但只活在 Read.note 里。本菲卡中轴卖空被独立重考证
四次（26101 场10 邻场、26102 场5、26103 场13、08-12 复述）；流浪者/克拉约瓦同理。
该判定生命周期为天到周——比 Team 画像短、比单场 Read 长，恰好两头都接不住。

### Schema

```
TeamIntegrity {
  team_id, as_of,
  verdict: pass | fail | symmetric_damage,
  gaps: [{area: shield|scoring|keeper|fullback, detail, evidence[]}],
  expires_hint: date?          -- 如停赛回归日/转会窗关闭日
}
```

- 判读时先读最近快照 → agent 只做**增量核验**（"8/09 后有无新增"），不做全量重考证。
- 与 §1 Tie 同理：**本体存人的结论，agent 采流量的原料**。明确不建 Player 对象
  （价值半衰期以天计，实时检索是正确工具；维持 7/07 提案"Appearance 过早不建"的判断）。

---

## §5 提案五：Rule 对象 —— 给判决表与证伪登记一个生命周期

### 证据

Factor 有自动生死（probation→active→retired），但项目真正的护城河——判决表 k-q 条、
预登记证伪条件——是 CLAUDE.md 散文 + memory 文件，迭代靠人工复盘：26103 落了四条
预登记预测，开奖后**核验它们是纯确定性算术**，却没有任何自动化；`legs_audit` 已把 7 条
规则代码化（每条带 `since` 指向哪次亏损），但规则的 n_for/n_against 没有地方累积。

### Schema

```
Rule {
  rule_id,                       -- 如 verdict-table.m.flagged-naked-single
  clause_text, status: active | probation | retired,
  n_for, n_against,              -- reconcile 自动累积
  falsifiers: [{condition, registered_at, issue, outcome: pending|confirmed|refuted}],
  enforcement: prose | validator,  -- validator = 已进 legs_audit/read_validate
  since: [亏损/实证引用]
}
```

- reconcile 结算时扫当期 pending falsifiers → 按赛果机械判 confirmed/refuted → 更新计数。
- calibrate 面板新增 Rule 段（与 Factor 并列）。**规则的生死由数据判决，校验器只执行
  已判决的规则**——这补上 Data Agent 定位里"学习平面"的闭环缺口。

---

## §6 分级采纳建议

| Tier | 内容 | 时机 | 成本 |
|---|---|---|---|
| **1（先做）** | §2 身份解析前置 + §1 Tie 对象 | **Package 5 cutover 前**（改 schema 的最后窗口） | 中 |
| **2** | §5 Rule 对象（先只做 falsifier 自动核验，接进 reconcile） | cutover 后第一个迭代 | 小 |
| **3** | §3 画像时效元数据 + §4 TeamIntegrity 快照 | 随用随长（JSONL 即可起步） | 小 |

## §7 明确不做

- **Player/Appearance 对象**：维持 7/07 判断——过早。伤停转会的价值半衰期以天计，
  agent 实时检索是正确工具；本体只存其**结论**（§4）。
- **Team 画像加厚**：26103 致胜的球队级信息无一来自 Team 画像，也不应来自。
  Team 层只存行为模式级事实（凯拉特 4 场破不开铁桶、安德莱赫特主场 4 次 0:0）。
- **判断进画像**：现有"无证据断言走 Read 进双轴"红线不动。

## §8 检验标准（收尾）

Palantir 本体的本义是**决策的操作性孪生**，不是知识图谱本身。任何新对象入本体前问一句：
**它会改变某条 Read 或某张 Ticket 吗？** 本提案五条的答卷：Tie 直接改 Read 先验（7/7 分型）、
身份解析让约束 j 不再靠手写、时效标签防 8/07 式画像误用、完整度快照防 26102 式重复论证
中的信息丢失、Rule 对象让 26103 的四条预登记不再依赖"我记得去核"。
