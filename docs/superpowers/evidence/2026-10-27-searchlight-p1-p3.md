# 2026-10-27 「AI 探照灯」P1–P3 落地（研究引用制 · 覆盖门 · 反证矩阵）

来源：Jun 发来一段「AI 是探照灯不是预言家」的视频提纲，问三件事——有没有值得参考的设计、
现有结构是否合理、市面有没有同类。对照与调研页：https://claude.ai/artifact/RvaNropyBL6ibgpcpWgPow 。
Jun 定：**P1–P3 按序开工，P4（采访拆命题）保持「缓」**。宪法里「研究层消费者＝读包的人」那句口径
调整 Jun 未答，本次**没有**写进 CONSTITUTION §1，只在 §5 加了数据纪律一行。

## 对照结论（摘要）

- 视频定位＝r3 退役后 Nutmeg 的实际位置（belief＝市场、研究不拨概率、人读包出票）。
- 仓里更远：每条线索（F16 赛程负荷 / 近期状态 / PM 资金 / F19）都回放过 403 天并过噪音地板；
  预登记单次结账；证据时间系统盖章；两读 κ。
- 缺四样：来源可复核（10-27 抽查 112 份研究只 6 份含 http）、停止规则（运行器只有 24/36 轮 + 900 s）、
  读包时的反证工序、采访→可验证命题。
- 市场无同类：商业产品只有预测器与去水价差工具；2026 三篇 arXiv（2607.17765 / 2608.04008 /
  2609.12495）一致：LLM 直接预测不胜市场、卷宗越厚越差、加批评者/元代理层不增益 → 反证工序落在
  人读的矩阵，不加 LLM 层。

## 做了什么

### P1 研究引用制 + 检索遥测（`nutmeg/decision/research_sources.py` 新）

- 契约（`research_prompt.RESEARCH_JSON_CONTRACT` / `rubric_contract()` / 分析员定义）：所有
  `source`/`evidence` 写 **完整 URL ＋ 原句 ≤40 字**（`URL ｜ 原句`）；新增顶层 `sources_consulted[]`
  （实际打开过的页）。
- `extract_urls` 一处实现（接受 `https://…` 与研究员惯写的 `sohu.com/a/123` 裸形；纯域名不算）；
  `evidence_sources(research)` 汇总 rubric 必带来源项 / events / premise_corrections / sources_consulted。
- 回抓 `probe_sources`：HEAD（403/405 再 GET 不读正文），任何失败只记录；`research run` 落盘前
  调用（`--no-probe` 关；测试与离线传 None）。结果写原件 `evidence_sources.probe / probe_ok`。
- 入库桥三个**只警告**的码：`source_url_missing` / `event_source_no_url` / `sources_consulted_missing`；
  腿上转录 `evidence_sources` 与 `coverage`。
- 遥测：`claude -p --output-format json` 的 `num_turns` 进 `TELEMETRY_KEYS`（json 输出没有工具调用
  明细，轮数是「搜了几次」的最近代理）；research-run 行加 `urls_cited / sites_cited / probe_ok /
  converged / stop_reason`；日投影 `telemetry.sources`；`rsi loop` 日报「研究成本」行报
  「带 URL n/m、收敛 k/m、均 N 轮」。**P1 验收线：带 URL ≥90%，连续 3 个研究日。**

### P2 覆盖门（`research_coverage`，只算不拦）

- 三条：①事实层 7 题全部作答（弃权也算；数归一前研究员真正写了的项）②研究员声明搜过反例
  `stop_rule.counter_searched` + `counter_note` 非空 + `falsifier` 成句 ③≥3 URL 且 ≥2 站点。
- `stop_reason` 取研究员声明（coverage / budget / dead_end），未声明＝`undeclared`；撞过轮数上限再说
  「按覆盖停的」改记 `budget`。
- 契约与分析员定义写明「三条齐了立即停、输出 JSON」。轮数上限 24/36 不变（它是兜底，不再是唯一门）。
- 分析包：§1 场号角标 ◇、胆表「研究收敛」列、§5 记「未收敛场许可胆 开/总」；**只展示不拦截**
  （规则瘦身：没有正向实证的规则不拦）。

### P3 反证矩阵 ACH-lite（`nutmeg/decision/counter_matrix.py` 新，`judgment counter-matrix --issue`）

- 每场 H1 锚方面（研究 `anchor_side`，缺则 fair 最大面）vs H2 翻车面（double 的 cover → alt_face →
  弱方胜面 → 平）。
- 证据行：`strength_balance.events` / rubric 事实项与 S_spine_intact=no、S_underdog_path、
  S_crash_candidate、S_draw_mode / `hole_location` / 许可证 q1、q3a / crash_markers /
  nondirectional_flags / 三证判死。符号规则：一侧变弱→自家胜面 −、对家胜面 +、平局跟弱方走。
- **两列同号的证据不显示只计数**（S_draw_mode 在 H2＝客胜时、无方向旗、判死第三面都被滤掉）；
  按不一致数排假设（只排序不推概率）；未价的行排前；区分力行 >5 标「打分偏松」。
- 末行：翻盘证据＝研究 `falsifier` ＋ 停售前拿不到（q5 名单窗）＋ 研究收敛 ✓/◇。
- 分析包 §1c 先贴矩阵，10-15 Jun 定的解读表判别列保留在矩阵下（两边都写）。桥上差异格理由写
  「场 N·矩阵行 k」或「矩阵外」；§5⑪ 计「理由引用矩阵行 k/n」——这是「研究产出↔消费」回路的读数
  （RULEBOOK 〇 观察量）。

## 26151 实跑观察（旧研究，P1 契约生效前）

- 矩阵读得通；四场里三场区分力行 6–8 > 5。原因是 `events` 本身每场 5–8 条且按构造都有区分力
  （一侧变弱必然对两个胜面反号），ACH 过滤只能滤掉平局模态 / 无方向旗 / 判死第三面。
  **20 期后看**：若多数场都「偏松」，把门槛改成按 `grade` 加权或把 rubric 事实项与同一事件合并；
  现在不动。
- 来源列：10-27 之前的研究基本是站点名（`スポニチアネックス 2026-10-26`），只有搜狐等少数裸 URL 能
  点开——这就是 P1 的起点。

## 验证

- `tests/decision/test_research_sources.py`（6）、`test_counter_matrix.py`（6）新；
  `test_research_prompt / test_claude_models / test_research_intake / test_research_runner /
  test_rsi_loop` 各加 1–2 条；`tests/decision` 全包 + `tests/test_single_source.py` 通过。
- `uv run ruff check .` All checks passed；全量 `pytest` 仅 2 条失败（`test_cli_crowd::test_nominate…`
  OptionInfo、`test_decision_web_runs::test_runs_page…`），在干净 HEAD（b1fd0606）worktree 上同样失败，
  与本次改动无关。

## 沙盒记录（生产副本，`NUTMEG_DATA_DIR` 指向沙盒）

- `research refresh --day 2026-10-27`：足彩 26151 Read 14 条、自动 legs-base written；腿上已带
  `intake_warn` 三个新码（旧研究全部命中 `source_url_missing` / `event_source_no_url` /
  `sources_consulted_missing`）与 `evidence_sources`（场 3 两个裸 URL、场 5 一个），`coverage=None`
  （旧研究没经新 runner）。
- 删掉沙盒 `26151-research-m5.json` 后 `research run --code 足彩26151-05`（opus，新契约）：
  **1 次尝试、12 轮、140 s、$0.67**（契约变了缓存重建 43k 一次，output 10k）；
  `coverage` 7/7 · counter_searched ✓（反例一句：查美因茨 3:2 负不来梅是主场还是客场）· 5 URL 5 站点
  → `converged=true, stop_reason=coverage`；回抓 5/5 全 200；三条 rubric 事实项来源都是
  `https://… ｜ 原句`。日投影 `telemetry.sources`：done 15 / cited 1 / converged 1（其余 14 场是旧研究）。
- `judgment counter-matrix --issue 26151` 场 5：5 行有区分力、0 行隐藏、来源列全部可点、H1 不一致 3 /
  H2 2；翻盘证据来自研究 falsifier。

## 没做 / 待 Jun

- P4 采访拆命题：缓。先看 20 期桥后理由里有没有自然出现「教练说了 X」。
- 口径调整「研究层的唯一消费者是读包的人，以桥后改动理由引用研究行计量」进 CONSTITUTION §1：
  待 Jun 答；现在只有 RULEBOOK 〇 的观察量在记。
- 不做：旅行距离/图表（F16 零效应）、魔鬼代言人 LLM 层（2609.12495）。
- 遥测里 `search_count` 仍无（需要 stream-json 解析工具调用），`num_turns` 代。
