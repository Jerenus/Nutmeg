# Nutmeg Workshop UI — AI-native 判读工作台（设计定稿）

> 2026-07-07 brainstorming 定稿。Palantir Workshop 的单人 AI-native 对应物：
> **AI 起草一切，人只做裁决；界面是人与 agent 共享的工作空间，不是数据陈列柜。**
> 视觉稿：Pencil `docs/design/nutmeg-workshop.pen`（待补）。实现计划另出（writing-plans）。

## §0 已确认的五个根决策（用户拍板）

| # | 问题 | 决策 |
|---|------|------|
| 1 | 核心 job | **判读工作台**——服务每天最重的事；账本/校准/对象浏览器为附属页 |
| 2 | 写权限边界 | **只读 + 两个白名单 typed action**（Read 草稿审批、legs 确认），全部复用既有 schema 闸，零旁门 |
| 3 | 设备场景 | **桌面为主**（与 Claude 会话双窗并排），手机响应式可看可审（晚间手机确认出票） |
| 4 | 对话宿主 | **渐进：v1 伴生态**（终端 Claude Code 仍是判读引擎，web = 实时镜像+审批面）→ **v2 内嵌态**（Agent SDK 进浏览器）；握手协议即预留槽 |
| 5 | 实现路线 | **独立 `decision-web` FastAPI 应用**（方案 A）；老 `client-web` 簇（8 命令 + ClientService + PWA 模板 + 3 测试文件）**整簇下葬**（用户产品决断） |

## §1 AI-native 立场（与传统驾驶舱的分界）

- **注意力流取代数据列表**：左栏是 agent 排序的"今天什么值得看"（因子候选/草稿待审/急动待查/跟市场），不是当日场次平铺。
- **审批卡取代表单**：Read 草稿、legs 提案以 typed-action 卡片呈现，一键批准/拒绝，批准即走 schema 闸——Palantir AIP 的 agent-with-guardrails 交互，人是审批环节不是录入员。
- **视图由 AI 组合**：agent 推送结构化视图块（DC 矩阵/证据摘要/画像引用/belief 对比条），UI 只负责渲染，不预设死版面。
- **对话是一等公民**：界面围绕对话组织；v1 对话槽空置（提示"判读在终端进行"），v2 由 Agent SDK 填充。

## §2 信息架构

```
nutmeg decision-web → 127.0.0.1:8787
┌────────────────────────────────────────────────────┐
│ 顶栏: 日期 · 编排三灯(am/close/settle) · ¥400 预算条  │
├──────────────┬────────────────────┬────────────────┤
│ 注意力流      │  舞台（agent 组合视图）│  裁决列         │
│ agent 议程   │  盘口/欧赔锚/DC矩阵/  │  typed-action  │
│ ·因子候选     │  画像引用/证据摘要/   │  审批卡队列     │
│ ·草稿待审     │  belief 对比条       │  Read ✓✗       │
│ ·急动待查     │  （agent 推送，      │  legs ✓✗       │
│ ·跟市场       │   UI 渲染）          │  + 空仓按钮     │
├──────────────┴────────────────────┴────────────────┤
│ ▼ 对话槽（v1 空置；v2 Agent SDK 内嵌）               │
└────────────────────────────────────────────────────┘
附属页: /objects 对象浏览器(血缘跳转) · /calibration 校准台 · /ledger 账本
手机: 三栏折叠单列 Tab，保住"手机审卡出票"路径
```

- **顶栏三灯**：am（数据入库 08:00）/ close（19:00 倒计时）/ settle（次晨 08:10）——从 store 数据新鲜度与 daily 文件推断，不读 launchd。
- **附属页全只读**：对象浏览器按血缘跳转（Read→Snapshot→Match→Team/League→Factor→Verdict）；校准台渲染因子生死表 + `@scope_key` 诊断行 + 参与精度（divergent vs shadow）；账本按日/按票列 Settlement 与 pnl、¥400 逐日核算。

## §3 agent↔UI 握手协议（架构的心脏，也是 v2 预留槽）

协议即文件，全部落盘可回放（延续仓内文件纪律）：

```
终端 agent ──写──► daily/<date>/workbench.jsonl   (append-only 事件流)
                    {kind: attention|view_block|read_draft|legs_proposal,
                     id, payload, at}
                         │  FastAPI 监视文件 mtime → SSE 推浏览器
                         ▼
浏览器 UI ──裁决──► POST /action/* ──schema 闸──► 落盘
                    · read 批准 → ingest_reads() 同一校验 → store
                    · legs 确认 → express 预算/schema 校验 → daily/<date>/legs.json
                    · 全部裁决留痕 daily/<date>/decisions.jsonl
                         │
终端 agent ◄──读── decisions.jsonl（下一轮推理感知裁决）
```

三个不变量：
1. **协议即对话槽**：v2 换 Agent SDK 时只是"谁写 workbench.jsonl"变了，UI 与闸门零改动。
2. **写路径零旁门**：UI 两个动作复用 `read_ingest.ingest_reads` 与 express 预算闸的同一份校验代码；界面拒绝理由与 CLI 一字不差。
3. **判断永不进 UI**：界面不产生判断，只渲染 agent 判断 + 记录人的裁决。SOP/宪法完全不变。

## §4 技术栈与目录

- FastAPI + uvicorn + Jinja2 服务端渲染 + 原生 JS + SSE——**零新依赖、零构建步骤**（全部已在 pyproject）。
- 结构：
```
nutmeg/interfaces/decision_web.py        # FastAPI app 工厂 + 路由
nutmeg/interfaces/web/templates/decision/  # Jinja2 模板（workbench/objects/calibration/ledger）
nutmeg/interfaces/web/static/decision/     # app.css / app.js（SSE+卡片交互）
nutmeg/decision/workbench.py             # 握手协议读写（事件流 append/tail、decisions 留痕）
CLI: nutmeg decision-web [--host 127.0.0.1] [--port 8787]
```
- 老 `client-web` 簇下葬清单（实现计划 Task 1）：`interfaces/client_web.py`、`services/client.py`、`cli/client.py`（8 命令）、`web/templates/client/`、`web/static/client/`、`web/static/jczq/`（旧遗迹）、`tests/test_client_web.py`、`tests/test_client_service.py`、`test_cli.py` 中 client 相关用例；`cli/__init__.py` hub import 同步清理。

## §5 错误处理与安全边界

- **校验拒绝可见且同源**：卡片翻"被拒"态，显示 `validate_read` 同文案理由；拒绝也留痕 decisions.jsonl。
- **幂等**：重复批准同一 `id` 无副作用（store upsert-by-id）；`legs.json` 写前留 `.bak`。
- **空态即引导**：无 workbench.jsonl → "在终端说『今天的方案』"；无在售 → 显式空盘（绝不静默）。
- **数据健康横幅**：store 跳过损坏行时顶部亮黄条。
- **SSE 断连**：自动重连 + 顶栏指示灯。
- **安全默认**：只绑 127.0.0.1；`--host 0.0.0.0` 时启动警告（无鉴权单人假设）。
- **纪律不破**：19:00 前 legs 未确认只倒计时警示，close 照跑空票——空仓合法，界面不改编排行为。

## §6 测试策略

- 只读端点：TestClient + tmp_path fixture store。
- 动作闸：合规草稿批准→store 断言；违规草稿→400 + 错误串与 validate_read 逐字相等；legs 超预算/超桶→拒绝。
- 握手协议：workbench 事件渲染断言；decisions.jsonl 留痕；幂等重放。
- e2e：伪造一天（快照+草稿）→批准→legs 确认→文件与 store 全链断言。
- 不做自动化视觉回归（YAGNI）；Pencil 稿为实现基准。

## §7 分期

- **v1（本期）**：伴生态全量——四页 + 握手协议 + 两个 typed action + 手机响应式 + client-web 下葬。
- **v2（另立 spec）**：Agent SDK 对话内嵌（浏览器内完整判读，含手机）；届时只动"谁写 workbench.jsonl"。
- **明确不做**：鉴权/多用户、自动化视觉回归、模拟/what-if 层、改因子词典或实体画像的写面（那些走终端+复盘纪律）。

## §8 视觉设计

- 视觉语言沿用项目已立的账本绿身份：paper `#F5F7F3` / ink `#1B2620` / pine `#1F5C46`（确定性代码与市场锚）/ cinnabar `#B23A2C`（**只留给判断与待裁决态**）/ gold `#8A6F2F`（实体层）。深浅双主题。
- Pencil 稿（`docs/design/nutmeg-workshop.pen`）：桌面工作台 1440 全景、手机 390 单列、Read 审批卡解剖三画板。（待 Pencil 连接后补，补完更新本节）
