# RUNBOOK — 每日执行清单（两条泳道；命令可直接复制）

> 只写"做什么"，不写"为什么"。为什么见 RULEBOOK 对应条目。launchd 的 am/close/settle 仍禁用，全部手动。

## 泳道 A：竞彩（JCZQ 日常）

| 步 | 动作 | 命令/门 |
|---|---|---|
| A1 | 数据入库+市场基线 | `uv run nutmeg decision-am --run-date $(date +%Y-%m-%d) --output-dir .nutmeg-data/jczq`；看 alias-audit 输出，未命中=该场丢国际锚 |
| A1b | v2 外部证据桥（shadow） | 外部采集产严格 `evidence-intake-v1` 后执行 `uv run nutmeg workflow ingest-evidence --manifest <path>`；`operator-evidence-policy-v1` 全门与本命令共同部署前，v2 只作 shadow，不替代现行 A1-A7 |
| A2 | 判读 | 深度请求→每场并行派 `jczq-match-analyst`（七阶段）；否则主循环直判。每场落到判决表四级之一 |
| A3 | 落 Read | `decision-read --reads-file …`（结构化 JSON；因子必须在词典内；league/team 因子带 scope_key） |
| A4 | 构票 | 写 legs.json（含 flags/anchor_integrity/**precedents**/`tracking_tags` 追踪标签） |
| A5 | **审计门** | `uv run nutmeg decision-audit-legs --legs-file …` — 默认/AI/无人值守遇 ERROR=退出码1不许出票；仅 Jun 显式 `--user-override` 且登记 reason/rule ID、evidence_rejected Adjudication 入账成功后可继续；WARN 逐条显式裁决入账 |
| A6 | 出票 | `decision-close --run-date … --dispatch-telegram --no-dry-run`；空 legs=空票合法 |
| A7 | 次日结算 | `decision-settle --run-date <昨天> … --no-dry-run` → 更新 `scoreboard.json` → 复盘写 rx outcome |

## 泳道 B：传统足彩（胜负彩/任九）

| 步 | 动作 | 命令/门 |
|---|---|---|
| B0 | **11:00 早刷新** | `uv run nutmeg zucai-prep --slot morning`（2026-09-11 新增）；产 `<issue>-prep-morning.json/md`。**出生事故 26122：14:00 才首次刷新，当天 8 场判读建立在前一日体彩 HAD 上** |
| B1 | 14:00 备料 | prep 链自动（`zucai-prep`）；产 `<issue>-prep-afternoon.json/md`，判读表留空；位移 diff 自动与**最近的前一个 slot** 比 |
| B2 | 入 canonical | `decision-am --run-date <开赛业务日> --issue <issue>`（prep 不入 store，必须跑这步）。**顺带落 `<issue>-store-ids.json`**（按 `zucai-canonical` 键查，禁用 fair 值反查——26122 场2/6/7 因同队也在竞彩板上被反查抢错身份） |
| B2b | v2 外部证据桥（shadow） | 14 场外部采集产严格 `evidence-intake-v1` 后执行 `uv run nutmeg workflow ingest-evidence --manifest <path>`；`operator-evidence-policy-v1` 全门与本命令共同部署前，v2 只作 shadow，不替代现行 B1-B10 |
| B3 | 判读 | 逐场：市场锚→DC→结构完整度→**两队 team_tags（RULEBOOK 球队影响因子标签词典，带证据与失效）→对位机制**→旗→判决表动作；产 P14 处方。**处方票价只作当日难度指数，不是待售票**。**读判在 14:00 备料复核后冻结**（RULEBOOK 临场只加面，probation） |
| B4 | 落 Read | `uv run nutmeg zucai-build-reads --judgment-file <judgment-v1> --issue <issue> --store-ids-file … --fair-file … --made-at …` → 产 reads.json + legs-base.json（只转录与词典校验，判断在 judgment 里）；再 `decision-read --reads-file …`。每场 note 显式列旗名与动作级；legs 带 `team_tags`/`tracking_tags`/`license_questions`/`ttg_shape_anchor` |
| B4b | **穷举候选比较** | 先跑 `uv run nutmeg zucai-candidates --options-file <声明空间> --fair-file … [--base-file <基准票面>]`（穷举/单点与两点替换报告），再用 `zucai-optimize --input-file <cand.json>` 固化已选版本；只穷举人已声明的有限票面空间，先保留全部 audit-blocked/over-cap 行，再对 eligible 候选**帽内按 P(全对) 降序**，**同 P 依次按票价升序、内容哈希升序**。**回本线/官方中位倍数只作报告**，**不排序、不阻断、不自动建议空仓**，首行不等于推荐且默认不选择 |
| B5 | **首版构票（一步到位，2026-08-24 用户定）** | 在处方之上**直接完成砍腿后的第一版实票**，不得只交全包清单等用户逐轮压缩：①单选＝牌照/实质单核验（净线优先）；②3进2＝排面活性验尸（先例载体存亡+钱流方向+热度×资讯偏差）后砍第三面；③2进1＝保险性价比表（兑现概率×每元效率）定裸/保；④附**资金使用率报告**（票价 vs 难度、每笔保险买的是哪个面）＋2-3 个备选档位 |
| B5b | **风险预警与裁决分工** | 翻车场/异常项（改场/夹心/源分歧/终核异动）逐条列出，标注「我已裁决：理由」或「需你裁决：两选项」。**默认我裁**；以下必须上交：翻车场裸单、终核≥2pp异动打在裸单上、用户历史点名过的死法形状 |
| B5c | **四表共振核对（probation, 2026-09-06）** | 首版实票成型后、审计门前，每一保留场一行四列：①牌照四问 0-4（中轴/正路破门机制/对手破门机制缺席/无情境旗与 C9）②被排面死亡三证 0-3（机制缺席/载体不在/正路 PASS）③崩塌双列（洞在哪侧、中轴哪个位置）④翻车预警名次+先失球走势。**决策矩阵**：四问 4/4 且翻车名次低→裸单；3/4→至多双选，三证 3/3 才排，2/3 且被排面 ≤15% 可排，否则全包或丢；被排面 >20% 且三证 <3→必须全包或丢；洞在正路中轴→禁裸单；多票共享 >20% 被排面→组合 WARN；附被排面按 P 降序的独立面效率表 |
| B6 | **审计门** | 同 A5；**同期多票必须一起跑**：`decision-audit-legs --legs-file <票1> --with-legs-file <票2> …` 才会触发 C15 共享被排面检查（分散注金不等于分散死点）|
| B7 | rx 预注册 | `<issue>-rx.json`：终版票+待裁刀+可证伪预测（含奖金模型分支检验）；落盘后 `uv run nutmeg workflow register-rx --rx-file <issue>-rx.json --issue <issue>`（幂等，裁决后重跑补录已决 ADJ） |
| B8 | 18:30 位移复核 | prep 链自动 diff；牌照线（体彩vs国际反向≥3pp→撤单选）、分歧场归属。**只核对新事实是否已被价格吸收；临场事实只许加面（双选→全包/裸单→双选），换被排面须首发/停赛级事实并注明未被价格吸收；深研 agent 的"最薄面"结论只作 note**（RULEBOOK 已定价≠可反转 / 临场只加面，probation） |
| B9 | **部署门**+出票+入账 | 所有候选逐行跑 audit、预算与部署算术；ERROR/over-cap 影响 eligible 分区，回本线门槛只显示历史可比报告，**不排序、不阻断、不自动建议空仓**。减注、丢场或空仓只由 Jun 显式裁决；正常路径仍以选择并出票为主。产 approved artifact 后跑 `uv run nutmeg ticket-confirmation request --ticket-artifact-id <id> --data-dir .nutmeg-data --no-dry-run`，只有 Telegram owner 按钮可消费第二段确认；callback 原子写 Ticket/ledger，截止未确认自动记 shadow 且不入 ledger，故仍是**没入账=没打**；同时落 `<issue>-final-tickets.json` 结构化票面与 `<issue>-af-map.json` 身份映射（faces 不再只住散文） |
| B9c | **实票登记** | 页面：`uv run nutmeg decision-web` → <http://127.0.0.1:8787/betslips>（任九/胜负彩；列表带方案号缺失告警）。CLI：`uv run nutmeg betslip register --slip-id <期-票号> --channel renjiu\|shengfucai\|jczq --placed-at … --faces "<整行或点名式>" --fair-file … --multiplier N --scheme-no <方案号> [--trial]`；竞彩用 `--legs-file` + `--combo 4` / `--combo 2,3`。**方案号缺失会在摘要里喊**——没入账=没打，账空则刹车条款失去输入 |
| B9b | 晨间夜账校准（多夜期次每夜一次） | `uv run nutmeg zucai-night-calibrate --issue <issue> --date <欧洲比赛日>`（90' 口径，AET/PEN 取 fulltime）；需推送时显式加 `--dispatch-telegram --no-dry-run`；报告供主循环写 rx night 块；af-map 缺映射=显式跳过，禁按队名猜测补 |
| B10 | 开奖结算 | `betslip settle --results-file <90'三源赛果> [--prize-per-note <官方单注>]`（竞彩按赔率连乘，足彩须给官方单注奖金）；okooo 先行 + 官方 gameNo=90 终核（含任九奖金→奖金模型记分）；ledger settle + rx outcome + scoreboard 更新（含 `tags` 组按追踪标签累计）+ retro memory；预测判定 `workflow grade-rx --rx-file <rx> --issue <issue>` 批量记账（P1..Pn 自动对号到 prediction-hex；判断在主循环，动作只记账）；**影子期双轨**：改完 scoreboard.json 跑 `nutmeg scoreboard settle-issue --scoreboard-file … --evidence-type official_draw --evidence-id <期号> --no-dry-run --acknowledge-manual-source` 一次性镜像（自动找 leaf 与 supersedes；JSON 仍权威，无镜像=违 M5），期末 `nutmeg scoreboard shadow` 对账入证据 |

## 收尾检查表（每期）

- [ ] scoreboard.json 更新（连锁/牌照/保险兑现/裁决记分）
- [ ] rx 每条预测标 outcome（✓/✗/NA+falsifier 执行）
- [ ] 被取代的记忆条目标记/归档
- [ ] 新联赛上线三步：别名表→实体种子（name_zh 精确=leagueAbbName）→sync+audit
