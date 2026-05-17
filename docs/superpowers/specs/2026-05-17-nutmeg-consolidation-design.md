# Nutmeg 整合设计 — 收敛为中国体彩投注助手

- **日期**：2026-05-17
- **状态**：✅ 全部 4 期完成（Phase 1 清理 / 2 精简 / 3 接线 / 4 收尾），主干 `e4efdeb` 测试全绿（711 passed）
- **目标**：把当前庞杂项目（~60% 投注 + ~40% 无关）收敛为一个聚焦的**中国体彩投注助手**。

---

## 1. 现状（全项目审计结论）

两套**互相独立**（无交叉 import）的投注子系统 + 大量无关模块：

- **JCZQ**（~21 服务模块）—— 竞彩足球日常系统。主产品，测试充分。
- **Zucai/足彩**（~5 服务模块）—— 第二套彩种系统，平行独立。
- **Value/Odds**（~8 模块）—— `api_football` + `the_odds_api` + Dixon-Coles + **`ValueBoardService`**。`ValueBoardService` 即"模型 vs 市场赔率的冲突点/价值检测引擎"。
- **非投注（~40%）**—— 视频生成（moneyprinter/seedance/remotion/video_worker/video_production）、内容生成（content/daily_content）、WeChat 发布。
- **临时/死代码** —— 空包、graphify-out/、notebooks/、一次性脚本、旧设计文档。

## 2. 用户决策（2026-05-17 拍板）

| 项 | 决策 |
|---|---|
| Zucai/足彩 | **保留** —— 纳入最终助手范围 |
| 非投注模块（视频/内容/WeChat）| **先归档到分支，再从主干删除** |
| psychology 信号子系统 | **保留并精简**（14 文件 → 1-3） |
| Telegram | 推送（dispatch）保留；交互式 polling bot 暂留不动 |

## 3. 目标架构 —— 最终助手

一个聚焦的体彩投注助手，服务 JCZQ + Zucai 两个彩种，核心是"冲突点驱动"的每日方案：

```
每日数据(体彩赔率 + API-Football 国际赔率) 
        │
        ▼
冲突点检测引擎 = ValueBoardService（模型概率 vs 市场公允概率 → edge → EV → Kelly）
        │            ＋ psychology 信号 + 情报（阵容/伤停）—— 多方因素并列呈现 [补充 A]
        ▼
串关构造器：冲突腿按信心 → 2/3/4串1，守 Rule O 同场合法性 + 集中度上限 [补充 B]
        │            玩法：胜平负 / 让球 / 总进球 / 比分（半全场已排除）
        ▼
debate 工作流（Claude 草案 → Codex review → 人工裁决）→ 最终方案
        │
        ▼
Telegram 推送 → 次日 jczq-daily-review 回测 → 冲突信号 store
        │
        ▼
注金阶梯 OBSERVE→SMALL→NORMAL→KILL（按累积 ROI 自动分档）[补充 C]
```

**两套投注子系统的关系**：JCZQ / Zucai 各自是"产品+工作流外壳"；Value/Odds 引擎是**共享的分析底座**——`ValueBoardService` 当冲突点来源，接入两者的每日流程。

**保留**：JCZQ、Zucai、Value/Odds 引擎、psychology（精简）、core/config/data/domain/models/storage/interfaces、Telegram 推送、analysis/operations 编排层、agents 合成层（可选 gate）。
**移除**：视频生成、内容生成、WeChat 发布、空包与临时文件。

> **作废说明**：本会话早先的"冲突引擎 spec v1-v4 + 实现计划"（提交 `8435e97`/`de3ccdc` 等）是在不知 `ValueBoardService` 已存在的情况下重复设计——**全部作废**。冲突引擎 = 已有的 `ValueBoardService`，工作是"接线 + 扩展玩法"，不是新建。

## 4. 分期执行

### Phase 1 — 清理（本设计落地后立即执行）
- 建归档分支 `archive/non-betting-2026-05-17`，保全当前完整代码。
- 主干删除非投注模块：服务 `content.py`/`daily_content.py`/`video_production.py`/`video_worker.py`/`moneyprinterturbo.py`/`seedance.py`/`remotion.py`/`wechat_publisher.py`；对应 domain、tests、`cli.py` 命令（content-pack / wechat-* / daily-content-pack / video-* / seedance-*）；顶层 `video/`。
- 删临时/死代码：`graphify-out/`、`notebooks/`、`Nutmeg-DESIGN-v0.2.md`、`agent-progress.md`、一次性脚本（`jczq_5_12_pdf_dispatch.py`、`render_v32_caption_overlays.py`、`refresh_graph.py`、`acceptance.sh`、`verify.sh`）、死锁的 agent worktree、空包。
- 验收：`uv run pytest tests/` 全绿（删模块同时删其测试，剩余必须全过）。
- evals / popularity 等"无关但低风险"模块本期**不动**，留作后续单独确认。

### Phase 2 — 精简
- psychology 14 文件合并为 1-3（保留 JCZQ 用到的信号能力）。
- 三个 odds 客户端（api_football / the_odds_api / european_odds）归一到单一 `OddsProvider` 协议。

### Phase 3 — 接线（核心价值）
- **3a ✅ 完成**：扩展 value 引擎到 4 玩法（胜平负 + 总进球 + 比分 + 让球），模型 + odds 解析 + 引擎 + 测试全绿。提交 `e876ae2` / `3471e51`。**半全场排除**（需半场模型 + R27 历史 0/18，用户决定不做）。
- **3b ✅ 完成**：`ValueBoardService` 接入 JCZQ 每日流程 —— brief 新增"冲突点"节，**并列呈现** value 冲突点 + psychology 信号 + 情报（补充 A 多方因素）；**串关构造器**把冲突腿按信心组装成 2/3/4串1，守 Rule O 同场合法性 + 集中度上限（补充 B）。
- **3c ✅ 完成**：接入 Zucai 流程。`ZucaiValueBridge`（`zucai_value_bridge.py`）复用 JCZQ 的 `MatchAligner` + 别名表，把一期足彩 14 场对齐到 API-Football fixture，跑 `ValueBoardService.build_board_for_fixtures`，为每场抽出一条逐场 1X2（had）冲突信号（模型最看好且有 +edge 的 `match_winner` 结果 → 体彩 3/1/0 + 短注解）。`ZucaiRenjiuDailyService.build_report` 接受可选 `value_bridge`，把信号挂到 `RenjiuMatchAnalysis.conflict_signal`，在 markdown/PDF 逐场判断里渲染「冲突引擎：模型：平 +6% edge」注解列。**精简**：既有 `_double_pick` / `_uncertainty_score` 选号算法不改写，冲突信号只是供人工/debate 额外权衡的一列。`zucai_value_wiring.build_zucai_value_bridge` 从 settings 组装生产桥；CLI `zucai-renjiu-daily` + `ZucaiRenjiuBotWorkflow` 接线。优雅降级：无 key / 桥崩 / 未对齐 → 无注解、报告照常出、记 warning、不崩。
- **3d ✅ 完成 — 自我验证（补充 C）**：冲突信号 store（`.nutmeg-data/jczq/memory/conflict-signals.json`）+ OBSERVE/SMALL/NORMAL/KILL 注金阶梯；引擎未攒够 ROI>1 样本前只能小注/纸面；次日 `jczq-daily-review` grade 冲突腿写回 store。
- **3e ✅ 完成**：odds 客户端归一 —— `OddsProvider` 协议落在 `nutmeg/domain/odds.py`，`api_football` / `the_odds_api` 两客户端**本已隐式满足**该协议，工作是把 `services/odds.py` 里重复的非正式协议收敛为单一 `@runtime_checkable` 定义、调用点改依赖它。`european_odds.py` 是 `cross_check_signals` 引擎、非 fetch 客户端，不在范围内。

### Phase 4 — 收尾 ✅完成
- **CLI 重组 ✅**：`cli.py`（3408 行）拆为 `nutmeg/interfaces/cli/` 包，按子系统分模块（jczq / zucai / odds / psychology / telegram / operations / core / client + `__init__.py` 持 `app` 与共享件、re-export）。**用户决策：非破坏式重组** —— 57 个命令全部保留原名（`nutmeg jczq-daily-brief` 等照旧），**不**拆 typer 子命令组（设计原稿写的是子命令组，但那会改掉每天在用的命令名，用户选择只重组文件内部）。`test_cli.py` 零改动。提交 `e4efdeb`。
- **端到端验收测试（补充 E）✅**：`tests/test_daily_pipeline_acceptance.py`，8 个测试串起完整每日流程（数据→冲突点→串关→brief 渲染→注金阶梯），逐级断言真实接线后的服务组合；网络边界用既有内存 fake。无集成 bug —— 每级输出干净对接下一级。提交 `d0fc2f9`。
- **文档收敛 ✅**：删 34 个死文档（视频/内容/wechat/漫画/抖音子系统的 specs+plans、作废的 odds-conflict-engine spec+plan、`docs/style-assets/` 漫画套件、`video-production-v2.md`、`content-publisher` 架构笔记）。**偏差说明**：未按字面"只留 4 份文档"执行 —— 记录活投注代码的设计文档（jczq / zucai / value / psychology 的 specs+plans、投注架构笔记、ADR）全部保留，删除活代码的设计依据会丢失真实历史。specs 25→17、plans 19→11。提交 `8b3e37b`。
- **`jczq_final_plan_pdf.py` "5张票"修复 ✅**：3 处硬编码 → `len(plan['tickets'])`，适配 R28 退役 C 票后的动态 4-5 张票；顺带抽出可测的 `_build_story`。提交 `c042fb4`。

## 5. 风险与原则

- **不可逆删除**：Phase 1 全部走"归档分支 → 主干删"，可回溯。
- **保持绿**：每阶段结束 `pytest` 全绿，不留破窗。
- **不超范围删**：只删用户签字的类别；evals/popularity 等留待单独确认。
- **分期**：Phase 1（清理）可快速完成；Phase 2-3（精简+接线）是工程量较大的后续构建。
- **精简规则、不再堆约束（硬原则）**：JCZQ 老框架的 R1-R28 是"每输一次禁一样"的治标跑步机——约束不产生 edge，过度约束只会让系统越来越只能做胆小的 -EV 注。新冲突引擎路径**只用三样规则**：Rule O 同场合法性 + 集中度上限 + 注金阶梯。注金阶梯是"按实绩定注金大小"，不是禁玩法——它不削弱找机会的能力。**禁止**把 R1-R28 补丁堆搬进新路径；旧 generator + R 规则仅作小联赛 fallback 保留。新系统的 edge 来自"独立赔率冲突"这个真实信号源，而非靠加规则。

### 原决策框架整合后定位
- **保留为运营闭环**：debate → review → 回测 → 策略记忆。
- **保留为薄风控层**：Rule O、集中度上限。
- **降为 fallback**：Poisson generator + R1-R28（冲突引擎无覆盖的小联赛兜底）。
- **被取代**：jczq_poisson 模型 → Dixon-Coles value 模型；generator 主候选 → 冲突引擎主候选。

## 6. 成功标准

- Phase 1 后：主干只剩投注相关代码（JCZQ + Zucai + Value/Odds + psychology + core），测试全绿，仓库体积显著下降。
- Phase 3 后：每日方案的候选来自冲突点引擎（模型 vs 国际赔率）→ 串关构造器 → debate；注金由 OBSERVE/SMALL/NORMAL/KILL 阶梯按累积 ROI 自动分档（引擎未验证前不重注）。
- 端到端验收测试通过：完整每日流程可跑、关键产出被断言。
- 最终：一个能维护、聚焦、**自我验证**的体彩投注助手——edge 未经实绩验证前注金受限，回测回路持续校准。
