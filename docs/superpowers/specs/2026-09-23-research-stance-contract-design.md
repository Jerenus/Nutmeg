# 研究表态块 `stance` · 设计（让判断层有出口）

日期：2026-09-23 ｜ 状态：Jun 2026-09-23 已按字段清单裁定，本文为定稿 ｜ 后续：writing-plans
依赖：深研桥（`research_runner` / `jczq_reads`）、判决表 l 条（RULEBOOK 权重表 / 归零 / C8）、F9 天平位移账。

## 0. 一句话

分析员每场必须**押一个面、给一个表达档、写一句作废条件**；只有 A/B 类证据才允许把 belief 拨离市场，拨了就进 F9 记账。「跟市场」从此是写下来的选择，不是管线的默认。

## 1. 出生事故（2026-09-22）

- 四场 Read 全部 `belief == prior`（拨动 0.0pp）。`build_jczq_reads` 的 belief 算法是「活面按 fair 归一」，没有面被判死就等于原样抄市场；判决表的「偏移 / 翻面」两格在代码里到不了。F9 连续 0/14 的根因在此。
- 周二002/003/004 深研第一次就 `Reached max turns (12)`，被记 `permanent`，不再重试；三场只剩旧标签、conf 2–3，裸单被 C4 拦、双选过不了旗，合法表达只剩全包——Jun：「等于比赛又放掉了」。

## 2. 三条原则

1. 每个字段要么喂一条已有判据（审计码 / 判决表 / F9），要么赛后可判真假；两者都不沾的不进表态块。
2. 判断由分析员出，判据入代码：表态块的合法性、拨动幅度、归零、上限全部由 `stance.py` 机械裁定，不听论证。
3. 空仓与跟市场永远合法，但必须写下来（`why_not_market`）。

## 3. 表态块 schema（研究 JSON 顶层新字段，必填）

```json
"stance": {
  "face": "3|1|0",
  "structure": "single|double|full",
  "cover": "3|1|0|null",
  "confidence": 1-5,
  "falsifier": "一句赛后可核验的作废条件（≥8 字）",
  "why_not_market": "none|tilt_evidence|structure",
  "tilt": null | {
    "face": "3|1|0",
    "evidence": [
      {"tier": "official|confirmed_structural|inferred|will",
       "kind": "<TILT_KIND_LEXICON>", "pp": 0-8,
       "source": "url 或来源名", "captured_at": "ISO 时间"}
    ],
    "expires_if": "证据失效条件"
  },
  "alt_face": "3|1|0|null",
  "market_read": "agree|overpriced|underpriced|null"
}
```

| 字段 | 喂谁 / 怎么判真假 |
| --- | --- |
| `face` | F9 `direction_right`；赛后 outcome 直接判 |
| `structure` + `cover` | 派生 `faces`（single→face；double→{face,cover} 按 3/1/0 排；full→310），进审计码 C1–C14 |
| `confidence` | C4 门槛；与顶层 `confidence` 必须一致（intake 以 stance 为准） |
| `falsifier` | Read 的 `falsifier`；F9 判错时先看它有没有兑现 |
| `why_not_market` | `none`＝跟市场；`tilt_evidence`⇔`tilt` 非空；`structure`⇔至少一面被三证判死 |
| `tilt.evidence[].tier` | RULEBOOK l-权重表：`official` 4–8pp、`confirmed_structural` 3–6pp、`inferred` 0–2pp、`will` 0–2pp 且只许 `tilt.face == "1"` |
| `tilt.evidence[].kind` | 封闭词典 `TILT_KIND_LEXICON`：`absence_official / suspension / goalkeeper_change / anchor_integrity_fail / lineup_confirmed / venue_anomaly / precedent_carrier / rotation_confirmed / schedule_congestion / motivation_dead_rubber` |
| `tilt.evidence[].captured_at` | T12：晚于开球的证据整条作废（记 reason，不入 belief） |
| `alt_face` / `market_read` | 只记录，进记分牌与 F1c/F5 分层，不进权重 |

## 4. 机械裁定（`nutmeg/decision/stance.py`）

- `validate_stance(stance, *, confidence, death_three_proofs) -> (norm, issues)`：枚举与类型；`double` 必有 `cover ≠ face`；`why_not_market` 与 `tilt` / 死面互相印证；`will` 只许朝平；`pp` 在该 tier 区间内；`kind` 在词典；表态的面集合不得含已判死的面（ERROR）。
- `apply_tilt(prior, tilt, *, kickoff=None) -> TiltResult{belief, applied_pp, zeroed, reason, tiers}`：
  1. 丢掉 `captured_at ≥ kickoff` 的证据（T12）；
  2. `net = Σ pp`；`net < 5` → 归零（belief=prior，reason「净偏移 <5pp 归零跟市场」）；
  3. 上限：含 `official` 15pp，否则 10pp；超出截断；
  4. `belief[face] = prior[face] + net/100`，其余面按 prior 比例缩，和为 1，单面夹在 [0.01, 0.98]。
- `stance_faces(stance) -> str`。

## 5. 接线

| 处 | 改动 |
| --- | --- |
| `research_prompt.RESEARCH_JSON_CONTRACT` + `.claude/agents/jczq-match-analyst.md` | 加「★表态块（必答）」；说明 tier 与 pp 区间、kind 词典、跟市场也要填 |
| `research_runner._REQUIRED / _validate` | `stance` 必填；`validate_stance` ERROR → 拒收（进既有重试） |
| `research_runner._research_one` | **max turns 第一次不判永久**：带标记的重试简报（`RETRY_MARKER`，要求最多 4 次检索后必须出 JSON）再试一次，`_claude_cli` 见到标记把 `--max-turns` 提到 24；第二次仍 max turns 才 `permanent` |
| `jczq_reads.intake_board` | `attach_face_status` 之后校验表态面集合不含死面；把 `stance` 与派生 `faces` 写回 leg |
| `jczq_reads.build_jczq_reads` | 有 `stance` 的场：`belief` 由 `apply_tilt` 决定（无 tilt / 归零 → 沿用活面归一）；`falsifier`、`confidence`、`commitment_tier`（single→commit / double→lean / full→cover）、`stance`、`adjustment_evidence_tiers` 进 Read |
| `day_brief` / `day_session` / `day.js` / `brief.md` | 卡片带 `stance`（面/档/为什么不跟市场/拨动 pp/归零原因）；逻辑层输入自动含它 |

足彩泳道的研究 JSON（`zucai-research-intake`）本期不改：其判断文件 `judgment-v1.json` 已有 `action / prescription / belief / adjustment_evidence_tiers`，与本 schema 同源；下一步把两者合流。

## 6. 与宪法的边界

- 拨动只经 `tilt`，只认 A/B 类证据，幅度封顶，归零规则照 RULEBOOK；C8 继续用 `adjustment_evidence_tiers` 复核。
- 表态不改审计门：裸单仍要过 C1/C4/C5，双选仍要过 C2/C6/C10；被拦的是一个明确立场。
- F9 的 `BALANCE_MOVE_EPS_PP` 不变；每一次非零 `applied_pp` 都进天平账。

## 7. 出口条件

某天 `research run` 后：板上每场研究 JSON 都有 `stance`；`reads.json` 里至少一场 `belief ≠ prior` 且 Read 带 `adjustment_evidence_tiers`；`/day` 卡片显示「面 / 档 / 为什么不跟市场」；被 max turns 拒的场有第二次尝试记录；F9 下一期 `n_moved > 0`。
