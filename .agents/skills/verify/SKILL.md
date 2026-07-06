---
name: verify
description: Nutmeg 项目端到端验证配方——改动 jczq/worldcup/zucai 代码后，除单测外还要驱动真实链路（replay 决策包、ledger 对账、tiered 复盘）观察行为
---

# Nutmeg 项目验证（/verify 的项目配方）

改动不同子系统时，跑对应的真实链路（不是只跑单测）。全部命令在 repo 根目录执行。

## 1. 通用（任何 nutmeg/ 代码改动）

```bash
uv run ruff check .            # 必须 All checks passed
uv run pytest -q               # 期望 0 failed（≈1200 用例，约 4 分钟）
```

只想快验相关模块时用 pre-commit 同款子集：
`uv run pytest tests/test_wc_judge_ledger.py tests/test_wc_predictions.py tests/test_wc_results.py tests/test_jczq_tiered_review.py -q`

## 2. jczq 决策链（jczq_tiered / jczq_today / packet 相关）

```bash
# 从已存快照回放,不打外网、不写盘——观察 §A 票面/§C 问题是否合理生成
uv run nutmeg jczq-today --replay $(ls .nutmeg-data/jczq/daily | tail -1) | head -80
```

回放日无快照时换一个近期日期。**看点**：A/B/D/E 档结构、主题汰留警告行、§C q_id 列表。

## 3. 世界杯判读/对账链（worldcup/*、judge_ledger、predictions）

```bash
# 幂等全量重对账 + 摘要行(picks 判定率/票 pnl/pending)
uv run nutmeg jczq-judge-reconcile
```

**看点**：`pending=0`（世界杯窗口内、赛果就绪时）；ticket pnl 数字变化要能解释。
改了 hhad 评分/匹配逻辑后，抽查 `.nutmeg-data/jczq/wc2026/judge-ledger.jsonl` 里
一张 hhad 票的 `line / ticket_outcome / pnl_yuan` 是否与比分手推一致。

## 4. tiered 复盘链（jczq_tiered_review）

```bash
uv run nutmeg jczq-tiered-review --date <近两天某日>   # 默认 dry,不推送
```

**看点**：腿级 actual/hit 填充、`tiered-plan-history.json` 同日替换（不重复追加）。

## 5. PDF/推送链（report_pdf / telegram）

```bash
uv run nutmeg jczq-report --date today   # 不带 --dispatch-telegram = 只落盘
ls -la .nutmeg-data/jczq/daily/$(date +%F)/*.pdf
```

**看点**：PDF 正常渲染（CJK 字体不缺字）。推送验证必须用户明确要求才加
`--dispatch-telegram --no-dry-run`。

## 红线

- 验证命令一律 dry/replay 优先；任何 `--no-dry-run` 推送都是对外动作，先问用户。
- `.nutmeg-data` 是生产数据：验证时只读或走幂等命令，不手改（修数据要留 note 字段）。
