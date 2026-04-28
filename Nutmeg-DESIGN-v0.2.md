# Nutmeg · 过人
**足球评估分析 AI Agent · 项目设计 v0.2**

> v0.2 关键决议：私有部署 + 未来服务化、Agent 激进决策人设、CLI/IM 优先 Web 后置、Sprint 0 即接入 LangSmith、首期仅目标联赛。详见 §9.3 决议记录。

> "Nutmeg" 取自足球术语 "穿裆过人"，引申为**看穿对手**、**穿透数据表象**。
> 中文名「过人」一词双关——既是足球动作，也是"高人一等"的判断能力。
> Logo 走**豆蔻**（Nutmeg 直译的肉豆蔻香料）意象，形成记忆反差。

---

## 目录

1. [项目定位](#1-项目定位)
2. [调研综述](#2-调研综述)
3. [数据源策略](#3-数据源策略)
4. [系统架构](#4-系统架构)
5. [核心功能模块](#5-核心功能模块)
6. [技术栈选型](#6-技术栈选型)
7. [MVP 迭代路线图](#7-mvp-迭代路线图)
8. [成本估算](#8-成本估算)
9. [风险与开放问题](#9-风险与开放问题)
10. [附录：关键开源项目与数据源清单](#10-附录)

---

## 1. 项目定位

### 1.1 一句话定位
**一个能替我采集足球分析数据、并辅助我做出主观评估判断的个人 Agent 助手。**

### 1.1.1 产品演进路径（v0.2 新增）
```
Phase 1 · 个人工具（当前）
  └─ 单用户私有部署，作为个人分析工作台试错
Phase 2 · 朋友共享（6-12 个月后）
  └─ 多用户私有部署，授权制，收集真实使用反馈
Phase 3 · 订阅服务（12 个月+）
  └─ SaaS 化，面向付费用户提供分析服务
```
**工程含义**：从 Phase 1 起就要按"将来会有多用户"来设计——`user_id` 贯穿全栈、偏好/记忆/策略分租户隔离、秘钥/配额分用户管理。只是现阶段用户表里只有一行（owner）。**详见 §4.4 多租户就绪设计**。

### 1.2 覆盖范围（已确认）
- **联赛**：英超、西甲、意甲、德甲、法甲 五大联赛
- **欧战**：欧冠、欧联
- **国家队**：世界杯、欧洲杯
- （中超、亚洲赛事**不在首期范围**）

### 1.3 分析三大支柱（已确认）
| 支柱 | 核心产出 | 使用场景 |
|---|---|---|
| **战术分析** | 阵型、跑位、xG、xT、传球网络、压迫图 | 赛前预览、赛后复盘、球队风格画像 |
| **盘口/博彩** | 三维赔率、亚盘/大小球、价值识别、模型对赔 | 赛前判断赔率是否偏离真实概率 |
| **球员数据** | 个人指标、伤病状态、出场状态、身价趋势 | 阵容评估、转会判断、状态追踪 |

### 1.4 核心设计原则
- **Agent 优先**：不是又一个数据看板，而是能"替我决策"的对话式助手
- **激进但诚实**（v0.2）：在数据支持的前提下敢于给明确判断——"我认为 X 会赢 / 这场值得下注 / 这名球员被高估"，不做无意义的中立回避；但对不确定性必须坦诚，置信度必须显式标注
- **人机协同**：关键主观判断可由 Agent 先给出初版，我在人类环节里修正
- **小步迭代**：三块业务并行推进，每 2 周一个可用 slice
- **可解释优先**：盘口/战术判断必须能追溯到数据和模型，不做黑盒
- **多租户就绪**（v0.2）：单用户阶段就按多用户架构搭建，避免未来重写

---

## 2. 调研综述

### 2.1 GitHub 生态扫描（精选）

#### 资源索引类（入门必看）
- **[eddwebster/football_analytics](https://github.com/eddwebster/football_analytics)** — 足球分析领域最全的资源汇编，项目、论文、数据、工具链全覆盖
- **[matiasmascioto/awesome-soccer-analytics](https://github.com/matiasmascioto/awesome-soccer-analytics)** — 另一个高质量 awesome 列表，中英西多语
- **[devinpleuler/analytics-handbook](https://github.com/devinpleuler/analytics-handbook)** — 足球分析新手教程，1k+ star，代码可直接跑通

#### 数据采集类
- **[probberechts/soccerdata](https://github.com/probberechts/soccerdata)** ⭐ 核心候选
  - 一个包统一封装 FBref、Understat、Sofascore、FotMob、WhoScored、ClubElo、SoFIFA 等八大源
  - 返回标准化 Pandas DataFrame，内置缓存
  - `pip install soccerdata`，几行代码拉整季数据
- **[dcaribou/transfermarkt-scraper](https://github.com/dcaribou/transfermarkt-scraper)** + **[transfermarkt-datasets](https://github.com/dcaribou/transfermarkt-datasets)** ⭐ 核心候选
  - 79000+ 场比赛，37000+ 球员，每周自动更新的结构化 Transfermarkt 数据集
  - 直接提供 DuckDB 文件和 CSV，免自己爬
- **[statsbomb/open-data](https://github.com/statsbomb/open-data)** — StatsBomb 免费开放数据（历史重大赛事），做模型训练的起点
- **[jakeyk11/football-data-analytics](https://github.com/jakeyk11/football-data-analytics)** — 个人项目但有 500 万+ Opta 传球聚类模型可借鉴

#### 数据处理与标准化
- **[PySport/kloppy](https://github.com/PySport/kloppy)** ⭐ 核心候选
  - 把 StatsBomb/Opta/Wyscout/Metrica/Sportec 等不同厂商的事件+追踪数据统一到同一套模型
  - 标准化坐标系、事件定义、正则匹配"传-传-射"等战术模式
  - 是 agent 数据层的底座
- **[PySport/databallpy](https://pypi.org/project/databallpy/)** — kloppy 的进阶，专做事件数据和追踪数据的同步融合

#### 模型与指标
- **[ML-KULeuven/socceraction](https://github.com/ML-KULeuven/socceraction)** ⭐ 核心候选
  - 比利时鲁汶大学出品，**VAEP**（动作价值估算）和 **xT**（预期威胁）的权威实现
  - 支持 StatsBomb/Opta/Wyscout/Stats Perform/WhoScored 五家数据
  - 注意：作者声明"不再积极开发"，但模型实现已足够稳定
- **[ML-KULeuven/soccer_xg](https://github.com/ML-KULeuven/soccer_xg)** — xG 模型专门库，可训练自己的 xG
- **[opisthokonta/goalmodel](https://github.com/opisthokonta/goalmodel)** — R 包，**Dixon-Coles** 等赔率建模经典实现，也可从赔率反推 xG
- **[dashee87/blogScripts](https://dashee87.github.io/football/python/predicting-football-results-with-statistical-modelling-dixon-coles-and-time-weighting/)** — Dixon-Coles Python 教程，博彩建模必读

#### 可视化
- **[andrewRowlinson/mplsoccer](https://github.com/andrewRowlinson/mplsoccer)** ⭐ 核心候选
  - 事实上的足球可视化标准库：球场、射门图、传球网络、radar/pizza 图
  - 基于 matplotlib，与 StatsBomb 数据开箱即用

### 2.2 关键论文与方法论

- **Dixon & Coles (1997)** — 博彩/赔率建模基石，至今仍是 baseline
- **Decroos et al. (2019) "Actions Speak Louder Than Goals"** — VAEP 原论文
- **Karun Singh — Expected Threat (xT)** — 区域威胁值，战术分析常用
- **StatsBomb 360** — 冻结帧数据，含防守压迫位置，是当前最前沿的开放格式

### 2.3 一个残酷现实
**顶级事件数据（Opta / Hudl StatsBomb）是企业级授权，官网不公示价格，需联系销售。** 这意味着：
- 个人用户直接拿 Opta/StatsBomb 付费数据的路径基本封死
- 实际落地需要"**付费 API（API-Football / Sportmonks）+ 合规爬虫（FBref、Understat、Sofascore）+ StatsBomb 开放数据**"的组合拳
- 这个现实在下一节的数据源策略里会系统消化

---

## 3. 数据源策略

### 3.1 三层数据架构

```
┌──────────────────────────────────────────────────────────┐
│  Layer 3 · 专业事件数据（历史+研究）                         │
│  StatsBomb 开放数据 · 免费 · JSON · 3000+ 场历史赛事          │
│  → 用途：训练 xG/xT/VAEP 模型、方法学研究                    │
├──────────────────────────────────────────────────────────┤
│  Layer 2 · 实时运营数据（赛程+赔率+基础统计）                  │
│  API-Football（付费 $19-39/月）                           │
│  → 用途：近实时赛程、阵容、基础统计、预赛+滚球赔率、预测       │
├──────────────────────────────────────────────────────────┤
│  Layer 1 · 深度补充数据（scraping+免费源）                   │
│  soccerdata（FBref/Understat/Sofascore）· 免费              │
│  transfermarkt-datasets · 免费 · 每周更新                   │
│  Club Elo · 免费 · 历史 Elo                                │
│  → 用途：赛季统计、xG shot-level、身价、伤病、球员档案        │
└──────────────────────────────────────────────────────────┘
```

### 3.2 各数据源详细对比

| 数据源 | 定价 | 覆盖 | 数据粒度 | 建议用法 |
|---|---|---|---|---|
| **API-Football** | $19-39/月 | 960+ 联赛（五大联赛+欧战+国家队全覆盖）| 赛程、阵容、基础统计、赔率、预测 | **首期主力 API**，负责一切近实时运营数据 |
| **StatsBomb 开放数据** | 免费 | 历史重大赛事（世界杯/欧洲杯/女足等）| 事件流 3400+ events/match + 360 冻结帧 | 模型训练、历史战术研究基石 |
| **Hudl StatsBomb（付费）** | 企业级（需联系销售，预算估计 5 位数/年起）| 190+ 竞赛 | 顶级事件数据+实时 GraphQL API | **首期不考虑**，后期若商业化可谈 |
| **Opta / Stats Perform** | 企业级（不公示）| 全球最全 | 顶级事件 | 同上，个人项目不现实 |
| **soccerdata**（爬虫包）| 免费 | 五大联赛+多数主流 | FBref：赛季聚合；Understat：shot+xG；Sofascore：评分 | **首期必装**，补齐 API-Football 不提供的深度指标 |
| **transfermarkt-datasets** | 免费 | 全球 | 身价、转会、合同、伤病（league-level）| **首期必装**，球员模块数据基石 |
| **The Odds API** | $30/月起 | 70+ 运动 | 40+ 博彩商实时赔率 | 如需 sharp 赔率（Pinnacle 等）可加 |
| **OddsPapi** | $49/月起，免费档 350+ 博彩商 | 全球 | 含 Pinnacle、Betfair 等 | 盘口模块深化时的替代选项 |
| **Sportmonks Football API** | $29/月起 | 类似 API-Football | 赛程、统计、赔率、预测 | API-Football 的竞品，可对比后择一 |

### 3.3 首期数据源推荐组合（已做取舍）

**立即接入（首月）：**
1. **API-Football Pro 档（$19/月）** → 近实时赛程/赔率/基础数据
2. **soccerdata（免费）** → FBref 赛季统计 + Understat shot-level xG + Sofascore 评分
3. **transfermarkt-datasets（免费）** → 身价/伤病/转会
4. **StatsBomb 开放数据（免费）** → 模型训练与历史研究

**观察后决定（2-3 个月后）：**
- 盘口深化：是否加 OddsPapi/The Odds API 获取 Pinnacle sharp 线
- 战术深化：是否升级 API-Football 到 Ultra/Mega 档
- 数据质量瓶颈：是否值得谈 Hudl StatsBomb 商业授权（预算门槛高）

### 3.4 合规提示
- `soccerdata` 的爬虫需遵循各目标站点 ToS，频率要克制（包内已有 rate-limit）
- `transfermarkt` 爬虫同样，`transfermarkt-datasets` 是别人已合规爬好的成品，优先用
- 博彩相关数据使用需留意当地法律；中国大陆用户仅做个人分析用途、不做公开投注建议

---

## 4. 系统架构

### 4.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                   用户交互层（Interface）                      │
│     CLI · Web UI · IM Bot（Telegram/Discord，可选）           │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│              Agent 编排层（LangGraph 多智能体）                │
│  Router Agent  →  分发至专业子 Agent                          │
│    ├─ TacticsAgent（战术分析）                                │
│    ├─ OddsAgent（盘口分析）                                   │
│    ├─ PlayerAgent（球员数据）                                 │
│    └─ SynthesisAgent（综合判断，多模块融合）                   │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                     工具层（Tools / MCP）                     │
│  DataFetchTool · ModelInferenceTool · VizTool · MemoryTool   │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                数据层（Data + Model + Storage）               │
│  kloppy 标准化 · DuckDB 缓存 · 模型服务（xG/xT/VAEP/Poisson）  │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                      外部数据源                               │
│   API-Football · soccerdata scrapers · Transfermarkt · SB   │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Agent 设计哲学

**为什么多 Agent 而不是单 Agent？**
足球分析三大支柱的**知识边界、数据需求、推理模式差异极大**：
- 战术分析要吃事件数据、做空间推理
- 盘口分析要吃赔率+历史，做概率反推
- 球员分析要吃身价+伤病，做画像判断

每个子 Agent 用独立的 system prompt 和专属工具集，Router 根据意图分发。复杂问题（如"推荐周末下注组合"）由 SynthesisAgent 跨模块召唤。

**对话记忆与状态：**
- 短期记忆：LangGraph checkpointing 保存对话（按 `user_id` 分片）
- 长期记忆：个人偏好（关注的队伍、风险偏好、历史判断复盘）写入向量库 + SQLite

#### 4.2.1 Agent 人设与决策风格（v0.2 新增）

**默认人设：激进判断者（Assertive Analyst）**

所有子 Agent 共享以下行为准则，固化在 base system prompt 中：

| 维度 | 行为准则 |
|---|---|
| **立场** | 数据充分时明确表态，不用"可能"、"或许"、"仁者见仁"糊弄 |
| **结构** | 每个分析必须以 `判断 → 核心理由（≤3 条）→ 反驳角度 → 置信度` 四段式收尾 |
| **置信度** | 必须显式输出 `高 / 中 / 低` 三档，并说明制约因素 |
| **转向** | 新数据推翻旧判断时，直接承认并给出新判断，不打太极 |
| **边界** | 数据真不足时说"数据不足以判断"——**这不是中立回避，是诚实**；和"我不想得罪人"的中立有本质区别 |

**示例对比：**

❌ 保守输出（我们不要）：
> 阿森纳和热刺的比赛比较难预测，两队各有优势。阿森纳主场有加成，但热刺最近状态不错。建议谨慎观察。

✅ 激进输出（我们要）：
> **判断**：阿森纳赢球概率 55%，平局 25%，热刺赢 20%。推荐方向是**阿森纳 -0.25 亚盘**。
> **核心理由**：
> 1. 阿森纳近 5 主场场均 xG 2.3，热刺客场 xGA 1.8，进攻端明显优势
> 2. 热刺中后卫罗梅罗缺阵，主帅已确认轮换右后卫
> 3. 阿森纳本届北伦敦德比至今 5 战 4 胜 1 平
> **反驳角度**：热刺反击速度快，阿森纳高位防守丢球隐患存在；首回合热刺曾零封对手
> **置信度**：**中**。模型推荐，但德比战情绪变量难建模。

**实现要点：**
- base_system_prompt 统一管理，放在 `nutmeg/agents/prompts/base.py`
- 每个子 Agent 继承 base 后只添加领域细节
- Router 在分发前做一次意图分类：`信息型`（只查数据，不要激进）vs `判断型`（激进模式全开）

### 4.3 数据标准化层

所有外部数据在进入业务逻辑前，统一通过 **kloppy** 转成标准格式，再用 **SPADL**（socceraction 提供）进一步归一化事件语义。这是为了：
- 今天用 API-Football，明天换 StatsBomb 付费，下游代码零改动
- xG/xT/VAEP 模型跨源复用

### 4.4 多租户就绪设计（v0.2 新增）

目标：**单用户阶段就按 SaaS 标准搭底座**，未来切换到 Phase 2/3 时是"拧开关"而不是"重构"。

#### 4.4.1 用户模型

```python
# nutmeg/core/identity.py
class User:
    user_id: str              # UUID
    tier: Literal["owner", "friend", "subscriber"]
    created_at: datetime
    quota: Quota              # 日/月请求配额
    preferences: dict         # 关注球队、激进度调整、语言等

# Phase 1：user_id 固定为 "owner"，其他字段预留
# Phase 2：新增 friend tier，授权码登录
# Phase 3：新增 subscriber tier，付费订阅 + API key
```

#### 4.4.2 全栈 user_id 贯穿清单

每一处涉及状态的地方，都必须带 user_id：

| 层 | 表现形式 |
|---|---|
| 数据库所有 mutable 表 | 加 `user_id` 列 + 复合主键 |
| LangGraph checkpointer | `thread_id = f"{user_id}:{conversation_id}"` |
| 向量库（长期记忆） | namespace = user_id |
| 配置文件 | `config/users/{user_id}/preferences.yaml` |
| 日志与 LangSmith | 全部 tag `user_id` |
| 缓存（DuckDB 共享数据除外） | `key = f"{user_id}:{resource}"` |

#### 4.4.3 共享 vs 隔离边界

| 类型 | 策略 | 原因 |
|---|---|---|
| 赛程、赔率、球员档案等**客观数据** | **全局共享**，一次拉取多用户复用 | 避免每用户各拉一次，浪费 API 配额 |
| 偏好、对话历史、决策记录 | **用户隔离** | 隐私 + 用户画像差异 |
| 模型文件（xG/VAEP 等） | **全局共享** | 训练成本高，模型本身无用户属性 |
| 秘钥（API-Football key 等） | **系统级** Phase 1-2；**用户级**（用户自带 key 或使用订阅配额）Phase 3 | Phase 3 商业化后需结算 |

#### 4.4.4 配额与限流

Phase 1 简单起步，Phase 2-3 逐步启用：
- `@requires_quota(resource="api_football", cost=1)` 装饰器用在所有外部 API 调用点
- Phase 1：配额无限，只是记录用量（为后面定价参考）
- Phase 2：按用户 tier 分级配额
- Phase 3：接入支付系统扣费

#### 4.4.5 部署形态演进

| Phase | 部署方式 | 关键组件 |
|---|---|---|
| Phase 1 | 本机或个人 VPS，单容器 | Python process + DuckDB + SQLite |
| Phase 2 | 云 VPS，多容器 | +PostgreSQL（取代 SQLite）+ Redis（会话缓存）+ 简单授权码登录 |
| Phase 3 | 云原生 | +K8s / Serverless + 对象存储 + CDN + Stripe 订阅 + 正式认证 |

**关键提醒**：Phase 1 *不需要*部署 PostgreSQL/Redis/K8s，但**代码要写成能无痛换存储后端**——比如用 SQLAlchemy 而不是直接 SQLite API、用 Repository 模式封装数据访问。

---

## 5. 核心功能模块

### 5.1 战术分析模块（Tactics）

| 功能 | 说明 | 数据来源 | 实现参考 |
|---|---|---|---|
| 赛前预览 | 双方近 5 场 xG/xT/压迫图、预期阵型、关键对位 | API-Football + soccerdata | mplsoccer |
| 赛后复盘 | 射门图、传球网络、进攻热区、xG timeline | soccerdata (Understat/FBref) | mplsoccer + socceraction |
| 球队风格画像 | 进攻倾向（直塞/两翼/高压）、防守线高度、控球风格 | FBref 赛季聚合 | 自研聚类 |
| 关键对位识别 | 基于球员位置热区的对位薄弱点 | StatsBomb 开放数据训练 | 自研 |
| 阵型识别 | 从开球 5 分钟位置推断实际阵型 | API-Football lineups + 若有追踪数据 | 规则+ML |

**输出范式**：
- Agent 文字判断 + mplsoccer 可视化附件 + 数据表

### 5.2 盘口/博彩分析模块（Odds）

| 功能 | 说明 | 数据来源 | 实现参考 |
|---|---|---|---|
| 赔率采集与对比 | 多家博彩商三维/亚盘/大小球赔率快照 | API-Football odds + 可选 OddsPapi | - |
| 无抽水公平概率 | 去 vig 还原真实隐含概率 | - | 自研，几行代码 |
| 模型对赔 | Dixon-Coles + Poisson 输出模型概率，对比市场赔率找价值 | goalmodel + 自训 | dashee87 教程 |
| xG 增强版盘口 | 用近 N 场 xG 代替进球数喂模型，抗运气偏差 | soccerdata Understat | 自研 |
| 亚盘/大小球专项 | 大小球模型基于双方历史场均 xG | soccerdata + 自研 | - |
| 凯利仓位建议 | 给定 bankroll 输出仓位（默认 1/4 Kelly） | - | 自研 |

**输出范式**：
- 赛事卡片：模型概率 / 市场均价 / 最佳赔率商家 / 价值评分 / 凯利仓位
- Agent 主观加分/减分：伤病、轮换、动机、场地——这些是**模型之外**的主观因素，由 Agent 结合其他模块判断

**重要立场声明**：
本模块仅供个人分析和教育用途。博彩有风险，Nutmeg 不会"推荐下注"——它帮你理解赔率与真实概率的偏离，决策权始终在你。

### 5.3 球员数据模块（Players）

| 功能 | 说明 | 数据来源 |
|---|---|---|
| 球员档案 | 基础信息、当前俱乐部、合同、身价历史 | Transfermarkt |
| 赛季指标 | 进球、助攻、xG、xA、关键传球、成功对抗率 | FBref via soccerdata |
| 状态评估 | 近 5 场 Sofascore 评分、xG/90、VAEP/90 | soccerdata + socceraction |
| 伤病追踪 | 当前伤病状态、预计复出时间、历史伤病 | Transfermarkt (tm_player_injury_history) |
| 转会可能性 | 身价趋势、合同剩余、近期新闻信号 | Transfermarkt + 可选新闻 API |
| 相似球员推荐 | 基于向量相似度找风格相近球员 | 自研（VAEP + Pizza 指标） |

### 5.4 综合判断（Synthesis）

这是 Agent 真正"替你决策"的地方。示例查询：
- **"周六皇马 vs 巴萨，给我一份赛前分析和下注建议"**
  → Router 分发 → TacticsAgent（双方战术画像）+ PlayerAgent（双方核心伤病/状态）+ OddsAgent（市场赔率+模型对比）→ SynthesisAgent 综合 + 主观风险提示
- **"曼联这个月的表现值得改变我对他们欧联出线的判断吗？"**
  → 调取近 5 场 xG/xT 趋势 + 对手难度 + 关键球员状态 → 给出"是/否/中立"的判断及理由

---

## 6. 技术栈选型

### 6.1 核心栈

| 层 | 选型 | 理由 |
|---|---|---|
| 语言 | **Python 3.12** | 足球分析生态几乎全 Python |
| Agent 编排 | **LangGraph** | 支持多 Agent、状态持久化、人机回路 |
| **Agent 评估与追踪** | **LangSmith**（Sprint 0 即接入，v0.2）| Agent 轨迹可观测、eval 数据集管理、Prompt 版本化——对多 Agent 复杂系统近乎必需 |
| LLM | **Claude Sonnet 4.5 / Opus 4.7**（首选） + 本地 Qwen/DeepSeek 兜底 | Claude 的长文和推理对复杂分析最好 |
| 数据标准化 | **kloppy** | 业界标准，一次接入全兼容 |
| 指标与模型 | **socceraction**（VAEP/xT/SPADL）+ **soccer_xg** + **goalmodel**(R via rpy2) | 成熟实现，避免造轮子 |
| 数据采集 | **soccerdata** + API-Football SDK + **transfermarkt-datasets** | 三者覆盖互补 |
| 可视化 | **mplsoccer** + Plotly（交互） | 事实标准 |
| 存储（Phase 1）| **DuckDB**（分析）+ SQLite（状态）+ Parquet（归档） | 本地轻量、SQL 友好 |
| 存储（Phase 2+ 预留）| PostgreSQL + Redis | 多用户后切换 |
| 数据访问 | **SQLAlchemy + Repository 模式**（v0.2）| 隔离存储后端，便于未来换库 |
| 调度 | **APScheduler** → **Prefect**（复杂后升级） | 每日增量拉取 |
| **交互界面（首期）** | **CLI（Typer）+ IM Bot**（v0.2 调整）| CLI 开发快，IM bot 天然适配个人助手 |
| **交互界面（后期）** | Streamlit → Next.js | 应用成熟后再上 Web UI |

### 6.2 项目目录结构建议

```
nutmeg/
├── README.md
├── DESIGN.md                    # 本文档
├── pyproject.toml
├── .env.example                 # API keys 模板（含 LANGSMITH_API_KEY）
├── config/
│   ├── leagues.yaml             # 关注的联赛/赛事白名单
│   ├── teams.yaml               # 队名标准化映射
│   └── users/                   # 每用户偏好（v0.2）
│       └── owner/
│           └── preferences.yaml
├── nutmeg/
│   ├── core/                    # 核心抽象（v0.2）
│   │   ├── identity.py          # User / Tenant 模型
│   │   ├── quota.py             # 配额与限流
│   │   └── repositories.py      # Repository 抽象
│   ├── agents/                  # LangGraph agents
│   │   ├── prompts/             # 人设 + 各模块 prompt（v0.2）
│   │   │   ├── base.py          # 激进决策基础 prompt
│   │   │   ├── tactics.py
│   │   │   ├── odds.py
│   │   │   └── player.py
│   │   ├── router.py
│   │   ├── tactics.py
│   │   ├── odds.py
│   │   ├── player.py
│   │   └── synthesis.py
│   ├── data/                    # 数据接入层
│   │   ├── api_football.py
│   │   ├── soccerdata_client.py
│   │   ├── transfermarkt.py
│   │   └── statsbomb_open.py
│   ├── models/                  # 模型层
│   │   ├── xg.py
│   │   ├── vaep.py
│   │   ├── dixon_coles.py
│   │   └── betting.py           # Kelly, no-vig conversion
│   ├── viz/                     # 可视化
│   ├── tools/                   # Agent tools（MCP-ready）
│   ├── storage/                 # SQLAlchemy + DuckDB 封装
│   ├── memory/                  # 用户偏好、决策历史（按 user_id 分片）
│   ├── interfaces/              # 交互入口（v0.2）
│   │   ├── cli.py               # Typer CLI
│   │   └── bot/                 # Telegram/Discord bot
│   └── evals/                   # LangSmith eval 数据集（v0.2）
├── notebooks/                   # Jupyter 探索
├── tests/
└── scripts/                     # 定时任务脚本
```

---

## 7. MVP 迭代路线图

以 2 周为一个 sprint。每个 sprint 结束有一个可演示的 slice。

### Sprint 0 · 基础设施（Week 1-2）
- [ ] 项目骨架、依赖管理（uv/poetry）、CI（GitHub Actions）
- [ ] **User / Tenant 抽象落地**（v0.2）：`core/identity.py`，Phase 1 硬编码 `user_id="owner"`
- [ ] **Repository 抽象**（v0.2）：SQLAlchemy + DuckDB，便于后续换 PostgreSQL
- [ ] API-Football Pro 订阅、Key 管理（`.env` + pydantic-settings）
- [ ] DuckDB 初始化、赛程表 schema（**所有 mutable 表都带 user_id 列**）
- [ ] **LangSmith 接入**（v0.2）：项目创建、tracing 启用、基础 eval dataset 骨架
- [ ] 拉取五大联赛+欧战未来 30 天赛程的 ETL 脚本
- [ ] 最小 CLI（Typer）：`nutmeg --help`、`nutmeg fixtures --league epl --next 7d`
- **交付物**：
  - CLI 能输出未来 7 天赛程
  - LangSmith 里能看到每次 CLI 触发的 trace
  - 架构已预留多用户切换点（虽然 Phase 1 只有一个 user）

### Sprint 1 · 数据拼图（Week 3-4）
- [ ] 接入 soccerdata：FBref 赛季统计、Understat shot 数据
- [ ] 接入 transfermarkt-datasets：身价、伤病
- [ ] kloppy 标准化层落地（先标准化 API-Football 事件）
- [ ] 团队/球员 ID 跨源映射配置文件
- **交付物**：给定一场比赛，能从多源拼出一份"数据快照"（赛程+双方阵容+近期战绩+伤病）

### Sprint 2 · 战术分析 v0（Week 5-6）
- [ ] 集成 mplsoccer，实现射门图、传球网络
- [ ] 用 StatsBomb 开放数据训练 xG 基线模型（或直接用 soccer_xg 预训练）
- [ ] 近 5 场风格画像（控球率、PPDA、xG 创造区、对抗成功率）
- [ ] TacticsAgent v0（LangGraph 单节点）
- [ ] **激进决策输出模板**（v0.2）：`判断 → 核心理由 → 反驳角度 → 置信度` 四段式
- [ ] **LangSmith eval**（v0.2）：至少 10 个战术分析 case，标注"理想输出"，跑 eval
- **交付物**：`"给我阿森纳 vs 热刺赛前战术分析"` 返回文字（符合四段式）+3 张图

### Sprint 3 · 盘口分析 v0（Week 7-8）
- [ ] API-Football 赔率拉取与入库
- [ ] 无抽水概率转换工具
- [ ] Dixon-Coles 模型实现（Python 或用 R goalmodel via rpy2）
- [ ] 模型概率 vs 市场对比报表
- [ ] OddsAgent v0
- **交付物**：周六赛前生成一份"全联赛价值榜"：模型看好但市场低估的场次

### Sprint 4 · 球员模块 v0（Week 9-10）
- [ ] 球员档案聚合（基础+赛季+伤病+身价历史）
- [ ] Pizza Chart / Radar 对比可视化
- [ ] PlayerAgent v0
- [ ] 相似球员 v0（用 FBref 标准 90 指标向量化 + 余弦相似）
- **交付物**：`"帮我分析一下居勒尔本赛季的状态，和去年同期比"`

### Sprint 5 · 综合判断（Week 11-12）
- [ ] Router + SynthesisAgent
- [ ] 记忆模块：关注的球队、历史判断复盘
- [ ] 跨模块问答 E2E
- **交付物**：能完整回答"周末曼市德比赛前分析+下注建议"

### Sprint 6 · 打磨与 IM 接入（Week 13-14）
- [ ] **Telegram/Discord Bot 接入**（v0.2 调整）：同一 Agent 内核，前端从 CLI 扩到 IM
- [ ] 定时任务：每日增量数据拉取、每周赛程推送
- [ ] 首轮实盘对照：每周复盘 Agent 判断和实际结果，统计模型 Brier Score
- [ ] LangSmith 上的 eval 扩展到 30+ case（三大模块各 10）
- **交付物**：可稳定日常使用的 v0.1（个人工具阶段成熟，准备进入 Phase 2 共享）

### Sprint 7+（Phase 2 起点）
**Phase 2（朋友共享）准备工作**：
- 授权码登录（简单 JWT）
- SQLite → PostgreSQL 迁移（Repository 抽象已就绪，零业务代码改动）
- 简易用户管理 CLI：`nutmeg user add --name=zhangsan`
- 每用户独立 LangSmith project 或 tag

**候选功能方向**（根据使用反馈选其一）：
- 实时滚球模式（in-play 赔率监控+异动告警）
- 冬窗转会信号（Transfermarkt + 新闻信号融合）
- 中超/亚洲赛事接入（API-Football 已覆盖，零增量成本）
- 中文解说稿件自动生成
- 追踪数据（若能拿到 Skillcorner 等）→ 防守压迫图、真实控球

---

## 8. 成本估算

### 8.1 首期月度运行成本（个人使用，Phase 1）

| 项目 | 成本 | 备注 |
|---|---|---|
| API-Football Pro | $19 | 7500 req/day 够用 |
| Claude API（Sonnet 4.5）| $20-50 | 视使用频率 |
| **LangSmith**（v0.2） | $0-39 | Developer 档免费 5k trace/月，Plus 档 $39 起 |
| 服务器（可选）| $5-10 | VPS；本地跑为 $0 |
| 域名（可选）| $1/月 | 项目站点 |
| **合计** | **≈ $45-120/月** | 主要变量是 Claude 和 LangSmith 档位 |

> LangSmith Developer 免费档在 Sprint 0-3 应该够用。Sprint 4+ 如果 eval 数据量大，再考虑升级。

### 8.2 升级路径（视实际需求）

| 触发条件 | 升级方案 | 增量成本 |
|---|---|---|
| API-Football 请求超限 | 升 Ultra ($29) 或 Mega ($39) | +$10-20 |
| 需要 sharp 赔率线 | OddsPapi Starter ($49) | +$49 |
| Agent 长链推理多 | 换 Opus 4.7 | +$50-150 |
| 需要顶级事件数据 | Hudl StatsBomb 商业授权 | **企业级谈判**（年 5 位数起）|

---

## 9. 风险与开放问题

### 9.1 技术风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| **soccerdata 爬虫被封** | 数据断流 | 多源冗余 + 主动限速 + 必要时 proxy pool |
| **API-Football 数据粒度不够** | 战术深度受限 | 首期用其作运营数据，深度靠爬虫补 |
| **StatsBomb 开放数据覆盖有限** | 模型训练样本偏 | 用 Understat 公开 shot 数据辅助 |
| **LangGraph 学习曲线** | Sprint 0-1 可能超期 | 前两个 sprint 允许单 Agent 先跑通 |

### 9.2 方法学风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| **xG 模型供应商偏差** | 不同源 xG 不可直接比较 | 统一用一家；或跨源用 rank 而非 absolute |
| **博彩市场有效性** | 长期跑赢市场极难 | 不做"赢市场"承诺；定位在**辅助主观判断** |
| **Agent 幻觉** | 编造比分、球员、事件 | 关键事实必须 tool call，禁止 LLM 直接生成数据 |

### 9.3 决议记录（v0.2 已回答）

v0.1 的 6 个开放问题已全部决议，影响架构的设计决策已在相关章节落地：

| # | 问题 | 决议 | 影响章节 |
|---|---|---|---|
| 1 | 开源 vs 私有 | **私有试错，未来走服务化路线（SaaS）** | §1.1.1 演进路径、§4.4 多租户就绪 |
| 2 | Agent 决策风格 | **激进型**：数据支持时敢于明确判断 | §1.4 原则、§4.2.1 人设 |
| 3 | 单用户 vs 多用户 | 首期单用户，未来朋友共享 → 付费订阅 | §4.4 全栈 user_id 贯穿 |
| 4 | Web UI 必要性 | **先不做**，成熟后再上 | §6.1 接口栈、Sprint 6 改 IM bot |
| 5 | LangSmith 启用时机 | **Sprint 0 即接入** | §6.1、Sprint 0 任务列表 |
| 6 | 中超/亚洲赛事 | 首期不做，未来加入（API-Football 已覆盖） | §1.2 覆盖范围不变 |

### 9.4 v0.2 新增的开放问题

1. **激进决策的"刹车机制"**：Agent 在极低置信度时是否强制降级到"拒绝判断"？判断失误后的学习闭环怎么设计？
2. **Phase 2/3 商业化边界**：博彩相关分析模块在未来对外服务时的合规问题（不同地区法律差异大）——是否把盘口模块做成"opt-in 付费插件"而非默认功能？
3. **LangSmith 数据敏感性**：个人偏好、下注历史送到 LangSmith trace 合适吗？是否需要 PII 脱敏层？

---

## 10. 附录

### 10.1 核心开源项目速查表

| 项目 | 用途 | 首期必装 |
|---|---|---|
| [soccerdata](https://github.com/probberechts/soccerdata) | 8 源统一爬虫 | ✅ |
| [kloppy](https://github.com/PySport/kloppy) | 事件/追踪数据标准化 | ✅ |
| [socceraction](https://github.com/ML-KULeuven/socceraction) | VAEP/xT/SPADL | ✅ |
| [mplsoccer](https://github.com/andrewRowlinson/mplsoccer) | 可视化 | ✅ |
| [transfermarkt-datasets](https://github.com/dcaribou/transfermarkt-datasets) | 身价/伤病/转会 | ✅ |
| [statsbombpy](https://pypi.org/project/statsbombpy/) | StatsBomb 开放数据 | ✅ |
| [soccer_xg](https://github.com/ML-KULeuven/soccer_xg) | xG 模型训练 | 视需要 |
| [databallpy](https://pypi.org/project/databallpy/) | 事件+追踪融合 | 拿到追踪数据后 |
| [goalmodel (R)](https://github.com/opisthokonta/goalmodel) | Dixon-Coles | 盘口模块 |
| [eddwebster/football_analytics](https://github.com/eddwebster/football_analytics) | 综合资源索引 | 学习参考 |
| [LangGraph](https://github.com/langchain-ai/langgraph) | Agent 编排 | ✅ |

### 10.2 数据源 API 端点速查

| 源 | 访问方式 | 认证 |
|---|---|---|
| API-Football | REST `https://v3.football.api-sports.io/` | `x-apisports-key` header |
| StatsBomb Open | GitHub raw + statsbombpy | 无 |
| StatsBomb Paid | GraphQL | HTTP Basic |
| FBref/Understat/Sofascore | soccerdata 封装 | 无（respect rate limit）|
| Transfermarkt | transfermarkt-datasets（DuckDB）或 scraper | 无 |

### 10.3 关键论文书单

- Dixon & Coles (1997). *Modelling Association Football Scores and Inefficiencies in the Football Betting Market*
- Decroos et al. (2019). *Actions Speak Louder than Goals: Valuing Player Actions in Soccer* (KDD)
- Singh, K. *Introducing Expected Threat (xT)* (blog post)
- Sumpter, D. *Soccermatics* (book)
- Anderson & Sally. *The Numbers Game* (入门读物)

---

## 文档迭代记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-04-24 | 初稿：基于 GitHub 生态调研 + 数据源对比，确定三层数据架构、多 Agent 设计、7 个 sprint 路线图 |
| v0.2 | 2026-04-24 | 落地 6 项决议：①产品演进三 Phase 路径 + 多租户就绪设计（§1.1.1, §4.4）；②Agent 激进决策人设（§1.4, §4.2.1）；③CLI/IM bot 优先，Web UI 后置（§6.1, Sprint 6）；④Sprint 0 即接入 LangSmith（Sprint 0, §6.1）；⑤目录结构增补 `core/`、`prompts/`、`interfaces/`、`evals/`；⑥更新成本测算加入 LangSmith |

---

**下一步动作建议：**
1. 你过一遍 v0.2，重点看 **§4.4 多租户就绪** 和 **§4.2.1 激进人设** 两块是否符合你的设想
2. §9.4 留了 3 个新问题，其中**"Phase 2/3 商业化时盘口模块的合规问题"**是最值得提前思考的
3. 方向 OK 后，可以立即进入 Sprint 0：
   - 我帮你起一份 **Sprint 0 的代码骨架**（`pyproject.toml` + 完整目录 + 最小 CLI + LangSmith 接入 stub + Repository 抽象雏形）
   - 或先画一版 **Mermaid 架构图**嵌入 DESIGN.md
   - 或起一版面向 GitHub README 的项目介绍（中英双语，含 logo 占位）
