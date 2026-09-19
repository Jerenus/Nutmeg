# RSI 观察台（只读全景界面 ②）· 设计

日期：2026-09-19 ｜ 状态：用户裁定 Q2→A；本文为定稿待审 ｜ 后续：writing-plans
依赖：RSI 层（已落地）；专项 spec（候选树、`zucai_capital_plan`）；深研桥 spec（R0）。数据缺席时页面必须优雅降级，不得空白。

## 0. 一句话

一个**只读**的观察实验界面：让用户不开聊天窗口也能看懂 RSI 全景——每条实验此刻在哪、离判决多远、哪几天缺了样本、今天的候选树长什么样、资金方案为什么是这个数——**不提供任何干预入口**。

## 1. 用户裁定

| # | 裁定 | 来源 |
|---|---|---|
| O1 | 不干预，只理解：页面没有写操作 | 用户原话 |
| O2 | 扩展现有 decision-web（FastAPI + Jinja + 原生 JS），图表用 cdnjs 的 ECharts；读 `ProductReadRepository` 与事件流，同一 `as_of` | Q2 → A |
| O3 | 「现代化智能视觉效果」——靠版式、动效与信息设计，不靠换框架 | 用户原话 + Q2 |

## 2. 三个页面

| 路由 | 回答的问题 | 数据源（全部只读） |
|---|---|---|
| `/observe` | **全景**：每条实验一张卡——状态、n_cum/n_min 进度环、CI 区间条与 falsifier 阈值线、距判决 pp、gaps 热力条、下一期义务倒计时；顶部「今日风向」（若有 tiers）与义务日历（今天/明天到期几张） | `experiments(as_of)`、`duties_due(day)`、`<issue>-tiers.json`（可缺） |
| `/observe/exp/<exp_id>` | **一条实验的一生**：时间线（登记 → 观察 → 结账 → 判决 → 上线/修正案），每次 grade 的 CI 演化折线 + 阈值线，冻结判据原文与 hash，gaps 列表 | `experiment_timeline(exp_id, as_of)` |
| `/observe/day/<date>` | **一天的过程**：候选树 DAG（tiers 根 → 前沿层 → 人的分叉，节点显示 P / 注数 / verdict，边 = parent_version）、资金方案卡（cap 来源、三个 max P 并排、门代价）、当日实票入账状态、判读入库列表 | 事件流 `candidate/slip/judgment`（已有 `_day_state`）、`uow.capital.latest_plan(issue)`（可缺） |

导航：工作台顶栏加「观察台」链接；观察台任何一页都有回工作台链接。观察台**不加载 `app.js` 的写操作模块**。

## 3. 视觉与交互

- ECharts 5（`https://cdnjs.cloudflare.com/ajax/libs/echarts/5.5.1/echarts.min.js`，固定版本）：进度环（gauge）、CI 区间（custom series）、时间线（timeline/scatter）、DAG（graph，force 或分层布局）。
- 版式：深色底可切换（跟 `prefers-color-scheme`），卡片网格，实验卡按状态着色（observing 青 / graded 琥珀 / falsified 灰 / survived 绿 / deployed 靛）；数字用等宽字。
- 动效只做两处：进度环加载、DAG 节点悬停高亮父链。**不做自动刷新以外的任何交互写入**；`/observe` 每 60 秒轮询一次 `/api/observe`。
- 移动端：卡片单列，DAG 可横向滚动。

## 4. 只读 API（供页面轮询与②以外的消费者）

- `GET /api/observe?as_of=` → `{experiments:[…], duties_today:[…], duties_tomorrow:[…], wind:{…}|null}`
- `GET /api/observe/exp/<exp_id>?as_of=` → 时间线数组
- `GET /api/observe/day/<date>` → `{tree:{nodes:[…], edges:[…]}, plan:{…}|null, slips:[…], judgments:[…]}`
所有端点无副作用；`as_of` 缺省 = 现在。

## 5. 降级规则

- 没有 tiers 文件 → 风向区显示「今日未定级」；没有资金方案 → 方案卡显示「未定案」；没有候选事件 → DAG 区显示「今日无候选树」。
- 内核不可用（未初始化）→ 全页显示一条明确错误，不抛 500。
- 页面永远不会因为某一块数据缺失而整页失败（每块独立 try）。

## 6. 测试

- 三个 API：空库返回结构完整（列表空、可缺项为 null）；塞入实验/观察/grade/verdict 后字段正确；`as_of` 早于登记时不可见。
- DAG 构建：`candidate` 事件 → 节点/边；`parent_version` 缺失 = 根；孤儿父（父版本不存在）不抛，边丢弃并计数。
- 页面：三个路由 200；HTML 含 ECharts script 标签且版本固定；不含任何 `POST`/`form`；工作台顶栏含观察台链接。
- 降级：无 tiers / 无 plan / 无 candidate 时对应文案出现。

## 7. 出口条件

打开 `/observe` 能看到 F1c/F2/F3/F4/F5/R0 六张卡，F1c 的 gaps 热力条有四格；点 F2 进入一生页看到 grade 的 CI 演化；`/observe/day/2026-09-19` 显示 SFC-B→E 的树与回填的资金方案。全程零写操作。
