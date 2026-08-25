# RUNBOOK — 每日执行清单（两条泳道；命令可直接复制）

> 只写"做什么"，不写"为什么"。为什么见 RULEBOOK 对应条目。launchd 的 am/close/settle 仍禁用，全部手动。

## 泳道 A：竞彩（JCZQ 日常）

| 步 | 动作 | 命令/门 |
|---|---|---|
| A1 | 数据入库+市场基线 | `uv run nutmeg decision-am --run-date $(date +%Y-%m-%d) --output-dir .nutmeg-data/jczq`；看 alias-audit 输出，未命中=该场丢国际锚 |
| A2 | 判读 | 深度请求→每场并行派 `jczq-match-analyst`（七阶段）；否则主循环直判。每场落到判决表四级之一 |
| A3 | 落 Read | `decision-read --reads-file …`（结构化 JSON；因子必须在词典内；league/team 因子带 scope_key） |
| A4 | 构票 | 写 legs.json（含 flags/anchor_integrity/**precedents**） |
| A5 | **审计门** | `uv run nutmeg decision-audit-legs --legs-file …` — ERROR=退出码1不许出票；WARN 逐条显式裁决入账 |
| A6 | 出票 | `decision-close --run-date … --dispatch-telegram --no-dry-run`；空 legs=空票合法 |
| A7 | 次日结算 | `decision-settle --run-date <昨天> … --no-dry-run` → 更新 `scoreboard.json` → 复盘写 rx outcome |

## 泳道 B：传统足彩（胜负彩/任九）

| 步 | 动作 | 命令/门 |
|---|---|---|
| B1 | 14:00 备料 | prep 链自动（`zucai-prep`）；产 `<issue>-prep-afternoon.json/md`，判读表留空 |
| B2 | 入 canonical | `decision-am --run-date <开赛业务日> --issue <issue>`（prep 不入 store，必须跑这步） |
| B3 | 判读 | 逐场：市场锚→DC→结构完整度→旗→判决表动作；产 P14 处方（全 14 场面集合） |
| B4 | 落 Read | 同 A3；每场 note 里显式列旗名与动作级 |
| B5 | 构票 | 两阶段：共振定面→盖率定场（q条）；预算压缩只许丢场（8/08铁律） |
| B6 | **审计门** | 同 A5；historical: 自查比人工多抓 2 条 |
| B7 | rx 预注册 | `<issue>-rx.json`：终版票+待裁刀+可证伪预测（含奖金模型分支检验） |
| B8 | 18:30 位移复核 | prep 链自动 diff；牌照线（体彩vs国际反向≥3pp→撤单选）、分歧场归属 |
| B9 | 出票+入账 | 用户确认后 ledger 追加（口径注明）；**没入账=没打** |
| B10 | 开奖结算 | okooo 先行 + 官方 gameNo=90 终核（含任九奖金→奖金模型记分）；ledger settle + rx outcome + scoreboard 更新 + retro memory |

## 收尾检查表（每期）

- [ ] scoreboard.json 更新（连锁/牌照/保险兑现/裁决记分）
- [ ] rx 每条预测标 outcome（✓/✗/NA+falsifier 执行）
- [ ] 被取代的记忆条目标记/归档
- [ ] 新联赛上线三步：别名表→实体种子（name_zh 精确=leagueAbbName）→sync+audit
