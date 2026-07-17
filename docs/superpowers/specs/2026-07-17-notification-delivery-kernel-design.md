# Nutmeg 正式通知投递内核设计

**日期：** 2026-07-17  
**状态：** 已批准  
**范围：** decision close/settle、胜负彩/任九正式报告、调度失败通知

## 1. 背景与目标

Nutmeg 当前把“生成报告”和“通过 Telegram 发送报告”耦合在多个业务服务中：

- `nutmeg.decision.report` 返回裸 `dict`；
- `ZucaiWorkflowService`、`ZucaiRenjiuDailyService` 各自维护一套 `_dispatch()`；
- `DailyOperatorService` 又维护一套文本消息状态；
- Telegram 配置解析、收件人循环、异常捕获和状态字符串重复分散；
- launchd 包装器依赖自由文本判断是否发送成功；
- close 与 settle 共用同一 PDF 路径，次晨报告覆盖前一晚的审计版本；
- 没有持久 notification/delivery/attempt 账本，无法准确回答“什么内容在何时发给谁、失败后重试了几次”。

本设计建立一个本地、同步、轻量的通知投递内核。它在不改变现有正式命令和默认 dry-run 行为的前提下，实现：

1. 正式报告的不可变发送快照；
2. 通知级幂等与内容 revision；
3. 逐收件人的持久投递状态；
4. 有界重试、错误分类、部分成功和不确定状态；
5. Telegram `message_id`、附件哈希与完整尝试时间线；
6. 结构化 CLI/调度结果和可靠非零退出码；
7. 调度上游失败的去重文本告警。

## 2. 非目标

本次不建设通用多渠道消息平台，也不接管：

- OpenClaw 的 Telegram 会话回复；
- 项目内置的 Telegram polling bot；
- Web/PWA 的 `Alert`、Watchlist 和 entitlement；
- `daily-run` 的历史文本通知；
- `scripts/` 下的一次性世界杯/足彩推送脚本；
- 邮件、短信、Push、Redis、消息队列或常驻 worker；
- 历史 Telegram 投递记录迁移。

这些能力可在通知内核稳定后独立评估，不能扩大本次 live 改造范围。

## 3. 总体架构

```text
decision / zucai 报告生成器
          |
          | NotificationRequest
          v
   NotificationService
     |-- ArtifactStore
     |-- NotificationRepository (SQLite)
     `-- TelegramProvider
          |
          v
   NotificationOutcome
          |
          |-- 兼容现有 CLI 文本与 dispatch 字段
          `-- 供 CLI / scheduler 读取结构化结果
```

### 3.1 业务报告生成器

业务层继续负责：

- 报告正文、标题、caption 和 PDF 渲染；
- 比赛日、期号、afternoon/revision 等业务身份；
- 从规范化业务内容生成 `semantic_fingerprint`。

业务层不再负责：

- 读取 Telegram token 或 chat ID；
- 实例化 Telegram client；
- 循环收件人；
- 网络重试和异常分类；
- 自定义 dispatch 状态。

### 3.2 NotificationService

`NotificationService` 是同步 application service，负责：

1. 校验 `NotificationRequest`；
2. 生成通知 ID 和 dedupe key；
3. 查询相同成功通知并抑制重复；
4. 保存不可变附件；
5. 创建通知和逐收件人 delivery；
6. 调用 provider 并持久化每次 attempt；
7. 汇总通知结果；
8. 提供显式重试和状态查询。

它不理解比赛、票面、Read、Ticket、Settlement 或足彩规则。

### 3.3 ArtifactStore

实际发送的附件复制到：

```text
.nutmeg-data/notifications/artifacts/<notification_id>/<filename>
```

保存后记录 SHA-256、字节数和媒体类型。该路径不可覆盖；同一通知的 artifact 只写一次。业务原路径继续存在，例如：

```text
.nutmeg-data/jczq/daily/<date>/decision-report-<date>.pdf
```

业务原路径是“最新版”兼容文件，不再承担审计职责。

### 3.4 NotificationRepository

通知账本复用 `.nutmeg-data/state/state.db`，通过独立 repository 管理通知相关表。SQLite 提供唯一约束和事务，不新增外部服务。

### 3.5 TelegramProvider

Provider 只负责将标准消息映射到 Telegram API，并返回：

- provider message ID；
- 标准成功/失败结果；
- 标准错误代码；
- 是否可重试；
- `Retry-After`（若存在）。

Provider 不负责多收件人循环、业务日志、持久状态或调度决策。

## 4. 请求与持久模型

### 4.1 NotificationRequest

请求至少包含：

- `kind`：如 `decision.close.report`、`decision.settle.report`、`zucai.report`；
- `business_key`：比赛日或足彩期号；
- `stage`：`close`、`settle`、`afternoon`、`revision`、`manual`；
- `semantic_fingerprint`：规范化业务内容的 SHA-256；
- `subject`、`caption`、可选短文本；
- 一个或多个附件源；
- 逻辑 audience；
- 是否为 required delivery；
- 非敏感 metadata；
- dry-run 标记。

`dedupe_key` 由 `kind + business_key + stage + semantic_fingerprint` 生成。PDF 元数据或渲染时间不得进入语义指纹。

### 4.2 Notification

字段包括：

- `notification_id`；
- `dedupe_key`（唯一）；
- `kind`、`business_key`、`stage`；
- `semantic_fingerprint`；
- `subject`、`caption`、metadata；
- `status`；
- `created_at`、`updated_at`。

状态：

```text
pending -> delivering -> sent
                      -> partial
                      -> failed
                      -> uncertain
```

聚合优先级固定如下：所有 required deliveries 均成功为 `sent`；任一 required
delivery 为 `uncertain` 时整体为 `uncertain`；至少一个 required delivery 成功且至少
一个终态失败时为 `partial`；没有 required delivery 成功且存在终态失败时为 `failed`。
尚有可继续尝试的 delivery 时保持 `delivering`。

### 4.3 NotificationArtifact

字段包括：

- `artifact_id`、`notification_id`；
- 快照路径、原始文件名；
- `media_type`、`size_bytes`、`sha256`；
- `created_at`。

### 4.4 Delivery

一个 delivery 对应一个渠道下的一个具体收件人。字段包括：

- `delivery_id`、`notification_id`；
- `channel`、逻辑收件人、实际目标；
- `required`；
- `status`；
- `attempt_count`；
- `provider_message_id`；
- 最后错误代码、清洗后的错误信息；
- `next_retry_at`；
- `first_attempted_at`、`delivered_at`、`updated_at`。

状态：

```text
pending -> sending -> sent
                   -> retryable_failed -> sending
                   -> permanent_failed
                   -> uncertain -> sending
```

### 4.5 DeliveryAttempt

每次真实网络调用写一条不可修改的 attempt：

- `attempt_id`、`delivery_id`、序号；
- `started_at`、`completed_at`；
- `outcome`；
- 标准错误代码、是否可重试；
- `retry_after_seconds`；
- provider message ID；
- 清洗后的非敏感响应 metadata；
- 是否属于 uncertain recovery。

## 5. 幂等与 revision

- 相同 dedupe key 已经全部送达时，返回 `deduplicated` outcome，不新建 delivery，不重复发送。
- 相同通知存在 `retryable_failed`、`uncertain` 或过期 `sending` 时，重用原 notification/delivery 继续恢复。
- 同一业务阶段的规范化内容发生实质变化时，semantic fingerprint 改变，形成新 notification revision。
- revision 按同一 `kind + business_key + stage` 的创建顺序展示；不依赖 PDF 二进制哈希。
- 已成功收件人不会因其他收件人重试而重复发送。
- dry-run 返回计划中的目标、附件和 dedupe key，但不写正式账本、不复制审计附件、不调用 provider。

Telegram 不提供客户端幂等键，因此系统只能提供“至少一次 + 本地幂等抑制”。如果进程在 Telegram 已发送但成功记账前崩溃，系统必须标记 `uncertain`，后续恢复允许重投并明确记录“可能重复”，不能宣称 exactly-once。

## 6. 错误分类、重试与降级

统一错误类型：

| 类型 | 示例 | 策略 |
|---|---|---|
| `configuration` | token、收件人、附件缺失 | 永久失败 |
| `validation` | caption 超限、文件不可读、媒体类型错误 | 永久失败；附件错误可文本降级 |
| `rate_limited` | Telegram 429 | 尊重 `Retry-After` |
| `transient` | timeout、连接错误、Telegram 5xx | 有界重试 |
| `uncertain` | 发送结果未知或发送后记账中断 | 标记不确定，恢复时可重投 |

规则：

- 每个收件人独立投递；一个失败不阻塞其他收件人。
- transient/rate-limited 每个 delivery 最多进行三次网络调用（首次 + 两次重试），使用短退避并尊重有上限的 `Retry-After`。
- 认证、无效 chat、不可读文件等永久错误不自动重试。
- 文档因附件或 caption 失败时，可发送一条短文本失败告警；文本成功不能把原报告 delivery 标为成功。
- provider token、带 token 的 URL、环境变量和未经清洗的响应体不得进入数据库、日志或 CLI。

## 7. 调度失败与恢复

- 正式命令只要存在 required delivery 未成功，就返回非零退出码。
- CLI 增加结构化 JSON 输出，scheduler 不再搜索自由文本。
- 报告生成或上游数据步骤在通知创建前失败时，scheduler 通过同一内核发布 `operations.failure` 文本通知。
- failure 使用 `任务 + 日期 + 阶段 + 错误指纹` 去重，避免重复刷屏。
- 同一任务先失败、后续重跑成功时，发送一次对应的 `operations.recovered`；没有前序失败记录时不发送恢复通知。
- 如果失败原因就是 Telegram 不可用，不递归创建 Telegram 告警；只保留通知账本、非零退出码和 launchd 日志。
- 第一阶段不新增第二告警渠道。

恢复命令：

```text
nutmeg notification-status --since 7d
nutmeg notification-show --notification-id <id>
nutmeg notification-retry --notification-id <id>
nutmeg notification-retry --failed-required
```

`permanent_failed` 修正配置后需显式 retry。`uncertain` 重试必须在输出和 attempt 中标明可能重复。

## 8. 业务接入

### 8.1 decision

- `decision-close` 使用 `stage=close`；
- `decision-settle` 使用 `stage=settle`；
- 直接 `decision-report` 使用 `stage=manual`；
- close/settle 保存不同 notification 和不可变附件；
- 原 `decision-report-<date>.pdf` 继续作为最新版；
- `run_report` 不再自行解析 Telegram 配置或直接发送。

### 8.2 胜负彩与任九

- `ZucaiWorkflowService`、`ZucaiRenjiuDailyService` 使用同一 NotificationService；
- `afternoon` 与 `revision` 使用不同 stage；
- 现有报告 JSON 的 `dispatch` 字段暂时由 `NotificationOutcome` 兼容映射；
- CLI 参数和默认 dry-run 不变；
- 当前未加载的足彩 LaunchAgent 不因本次改造自动启用。

### 8.3 配置装配

- 继续使用现有 `NUTMEG_TELEGRAM_BOT_TOKEN`、`NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS` 和 Telegram base URL；
- Telegram 配置只在通知 wiring 层解析一次；
- 业务 service builder 接收 NotificationService，而不是 token/client/chat IDs。

## 9. CLI 兼容性

保持：

- `decision-close`、`decision-settle`、`decision-report`；
- `zucai-report`、`zucai-renjiu-daily`、`zucai-auto-run`；
- `--dispatch-telegram`；
- `--dry-run/--no-dry-run`；
- 默认文本输出；
- 原报告兼容路径。

新增可选 `--format json`，输出工作流步骤和通知结果。required delivery 失败时，文本和 JSON 都返回非零退出码。

旧的 `dispatch` JSON 兼容字段映射到统一状态：

- `skipped`；
- `dry_run`；
- `sent`；
- `partial`；
- `failed`；
- `deduplicated`；
- `uncertain`。

## 10. 迁移顺序

### 阶段一：通知内核

实现模型、repository、ArtifactStore、TelegramProvider、NotificationService 和纯 fake 测试，不接 live 命令。

### 阶段二：decision 切换

接入 report/close/settle，增加 stage、不可变快照、结构化结果和可靠退出码。正式报告保持唯一发送者，不做双发。

### 阶段三：足彩切换

接入胜负彩、任九和 scheduled delivery，保留旧 JSON/CLI 兼容表面。

### 阶段四：收敛重复实现

删除三个业务模块中的重复 `_dispatch()`、重复 Telegram 配置解析、分散状态字符串和 scheduler 文本解析。

历史 Bot、Web Alert、daily-run 和一次性脚本只记录为后续候选，不在本次修改。

## 11. 测试策略

### 11.1 通知内核

- 状态合法转换；
- 相同内容去重；
- 内容变化产生 revision；
- ArtifactStore 不可变、SHA-256 与字节数；
- dry-run 无持久副作用；
- 输出和错误不泄密。

### 11.2 TelegramProvider

- 保存 message ID；
- 429/Retry-After；
- timeout、连接错误、5xx；
- 无效 token/chat；
- 文档失败后的文本降级；
- 网络前输入校验。

### 11.3 故障注入

- 多收件人部分成功；
- 已成功收件人不重复；
- transient 恢复和重试耗尽；
- 过期 sending -> uncertain；
- uncertain 重投；
- 模拟发送成功后记账前崩溃。

### 11.4 业务集成

- close/settle 两个独立通知和附件；
- 原最新版路径保留；
- 相同重跑不重复；
- 内容变化形成更新版；
- 足彩旧 dispatch 字段兼容；
- 所有 dry-run 不触网。

### 11.5 调度与回归

- scheduler 消费结构化状态；
- required delivery 失败返回非零；
- 上游失败通知去重；
- Telegram 失败不递归；
- 现有 decision、足彩、Telegram、CLI 测试通过；
- ruff、pytest 和项目验证脚本通过。

## 12. 可观测性与保留策略

`notification-status` 汇总指定时间窗口内的成功、部分成功、失败、待重试和不确定数量。`notification-show` 展示：

- 业务身份、stage 和 revision；
- 附件路径、哈希和字节数；
- 逐收件人状态；
- provider message ID；
- attempt 时间线和清洗后的错误。

普通输出隐藏完整 chat ID。第一版不自动删除通知账本或不可变附件；Nutmeg 的长期复盘需要显式 retention 设计，不能静默过期。

## 13. 验收标准

1. 现有 live 命令、参数和默认 dry-run 行为兼容。
2. close 与 settle 的实际发送版本可独立追溯。
3. 相同正式任务重跑不重复发送。
4. 内容更新形成清晰的新 revision。
5. 每个收件人的状态、Telegram message ID、附件哈希和 attempts 可查询。
6. transient、partial、permanent、uncertain 均有故障注入证据。
7. scheduler 不再通过自由文本猜测发送成功。
8. 无真实推送的全链 dry-run 验证通过。
9. 真实 Telegram smoke 只有在用户再次明确确认后执行；成功后才宣告 live 切换完成。

## 14. 回退

切换期间每个业务命令始终只有一个发送者。若首次 live smoke 失败：

- 保留通知账本和不可变失败快照；
- 不回滚 decision store、票面或业务报告；
- 恢复旧发送装配点后再运行原命令；
- 已确认 sent 的 delivery 不得无条件重发；
- 修复后重新切换并再次完成 dry-run 与显式确认的 live smoke。
