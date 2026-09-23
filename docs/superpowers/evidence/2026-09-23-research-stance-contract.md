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

## 真实首跑（2026-09-23 11:11 补记）

08:00 由 `decision.am` 链起的深研早于表态契约提交（08:20），两份研究没有 `stance`，10:00 的 intake 把它们隔离（`stance.stance: 缺 stance 表态块`）——守则起作用。11:08 手动重跑 `research run → intake --write → jczq-build-reads → day brief --with-logic`：

| 场 | stance | falsifier |
| --- | --- | --- |
| 周三001 中国-阿联酋 | 押 3 · double(31) · conf 2 · why_not_market=none | 若中国 90 分钟输给阿联酋，则本判读作废；若开出平局，只有平局对冲这一腿命中 |
| 周三002 日本-? | 押 3 · single · conf 3 · why_not_market=none | 若 90 分钟日本未胜，或日本首发轮换超过 8 人且半场仍未领先，则本判断作废 |

两场都是「跟市场」但**写下来了**：面、档、作废条件齐全；无 A/B 类证据故无 tilt，`belief == prior` 是选择而非默认。Read 的 `commitment_tier` 分别 lean / commit。
逻辑层（新提示词）两场都 `ok`，说人话、≤6 句、字段名只在 cites。

顺带暴露：重跑时 `rsi fulfill --exp R0` 撞幂等键（同日同场第二次兑现被拒），与「rsi schedule 同日幂等」是同一族 bug，待修。


## 未做

足彩泳道 `judgment-v1.json` 与本 schema 合流（它已有 `action / prescription / belief / adjustment_evidence_tiers`）。
