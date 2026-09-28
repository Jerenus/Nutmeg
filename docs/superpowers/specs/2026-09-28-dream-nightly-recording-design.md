# Dream 夜间录制（常设批准 · 20:30 定时 · 实际出票对照 · 开球过滤）· 设计

日期：2026-09-28 ｜ 状态：Jun 批准方向（聊天 2026-09-28：「以上全写成设计，常批准先实验到 10.31」）｜ 后续：writing-plans
依赖：Discovery Harness D0–D7、day 源（`2026-09-23-discovery-day-source-design.md`）、试点改写为成本裁剪（`2026-09-22-dream-rsi-pilot-cost-pruning-restatement.md`）、`nutmeg day run` 运行器、`nutmeg rsi loop`。

## 0. 一句话

Dream 回放的「世界」今后每晚 20:30 自动录一个：用 Jun 签一次的**常设批准**（至 2026-10-31）代替每天手签，世界只收**截止时刻未开球**的场次，并把当时的**实际票面**冻结成引用；次日 10:45 的 RSI 闭环把「实际出票 / 决策规则最优 / 世界各档最优 / 空仓」四者对着 90 分钟赛果记账。锦标赛、晋级、部署仍只许人。

## 1. 出生事故

**首个真实世界（2026-09-28 21:42，`discovery-world-3b91e3ce6edf4eb1b9fb53e9`）四个分片全部超时。**
Jun 下午批准「开始跑」，因工具故障拖到 21:42 才录。7 场入世界（周一002–008），模板 pass-2-1…pass-5-1 四个分片同时起跑，全部在 120 s 墙钟处 `timeout`，世界以 `no_solution / wall_budget_exhausted` 封存，readiness 把它记为 failed/degraded。

根因是生成器的物化循环，不是数据、不是隔离进程（进程内直接跑 pass-2-1 同样跑不完）：

- `enumerate_candidates`（`nutmeg/discovery/candidates.py:507`）先对**全部原子票**做 `combinations(atomic, size)`，size 取到 `maximum_batch_size = min(20, 原子票数)`，**生成之后**才用 `_batch_respects_group_limits` 过滤「每模板至多 `maximum_groups` 组」。
- 今天 pass-2-1 单分片有 207 张原子票、每模板上限 1 组：合法候选只有 207 个，循环却要遍历 C(207, k)（k≤20）量级。cProfile 45 s 内 `_batch_respects_group_limits` 被调 1.1 亿次，才走到 size=5（C(207,5)≈30 亿，后面还有到 size=20 的十几层）。
- 计数函数 `_calculated_candidate_count` 按限制计数（=207），所以 `CandidateSpaceLimitError` 这道门没拦住：**门算的是对的，循环跑的不是它算的那个空间**。夹具板面原子票很少，D0–D7 的测试看不出来。

同时暴露三件事：

1. **手签节奏达不到就绪门**：`record_to_baseline` 要 30 个封存世界、20 个独立业务日。每晚一份手签批准＝连续 20 天不漏一次。
2. **已开球场次混进了「前瞻」世界**：21:42 截止时 001（18:25）、002（19:00）已开球；001 因研究被拒不在世界里，002 在。输入里没有赛果、Read 都在开球前定，但 day 源不按开球过滤是一个口子。
3. **世界的质量口径与现行决策规则不一致**：试点评估器按 10x/20x/50x/100x 赔率档取各档最高 P（`ODDS_BAND_INTERVALS`），而 2026-09-27 起竞彩「只放判断腿、不按 10/20/50/100 倍凑腿」。世界里的「各档最优」只能说明录制链路是否正常，**不能当出票建议读**——这也是为什么实际出票对照要另算一套决策规则口径（§3.5）。

## 2. 范围

| 做 | 不做 |
|---|---|
| P0 生成器物化修复（输出逐字不变） | 改评估器、改试点契约数字（`max_concurrency`/`max_wall_seconds` 等） |
| P1 day 源开球过滤 + 票面引用 | 在世界里加单关模板（世界只有 `jczq_pass` 串关，见 §7 已知缺口） |
| P2 常设批准（至 2026-10-31，可撤销） | 机器生成或延长任何批准 |
| P3 夜间作业 `day run --job dream` + 20:30 plist | 锦标赛/晋级/部署自动化（仍只许人） |
| P4 决策对照记账进 RSI 闭环报告 | 把对照登记成 RSI 实验（结账前只报告；登记只许 Jun） |

## 3. 组件

### 3.1 P0 生成器物化修复（语义不变）

- 物化改为**按模板分组生成**：原子票按 `structure_code` 分桶；每桶取 0…min(桶大小, `maximum_groups`) 张的组合；各桶做笛卡尔积；只保留总张数 1…`maximum_batch_size` 的批次。这正是 `_calculated_candidate_count` 计数的那个空间。
- 新增对账：物化出的批次数必须等于 `calculated_count`，否则 `RuntimeError`（与已有「原子票对账」同一写法）。门算的空间和循环跑的空间从此是同一个。
- **输出逐字不变的依据**：`_ordered_candidates` 以（分区、−P、票价、内容哈希）排序，是全序；只要批次集合相同，输出序列就相同。计划里用新旧两种实现在随机小夹具上比对全部候选的内容哈希序列（不只比数量）。
- 冻结面声明：评估器代码不动；试点契约按函数路径引用生成器，契约哈希不变；`generator_version` 不变。修复前录下的 09-28 超时世界保留原样——它是真实的 failed/degraded 世界（optimizer 门本来就要求 ≥3 个这类世界），不删、不重录。
- 修复后若 7 场板四个分片仍超过 120 s，**不静默调参**：停下交 Jun 裁契约修订（D7 流程）。

### 3.2 P1 day 源：开球过滤 + 票面引用（`nutmeg/discovery/day_inputs.py`）

- **开球过滤**：体彩 `matchDate + matchTime`（北京时间）≤ `cutoff_at` 的场次不进 `offers`。被排除的场次各记一条引用 `kind="excluded_started"`，`id=<场次>`，`captured_at=<开球时刻>`（必然 ≤ cutoff，能过现有引用校验），世界里看得到「为什么少了这几场」。
- 过滤后不足 2 场 → 抛 `DayBoardTooSmall(ValueError)`，由夜间作业记为 `skipped: board_too_small`，不算失败。
- **票面引用**：截止时刻的当天实际票面＝`<jczq_dir>/daily/<日>/legs.json` ＋ `.nutmeg-data/betslips.jsonl` 中 `channel=jczq` 且 `placed_at=<日>` 的行（按 `slip_id` 排序）。
  - 规范化 JSON 的 sha256 进引用 `kind="ticket"`，`id=<日>:tickets`，`captured_at=cutoff_at`。
  - 内容另存 `~/nutmeg-shadow/tickets/<日>-<sha前16位>.json`（仓外，按内容寻址），供次日核对。
  - 没票也记一条（空票面的哈希）——「那天空仓」也是可核对的事实。
- **指纹**：`day_fingerprint` 纳入票面摘要。录制期间有人登记实票 → 封存被拦，夜间作业重试一次（§3.4）。
- 以上只改 day 源的输入冻结；manifest 结构不变，只多两类引用。

### 3.3 P2 常设批准

**批准文件**：`experiments/discovery/approvals/standing-dream-nightly-2026-10.json`，进 git，git 历史即审计线。实施 P2 时由主会话按下面内容落文件（`approved_at` 取落文件时刻），提交信息引用 Jun 的批准原话；此后任何程序都不写它。

```json
{
  "approval_id": "standing-dream-nightly-2026-10",
  "kind": "standing",
  "approved_by": "op:jun",
  "approved_at": "<本设计批准落文件时刻，+08:00>",
  "valid_from": "2026-09-29T00:00:00+08:00",
  "valid_until": "2026-10-31T23:59:59+08:00",
  "revoked_at": null,
  "scope_template": {
    "source_kind": "day",
    "jczq_dir": "/Users/jz71/Projects/Nutmeg/.nutmeg-data/jczq",
    "shadow_db": "/Users/jz71/nutmeg-shadow/ontology/ontology.db",
    "policy_revision_id": "structural-baseline-v1",
    "generation_request_pattern": "day:{business_date}",
    "cutoff_window_bjt": ["20:00", "23:59"],
    "max_worlds_per_business_date": 1
  },
  "note": "Jun 2026-09-28 聊天：「以上全写成设计，常批准先实验到10.31日」"
}
```

**校验**（新函数 `nutmeg/discovery/standing_approval.py`，夜间作业唯一入口）逐条满足才放行：

- `approved_at ≤ cutoff`
- `valid_from ≤ cutoff ≤ valid_until`
- `revoked_at` 为空
- `cutoff` 的北京时间落在窗口内，且业务日＝cutoff 的北京日期
- `scope_template` 里的路径 resolve 后与实参一致
- 基线登记人（`policy.created_by`）＝`approved_by`
- 影子库里该业务日还没有一个带本常设批准引用的封存世界

**派生单次批准**：校验通过后派生现有 `_validate_recording` 认的单次批准字典（`approval_id=<常设id>:<日>`，scope 五键逐字一致），世界 manifest 另加引用 `kind="approval"`，`id=<常设id>`，`source_revision=<批准文件 sha256>`，`captured_at=approved_at`。**每个世界都能回溯到那份签字文件和它当时的字节**。

**机器不写批准**：

- 夜间作业只读打开批准文件；测试断言作业路径上没有对 `approvals/` 的任何写。
- 过期或撤销 → `skipped: approval_expired | approval_revoked`，退出码 0。
- 到期前 7 天起，RSI 闭环报告「待人决定」显示倒计时。

**撤销**：Jun 在文件里填 `revoked_at`，或直接删文件。下一晚生效。

**单次路径不变**：`nutmeg discovery shadow-run --approval-file` 仍按现状工作，供手动补录或试跑。

### 3.4 P3 夜间作业

- **命令** `nutmeg discovery nightly --day <日> [--dry-run]`：
  1. 读常设批准
  2. `cutoff = 当前北京时间（秒）`
  3. 冻结 day 源（开球过滤 + 票面引用）
  4. 录制并封存
  5. 写报告 `~/nutmeg-shadow/reports/<日>.json`（world_id、封存哈希、入世界/被排除场次、各分片状态与耗时、跳过原因）
  - `--dry-run` 只打印将冻结的场次与批准校验结果，不写影子库。
- **重试**：仅对「protected source changed」（录制期间当天文件被改）等 60 s 重试一次，新 cutoff＝新世界。分片超时/无解是数据，不重试。
- **编排**：`nutmeg day run --job dream`（`day_runner.JOBS` 加 `dream`）以子进程调上面的命令，结局写当日 `timeline.json`，`ops-status` 与 `/day` 页自然看得到。
- **退出码**（与 rsi loop 同纪律）：

  | 情况 | 退出码 |
  |---|---|
  | 跳过（批准过期/撤销、板面不足、当日已录） | 0 |
  | 分片失败 / `no_solution` | 0（是数据） |
  | 基础设施错误（影子库缺失、迁移版本不足、批准文件损坏） | 1 |

- **定时**：`ops/launchd/com.nutmeg.day.dream.plist`，每天 20:30。装载属行权门：Jun 已于 2026-09-28 在聊天中授权本试验，装载时把授权原话记入实施证据。
- **为什么 20:30**：
  - 18:45 晚版判决刷新后，当天三份文件不再变，不会撞指纹保护；
  - 在 22:00 停售前，已下的票能被冻结进引用；
  - 不与白天定时任务抢资源。
  - 代价：20:30 前开球的场次（日韩联赛、部分周末欧洲早场）被开球过滤排除。10-31 复盘时按「被排除场次数/晚」判断要不要把时间提前到 18:50。

### 3.5 P4 决策对照（实际出票 vs 决策规则最优 vs 世界各档最优 vs 空仓）

**为什么不做成世界树里的节点**：

- 评估器是冻结面；
- 锦标赛靠「前缀回放只揭示录下的子节点」比较策略。插入一个不是策略动作产生的「人工参照节点」，会让回放看到基线策略从未走过的分支，破坏锦标赛不变式。

因此对照是**世界之外**的只读记账，只消费世界的冻结 manifest。

**时机**：RSI 闭环（10:45）新增步骤 `dream_compare`，排在 09:45 `day run --job results` 之后；对象是前一业务日的夜间世界。

**四行口径**（P 一律用世界 manifest 里 cutoff 时刻的 belief 与赔率，不读事后文件）：

| 行 | 内容 | P 与回报 |
|---|---|---|
| A 实际出票 | 该业务日每张 `purchased=True` 的竞彩实票 | P_belief：腿全在世界 offers 内时按 belief 连乘；有腿在世界外（开球被排除、让球/总进球玩法）→ `outside_world`，只记实际结果不给 P。每张另标 `frozen_at_cutoff`：内容哈希是否等于 20:30 冻结的票面引用 |
| B 决策规则最优 | 世界 offers 上的胜平负 2–4 串、≤4 注组合中，**全中每元回报 >1** 的 P_belief 最大者（与 `jczq-combos` 同一算术，复用其枚举函数） | 已知缺口：不含单关（manifest 不带单关开售信息） |
| C 世界各档最优 | 每档（10x/20x/50x/100x）P 最高的审计通过候选 | 在冻结 snapshot 上重跑纯分片函数恢复候选内容（确定性）；世界非 `policy_stop` 时该行为空 |
| D 空仓 | — | 回报 0 |

**结算**：

- 胜平负按 `results-90.json` 的 `outcome_90`；让球/总进球按其进球数。
- 回报用 `betslip settle` 的同一结算函数（竞彩按赔率连乘），不另写一套。

**产出**：

- 每日 `.nutmeg-data/analytics/dream-compare/<日>.json`，并追加到 `ledger.jsonl`；
- RSI 闭环报告新增「Dream 对照」节：昨日四行、累计 n、各行「平均 P vs 实际命中率」、累计每元实际回报、A−B 差。
- A−B 差在 n≥20 个业务日后才给 bootstrap CI，此前只列数字不下结论。

**纪律**：只报告。不改票面、不改权重、不登记实验。n≥20 后若 Jun 要把它变成前瞻实验，另立 F12 登记（原件冻结，判决归代码）。

## 4. 数据流

```
18:45 day.verdict ──► daily/<日>/{jczq-legs-base,reads,sporttery_markets}.json（当天最后一次改写）
全天   betslip register / legs.json ──► 实际票面
20:30 day run --job dream
        └► discovery nightly：常设批准校验 → 开球过滤 → 票面引用 → 录制 4 分片 → 封存
             └► ~/nutmeg-shadow/{ontology.db, reports/<日>.json, tickets/<日>-<sha>.json}
次日 09:45 day run --job results ──► daily/<次日>/results-90.json
次日 10:45 rsi loop … → dream_compare ──► analytics/dream-compare/<日>.json → latest.md「Dream 对照」
随时（人）  锦标赛 / 晋级 / 部署 —— 就绪门未过前不会触发
```

## 5. 错误处理

| 情况 | 行为 |
|---|---|
| 常设批准缺失/过期/撤销/字段不符 | `skipped` + 原因，退出码 0；过期前 7 天报告倒计时 |
| 截止时未开球的场 < 2 | `skipped: board_too_small`，退出码 0 |
| 当日已有封存世界 | `skipped: already_recorded`，退出码 0 |
| 录制中当天文件被改（指纹变） | 60 s 后重试一次；仍失败 → 世界留作未封存记录，报告写明，退出码 0 |
| 分片超时/无解 | 照常封存为 failed/degraded 世界（readiness 需要这类样本），退出码 0 |
| 影子库缺失、迁移版本 <43、批准文件不可解析 | 退出码 1，timeline 记失败 |
| `dream_compare` 缺赛果（`results-90` 未封存） | 该日标 `pending`，下一轮闭环再补；不回填前瞻口径以外的数据 |

## 6. 测试

- **P0**：新旧物化在随机小夹具（多模板、`maximum_groups` 1–2、含省略场）上候选内容哈希序列逐一相等；物化数≠计数时抛错；用与 09-28 同形的 7 场夹具（面集合逐场照抄当天，含 `310` 全包场）跑四个分片并断言各自在契约墙钟内完成（超了就是契约问题，交 Jun）。测试不读生产数据。
- **P1**：已开球场被排除且留 `excluded_started` 引用；过滤后 <2 抛 `DayBoardTooSmall`；票面引用对空票/`legs.json`/betslips 三种来源哈希稳定；票面变化会改指纹。
- **P2**：有效、过期、未生效、撤销、窗口外、路径不符、登记人不符、同日第二次，各一条；派生单次批准能过现有 `_validate_recording`；作业路径对 `approvals/` 零写入。
- **P3**：`day run --job dream` 各结局的 timeline 记录与退出码；`--dry-run` 不写影子库；重试只在指纹变化时发生。
- **P4**：四行在夹具世界 + 夹具赛果上的 P、命中与回报；`outside_world` 与 `frozen_at_cutoff` 标记；赛果缺失标 `pending`。
- **E2E**（verify 技能口径）：实施完当晚 `discovery nightly --dry-run` 对当天板面，再由 20:30 定时真跑一次；次日 10:45 闭环报告出现「Dream 对照」节。

## 7. 已知缺口（本期不修，10-31 复盘再议）

- 世界与对照 B 行都不含单关（今天 004/005 开了胜平负单关，单场双选 P 最高 71.9%）。世界要加单关需改生成器模板与契约；对照要加需在冻结时带上单关开售信息。
- 20:30 前开球的场次不进世界。
- 世界的赔率档质量口径与现行「只放判断腿」规则不一致（§1 第 3 点）：本试点的价值仍是跑通录制→封存→回放→锦标赛→晋级→刹车，**不产出出票建议**。

## 8. 验收与 10-31 复盘

- **P0–P4 合并且当晚真跑**：`discovery status` 的封存世界数逐晚 +1（或有记录在案的跳过原因）；次日报告有对照节。
- **10-31 复盘交 Jun 裁**：
  1. 续期、撤销还是改窗口；
  2. 录制时刻是否提前（依据：被排除场次数/晚）；
  3. 单关缺口是否进契约修订；
  4. 对照 n 是否够登记 F12；
  5. 就绪门进度（封存世界 x/30、独立业务日 y/20）。

## 9. 实施顺序

P0 → P1 → P2 → P3 → P4。P0 必须最先：不修它，每个真实世界都会超时，后面四步录下的全是 failed 世界。P3 的 plist 在 P0–P2 合并并手动 `--dry-run` 通过后才装载。
