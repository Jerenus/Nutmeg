# 历史回放环境（Replay Gym）· 设计

日期：2026-10-01 ｜ 状态：假期迭代 #1，Jun 批准方向（「一二三四都处理完成后开始五六」），本文待 Jun 过目后出计划 ｜ 依赖：`experiments/corpus-v2.json`、`.nutmeg-data/jczq/daily/<日>/sporttery_markets.json`、`jc-results.json`、`closing_odds.json`、`zucai/<期>-*.json`、`nutmeg/decision/betslip.py::settle_slip`、`structure_space.enumerate_frontier`、`jczq_combos`

## 0. 一句话

把 2026-05-18 → 09-30 的 134 个竞彩板面日和 42 期足彩做成一个可反复"虚拟下注"的环境：给一条**决策规则** `policy(board) → 票面列表`，按真实赛果与官方派奖精确结算，产出逐日 ¥ 账、累计曲线、bootstrap CI、最大回撤、相对基线的 regret。F9 已证明我们的 belief ≈ 市场，钱亏在结构与决策——这一层此前从未被量化评估过（F14 n=0、Dream n=2）。

## 1. 为什么不是 RL，而是"全信息反事实"

我们的动作不改变赛果。任何反事实票面的收益都能**精确算出**（竞彩：赔率乘积 × 2 元 × 倍数；足彩：官方当期每注奖金），不需要 importance sampling 之类的离线策略估计。唯一的近似是足彩奖池（别人的投注决定每注奖金）——用官方公布的当期奖金，再用奖金中位数做稳健性。借 RL 的只有骨架：环境 / 奖励 / 策略三分；奖励＝净 ¥（不是 P 全对）；相对基线的 regret；按 regime 分桶；探索预算与预登记分离。

## 2. 数据（全部已在磁盘，勘察 2026-10-01）

| 对象 | 来源 | 覆盖 | 坑 |
|---|---|---|---|
| 竞彩板面 | `jczq/daily/<日>/sporttery_markets.json`（17:00 快照；含次日场次） | 134 天，2,635 条 → 1,331 个 (businessDate, code) | 一天只有一份快照：**价格＝17:00 的价**，等于假设 17:00 下单；had 单关只有 655/2,303 开放（`poolList.single`），**多数场次最少 2 串 1** |
| 竞彩赛果 | `jczq/jc-results.json`（titan007 全场比分） | 134 天，1,314 场；1,305 能对上板面 | 标「全场」未保证 90'；用 titan007 id 对终盘，用 code 对板面 |
| 终盘 | `jczq/daily/<日>/closing_odds.json`（titan007 sharp/all） | 132 天，1,312 场 | 终盘在开球时刻，晚于 17:00——只能作 belief 源，**不能作可买价格** |
| 判断 | `reads.json`（23 天，239 条）、语料 `provably_prospective` | 09-19 起才有连续覆盖 | 用于"判断叠加"变体，默认 belief＝市场 |
| 足彩期次 | `zucai/<期>-issue.json`、`-odds.json`（≥26091，42 期，去水赔率） | 42 期 | 26091–26099 的 odds 是原始均价（Σ1/x≈1.05），≥26110 去水 |
| 足彩赛果 | `zucai/official-results.json`（110 期，`3 1 0 …`，`*`＝作废） | 26024–26134 | **26133 缺**（要补抓） |
| 足彩奖金 | **磁盘上没有**（只有 26112） | — | `zucai_official.fetch_official(issue)` / `fetch_renjiu_history(page_size)` 能取：任九每注奖金与注数、胜负彩一/二等奖、销量；要**缓存一次** |
| 真票 | `.nutmeg-data/betslips.jsonl`（47 张，09-11 → 09-28，实购 ¥7,170）、`zucai-ledger.jsonl`（45 行，含 prize_yuan） | 9 月 | 两张带 hafu 腿的票现有结算算不了 |

## 3. 目标形态

```
nutmeg/gym/
  board.py      # 历史板面：JczqBoard(day) / ZucaiIssue(issue)，只装"下单时刻可得"的信息
  payout.py     # 派奖：竞彩串关（复用 settle_slip，补 hafu 与过关方式校验）；足彩任九/胜负彩一二等奖
  prizes.py     # 官方奖金缓存：zucai/official-prizes.json（一次性抓 + 增量）
  policy.py     # Policy 协议 + 注册表（名字、版本哈希、参数、预登记日期）
  policies/     # 基线与候选策略（见 §5）
  run.py        # 逐日/逐期跑 → ledger.jsonl；汇总：净额、ROI、回撤、CI、regret、regime 分桶
  report.py     # Markdown 报告
nutmeg/interfaces/cli/gym.py   # nutmeg gym prizes-cache | run | compare | verify
```

### 3.1 Board（环境状态）
- `JczqBoard`：`day`、`matches[code]`＝{`kickoff_bj`, `league`, `had{3,1,0}`, `hhad{line,3,1,0}`, `ttg`, `crs`, `single_allowed{had,hhad}`, `allup`（允许的过关方式）, `closing_fair`（可选）, `read_belief`（可选，只在 `provably_prospective` 时给）}；`results[code]`＝{`outcome_90`, `goals_h`, `goals_a`}（结算用，策略看不到）。
- `ZucaiIssue`：`issue`、`sale_deadline`、`matches[1..14]`＝{`fair`(去水), `kickoff_bj`, `jczq_code?`}、`result`（14 位串）、`prizes`＝{`rj9{count, amount}`, `sfc_first{count, amount}`, `sfc_second{…}`, `sales`}。
- **信息边界**：`policy` 只拿 `Board.visible()`——没有 results、没有 prizes；closing 只在策略显式声明 `belief_source="closing"` 时给，并在报告里标「用了开球时刻的价」。

### 3.2 Policy
```python
class Policy(Protocol):
    name: str; version: str          # version = 参数 + 代码哈希
    def decide(self, board: JczqBoard | ZucaiIssue, ctx: Ctx) -> list[BetSlip]: ...
```
`Ctx` 带：当日/当期注金帽（默认宪法 §4：竞彩日 ≤¥400、足彩复式 ≤¥400、日总 ≤¥2,000）、月度止损状态（`bankroll.brake_state`，触发则策略必须空仓——由 run 强制，不信策略自觉）、随机种子。票面就是 `BetSlip`（与真票同一数据类，结算走同一条路）。

### 3.3 结算与账
- 竞彩：`settle_slip` 精确结算（赔率乘积 × 2 × 倍数）；新增：**过关方式合法性**（`allup` 与 `single_allowed`，非法票面直接拒绝并计 `illegal`）、hafu 腿结算（半全场）。
- 足彩：任九＝9 场全对 × 当期每注奖金；胜负彩＝14 场全对一等奖 + 13 场二等奖（`settle_slip` 现在没有二等奖路径，补）；`*` 作废场按官方规则全对。奖金来自 `official-prizes.json`；缺当期奖金的期次跳过并计数，不猜。
- 账：逐票 ledger（day/issue、policy、slip 内容哈希、stake、payout、net）；逐日汇总；累计曲线；最大回撤；按日 bootstrap 的净额 CI（n＝日数）；**regret**＝相对 `flat`（空仓）与相对事后最优固定策略的净额差；regime 分桶（竞彩：当日热门场数占比；足彩：任九奖金分位 冷/中/热）。

### 3.4 验证（gym 自己要先过的门）
- `nutmeg gym verify`：把 `betslips.jsonl` 里 9 月的 41 张实票按原样喂进结算，总净额必须等于记分牌 `tickets` 的 9 月净额 **−¥4,721**（允许 hafu 两张标 unsupported 后的差额逐条说明）。结算算不对，后面全是废话。
- 任九奖金：缓存值与 `zucai-ledger.jsonl` 里已登记的 `prize_yuan` 逐期核对。

## 4. 不做
- 不做 ttg/crs 的策略（结算支持即可）；不做比分模型（让球腿用 `dcfit.fit_match` 已有的 hhad_cover）。
- 不碰内核（gym 只读文件）；不改 Dream（Dream 继续记"今天"，gym 回放"过去"；10-31 两者口径对齐）。
- 不做 RL 训练；策略数量克制（§5 的 7 条 + 真票回放），新增策略必须先登记再跑测试窗。

## 5. 首批策略（锦标赛 #3 的输入，先在 spec 里登记）

| 名 | 渠道 | 规则 |
|---|---|---|
| `flat` | 两者 | 永远空仓（基线） |
| `jczq_max_p` | 竞彩 | belief＝体彩去水；`enumerate_combos` 帽内 P 最高的 2–4 串 1，¥400/日 |
| `jczq_ev_filter` | 竞彩 | 同上但只用 终盘隐含 EV>0 的面（#2 的表 2 说它不可靠——放进来被证伪） |
| `jczq_fav_pairs` | 竞彩 | 终盘 ≥0.70 热门两两 2 串 1（#2 的 +15pp 结构化用法） |
| `zucai_max_p` | 足彩 | `enumerate_frontier(mode=belief)` 帽内 max P（¥400） |
| `zucai_fav_single` | 足彩 | ≥0.70 大热单选、0.2 以下面不进全包、其余按 max P |
| `zucai_prescription` | 足彩 | 有 `judgment-v1`/`final-tickets` 的期次回放处方票（26111+） |
| `real` | 两者 | 真票原样回放（09-11 → 09-28） |

训练/测试切分：按日期，测试窗＝最近 30 天（与 `zucai_loop search` 同纪律）；报告给出策略数与期望最大 |z|。

## 6. 验收
1. `gym verify` 复现 9 月真票净额。
2. `gym run --policy flat,jczq_max_p,…` 跑完 118 个竞彩日 + 42 期足彩，报告含净额、ROI、回撤、CI、regret、regime 分桶。
3. 任一策略一天的结果可用 `--day` 单独复现，ledger 可追到每一注。
4. 时间：单策略全量 < 5 分钟（枚举已有，足彩 DP 已有）。
