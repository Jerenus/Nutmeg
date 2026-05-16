# Nutmeg 整合设计 — 收敛为中国体彩投注助手

- **日期**：2026-05-17
- **状态**：设计已定（用户拍板三项决策），进入分期执行
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
        │            ＋ psychology 信号（精简版，反直觉/叙事）
        ▼
候选组合（2/3/4串1，跨 胜平负/让球/总进球/比分/半全场 五玩法）
        │
        ▼
debate 工作流（Claude 草案 → Codex review → 人工裁决）→ 最终方案
        │
        ▼
Telegram 推送 + 次日 jczq-daily-review 回测 → 策略记忆
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
- `ValueBoardService` 接入 JCZQ + Zucai 每日流程，作为冲突点候选来源。
- 扩展 `ValueBoardService` 从单一 `match_winner` 到五玩法（让球/总进球/比分/半全场）。
- 冲突点 → 候选 2/3/4串1 → debate → 最终方案。

### Phase 4 — 收尾
- `cli.py`（47 命令）按子系统拆分为 typer 子命令组。
- 文档收敛：保留 `Nutmeg-DESIGN-v0.3.md` + `AGENTS.md` + 本设计 + jczq 决策框架；其余清理。
- 提交此前遗留的 `jczq_final_plan_pdf.py` "5张票"修复。

## 5. 风险与原则

- **不可逆删除**：Phase 1 全部走"归档分支 → 主干删"，可回溯。
- **保持绿**：每阶段结束 `pytest` 全绿，不留破窗。
- **不超范围删**：只删用户签字的类别；evals/popularity 等留待单独确认。
- **分期**：Phase 1（清理）可快速完成；Phase 2-3（精简+接线）是工程量较大的后续构建。

## 6. 成功标准

- Phase 1 后：主干只剩投注相关代码（JCZQ + Zucai + Value/Odds + psychology + core），测试全绿，仓库体积显著下降。
- Phase 3 后：每日方案的候选来自冲突点引擎（模型 vs 国际赔率），经 debate + 回测闭环。
- 最终：一个能维护、聚焦、自我验证的体彩投注助手。
