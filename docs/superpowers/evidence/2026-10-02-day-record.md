# 2026-10-02 工作记录（会话收尾）

本会话从 2026-10-01 下午接续到 2026-10-02 晚。下表按主题列出成果、提交与证据；数字以证据文档、`nutmeg rsi status` 与 `.nutmeg-data/` 为准，本页只做索引。

## 1. 成果与提交

| 主题 | 做了什么 | 提交 | 证据 / 文档 |
|---|---|---|---|
| 足彩机器初稿恢复 | `nutmeg judgment draft --issue`：处方忠实（只丢场不降档）、刹车档、max-P 对照；奖金模型 log(奖金)=a+b·S，b≈1 | `7c7f994`（10-01） | `evidence/2026-10-01-design-series.md` §11 |
| 每日作战面板同步 | 当日报告 / 会话入口 / 站点 / 判决页 / 任务条对齐 10-01 定位：账房行、初判包摘要、已登记实票复核、足彩初稿 | `0a51f60`（10-01） | `docs/ARCHITECTURE.md` §2、§4 |
| 九月月底账 | 月底任务未跑，手动出账：9 月净 −4,721（投入 3,774，10 条入账） | 数据，不进 git | `.nutmeg-data/analytics/account/2026-09.md` |
| 判断 rubric r1 | 15 项类型化问题表（事实 7 / 结构 6 / 价格 2）、协议级聚合派生 tilt、强制弃权、读者 B（haiku）两读 κ、K1 登记、11 个逐项 T13 因子、闭环新增 rubric_read 步 | `c416a0a` `8a0abf9` `6b3f3c5` `472cc1a` `ebf845b` `5879747` | spec / plan / evidence `2026-10-02-rubric-judgment-contract*`；RULEBOOK「九」 |
| rubric 进其它环节 | 改判落到 rubric 项 + 封闭理由；人的偏离登记（理由 + 可证伪预测）、账房按理由结账；版本治理（SUPPORTED_VERSIONS / CHANGELOG / since·until）；source_tier 只采集不加权 | `cd220fc` `d682856` `9676521` | 同上 §5 |
| 历史重打分 | 260/260 份历史研究有读者 B 侧车，190 行进语料（标非前瞻）；公开事实项成立时所押方向比市场少中 6–11pp，只有弱方路径 +2.3（n=100）与轮换 +2.4（n=27）为正；**不改权重**，等前瞻 n≥60 | `3bbfb42` `0be4e1d` `1e02f1e` `10c0602` | 同上 §6 |
| 池子 RSI 与 Dream 体检 | 空盘日 Dream / 深研入库 / 建 Read 改为跳过；因子提案解析 rubric 因子（原 KeyError）；rubric 永不导致深研拒收；R1 按观测数显示（37 而非 0）；两读步补读前一天、并发 4 | `c1cd735` | 同上 §7 |
| 月初账房定时器 | `com.nutmeg.account.month` 每月 1 日 16:10，已装载；状态页 / 运行记录页认识月度、周度排程；偏离账跳过旧式文字条目 | `fe103b9` | `evidence/2026-10-02-ops-review.md` §1 |
| 播报换内容、F2 退役、遗留问题 | 截止播报只提醒「足彩停售前无登记实票」「竞彩预审过未登记」；F2 / F1c 退役且义务停用，观察定时器卸载删除；足彩 legs-base 自动建（不覆盖手工版）；早盘入板与 17:15 刷板空盘不报失败 | `f252000` | `evidence/2026-10-02-ops-review.md` §3–§6 |
| 架构文档 | `docs/ARCHITECTURE.md` 成为现役结构权威（v1.0），定时数据流文档重写，README / RUNBOOK / CLAUDE.md / AGENTS.md 指针同步 | `35823d3` | `docs/ARCHITECTURE.md` |
| 架构文档美化与 Word 版 | v1.1：统一配色与图例、目录、提示框、图题、术语表、版本记录，10 张图重排版；Word 版 26 页（封面、带页码目录、页眉页脚、表格样式），生成脚本可复现 | `bae76cc` | `docs/ARCHITECTURE.docx`、`scripts/build_architecture_docx.py` |

10:45 的闭环照常自动提交了实验输出（`41116f5`）。

## 2. 当前状态（2026-10-02 晚）

- **定时任务**：launchd 14 个 + OpenClaw 3 个确定性任务；今天是假期空盘日，早盘入板记为 `empty_board`，Dream 与深研链记为跳过。
- **实验**（`nutmeg rsi status`）：R0 101/200、R1 37/200、F5 148/120（已过 n_min，等判决到期）、F10 17/150 CI[+1.8,+32.5]、F3 37/120、F11 15/80；F14 / F15 / G1 / K1 / F13 尚无前瞻观测；F2、F1c 已退役。
- **账**：9 月净 −4,721；10 月从零开始，月度止损线 −3,000。

## 3. 留给 Jun 的事

| 时间 | 事项 |
|---|---|
| 每天 | 12:00 当日报告 / 12:30 判决页看初判包与足彩初稿；买票前 `betslip preview`，买后 `betslip register`（偏离初稿带理由与预测） |
| 10-09 | 内核 `operator_*` 退役专项（分支 `kernel/operator-retirement`） |
| 10-31 | Dream 常设批准到期续不续；评估器 v3 是否成为唯一规则行 |
| 样本够时 | rubric 逐项上限：前瞻 n≥60 才按结账下调；K1 到 100 项次判两读一致性；source_tier 在 K1 之后再看 |
| 可选 | F1c 如要恢复，只能用 `rsi deploy --extend` 另立新实验 |
| 可选 | 本地 main 领先 origin 202 个提交，是否推送由你决定 |
