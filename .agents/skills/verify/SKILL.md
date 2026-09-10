---
name: verify
description: Nutmeg 项目端到端验证配方——改动 nutmeg/decision 决策本体代码后，除单测外还要驱动真实链路（decision-am 快照回放、decision-settle 结算链、decision-close 出票链）观察行为
---

# Nutmeg 项目验证（/verify 的项目配方）

改动不同子系统时，跑对应的真实链路（不是只跑单测）。全部命令在 repo 根目录执行。
2026-07-07 M2 切换后唯一 live 链路 = 决策本体五动词（decision-am/read/close/settle）；
旧 jczq-today/tiered/report/judge-reconcile 配方已随命令下葬。

## 1. 通用（任何 nutmeg/ 代码改动）

```bash
uv run ruff check .            # 必须 All checks passed
uv run pytest -q               # 期望 0 failed（≈700 用例）
```

只想快验决策本体时用 pre-commit 同款子集：
`uv run pytest tests/decision/ -q`

## 2. 决策日循环 replay（sense/backfill/入库相关）

> ⚠️ **`--output-dir` 只重定向文件产物,不隔离本体库。** 只给 `--output-dir` 的回放会
> 写生产 `.nutmeg-data/ontology/ontology.db`(并在那里自动跑待执行迁移)。隔离本体库靠
> `NUTMEG_DATA_DIR`,两个都要给。2026-09-10 实测:漏了它的一次 settle 回放把 2 条
> `record_outcome` 写进了生产库,并把生产自动迁到 schema 28。

```bash
# 拷生产快照到临时目录回放;NUTMEG_DATA_DIR 隔离本体库,--output-dir 隔离文件产物
D=<近两天某日>; TMP=$(mktemp -d)
export NUTMEG_DATA_DIR="$TMP"          # 少了这行就是在写生产库
mkdir -p "$TMP/daily/$D" && cp .nutmeg-data/jczq/daily/$D/*.json "$TMP/daily/$D/"
uv run nutmeg decision-am --run-date $D --output-dir "$TMP"        # D=今天/断网时
# ⚠️ D 是历史日期且网络可达时,decision-am 内的 fetch 会重抓今日盘覆盖已拷快照
#    (sense 得 0 场)——历史日期改跑两段回放(已实测 4 场入库+4 shadow):
uv run nutmeg decision-sense --run-date $D --output-dir "$TMP" --taken-at "${D}T15:00:00+08:00"
uv run nutmeg decision-backfill --run-date $D --output-dir "$TMP" --made-at "${D}T16:00:00+08:00"
```

fetch 失败是 best-effort（离线合法），sense 从已拷快照回放。**看点**：
`$TMP/decision/matches.jsonl` 带 competition/实体 id、backfill 补的 shadow 条数、
teams/leagues 实体种子落盘。

## 3. 结算链（reconcile/calibrate/scoring 相关）

```bash
# 同一临时目录接着跑;默认 dry,不推送
uv run nutmeg decision-settle --run-date $D --output-dir "$TMP"
```

**看点**：Read + Ticket 两类 Settlement 落库、`calibration-panel-<date>.md` 正常渲染
（含参与精度小节）、`factors.jsonl` 的 scope 字段。

隔离库是空的，所以 kernel-backed reconcile 会报「结算 0 场结果」——这是隔离生效的正常
结果，不是坏了。要在隔离库里看到非零结算，先用 `nutmeg ontology ingest-market-day` /
`ingest-evidence-day` 把那天的比赛与赛果喂进 `$TMP` 的本体库，再跑 settle。

## 4. 出票链（express/report/PDF 相关）

```bash
# 无 daily/<date>/legs.json = 空票,合法;默认 dry,不推送
uv run nutmeg decision-close --run-date $D --output-dir "$TMP"
ls "$TMP"/daily/$D/*.pdf
```

**看点**：PDF 正常落盘渲染（CJK 字体不缺字）。

## 红线

- 验证命令一律 dry/replay 优先（临时目录回放）；任何 `--dispatch-telegram --no-dry-run`
  推送都是对外动作，必须用户明确要求才加。
- 回放前先确认隔离生效：`NUTMEG_DATA_DIR="$TMP" uv run nutmeg ontology status` 必须报
  `initialized=False schema_version=0`；报出生产 schema 版本就说明还连着生产库，停下。
- `.nutmeg-data` 是生产数据：验证时只读或走幂等命令，不手改（修数据要留 note 字段）。
