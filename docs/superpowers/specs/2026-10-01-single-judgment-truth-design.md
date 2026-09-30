# 判断唯一事实（内核 ForecastRevision 为源，文件为投影）· 设计

日期：2026-10-01 ｜ 状态：Jun 已批准 spec（10-01 01:10）；**P0/P1 已落地**（计划 `docs/superpowers/plans/2026-10-01-single-judgment-truth-p0-p1.md`，schema 47），P2–P4 待 P0 比对满一周（≥ 2026-10-08）零分歧后出计划 ｜ 依赖：本体内核 ForecastRevision / `decision-read` / `research refresh`

> **勘察修正（2026-10-01 01:40）**：内核 `forecast_revisions` 原本没有 kind/note/stance 列，表态只住文件——P0 先给 revision 加 `kind / board_key / judgment_json` 三列装下整条 Read；`belief-v2.json` 经勘察在代码里既无写者也无读者（下表已删），`plan frontier` 实读 `<issue>-legs-base.json` 的 `fair`（足彩 `fair` 语义＝belief，竞彩 `fair`＝市场 prior，P3 并轨时要一并正名）；jczq Read 以 draft 入库（`ai:jczq-analyst`），足彩以 committed 入库（`judge:owner`）。

## 0. 一句话

同一场的判断今天同时住在 5–6 份文件里，靠 `research refresh` 互相重建；今后**内核的 ForecastRevision 是唯一可写的判断**，每次改判都是一次新 revision（带作者、时刻、理由、证据），其余文件只是从内核**投影**出来的只读视图，投影可以随时删掉重生成。

## 1. 出生事故

- 26133 场4 冰岛：竞彩研究 +7pp 的原判被主循环 14:15 覆盖，`reads.json` 重建后原判只剩一份手工备份（→ 才有了 overrides.jsonl 这块补丁）。
- 2026-09-28：`jczq-combos` 显示的 belief 与 `reads.json` 不一致（一个按 sporttery 新盘口重算 prior，一个是早上的）。
- RSI sweep 每小时报 `F9:balance-ledger: reads 尚未落盘`——义务盯着文件，文件却由另一条链重建。
- 足彩：`judgment-v1.json`（主循环/自动转录）、`belief-v2.json`、`<issue>-reads.json`、`<issue>-legs-base.json` 四份，`plan frontier` 读 belief-v2，签字页读 judgment-v1，Dream 读 legs-base——三个消费者可能看到三个不同的 belief。

## 2. 现状：判断的副本

| 副本 | 写者 | 读者 |
|---|---|---|
| `research-<code>.json` / `<issue>-research-m<n>.json` | 深研 agent（原件只读） | 入库桥、信号面板、判决页 |
| `overrides.jsonl` | 主循环改判 | 入库桥叠加、信号面板、复盘编码器 |
| `jczq-legs-base.json`（stance/faces/标签） | `research intake` | combos、审计门、Dream day 源、语料 v2 |
| `reads.json` | `jczq-build-reads` | `decision-read`（→内核）、combos、F9、Dream、复盘编码器 |
| 内核 `forecast_revisions` | `decision-read` | 结算/校准（Brier/CLV）、`current_committed_revision`（Ticket 入账） |
| 足彩 `judgment-v1.json`（手写）/ `<issue>-reads.json`（zucai-build-reads / build_auto_reads）/ `<issue>-legs-base.json`（`fair`＝belief） | 主循环 / 自动转录 / build-reads | auto_judgment、betslip 诊断、复盘编码器、语料；plan frontier/audit 读 legs-base |

## 3. 目标形态

- **写**：只有两种写入判断的动作，都落内核：① `research intake` 把研究原件转录成 `ForecastRevision(author=ai:<model>, kind=research)`；② `research override` 写 `ForecastRevision(author=claude-main-loop, kind=override, supersedes=<上一 revision>, note, tilt)`。改判＝新 revision，历史全在。
- **读**：`reads.json`、`legs-base.stance`、`belief-v2`、`judgment-v1` 全部改为 `nutmeg judgment project --day/--issue` 从内核生成的投影（含 `revision_id` 与生成时刻），任何消费者读到的 belief 都能回指一条 revision。
- **消费者改接**：combos / Dream day 源 / F9 / 复盘编码器 / plan frontier / 签字页 / 审计门读投影或直接读内核；`overrides.jsonl` 退役（历史可一次性导入为 revision）。
- **义务**：R0/R1/F9 的「已落盘」改为「内核有该场当日 revision」。

## 4. 分片（每片独立可用、可回滚）

1. **P0 只读投影 ✅（2026-10-01，schema 47）**：revision 加 `kind/board_key/judgment_json`；每条 Read 自报 `kind/board_key/code`；`decision-read` 存整条；`nutmeg judgment project` 按 `board_key` 取每序列最高 revision 投影回列表，与 `reads.json` 以 match_id 对齐比对（同判断换版本号不算分歧）；`research refresh` 每次落 `judgment-projection.json`。不改写路径。
2. **P1 override 入内核 ✅**：`research override` 记账后立刻 refresh → 重入库 → 该 Read `kind=override`（带 `override.note`）→ 交本体成为新 revision（draft 链记 `supersedes`）。jsonl 仍是文件侧的传输带，P4 才退。
3. **P2 研究入库直落内核**：`research intake` 直接产 revision；`jczq-build-reads`/`decision-read` 合并为投影。门槛：P0 比对连续 7 天分歧为零。
4. **P3 足彩并轨**：`judgment-v1` 与 `<issue>-legs-base.fair` 由投影生成；`plan frontier`/审计门改读投影；`fair` 语义正名。
5. **P4 退役**：删 `overrides.jsonl` 写路径、`jczq-build-reads`；义务改看内核。

## 5. 不做

- 不改 ForecastRevision 的表结构（现有字段够：作者、时刻、prior/belief、证据）；如需 `kind`/`supersedes` 列，走一次迁移。
- 不动研究原件（仍冻结、只读）。
- 不在此系列里改判断内容本身。

## 6. 验收

- 任一天 `judgment project` 生成的 `reads.json` 与消费者实际用的一致（字节或字段级）。
- 改判后信号面板、combos、Dream、F9 看到同一个 belief 与同一个 revision_id。
- `overrides.jsonl` 不再被任何程序写。
