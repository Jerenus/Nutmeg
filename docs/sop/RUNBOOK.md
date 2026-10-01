# RUNBOOK — 每日执行清单（两条泳道；命令可直接复制）

> 只写"做什么"，不写"为什么"。为什么见 RULEBOOK 对应条目。launchd：am 08:00 自动（失败 30 分后重试）；close 链 2026-10-01 退役（真票走 A6/B9c 登记）；settle 由 `com.nutmeg.day.settle` 09:45/15:45 承担。 **出生事故全文在 `INCIDENTS.md`（按步骤编号索引，2026-09-30 迁出）；本表只留指针。**

## 每日先看一眼：状态页

`uv run nutmeg ops-status` —— launchd + OpenClaw + 不会自己消失的待办，一屏看全，**只读**。
<http://127.0.0.1:8787/observe> —— RSI 实验全景（只读）；`/observe/day/<date>` 看当天候选树与资金方案。
**出生事故 2026-09-17**（为什么每条结局都要并排时间证据）→ `INCIDENTS.md` §状态页

> **并集样本池（2026-09-27 起，Jun 定）**：每天的分析样本池 = 当天截止的传统足彩期次（优先）∪ 竞彩板面，按对号表去重（人工 `{issue}-channel-map.json` 优先，缺则备料自动落 `.auto`）。`research run` 队列取并集：未试过优先 → 足彩独有场次优先 → 开球先后；足彩独有场次的研究写 `zucai/{issue}-research-m{n}.json`，登记 R1。研究有新产出、17:15 刷新、足彩备料之后都跑 `uv run nutmeg research refresh --day <日>`：竞彩入库重建 Read、足彩由研究表态自动转录 Read（judge=`ai-pool`；主循环 judgment-v1 永远优先）、**未开球且内容有变的 Read 自动交本体**（开球后一律不交）。足彩备料完成会自动带期号跑 `decision-am --issue`（产 store-ids），足彩场次才进得了池。预算仍 40 次/天。

> **信号留存与人工裁决（2026-09-27 起，Jun 定）**：研究原件**只读**——主循环改判一律 `uv run nutmeg research override --day <日> --code <场次> --note "<理由>" (--market | --tilt-json '<tilt>')`，记进当日 `overrides.jsonl`（原拨动、终拨动、两个判断分布、理由、时间），入库时叠加；**禁止手改 research-*.json**。每次 `research refresh` 自动重写 `daily/<日>/signals.md`（也可 `uv run nutmeg research signals --day <日>`）：置顶「主循环改判了研究的信号」「同场两份研究打架」，其余按信号强度排；有赛果后给研究原判 vs 终判的 Brier（改判得失）。证据采集时间由系统盖，研究员自填的留作 `captured_at_declared`。

> **当日判决参考页（2026-09-27 起，Jun 定）**：`com.nutmeg.day.verdict` 每天 **12:30 主版**（08:00 入板 + 上午研究 + 足彩截止日 11:00 备料后的足彩研究都已落）与 **18:45 晚版**（17:15 加场 + 18:00 研究 + 18:30 足彩复核之后，赶在 19:00 后主要开球与足彩停售前）自动 `research refresh` + `research verdict`，产 `daily/<日>/verdict.html`（本地 `http://127.0.0.1:8787/verdict/<日>`）。页面置顶「需要你裁决」（主循环改判 / 两份研究打架），逐场给市场·研究原判·终判三行与证据，附判断腿组合与判断力账本。主循环会话中复核改判后，重跑 `uv run nutmeg research verdict --day <日>` 刷新。

## 泳道 A：竞彩（JCZQ 日常）

> **strength-v2（2026-09-26 起）**：深研产「强弱天平」块（双方本场强度/风格对位/战术剧本/弱势方取胜路径/事件分级）→ 主循环写 belief（事件分级 → pp，**<5pp 不再归零**，可多面 shift）→ 帽内按**判断概率**最大化 P → 审计门**无判断类拦截**（2026-09-27 规则瘦身：判断类规则无一有正向实证，C1 降为记录、C19 降为未证实提示），只记账。见 RULEBOOK「〇、规则实证表」。

| 步 | 动作 | 命令/门 |
|---|---|---|
| A1 | 数据入库+市场基线 | `uv run nutmeg decision-am --run-date $(date +%Y-%m-%d) --output-dir .nutmeg-data/jczq`；看 alias-audit 输出，未命中=该场丢国际锚。成功后自动 `research board` + `rsi schedule`，为板上每场生成 R0 duty |
| A1b | v2 外部证据桥 | 外部采集产严格 `evidence-intake-v1` 后执行 `uv run nutmeg workflow ingest-evidence --manifest <path>`。（`workflow jczq-status` 所属的 operator_v2 板工作流已于 2026-09-23 退役，研究终态核对改看 `research intake` 输出） |
| A2 | 判读 | `uv run nutmeg research run --day $(date +%Y-%m-%d)`（headless，预算 40 场/日，按开球排队；研不到如实保留 `price_only`）→ `uv run nutmeg research intake --day $(date +%Y-%m-%d) --write`；每场落到实际 `judgment_tier`，不得补造中间态 |
| A3 | 落判读 | `uv run nutmeg jczq-build-reads --day $(date +%Y-%m-%d)` 生成 `reads.json` → `uv run nutmeg decision-read --reads-file …` 提交 ForecastRevision。（operator_v2 板工作流及其 `workflow jczq-project` 投影已于 2026-09-23 退役） |
| A4 | 构票（只放判断腿，2026-09-27） | `uv run nutmeg jczq-combos --day $(date +%Y-%m-%d)`：腿＝深研过且未开球的场次；玩法＝胜平负单/双选 + 由判断概率拟合的让球单选；**不含总进球、不按 10/20/50/100 倍凑腿**；按判断概率排序并报每元回报。用户要求赔率档位时，逐条标明哪些腿没有判断成分。**历史回放（2026-10-01 起）**：`uv run nutmeg gym run --policy jczq_max_p,jczq_fav_pairs,real --from <30 天前>` 看同一构票规则最近 30 天的精确账（竞彩按 17:00 快照价、2 串 1 起、单关只在开单关的场）；策略先登记（`nutmeg/gym/policies/`）再跑，结果不是出票指令 |
| A5 | **审计门** | `uv run nutmeg decision-audit-legs --legs-file …` — 默认/AI/无人值守遇 ERROR=退出码1不许出票；仅 Jun 显式 `--user-override` 且登记 reason/rule ID、evidence_rejected Adjudication 入账成功后可继续；**WARN 是提示，只记账**（strength-v2） |
| A6 | 出票（真实路径，2026-10-01） | 真票在 500 app 下单。**下单前** `uv run nutmeg betslip preview --channel jczq --placed-at <日> --legs-file … --combo …`（注数/P/共享裸单/对照处方）；**下单后** `betslip register`——写票面 `diagnosis` 并把每注写成内核 Ticket（`ledger_writeback`：没有已提交 Read/选项/真实赔率的注跳过计数，绝不伪造），「没入账=没打」以登记簿为准。`decision-express`/`decision-close`/Telegram 二段确认/`legs.json` 出票链 2026-10-01 退役（74 天里从未产出一张真票） |
| A7 | 次日结算 | 通过正式 result/settlement/review Actions 结算；no-ticket 资金结算为 0 但 Forecast 仍进入复盘。historical replay 永不增加 prospective R0/F5/F9 样本。体彩按取消处理的场（延期 >36h）登记在 `.nutmeg-data/jczq/void-matches.json`（板面日 → 编号），`betslip settle` 与 gym 结算都按腿算中、赔率 1 |

切换门：operator_v2 的 `workflow jczq-replay` / `jczq-cutover` 切换门已于 2026-09-23 随板工作流一并退役；`decision-close` 固定走旧路径，出票授权仍只来自 A5 审计门 + Jun 当次确认。

## 泳道 B：传统足彩（胜负彩/任九）

> **strength-v2（2026-09-26 起）**：深研产「强弱天平」块（双方本场强度/风格对位/战术剧本/弱势方取胜路径/事件分级）→ 主循环写 belief（事件分级 → pp，**<5pp 不再归零**，可多面 shift）→ `plan frontier`（belief 模式：纯判断概率，任何腿都可裸单，保险给谁由 P 算）出前沿，B5c 矩阵与 strict 地板只作旧规则对照 → 审计门**无判断类拦截**（2026-09-27 规则瘦身；胜负彩大胆单选渠道规则随之退休），只记账。见 RULEBOOK「〇、规则实证表」。多张票同期出：同一个没把握的裸单不得出现在每一张里（C15b 报出全部票同死于该场的概率）。

> **页面按钮＝同一条命令（2026-09-18 起）**：`uv run nutmeg decision-web` → 顶部 SOP 任务栏按期号列出 B0/B1/B2/B3a/B4/B4b/B5c/B5/B6/B6b/B9 十一步，点一下＝进程内跑本表同一条 CLI，`task_started/task_done/task_failed` 进当日 `workbench.jsonl`。
> ⛔按钮里没有 B3 深研（要 agent）、B5 的人工 choose、B6b 的 ruling（人填）——那是设计，不是缺功能。
> B6 审计门退出码 1＝「有 ERROR」这个判决，任务栏按成功记（`ok_exit_codes`），ERROR 仍须人裁。

| 步 | 动作 | 命令/门 |
|---|---|---|
| B0 | **11:00 早刷新** | `uv run nutmeg zucai-prep --slot morning`（2026-09-11 新增）；产 `<issue>-prep-morning.json/md`。**出生事故 26122：14:00 才首次刷新，当天 8 场判读建立在前一日体彩 HAD 上**。**备料完成后自动 `rsi schedule` + `rsi due`，并按 due 列出的 instrument 执行**（2026-09-18 起） |
| B1 | 14:00 备料 | prep 链自动（`zucai-prep`）；产 `<issue>-prep-afternoon.json/md`，判读表留空；位移 diff 自动与**最近的前一个 slot** 比 |
| B2 | 入 canonical | `decision-am --run-date <开赛业务日> --issue <issue>`（prep 不入 store，必须跑这步）。**顺带落 `<issue>-store-ids.json`**（按 `zucai-canonical` 键查，禁用 fair 值反查——26122 场2/6/7 因同队也在竞彩板上被反查抢错身份） |
| B2b | v2 外部证据桥（shadow） | 14 场外部采集产严格 `evidence-intake-v1` 后执行 `uv run nutmeg workflow ingest-evidence --manifest <path>`；`operator-evidence-policy-v1` 全门与本命令共同部署前，v2 只作 shadow，不替代现行 B1-B10 |
| B3 | 判读 | 逐场：市场锚→DC→结构完整度→**两队 team_tags（RULEBOOK 球队影响因子标签词典，带证据与失效）→对位机制**→旗→判决表动作；产 P14 处方。**处方票价只作当日难度指数，不是待售票**。**读判在 14:00 备料复核后冻结**（RULEBOOK 临场只加面，probation） |
| B3a | **前提卡（2026-09-17 新增）** | 派深研 agent **之前**：`uv run nutmeg zucai-premise-card --issue <issue> [--out …]`，把对应场次的卡原样贴进任务提示。卡**只写 store `profile_notes` 里有的**，其余明写「本卡未提供——请独立取证，不要替我补全」。agent 的任务因此从「从零查」变成「**核实并纠正这张卡**」，纠正写进研究 JSON 的 `premise_corrections`（每条需 `subject`/`correct`/`evidence`，**缺 evidence 不收**——纠正也是证据）。⛔**`subject` 必须是 store 的 team_id（如 `eng-everton`）或 league_id，`field` 必须是 profile_notes 的 key**（沿用卡上已有的 key，如 `availability_2026_08_20`；没有就新建带日期的 key）。**出生事故 26130 → INCIDENTS B3a**（subject 写成散文主语，回写 0/109）。派 agent 的提示里必须写死这三个字段的格式。赛后 `uv run nutmeg zucai-premise-corrections --issue <issue> [--apply]` 回写 store —— **纠正不回写＝白纠正**。**出生事故 26128 → INCIDENTS B3a**（写错的前提比不给前提更贵；「store 覆盖 0/140」是接线 bug）。卡改为**有什么发什么**，并单列两节：**别名未命中的队名**（补法＝`decision-alias-propose`，26128 有 19 支）与**未解析的联赛**（scope_key 无处可挂）。另外无论 store 有无内容，卡上永远印一份「必须独立核实」清单＝主帅／级别位次／欧战路径，那正是 26128 错掉的三类 |
| B3b | **研究入库桥（2026-09-17 新增）** | 深研 agent 产出 `<issue>-research-m<N>.json` 后：`uv run nutmeg zucai-research-intake --issue <issue> --legs-file <legs-base> [--match N] [--write]`（不加 `--write` 只预演）。**只转录与校验，不产生判断**——不改任何一场 faces。三类检查：①**封闭词典**：词典外的旗/标签剥离进 note 并留痕，**不阻断出票**（agent 自命名的旗若能堵死单选，那不是纪律是瘫痪，26103 一次冒出三个）；②**结构自相矛盾判 ERROR 拒绝写入**：四问④判「无情境旗」却挂着旗、宣告死面而三证不齐、叙述被写进标签位；③**定义漂移与编码/正文相反判 WARN 交人工复核**：三证 (c) 逐面不同或与完整度不符、③b 等编码与 summary 极性相反。⛔**提案（2026-09-20 立，待入码）：封闭词典改前缀匹配，余文剥离进 note**。现状不对称——旗/标签是「词典外剥离进 note、不阻断」，而 `crash_markers` 是**整份拒收**；且词典做精确匹配，旗名后面拖一句解释也整份被拒。（出生事故 → `INCIDENTS.md` §B3b） |
| B4 | 落 Read | `uv run nutmeg zucai-build-reads --judgment-file <judgment-v1> --issue <issue> --store-ids-file … --fair-file … --made-at …` → 产 reads.json + legs-base.json（只转录与词典校验，判断在 judgment 里）；再 `decision-read --reads-file …`。每场 note 显式列旗名与动作级；legs 带 `team_tags`/`tracking_tags`/`license_questions`/`ttg_shape_anchor`。**判断唯一事实 P0（2026-10-01 起）**：`research refresh` 后每块板落 `judgment-projection.json`（内核 revision 投影 vs 文件逐场比对），`nutmeg judgment project --day <日>｜--issue <期>` 可随时重跑；**分歧 > 0 先查再改判**（改判走 `research override`，记账后自动刷新、当场成为内核里一条 `kind=override` 的 revision）；P0 比对满一周零分歧再把写路径搬进内核（P2–P4） |
| B4b | **穷举候选比较** | 先跑 `uv run nutmeg zucai-candidates --options-file <声明空间> --fair-file … --legs-file <legs-base> [--audit-top N] [--structure 3/3/3] [--base-file <基准票面>]`（穷举/单点与两点替换报告），再用 `zucai-optimize --input-file <cand.json>` 固化已选版本；**审计两段式（2026-09-17 接入）**：先用 `face_options` 逐腿查表给全部候选贴腿级码（便宜），再对前 `--audit-top` 个跑真审计补票级码（C15/C15b/C17/全包分配）。⚠️**便宜查表的「零 ERROR」不是干净票**——它看不见票级码；26128 实测腿级零 ERROR 的 1,194 个候选里真审计过的每一个都触发 C17，输出里 ✓ 与 ≈ 两列必须分开读。`--structure 3/3/3`＝只留 3单3双3包（**出生事故 26127 → INCIDENTS B4b**）。⛔ERROR 不剔除候选、不改排序——行权空间归 B6b。⛔**声明空间 ≠ 合法空间（2026-09-18 入册）**：本命令按设计只穷举**人已声明**的票面空间（26125 内存被打爆后定的），所以它报的「帽内零 ERROR 解＝0」说的是**「我声明的那几个形状里没有」**。26127「严格空间帽内零解(机器确认)→空仓」与 B6b「26125-26128 严格裁决全部空仓」都是这么来的——实测全合法空间（C(14,9)×七面集，生产码 face_options 判 ERROR）：26127 ¥400 帽内 33,745 个前沿解 max P=23.09%；26128 ¥400 有 120 个 max P=6.06%、¥432 有 624 个 max P=6.94%；两张 max P 票面跑真审计均 0 ERROR，**只有 26126 是真零解**。谈空仓之前先跑 `uv run python experiments/exp-strict-space.py <期> --cap-notes <帽>` 打印全合法空间地板——「零解」必须是机器对全空间的判定。**出生事故 26125-26128 → INCIDENTS B4b**（/tmp 枚举器把内存打爆）；只穷举人已声明的有限票面空间，先保留全部 audit-blocked/over-cap 行，再对 eligible 候选**帽内按 P(全对) 降序**，**同 P 依次按票价升序、内容哈希升序**。**回本线/官方中位倍数只作报告**，**不排序、不阻断、不自动建议空仓**，首行不等于推荐且默认不选择 |
| B4c | **面集展开（2026-09-14 新增）** | `uv run nutmeg decision-explain-faces --legs-file <legs-base> [--match N] [--out …]`——每场七个面集 × 盖率/被排面档位/裸单总暴露/触发哪些码，**由机器机械展开条文**。⛔它只摊算术：**不排序、不推荐、不裁合法性**，退出码恒 0，不是出票门。死亡三证(a) 机制一证、牌照四问、旗的证据等级留空给主循环填（表末「判断栏」）。（出生事故 → `INCIDENTS.md` §B4c） |
| B5 | **首版构票（一步到位，2026-08-24 用户定）** | **先 `plan tiers` → `plan frontier` → `plan choose`（2026-09-19 起，票面只从前沿上来）**。在处方之上**直接完成砍腿后的第一版实票**，不得只交全包清单等用户逐轮压缩：①单选＝牌照/实质单核验（净线优先）；②3进2＝排面活性验尸（先例载体存亡+钱流方向+热度×资讯偏差）后砍第三面；③2进1＝保险性价比表（兑现概率×每元效率）定裸/保；④附**资金使用率报告**（票价 vs 难度、每笔保险买的是哪个面）＋2-3 个备选档位。**每一版被考虑过的票面（含被否掉的）用 `POST /action/candidate` 或 `append_candidate()` 进事件流，否决理由进 `note`；事后 `uv run nutmeg workbench-export --date <开球日>` 出复盘底稿、`/replay?date=` 看时间线**——出生事故 26129：SFC-B/C/D/E 四轮迭代与「平局是不是太少」的曲线只活在聊天窗口，仓里只剩终版文件，第二天在 app 里什么都看不到 |
| B5a | **深想结论先落对象，再构票（2026-09-28 新增）** | 构票过程中任何一轮补查/深想得出「A 场比 B 场更脆」「某面被低估」，**先** `uv run nutmeg research override --day <日> --code <场次> --note … --tilt-json …`（足彩独有场次同样适用）或改 judgment-v1 的 belief，重建 Read/legs 后再跑 `plan frontier`——只在聊天里做「二选一」的结论，下一轮按 belief 重算 P 时会被静默推翻。⛔**反转明示**：后续任何一版票面若与当天早先的明确结论相反（换回被弃的裸单、撤掉点名的保险），必须在候选 `note` 与回复里并列写「推翻 HH:MM 的 X；理由；P 的差」交 Jun 裁。保险面对准弱方路径的产物（只通平→盖平；能赢→盖弱方胜或全包）。（出生事故 → `INCIDENTS.md` §B5a） |
| B5b | **风险预警与裁决分工** | 翻车场/异常项（改场/夹心/源分歧/终核异动）逐条列出，标注「我已裁决：理由」或「需你裁决：两选项」。**默认我裁**；以下必须上交：翻车场裸单、终核≥2pp异动打在裸单上、用户历史点名过的死法形状 |
| B5c | **四表共振核对（probation, 2026-09-06；strength-v2 起降为参考，不再是出票前提）** | 首版实票成型后、审计门前，每一保留场一行四列：①牌照四问 0-4（中轴/正路破门机制/对手破门机制缺席/无情境旗与 C9）②被排面死亡三证 0-3（机制缺席/载体不在/正路 PASS）③崩塌双列（洞在哪侧、中轴哪个位置）④翻车预警名次+先失球走势。**决策矩阵**：四问 4/4 且翻车名次低→裸单；3/4→至多双选，三证 3/3 才排，2/3 且被排面 ≤15% 可排，否则全包或丢；被排面 >20% 且三证 <3→必须全包或丢；洞在正路中轴→禁裸单；多票共享 >20% 被排面→组合 WARN；附被排面按 P 降序的独立面效率表 |
| B6 | **审计门** | 同 A5；**同期多票必须一起跑**：`decision-audit-legs --legs-file <票1> --with-legs-file <票2> …` 才会触发 C15 共享被排面检查（分散注金不等于分散死点）|
| B6b | **裁决单（2026-09-17 新增）** | 仅当 B6 有 ERROR 且**打算行权**时走这步。①签发：`uv run nutmeg decision-adjudicate --legs-file <票面> --out <裁决单>`——机器把每条 ERROR 摊成一个裁决位，`ruling`/`reason`/`rule_ids`/`predictions` **四栏全部留空**（判断永不入脚本）。②人填 `ruling=accept\|reject`。③落文书：`--apply <裁决单>`——写回 `deviation_registry`，驳回预测并入 `<issue>-rx.json`。⛔**驳回必须附可证伪预测**（claim+falsifier）与**已登记条名**：26098/26101/26102/26103 四次撤保险，理由一次比一次讲究且全亏，**理由的质量不可自证**，能自证的只有事后可判真假的断言。⛔**接受门 = 这张票不出**，`--apply` 拒绝为它落文书（8/08 铁律：合法动作是丢整场）。⛔裁决单带 ERROR 集指纹，签发后票面被改过即作废。⛔**它不是门也不放宽门**——落完文书仍须 `decision-audit-legs --user-override --ticket-batch-token <Web 工位签发>`。（出生事故 → `INCIDENTS.md` §B6b） |
| B7 | rx 预注册 | `<issue>-rx.json`：终版票+待裁刀+可证伪预测（含奖金模型分支检验）；落盘后 `uv run nutmeg workflow register-rx --rx-file <issue>-rx.json --issue <issue>`（幂等，裁决后重跑补录已决 ADJ）。**B6b 驳回预测已自动并入本文件**，此处只补票面级与奖金模型分支 |
| B8 | 18:30 位移复核 | prep 链自动 diff；牌照线（体彩vs国际反向≥3pp→撤单选）、分歧场归属。**只核对新事实是否已被价格吸收；临场事实只许加面（双选→全包/裸单→双选），换被排面须首发/停赛级事实并注明未被价格吸收；深研 agent 的"最薄面"结论只作 note**（RULEBOOK 已定价≠可反转 / 临场只加面，probation） |
| B9 | **部署门**+出票+入账 | **刹车状态（2026-09-30 起）**：连续两期全灭后的下一期默认 `plan frontier --cap 200 --cap-source brake`（复式 ≤¥200、两票 ≤¥800、同日竞彩 ≤¥200）；26135 已由 Jun 事前登记减半（scoreboard `adjudications/brake_26135_precommit`），全额须 `--user-override` 另立裁决。**`plan commit --cap-source baseline\|override --adjudication …`（override 必带裁决；日帽扣竞彩已登记）；`plan status` 对账**。所有候选逐行跑 audit、预算与部署算术；ERROR/over-cap 影响 eligible 分区，回本线门槛只显示历史可比报告，**不排序、不阻断、不自动建议空仓**。减注、丢场或空仓只由 Jun 显式裁决；正常路径仍以选择并出票为主。 **空仓前必须并排打印两个数字（2026-09-18 起）**：全合法空间帽内 max P(全对) 与所选票面的 P——空仓是对着一个数字做的选择，不是从空集里退出来（prereg-26129-F4 每期记账）。Telegram 二段确认链 2026-10-01 退役——真票下单后 `betslip register` 入账（**没入账=没打**）；同时落 `<issue>-final-tickets.json` 结构化票面；身份映射只认 `<issue>-channel-map(.auto).json`（af-map 2026-10-01 退役）。**月度止损**（宪法 §4）：`betslip preview/register` 与 `plan frontier` 每次打印本月净值 vs −¥3,000；触发即空仓到月底 |
| B9c | **实票登记** | **买前先看（2026-09-30）**：`uv run nutmeg betslip preview --channel … --legs-file …`（足彩 `--faces "…" --issue <期>`）——同一张票的注数/P、与同日/同期/跨渠道实购票的共享裸单及联合同死概率、对照处方的收窄与翻面，不写盘。登记后同一份诊断写进票面 `diagnosis`。页面：`uv run nutmeg decision-web` → <http://127.0.0.1:8787/betslips>（任九/胜负彩；列表带方案号缺失告警）。CLI：`uv run nutmeg betslip register --slip-id <期-票号> --channel renjiu\|shengfucai\|jczq --placed-at … --faces "<整行或点名式>" --fair-file … --multiplier N --scheme-no <方案号> [--trial]`；竞彩用 `--legs-file` + `--combo 4` / `--combo 2,3`。**方案号缺失会在摘要里喊**——没入账=没打，账空则刹车条款失去输入。**历史回放**：`uv run nutmeg gym run --policy zucai_max_p,zucai_fav_single,zucai_prescription,real` 看同一结构规则在 42 期上的账（官方当期奖金结算；验收门 `nutmeg gym verify` 须复现记分牌净额） |
| B9b | 晨间夜账校准（多夜期次每夜一次） | `uv run nutmeg zucai-night-calibrate --issue <issue> --date <竞彩板面日>`（赛果 = `jczq/jc-results.json[板面日]`，90' 口径；身份链 = 足彩场号 →`<issue>-channel-map(.auto).json`→ 内核 match_id →`jczq/daily/<日>/jczq-legs-base.json`→ 竞彩编号，见 RULEBOOK g-scope）；需推送时显式加 `--dispatch-telegram --no-dry-run`；报告供主循环写 rx night 块；任一环缺映射=显式跳过，禁按队名猜测补；不在竞彩板的场次由 09:45 官方结算补 |
| B10 | 开奖结算 | `betslip settle --results-file <90'三源赛果> [--prize-per-note <官方单注>]`（竞彩按赔率连乘，足彩须给官方单注奖金）；okooo 先行 + 官方 gameNo=90 终核（含任九奖金→奖金模型记分）；ledger settle + rx outcome + scoreboard 更新（含 `tags` 组按追踪标签累计）+ retro memory；预测判定 `workflow grade-rx --rx-file <rx> --issue <issue>` 批量记账（P1..Pn 自动对号到 prediction-hex；判断在主循环，动作只记账）；**影子期双轨**：改完 scoreboard.json 跑 `nutmeg scoreboard settle-issue --scoreboard-file … --evidence-type official_draw --evidence-id <期号> --no-dry-run --acknowledge-manual-source` 一次性镜像（自动找 leaf 与 supersedes；JSON 仍权威，无镜像=违 M5），期末 `nutmeg scoreboard shadow` 对账入证据。足彩官方奖金缓存 `nutmeg gym prizes-cache`（`zucai/official-prizes.json`，含作废场与一二等奖） |

> **非决策附录 · 候选因子观察仪（不影响票面）**
> `uv run python scripts/zucai_f2_observe.py record --issue <期>`（**最早一场开球前**跑，开球后整期拒收）
> → 开奖后 `… grade --issue <期>` 累计进 `experiments/prereg-26126-F2-ledger.json`。
> 前瞻预注册见 `experiments/prereg-26126-F1c-F2.json`（26126-26137，n≥140 结账）。
> ⛔**候选档因子不得以任何形式进入判读或票面**：观察仪不写 legs、不进 prep、
> 不被 B0-B10 任何一步引用；分档常量结账前冻结。本条列在收尾表之前只为「别忘了跑」，
> **不是决策步骤**。

> **非决策附录 · RSI 实验对象（2026-09-18）**
> `uv run nutmeg rsi status` 一屏：每条实验的状态 / n_cum / CI / 距 falsifier / gaps / 下一期义务。
> 登记 `rsi register experiments/registry/<id>.json`（原件全冻结，改判据＝另立新 exp_id）；
> `rsi verdict` 由代码按冻结判据判、人不得代判；`rsi deploy` 只许人。重放（`--mode replay` / dream）结果进不了判决。
> 出生事故 → `INCIDENTS.md` §F1c
> **R0 竞彩全板覆盖率义务**：`scope=match`，每场截止各自开球；`research run` 成功即逐场 fulfill，
> 未研、预算外、开球后启动或拒收的场都保留为 gap，不以 `price_only` 冒充深研。
> **R1 并集池覆盖率义务**（2026-09-27 起）：population=both，同一条 `research run`；足彩独有场次只有 R1 义务。R0 冻结不动。

> **非决策附录 · 统一语料 v2（2026-09-18 用户裁定并入）**
> `uv run python experiments/corpus_build.py` → `experiments/corpus-v2.json`
> ＝ 足彩 `*-legs-base.json`（fair + 旗/完整度/牌照四问/先例标签，**跳过 B4 也有**）
> ＋ 竞彩日板 `daily/<date>/bold_odds.json` × `jc-results.json`（**从没下过注的场次**＝无选择偏差价格样本）。
> 去重按 titan007 match_id，其次按「同日 + fair 三元组 ≤1.5pp」。
> 消费：`uv run python scripts/zucai_loop.py <cmd> --corpus v2`（按日期切窗；`v1` 行为不变）、
> `experiments/exp-price-bands.py`、`experiments/exp-label-residuals.py`。
> ⛔**口径纪律**：价格带类检验吃全部行；**标签类检验只能吃带标签的那 70 行**；
> **F2/F3/F4 的前瞻窗与口径写死在各自 prereg 里，不得用本语料回补样本**。
> 出生事故 → `INCIDENTS.md` §语料 v2

> **非决策附录 · 追问应答器（2026-09-18）**
> 模型走**用户 Claude Code 订阅**（本机 `claude -p`，禁工具/单轮/中性 cwd，不传 `--model` 即继承当前默认模型）；没有本机 CLI 才退回 Portkey key。实测一问约 12 秒。
> `uv run nutmeg workbench-respond --date <开球日> --issue <期> [--watch]` —— 监听当日 `workbench.jsonl` 里没被回复的 `user_message`，用该场深研 JSON ＋ 内核判读作上下文调模型，把 `agent_reply` 写回线程；页面轮询即显示。
> **常驻只在「不开聊天窗口、只看页面」时才需要**：您在终端里跟主循环说话时它是冗余的——它只能解释，改不了票面。
> 空转零 token（每 15 秒只读本地 jsonl，无待答连内核都不查）；开销只跟提问次数成正比，单次上下文约 1.1 万字符（九成是那场深研 JSON）、无跨次缓存。
> `--idle-exit N` 连续空转 N 次自动退出（默认 240≈1 小时），免得忘了关空跑一夜。
> ⛔**只解释已落库的研究与判读**：不产生新面集建议、不改 belief、只引用上下文里已有的数字。回复含「建议买/应该排/改成」即**拒答留痕**（不写答案，写一条说明）。
> 判断仍在主循环：要改票面，回终端说「今天的方案」。 出生事故 → `INCIDENTS.md` §追问应答器

## 收尾检查表（每期）

- [ ] scoreboard.json 更新（连锁/牌照/保险兑现/裁决记分）——**事实部分由复盘编码器写**：竞彩随 09:45 `day.settle` 自动（`tickets/jczq-<日>` 断腿/注金/派奖、`balance_ledger/jczq-<日>` 市场/研究/终判 Brier）；足彩开奖后 `uv run nutmeg retro encode --issue <期> --prize-per-note <官方单注>`（`key`/`board`/`note` 人写字段不会被覆盖）
- [ ] rx 每条预测标 outcome（✓/✗/NA+falsifier 执行）
- [ ] 被取代的记忆条目标记/归档
- [ ] 新联赛上线三步：别名表→实体种子（name_zh 精确=leagueAbbName）→sync+audit
