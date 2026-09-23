# 研究表态块 · 证据（2026-09-23）

计划：`docs/superpowers/plans/2026-09-23-research-stance-contract.md`（Task 1–5 落地，子代理逐任务）。
提交：5eec5c5（stance.py）→ 550b8ff（max turns 重试一次）→ a0c7466（契约 + intake 回填）→ b4b9719（日报/页面显示）→ b2cf4d2（Read 用表态定 belief）→ CLI 夹具补表态。

## 现在的链路

1. 分析员（`claude -p`）每场必须输出 `stance`：面 / 表达档 / cover / confidence / 作废条件 / 为什么不跟市场 / 可选 `tilt`。
2. `research_runner._validate` → `validate_stance`：枚举、双选必有不同的 cover、confidence 与顶层一致、falsifier ≥8 字、`why_not_market` 与 `tilt`/死面互证、tier 区间（官宣 4–8 / 确证结构 3–6 / 推断 0–2 / 战意 0–2 且只许朝平）、kind 词典、`captured_at` 合法；任何 ERROR 拒收进重试。
3. `intake_board` 把 `stance` 与派生 `faces` 写回 legs-base；表态含已判死的面 → 拒收。
4. `build_jczq_reads`：`apply_tilt` 按 l 条算净偏移（<5pp 归零、无官宣封顶 10 / 有官宣 15、开球后证据作废），三证优先于拨动（死面清零后归一）；Read 带 `falsifier`、`confidence`、`commitment_tier`（single→commit / double→lean / full→cover）、`stance`、`adjustment_evidence_tiers`（C8 用）。
5. 日报卡片 / `brief.md` / `session.md` / `/day` 显示「押3·31」与拨动原因。
6. max turns 第一次不再永久：带标记的重试简报把 `--max-turns` 提到 24 并要求最多 4 次检索后必须输出；第二次仍 max turns 才 `permanent`。

## 测试

`test_stance`（6）、`test_research_runner`（12，含新政策两条）、`test_jczq_reads`（+5）、`test_day_brief`/`test_day_session`（+2）、`test_cli_research` 夹具补表态；全量 pytest 通过；ruff 干净。

## 计划里被子代理纠正的两处

- `validate_stance` 的 cover 检查在 `face` 本身非法时不会触发（计划的条件漏了 `face not in FACES`）。
- Task 4 测试断言 `belief.home − prior.home == 0.06` 忽略了死面归一：+6pp 后再把 away 清零归一，home 实为 0.756。

## 真实首跑（待补）

2026-09-22 的四场已过开球，不能回放（T12）。今天 10:00 `com.nutmeg.jczq.research` 会用新契约跑 2026-09-23 板面；补记：每场 `stance` 原文、`reads.json` 里首条 `belief ≠ prior`、被 max turns 重试的场的 `attempt_errors`。

## 未做

足彩泳道 `judgment-v1.json` 与本 schema 合流（它已有 `action / prescription / belief / adjustment_evidence_tiers`）。
