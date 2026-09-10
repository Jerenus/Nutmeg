# Nutmeg Application 操作手册

本手册面向 Nutmeg 的唯一操作员 Jun。Application 是两条泳道的工作台：它把官方任务、
证据、逐场判断、候选票、审计、确认、账本、结算和复盘串成一条可追溯流程。它不替你研究
比赛、不替你选择比赛或投注面，也不替你确认实际出票。

日常主线是：`Today -> 证据 -> 逐场判断 -> 候选比较 -> 审计 -> 受保护票据 -> Telegram
本人确认 -> 账本 -> 三源赛果 -> 结算 -> 复盘`。正常流程以选择合规票面并推进为主；
“不出票”是由你明确行权的次级入口，系统不会因为赔率、奖金倍数或模型输出自动建议空仓。

本文中的 `<...>` 是需要由当前任务、外部采集流程或受控诊断回执提供的值，不要把尖括号本身
输入命令，也不要猜测内部 ID 或复用旧 token。命令都从仓库根目录
`/Users/jz71/Projects/Nutmeg` 执行。

## 1. 启动与地址

日常生产实例的启动命令固定为：

```bash
uv run nutmeg app --host 127.0.0.1 --port 8788
```

该命令使用配置中的生产数据目录和已批准运行模式。服务基址是
`http://127.0.0.1:8788`，具体工作台路径按下表选择；不要依赖旧会话留下的随机端口。需要
验证服务是否仍在运行时，执行：

```bash
curl -fsS http://127.0.0.1:8788/api/v1/system/health >/dev/null
```

退出码为 0 表示本机服务可访问；该检查不修改任何业务数据。终端必须保持运行，关闭终端或
按 `Ctrl-C` 会停止服务。

启动后的页面取决于已经由 Jun 批准并写入运行配置的模式：

| 运行状态 | 应打开的地址 | 可做什么 |
| --- | --- | --- |
| 生产 `legacy_read_only` | `/` | 查看旧工作台；`/operator-next` 不开放 |
| 生产 `shadow` | `/operator-next` | 查看新工作台的生产投影；所有浏览器写操作关闭 |
| 隔离验收 `active` | `/operator-next` | 在独立数据目录演练；确认请求使用进程内模拟传输，不会发送真实 Telegram |
| 生产 `active` | `/`，会进入新工作台 | 仅在 Jun 已接受精确提交后使用允许的操作 |

手册不提供改变生产模式或接受提交的命令。这些都是 Jun 的上线行权门，不是应用内按钮。
所有模式都要求本体已经初始化、完整性检查为 `ok` 且没有待执行迁移。任何 `active` 模式都要求
至少 32 字节的独立签名密钥；生产 `active` 还要求工作树干净，并且 accepted、candidate、
running 三个完整 40 位提交精确相同。

已经由工程验收流程配置为隔离 `active` 时，启动命令还必须显式给出一个**绝对**且已经准备好
本体的独立数据目录：

```bash
uv run nutmeg app --host 127.0.0.1 --port <acceptance-port> \
  --data-dir </absolute/path/to/prepared-isolated-data>
```

省略 `--data-dir`、使用相对路径、指向生产目录、继承真实 Telegram token 或启用调度器都会
使隔离实例拒绝启动。隔离实例可在 Application 内演练模拟确认请求，截止扫描也会自动形成
shadow；由于没有真实 owner 接收按钮，placed callback 及 callback/超时竞态只能由受控验收
夹具驱动，不能把模拟发送当作真实出票。

`legacy_read_only` 和 `shadow` 是浏览器表面只读，不表示进程绝对不写。两种模式仍运行确认
截止扫描，并可按到期事实追加 shadow 终态；证据冻结、市场基线、候选、结算和复盘完成 worker
保持暂停，直到经过行权门恢复 `active`。

若启动提示 `app_instance_conflict`，先使用已经运行实例的地址。不要删除锁文件；只有确认原
进程应当停止后，才在原终端正常停止并重新启动。一个数据目录同一时刻只运行一个
Application。

## 2. Today、胜负彩与竞彩导航

顶栏只有三个日常入口：

- **Today**：回答“现在什么需要我处理”。第一行是当前主动作，其余行按明确的流程优先级、
  截止时刻和稳定业务键排列，不按赔率、概率、收益或叙事排序。
- **胜负彩**：按期号查看当前在售期、下一期预售和历史期次。一个期次固定包含官方 14 场。
- **竞彩**：按上海业务日查看当前销售波次、后续新增波次和历史日期；每场保留自己的截止
  时刻。

从 Today 行进入任务后，先看“当前流程”，再进入其唯一可执行工作项。任务页的“比赛与证据”
用于核对比赛、赛事、开赛时间、销售截止和证据完成数。历史记录在泳道页单独显示，不会在有
当前任务时抢占焦点。

Today 只显示需要人工动作或外部恢复的事项。单纯等待赛果、等待后台已排队工作以及已完成的
任务不会长期占据 Today；但历史任务一旦产生待处理复盘，会重新回到 Today。若 Today 为空，
到两个泳道的历史记录核对等待赛果、结算或已完成状态，不要据此推断“今天官方无票”。

“运行状态”是轻量维护入口，只读显示调度归属、Telegram 确认处理和传输状态。它不是日常
决策入口，也不会启停或修复调度任务。

## 3. 官方赛程与证据的外部采集

新工作台不负责采集外部网站、不自主研究，也不把昨天的文件当作今天的任务。官方赛程、市场
和证据必须先由外部主循环采集，再通过严格版本化入口写入本体。

现有准备命令仍可产生采集与确定性算术底稿：

```bash
uv run nutmeg decision-am \
  --run-date <YYYY-MM-DD> \
  --output-dir .nutmeg-data/jczq

uv run nutmeg zucai-prep \
  --run-date <YYYY-MM-DD> \
  --slot afternoon \
  --zucai-dir .nutmeg-data/zucai \
  --output-dir .nutmeg-data/jczq
```

当前 ontology v2 模式下，`decision-am` 的正常业务输出是 fetch 与 Match/Snapshot 入库结果；
带 `--issue` 时还会输出足彩 snapshot 入库及 actions 表对账结果，不包含独立的别名审计步骤。
`zucai-prep` 的正常业务输出是“有期则生成备料/brief 路径，无期则给出明确心跳”。二者只产
事实和算术，不做判读。它们也不等于新工作台已经收到官方任务；外部流程还必须生成严格清单
并调用以下入口。

有官方销售任务时，先逐个导入官方销售清单，再登记当天赛程检查：

```bash
uv run nutmeg workflow ingest-official-sale \
  --manifest <official-sale-slate.json> \
  --contract-version official-sale-slate-v1 \
  --data-dir .nutmeg-data

uv run nutmeg workflow record-official-schedule-check \
  --manifest <official-schedule-check.json> \
  --contract-version official-schedule-check-v1 \
  --data-dir .nutmeg-data
```

销售导入成功时，业务输出必须同时说明 `committed`、泳道、业务日或期号、版本号，以及
slate revision、offer family、offer revision 的 `created_counts`、`committed_counts` 和
`persisted_counts`。`committed_counts` 与 `persisted_counts` 必须逐项相等；修订沿用已有 offer
family 时，对应 `created_counts` 可以为 0，不能把这种正常复用误报为失败。赛程检查成功时，
业务输出必须为 `committed`，说明泳道、上海检查日期、清单中的实际 `check_state`，并且
`persisted_receipt_count=1`；只有已经导入 slate 的检查才应为 `slate_imported`。

若官方明确没有销售任务，仍要导入 `confirmed_no_sale` 检查清单。若采集失败，则导入带封闭
错误码的 `failed` 检查清单；Today 会显示泳道级恢复项。绝不能把“采集失败”记录成“官方无
销售”。

外部主循环完成逐场研究和来源留痕后，导入严格证据清单：

```bash
uv run nutmeg workflow ingest-evidence \
  --manifest <evidence-intake.json> \
  --data-dir .nutmeg-data
```

成功业务输出必须为 `committed`，并显示正确泳道、业务键，以及相等的 `committed_count` 与
`persisted_count`。入口检测到任何 rejected 或 skipped 时会以非零退出码失败，不会输出成功
回执；对应要求仍未完成。重新打开任务，按 E1 到 E6b 和 EC 查看缺少、过期或冲突的具体比赛。

证据门的业务含义如下：E1 是规范比赛/球队身份，E2 是当前官方赛程与销售范围，E3 是体彩
市场，E4 是至少一个身份已解析的国际市场，E5 是双方可用性，E6a 是权威赛果支持的近期表现，
E6b 是阵型/磨合/阵容实质变化，EC 是冲突已清偿。空搜索、来源故障和过期缓存都不是“无异常”
证据。okooo 只走人工来源留痕，不绕过 WAF。

## 4. 证据冻结与逐场结构化判断

证据齐全后，在任务中按以下顺序操作：

1. 核对每场证据完成数和截止时刻，点击“冻结当前证据并继续”。页面先记录你的冻结请求，
   后台确定性 worker 再生成不可变证据版本。
2. 证据冻结后，填写有限表达空间：玩法、允许的面组合、可否丢场、串关或分组模板、资金帽、
   最多票数和穷举上限。这里声明“允许比较什么”，不是让软件选什么。
3. 逐场填写市场先验之上的最终概率、影响因子与逐面偏移、表达面、命名规则、证伪条件和简短
   理由。非零偏移必须有命名因子和已冻结证据引用；零偏移可以是合法的人类判断。
4. 同一表单里登记两项结构事实。这两项不是描述，是审计的输入：
   - **锚方结构完整度**（完整 / 有洞 / 对称受损 / 未判）。选“有洞”后再裸单，审计给 ERROR
     直接挡住批准（C5，26102 本菲卡）；有洞还用双选把一面判死，给 WARN（C13，26118 场8）。
   - **被排面先例**：逐面填同场地同型先例和载体状态（载体已不在 / 载体仍在）。被排面上留着
     **活**先例要“先例+钱流”双证（C7）；被排面 fair 高于 20% 而没有“锚方完整 + 该面先例记
     dead”，审计判为昂贵排除并要求你逐条裁决（C14）。没有先例就留空。
   四个选项没有默认值，软件不替你猜；不填不是“没问题”，而是“没登记”，昂贵排除照样亮 WARN。
5. 每次点击“提交本场并继续”。页面只以已提交 Action 和本体行计算进度，不以浏览器提示或
   生成报告计数。
6. 全部必需比赛提交后，点击“冻结处方并比较票面”。这会绑定当前每场判断；后续证据或官方
   版本变化不会改写旧处方，只会使依赖项失效并要求重新确认。

若冻结后出现新证据，页面会显示“有新证据可用”。由你决定保留已绑定版本，或重新冻结并
重开受影响判断。软件和 AI 都不能把研究草稿直接提升为正式判断；最终提交角色始终是
`judge_operator`。

## 5. 候选比较、审计、行权边界与不出票

冻结处方后，点击生成候选。系统只穷举你已经声明的有限票面空间；超出上限时要求你收窄
空间，不会暗中裁剪。候选表必须保留三类行：`eligible`、`audit_blocked` 和 `over_cap`。

比较时重点核对：单/双/全包与丢场、串关或任九分组、票数和注数、票价与资金使用率、精确
联合命中概率、期望断腿、共同死面、相对处方的每处偏离，以及每条审计结果。合规候选按
`P(全对)` 或“至少一票全对”的精确概率降序；同概率才按低票价和稳定内容顺序破平局。首行
不是推荐项，也不会被默认选择。回本线和历史中位奖金倍数只作报告，不排序、不阻断、不触发
空仓。

由你选中一个候选并填写采用理由。所有处方偏离都必须引用命名规则 ID。进入审计后：

- PASS 可以继续创建受保护票据；
- WARN 必须在页面逐条勾选并填写裁决理由；
- ERROR 保持硬阻断，普通任务页面不能覆盖。优先返回修改表达空间、判断或候选。

若 Jun 明确行使 ERROR 裁决权，从当前工作项的“技术审计”页取得完整当前批次 token。普通任务
页和 API 任务 DTO 不导出该 token，Application 也没有 Web override 控件。下面的命令只能由
Jun 在外部终端显式执行：

```bash
uv run nutmeg decision-audit-legs \
  --legs-file <current-legs.json> \
  --user-override \
  --ticket-batch-token <current-opaque-ticket-batch-token> \
  --data-dir .nutmeg-data
```

legs JSON 还必须为每个 ERROR 提供 `user_override=true`、非空理由和已登记规则 ID。成功业务
输出必须保留原 ERROR，并明确显示 `ERROR -> Adjudication` 的相等计数；失败或缺少当前 token
时退出码为 1，且不能推进。成功 Action 会自动排队新的候选生成请求；返回 Application 后刷新
并等待后台生成完成，再重新选择新候选，不需要再次点击“生成完整候选集”。这个通道只属于
Jun；Web、AI 和无人值守流程都不能调用。

legs 文件仍是受控审计交接材料，不从页面 JSON 中寻找。批次 token 只在当前工作项的显式技术
审计页显示；若没有同时取得当前 legs 文件和该页签发的完整 token，停止 override。不能手填
内部 ID、复用旧 token 或绕过页面状态。

正常主动作是“创建受保护票据”并继续确认。“明确不出票”位于次级折叠入口，只有你判断当前
范围确实不应部署时使用；“全是骰子”也必须是你的明确判断，程序不能推断。选择封闭理由、
依据类型和说明后，剩余销售范围会被记录为不出票，结算显示 `not_applicable` 且不写资金账。
只在有效截止前，你才可以明确重开仍开放范围；系统不会自动反悔或用事后结果重建反事实票。

## 6. Telegram 实际出票确认与超时 shadow

候选通过审计后，Application 中依次执行“创建受保护票据”“记录 WARN 裁决”（若有）和“审批
受保护票据”，最后点击“发送 Telegram 确认”。Application 的第一段确认只是**请求确认**：
它锁定票面、金额和截止时刻，核对唯一 OpenClaw callback owner 的新鲜 heartbeat，再由
Application 的 Telegram transport 发送 owner-only 按钮；此时没有正式 Ticket，也没有资金账。
生产请求还要求 bot token、恰好一个允许的 chat 和无时钟偏移的有效 owner heartbeat。

日常操作只使用 Application 的“发送 Telegram 确认”。下面的 CLI 仅供工程验收或受控诊断，
其中 artifact ID 必须由当前审批回执或验收夹具提供，Application 页面不会展示这个内部 ID。
不要对任何计划真实出票的生产 artifact 运行这条 dry-run：

```bash
uv run nutmeg ticket-confirmation request \
  --ticket-artifact-id <approved-ticket-artifact-id> \
  --data-dir .nutmeg-data \
  --dry-run
```

即使使用 `--dry-run`，这个 CLI 仍要求生产确认通道已经配置 Telegram token 和允许的 owner；
它不是隔离 Application 的模拟 transport 入口。dry-run 会真实写入一个会过期的 confirmation
challenge，只跳过 Telegram 发送，并非数据库只读；同一 v2 artifact 的后续请求只会复用
已有 challenge，不能靠把参数改成 `--no-dry-run` 再补发。正常输出应显示挑战有效期和
`dispatch_state=dry_run`，但不声称已出票。若只配置一个 owner，可省略 `--chat-id`。

Telegram 按钮的含义是“本人确认已经实际出票”。只有 Jun 在外部完成实际票据操作并核对
票面、金额后，才点击 owner 按钮。OpenClaw 的唯一 callback owner 会原子地消费挑战、创建
Ticket、写实际出票凭据和 stake ledger；任何一步失败都不应留下半张票或半笔账。网页和 AI
没有最终确认接口。

新工作台 challenge 的有效期直接取审批时冻结截止与所有当前销售截止中的更早者，不是固定
五分钟；官方新版本还可以缩短或取消。到达当前有效截止仍未确认时，系统自动记录 shadow，
不写 Ticket 和 stake ledger，也没有“先过期再重发”的日常步骤。多票批次逐个确认：已确认票
正常入账，未确认票单独 shadow。

判断是否实际出票只看账本：**没有 ledger 行就是没有出票**。Telegram 消息已发送、按钮曾
显示、Application 显示等待中或人工口头确认，都不能替代账本。

## 7. 账本、三源赛果、结算与更正

Telegram 本人确认成功后，任务页应显示正式出票金额和账本状态。先核对 Ticket 总额、各注
金额和 stake ledger 一致；若显示 `placement_ledger_integrity`，停止结算，按第 9 节恢复，
不能用浏览器补一笔“看起来正确”的账。

赛后由外部流程采集每场 90 分钟口径的三源结果：API-Football `score.fulltime`、体彩官方
`gameNo=90`、okooo 人工来源留痕。清单必须为每场保留恰好三个来源槽；缺失来源可以明确记为
`missing` 并进入等待，但不能省略该来源。形成 Outcome 前，三源必须满足一致性规则；加时和
点球不替代 90 分钟比分。胜负彩可先导入赛果并等待奖金，但正式结算前还必须导入官方奖金表。
导入命令为：

```bash
uv run nutmeg workflow ingest-results \
  --manifest <result-evidence.json> \
  --data-dir .nutmeg-data
```

成功业务输出应显示业务键、`committed`、逐状态 agreement 计数、创建的 Outcome 数，以及
竞彩 `not_applicable` 或胜负彩 `available/waiting` 的奖金状态。结果缺源时保留为 waiting；
三源分歧或格式无效时不创建该场 Outcome；延期保持 pending；只有 agreement 为 `agreed` 的
`played_90`，或满足官方 void 一致性规则的 `official_void`，才能结算。

结果与奖金就绪后，在 Application 点击“开始结算”。页面先显示排队，后台确定性 worker 再
按不可变票面逐腿、逐注、逐票结算。完成后核对：

- 竞彩每腿使用自己的 Outcome、已锁定赔率和让球线，显示命中/未中/退回及逐注返奖；
- 胜负彩一等奖精确 14 场、二等奖精确 13 场，任九精确 9 场，使用官方每注奖金；
- 总投入等于 placement ledger，总返奖等于新写入的 payout ledger；
- 不出票、自然过期或官方取消且没有实际票时显示无需结算，不产生虚构资金流水。

`decision-settle` 仍是现行 RUNBOOK 的传统日循环命令，但它不能替代新工作台中“严格三源清单
导入 + 任务绑定的结算请求”。不要同时用两条路径为同一张新工作台 Ticket 手工补账。

结果或奖金后来被权威来源更正时，生成带直接前版 supersedes 引用的新
`result-evidence-v1` 清单，再运行同一 `workflow ingest-results` 命令并在页面重新点击“开始
结算”。
更正会追加新结算版本：先冲销直接前版仍有效的正返奖，再写替代返奖；它不会删旧结算、改旧
流水、重复扣本金或逆向修改历史 Outcome。

## 8. 复盘、外部 scoreboard.json 更新、observe、shadow 与完成

结算或零出票终态会生成复盘项。复盘页把“判断事实”“资金账”“干预质量”分开显示；不要用
一项的好坏代替另一项。预测的 hit/miss/na 由你根据权威赛果判断，Application 只登记 typed
Action。必要时也可使用同一记账命令：

```bash
uv run nutmeg workflow grade-prediction \
  --prediction-id <prediction-id> \
  --outcome <outcome> \
  --reason "<Jun 的判定依据>" \
  --data-dir .nutmeg-data
```

`<outcome>` 必须精确替换为 `hit`、`miss` 或 `na` 之一；成功输出为
`<prediction-id>: committed`。

多夜胜负彩的夜间报告使用：

```bash
uv run nutmeg zucai-night-calibrate \
  --issue <issue> \
  --date <European-match-date>
```

正常业务输出是 90 分钟彩果和现有票面存活报告，同时在默认足彩目录写入
`<issue>-night-<date>-af.json` 事实快照；它不写 rx，也不写 `scoreboard.json`。

处理记分牌影响时，先由你在复盘页明确选择：

- `no_effect`：填写理由且不选指标；该人工 Action 可直接完成此复盘。
- `effect_required`：选择精确指标并填写理由；随后必须完成外部权威更新、对应观察和 shadow
  对账，Application 不能替你选择指标或跳过任一门。

影子期 `.nutmeg-data/scoreboard.json` 仍是唯一权威。`effect_required` 的严格顺序是：

1. 在 Application 外，由 Jun 按现行治理流程更新 `scoreboard.json`；先后哈希必须能证明只有
   这一步改变了文件。
2. 为每个必需指标记录一条对应观察。日常路径是在复盘页使用绑定当前复盘的入口。下面的 CLI
   是通用治理观察入口，适合外部治理步骤或诊断；它提交成功本身不证明当前复盘已经建立绑定：

```bash
uv run nutmeg scoreboard observe \
  --data-dir .nutmeg-data \
  --group-key <group-key> \
  --metric-key <metric-key> \
  --tally "<human-reviewed-tally>" \
  --detail "<business-detail>" \
  --status <status> \
  --evidence-type <ontology-object-type> \
  --evidence-id <ontology-object-id> \
  --effective-at <ISO-8601-with-timezone> \
  --requested-at <ISO-8601-with-timezone> \
  --acknowledge-manual-source
```

按指标需要补 `--numerator/--denominator` 或 `--value/--unit`；修订现有观察时还必须用
`--supersedes <current-observation-id>`。成功业务输出是一个 `committed` 的
`record_scoreboard_observation`。随后回到复盘页，确认每个必需指标恰好链接一次；未显示绑定的
全局观察不能越过完成门。

3. 每当页面显示 `projection_stale`，执行 build-only 重建，再刷新页面：

```bash
uv run nutmeg scoreboard rebuild-projection \
  --data-dir .nutmeg-data \
  --as-of <ISO-8601-with-timezone> \
  --built-at <ISO-8601-with-timezone>
```

正常业务输出是 `succeeded`、`projection_version=sb-v1`、新的 source high-water 和各投影计数。
该命令不写 `scoreboard.json`，也不执行 cutover。任何后续业务 Action 都会再次使投影过期。

4. 用重建输出的精确版本和 high-water 运行 shadow：

```bash
uv run nutmeg scoreboard shadow \
  --data-dir .nutmeg-data \
  --legacy-file .nutmeg-data/scoreboard.json \
  --classification-file <complete-classification.json> \
  --projection-version sb-v1 \
  --source-high-watermark <current-source-high-watermark> \
  --requested-at <ISO-8601-with-timezone> \
  --acknowledge-manual-source
```

正常 CLI 输出是 `status=committed`、`action_type=record_scoreboard_shadow_review` 及其结果引用；
成功提交本身不代表零 unexplained，输出也不直接列出该计数。回到 Application 或查询已存
review，确认当前复盘涉及的指标为零 unexplained。shadow 本身会推进 Action high-water，因此
页面若再次显示 stale，先重建并从新 GET 取得当前表单。

5. 回到复盘页，明确选择刚刚核对的**精确 shadow 记录**并请求完成。系统不会自动选择“最新
一个”。完成回执必须绑定同一复盘、同一 JSON 哈希、全部 observation、该 shadow 的精确
high-water 和零相关 unexplained；后台回执出现后，复盘才转为 complete。

Application 永不改写 `scoreboard.json`，也没有 scoreboard cutover 按钮。

## 9. 常见页面状态与恢复码

第一列是 Application 页面与接口共同使用的稳定恢复码。看到这些信息时不要重复点击。先按表
处理根因，再从 Today 或当前任务重新 GET；旧页面中的不透明表单状态不会因重建或重试自动
变成当前版本。

| 页面状态/恢复码 | 阻止什么 | 修复责任与动作 | 重新检查 |
| --- | --- | --- | --- |
| `official_schedule_missing` | 该泳道没有当天官方检查或任务 | 外部采集者导入官方 slate，并登记 `slate_imported`；确实无售时登记 `confirmed_no_sale` | 导入后刷新 Today |
| `identity_unresolved` | 证据冻结及后续判断 | 外部身份治理解析 Match/Team 与全部来源别名；禁止按队名字面猜测 | 新身份/清单提交后重开任务 |
| `evidence_missing` | 整个任务的证据冻结 | 外部主循环补齐页面列出的比赛和 E 项，再运行 `workflow ingest-evidence` | 导入成功后刷新 |
| `evidence_stale` | 旧事实不能覆盖当前截止 | 重新采集有效期覆盖截止的来源并导入新证据 | 新证据提交后重新冻结 |
| `evidence_conflict` | 冲突比赛使全任务冻结失败 | Jun 通过正式 Claim 裁决/撤回路径清偿 EC；不能删除冲突行 | 裁决提交后重新评估 |
| `source_contract_invalid` | 非法清单被隔离，进度不前进 | 外部采集者修正版本、字段、引用或来源回执后整包重投 | CLI 返回 committed 且计数相等后刷新 |
| `task_snapshot_changed` | 旧表单不能写当前任务 | 返回 Today/任务重新加载；复核官方新增、截止缩短或依赖版本变化后再提交 | 必须使用新页面签发的状态 |
| `audit_error` | 候选不能审批 | 修改判断、表达空间或候选；Jun 明确行权时从技术审计页取得当前 token，并在外部终端实名裁决 | 新候选审计或外部裁决提交后再推进 |
| `confirmation_expired` | 旧 Telegram 按钮不能入账 | 接受截止扫描形成的 shadow；不要重放旧 callback | 截止扫描完成后刷新 |
| `telegram_update_owner_conflict` | 真实确认请求/回调被阻断 | Jun 在 Application 外恢复唯一 OpenClaw update owner；维护页只读，不启停任务 | owner heartbeat 和传输均恢复后刷新 |
| `telegram_owner_missing` | 不能发起真实确认 | 在 Application 外恢复已登记的唯一 OpenClaw owner | 维护页显示 owner 后刷新 |
| `telegram_owner_heartbeat_expired` | 不能发起新的真实确认 | 恢复 OpenClaw owner 心跳；在途 callback 与截止扫描仍按既有状态处理 | heartbeat 恢复后刷新 |
| `telegram_owner_clock_skew` | owner 时间证据不可信 | 校准本机/OpenClaw 时间并重新取得 heartbeat | 无时钟偏移后刷新 |
| `placement_ledger_integrity` | Ticket、账本或结算不可信 | 工程维护者从 Action、Ticket、note 和 cash link 对账；禁止浏览器补票/补账 | 完成受控修复并重新查询 |
| `result_source_missing` | 相关比赛不能形成 Outcome/结算 | 外部采集者补 API-Football、gameNo=90、okooo 三源缺项并导入新 revision | 三源到齐后刷新 |
| `result_pending` | 延期比赛暂不结算 | 等待补赛或官方 void，再采集满足一致性规则的新 revision | 新官方状态发布后重投 |
| `result_source_conflict` | 分歧比赛及依赖票暂停结算 | 核对 90 分钟口径和身份，提交直接 supersede 的更正清单；禁止投票猜结果 | 新三源 agreed revision 后刷新 |
| `projection_stale` | 记分牌 disposition/observe/完成控制不可用 | 运行 `scoreboard rebuild-projection`；它只重建投影 | 重建后必须重新打开页面 |
| `scoreboard_authority_unavailable` | 不能登记记分牌影响 | 恢复可读的外部 `scoreboard.json` 权威文件；Application 不代写 | 权威文件可核验后刷新 |
| `app_instance_conflict` | 第二个 Application 无法启动 | 使用现有实例；若确需重启，在原终端正常停止，禁止删锁 | 原实例释放后重新启动 |
| `diagnostic_unavailable` | 无法判断调度/Telegram 归属 | 在外部核对 OpenClaw 与 launchd 可读状态；不能把诊断失败解释为“无人占用” | 诊断命令恢复后重开维护页 |
| `ontology_maintenance_conflict` | 迁移/独占维护不能与写入并发 | 等当前 Action 或 Application writer 完成；禁止强删锁或复制 WAL 主文件代替协调 | 安静窗口重新执行原维护步骤 |
| `projection_unavailable` | 尚无可用记分牌投影 | 运行同一 build-only `scoreboard rebuild-projection` | 成功后重新 GET |
| `command_unavailable` | 当前模式或部署未安装该动作 | 返回 Today，核对当前是否只读及服务是否为已验收构建；不要猜 API | 正确实例/模式就绪后重开页面 |

未预期故障只记录页面给出的 correlation ID，并保留业务日/期号和当前步骤交给工程排查；不要
粘贴秘密、原始来源 payload 或不透明 token。

## 10. 只读回滚与权限边界

生产回滚只把界面恢复为 `legacy_read_only` 并重启同一个、向前兼容的程序。它不执行 down
migration、不恢复旧数据库、不删除或改写 Actions、不冲销账本，也不启动旧提交。回滚后禁止
新的浏览器判断、候选、审批和确认请求，但已经发出的挑战仍由既有 OpenClaw callback owner
处理并可形成 placed；Application 的截止扫描只负责把到期未确认的在途 artifact 收敛为
shadow。证据冻结、市场基线、候选、结算和复盘完成队列保持 durable queued，回到已批准的
`active` 后才继续消费。

权限边界固定如下：

| 主体 | 可以做 | 绝不能做 |
| --- | --- | --- |
| Jun / `judge_operator` | 冻结请求、逐场判断、选择候选、WARN 裁决、受控回放中的显式 ERROR 行权、不出票、结算请求、预测判定、记分牌影响与完成选择 | 绕过 typed Action 直接改本体；让系统代替本人确认实际出票 |
| 确定性 worker | 结构校验、算术、生成候选、消费已授权请求、结算、创建完成回执 | 研究比赛、解释规则、选择面、选择候选、选择 no-ticket 或 shadow 记录 |
| 外部采集主循环 | 取得官方赛程、证据和三源结果，生成严格清单 | 把来源失败当作无事发生；绕过 WAF；伪造规范身份 |
| OpenClaw Telegram owner | 维持唯一 inbound owner heartbeat、验证 callback、在 Jun 确认后原子写 Ticket 与 ledger | 发送出站按钮；把 AI 消息、网页点击或定时规则当作实际出票确认 |
| Application GET/维护页 | 展示业务状态；用固定、受限且 `shell=False` 的只读探针检查调度与 Telegram 健康 | 接受用户 shell 文本、运行决策 CLI、启停或编辑 launchd、改调度、写 `scoreboard.json` |
| AI | 提供带来源的草稿，供 Jun 修改和判断 | 提交 Forecast、裁决、选票、批准、grade、确认出票、cutover 或 ReleaseApproval |

以下事项始终不属于日常 Application 流程：生产 `active` 接受提交、`scoreboard cutover`、soak
录入、ReleaseApproval、launchd 启用/停用/编辑、真实 Telegram owner 配置变更和任何自动
下注。维护页发现冲突时只报告，不替 Jun 行权。

最后用三个事实判断闭环是否完成：当前页面显示任务业务键正确；正式出票必有对应 ledger；复盘
complete 必有精确绑定的完成回执。页面提示、CLI 服务返回数或聊天结论都不能代替本体中的已
提交记录。
