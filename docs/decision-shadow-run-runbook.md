# 决策本体系统 · 每日影子运行 runbook（M1 运营 → M2 已转正）

> 2026-07-06 M1 影子运行起步；**M2 已于 2026-07-07 完成切换**——决策本体（`nutmeg/decision/`）
> 即唯一 live 系统，旧 SOP/launchd 已下葬，launchd 现挂 decision-am/close/settle 三段
> （见文末"与现系统的边界"）。数据落
> `.nutmeg-data/jczq/decision/{matches,snapshots,reads,factors,settlements,tickets,verdicts}.jsonl`。

## 每日序列（顺序纪律：判读 → 补 shadow，绝不反向）

```
① 读时(下午,现 SOP 抓完盘后)   decision-sense    体彩+欧赔读时快照入库
② 判读(我·Claude 运行时)        decision-read     我产的 Read(校验落库)
③ 判读收尾(② 之后)             backfill-shadows   未判场补市场基线 shadow
④ 近开赛(晚,主赛前)            decision-capture-closing   收盘欧赔快照(CLV 参照)
⑤ 次日晨(赛果出后)             decision-reconcile 结算 Brier+CLV
⑥ 次日晨(⑤ 后)                decision-calibrate 因子判决 + 面板
```

**顺序铁律**：③ 必须在 ② 之后。`backfill_shadows` 跳过任何已有 Read 的场；若先补
shadow 再判读，同场会出现 shadow + 真 Read 两条（读时 id 不同不互斥）。因此**先判读、
后补 shadow**。（已知细化：ingest 覆盖同场 shadow 的守卫留 M1.5，当前靠顺序纪律。）

## 命令速查

```bash
OUT=.nutmeg-data/jczq
TODAY=$(date +%Y-%m-%d)

# ① 读时感知(体彩+欧赔两源;欧赔缺则只体彩,不崩)
uv run nutmeg decision-sense --run-date $TODAY --output-dir $OUT \
  --taken-at "${TODAY}T15:00:00+08:00"

# ② 判读:我产 Read JSON 数组(schema 见 spec §2 / read_validate)。
#    默认跟市场=不产 Read;只在有命名因子+证据时产 divergent Read。
uv run nutmeg decision-read --reads-file <today-reads.json> --output-dir $OUT

# ③ 补 shadow(市场基线,belief=prior;只补②未判场)
#    decision-backfill CLI 已就绪(decision-am 编排内含;单独补跑用下行)
uv run nutmeg decision-backfill --run-date $TODAY --output-dir $OUT \
  --made-at "${TODAY}T16:00:00+08:00"

# ④ 近开赛收盘欧赔(需 NUTMEG_API_FOOTBALL_KEY;缺则该场 CLV=null)
uv run nutmeg decision-capture-closing --run-date $TODAY --output-dir $OUT \
  --taken-at "${TODAY}T21:30:00+08:00"

# ⑤ 次日结算(okooo 赛果 + 收盘快照 → Brier+CLV)
uv run nutmeg decision-reconcile --run-date $TODAY --output-dir $OUT \
  --settled-at "$(date +%Y-%m-%d)T08:00:00+08:00"

# ⑥ 校准面板(因子生死;写 calibration-panel-<as_of>.md)
uv run nutmeg decision-calibrate --as-of $(date +%Y-%m-%d) --output-dir $OUT
```

## 判读（②）纪律——继承 CLAUDE.md 硬约束 a-f

- **默认跟市场**：无命名因子 = 不产 divergent Read（③ 会补 shadow）。空仓/跟盘永远合法。
- **偏移须命名因子 + 证据**：因子只能来自词典（`decision_factors_seed.json` 6 个 probation
  或已转正的），带证据 URL/quote。词典外因子 read_validate 直接拒。
- **先验锚欧赔 fair**（sharp），非体彩（−13% 抽水几乎不动）。resolve_prior 已欧赔优先。
- **conf5 仅 90' 方向市场**；反偏置六条（低分/疲劳/fade/战意/生疏/3路口径）已烤进
  `jczq-match-analyst` agent 与本纪律。

## 度量（判读价值的真实检验）

- **CLV（快,信息含量）**：偏移是否朝收盘欧赔移动。开赛即可结,方差远小于赛果。
  持续 CLV>0 = 判读含真实信息（Starlizard 度量学）。
- **Brier（慢,真理）**：对赛果的校准。brier_delta<0 = 偏移改善市场先验（Metaculus Baseline）。
- **因子生死**：n≥30 双轴达标转 active、平庸退休；词典上限 12（反积累免疫）。

## 与现系统的边界

- **M2 已于 2026-07-07 完成**：旧 SOP/launchd（jczq-today/tiered/report 等引擎命令）已下葬，
  决策本体即唯一 live 系统。launchd 现挂三段：decision-am（08:00 数据入库+基线）/
  decision-close（19:00 出票+报告推送）/ decision-settle（次晨 08:10 结算+校准）。
- 数据位置：本体数据在 `.nutmeg-data/jczq/decision/`；`daily/<date>/` 存原始盘口快照与 legs.json。

> 关联：spec `docs/superpowers/specs/2026-07-06-decision-ontology-design.md` · M1 计划
> `docs/superpowers/plans/2026-07-06-decision-ontology-m1.md` · 记忆 `decision-ontology-design`。
