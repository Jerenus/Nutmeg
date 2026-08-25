# Nutmeg 应用蓝图 —— 类 Palantir 的比赛分析决策系统

日期：2026-08-24 ｜ 性质：产品规划初稿（用户提问驱动）｜ 前置：`2026-08-23-memory-ontology-sop-redesign.md`

## 1. 现有能力盘点（按稳定性分层）

### T0 确定性核（已存在，必须 100% 稳定）
| 能力 | 载体 | 现状 |
|---|---|---|
| 数据采集 | sporttery API(WAF-aware)/API-Football/500.com/okooo/官方开奖 gameNo=90 | ✅ 稳定，别名审计 94.4% |
| 备料流水线 | zucai-prep 14:00+18:30 位移 diff（launchd） | ✅ 通电在跑 |
| 编排 | decision-am：fetch→sense→backfill→day-regime→alias-audit | ✅ |
| 确定性算术 | devig/fair、dcfit(DC矩阵/让球三路/进球带)、Brier/CLV | ✅ 禁嘴算的执行者 |
| 审计门 | legs_audit C0-C7 + modal_stack（退出码1） | ✅ C7 刚上线 |
| 账本 | zucai-ledger / settlements / scoreboard.json 单一事实源 | ✅ |
| 本体 store | 九对象+五动词；Kernel v2 SQLite typed Actions（P1-4 已并，**P5 cutover 待批**） | ⚠️ 双轨期 |
| 实体层 | League/Team profile_notes + seed sync + alias 表 | ✅ |

### T1 AI 判断层（存在，不承诺稳定——用双轴度量代替稳定承诺）
- 七阶段深研（jczq-match-analyst 并行 agent，五件套+旗点检+先例块+falsifier）
- 判决表 k-s、牌照、旗词典、偏移 Read（因子词典校验）
- 处方 P14 → 首版实票（B5 新流程：3进2/2进1 已裁+资金使用率）

### T2 人机裁决层（存在于对话，待产品化）
- 裁决分工协议（我裁/上交三类）、evidence_rejected 记账、轮盘位记分

### T3 学习回路（半自动）
- calibrate 因子生死、rx 预注册预测记分、记分牌累计、复盘 memory 蒸馏（consolidate 命令排队）

## 2. 是否具备做 UI 的条件 —— **是，而且时机刚好**

难的部分（本体、确定性算术、审计、账本、双轴度量）已经存在并被 20+ 期实战验证；UI 只是给它们一层玻璃。**前置条件只有一个：Package 5 cutover**（SQLite 单轨），否则 UI 要对着双轨数据写两套读取。

## 3. 类 Palantir 映射（我们已经在无意中复刻它的四层）

| Palantir | Nutmeg 对应 | 状态 |
|---|---|---|
| **Foundry**（管道+血缘） | prep 泳道 + sense/backfill + 三源对账 | 有，缺血缘可视化 |
| **Ontology**（对象/链接/动作） | 九对象+实体层+因子词典；**typed Actions 就是 Palantir 的 Action Types** | 有，缺 Flag/Precedent/Adjudication/Prediction 四对象（P2b） |
| **AIP**（LLM 绑定本体+护栏） | 主循环判读+深研 agent；**audit=护栏、词典=schema 约束、没入账=没打=writeback** | 有，这是全项目最独特的部分 |
| **Workshop**（本体之上的应用） | **缺——这就是要做的 UI** | 无 |

核心洞察：Palantir 的本质是"**让操作者在本体之上做决定，每个决定都是带血缘的动作**"。Nutmeg 的对话式流程已经是这个模式（judgment→Read→audit→ticket→settle→scoreboard），UI 的任务不是发明新功能，是**把对话里的裁决流固化成界面**。

## 4. AI-native 总结：这不是"带 AI 的软件"，是"带护栏的 AI"

倒置原则：**不稳定化判断，而是仪表化判断。**
- 软件层的职责（100% 稳定）：真相（数据/算术/结算）、约束（审计）、记账（账本/记分牌/血缘）
- AI 层的职责（不承诺稳定，被度量）：判读、深研、处方、构票——每次输出被 Brier/CLV/兑现率打分
- 人的职责（被记录）：裁决——每次锁定/否决带 evidence_rejected 入账
- 学习回路：因子/旗/规则的生死由战绩驱动，不由散文驱动

## 5. 应用功能规划（七个界面，按优先级）

| # | 界面 | 内容 | 依赖层 |
|---|---|---|---|
| 1 | **板面看板** | 14场 fair锚+旗+难度指数+位移火花线+截止倒计时 | T0 |
| 2 | **单场档案** | 深研五件套结构化：锚/DC矩阵/旗+证据链接/先例块/falsifier/位移 | T0+T1 |
| 3 | **构票工作台**⭐ | 面选格+**实时审计**(ERROR/WARN内联)+P/票价/门槛实时算+版本对比+裁决捕获(我裁/需你裁) | T0+T2 |
| 4 | **记分牌** | scoreboard.json 实时渲染：连锁/牌照/保险兑现/裁决记分/C7兑现率 | T0 |
| 5 | **复盘室** | 结算 vs 预注册预测、反事实阶梯、奖金经济学（64%常数/二变量模型） | T0+T3 |
| 6 | **本体浏览器** | 球队/联赛画像、因子词典、RULEBOOK（每条规则带状态与战绩） | T0 |
| 7 | **预警流** | 位移≥2pp/falsifier触发/截止提醒 → 推 Telegram（复用 OpenClaw） | T0 |

### 必要 vs 100% 稳定清单（直接回答）

**必须 100% 稳定（软件承诺）**：①三源采集与对账 ②canonical 身份（8/23 的 M-0823/0824 分裂 bug 是此项的整改单）③去水/DC/盖率算术 ④审计门 ⑤账本与记分牌 ⑥截止时间/日程 ⑦裁决记录的 writeback。
**必要但不承诺稳定（AI 承诺被度量）**：深研、判读、处方、首版实票、预警的判断部分。
**可以后置**：多用户、移动端、实盘接口、自动下单（永不做——出票永远人手）。

## 6. 路线图

| 里程碑 | 内容 | 前置 |
|---|---|---|
| M0 | Package 5 cutover（SQLite 单轨）+ canonical 身份修复 | 用户批准 go-live |
| M1 | 只读三件：板面看板+单场档案+记分牌（FastAPI + 轻前端，读 store） | M0 |
| M2 | 构票工作台：audit 内联 + 裁决 writeback（Adjudication 对象随此落地） | M1 + P2b |
| M3 | 预警流 + consolidate 回路 + Prediction 对象自动记分 | M2 |
| M4 | 复盘室 + 本体浏览器 + 打磨 | M3 |

技术栈建议：后端复用 nutmeg 包（FastAPI 薄封装，判断永不进后端）；前端从服务端渲染起步（HTMX/轻 React），实时算术走既有 Python 函数——**UI 里不许出现第二套概率实现**（禁嘴算的界面版）。
