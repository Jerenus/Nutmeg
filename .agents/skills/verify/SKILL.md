---
name: verify
description: Nutmeg 项目端到端验证配方——改动 nutmeg/ 代码后，除单测外还要在生产数据的沙盒副本上驱动现役链路（研究刷新/判决页、当日报告、审票、内核结算、实验闭环、回放复现）观察行为
---

# Nutmeg 项目验证（/verify 的项目配方）

现役链路以 `docs/ARCHITECTURE.md` 为准（2026-10-01 起机器不出票：研究 → Read → 面板 → 人出票
→ `betslip preview` 审票 → 登记 → 结算 → 账房 / 实验）。全部命令在 repo 根目录执行。

## 1. 通用（任何 nutmeg/ 代码改动）

```bash
uv run ruff check .            # 必须 All checks passed
uv run pytest -q               # 期望 0 failed；全量约 3.5 分钟
```

快验决策层用 pre-commit 同款子集：`uv run pytest tests/decision/ -q`。

有 4 个用例读相对路径 `.nutmeg-data/`（`test_balance_ledger`、`test_rsi_population` 两个、
`tests/decision/test_rsi_prereg.py` 的注册表用例——F13/F14 的 `source_doc` 指向 `.nutmeg-data/scoreboard.json`）。在 git worktree 里开发时，先建好第 2 节的沙盒，再
`ln -s "$SB" .nutmeg-data`（目录已存在就先删掉它——那是命令自动建的空库）：测试和本地命令
都只碰沙盒，绝不链到生产目录。

## 2. 沙盒：生产数据的隔离副本

> ⚠️ **`--data-dir` / `--output-dir` 只重定向文件产物，不隔离本体库。** 内核路径来自
> `NUTMEG_DATA_DIR`；漏了它就会写生产 `.nutmeg-data/ontology/ontology.db`（并自动跑待执行
> 迁移）。2026-09-10 实测：漏了它的一次 settle 回放把 2 条 `record_outcome` 写进了生产库。
> **两个都要给。**

```bash
SB=$(mktemp -d)/.nutmeg-data
rsync -a --exclude archive --exclude 'ontology/ontology.db*' \
  --exclude 'analytics/analytics.duckdb*' .nutmeg-data/ "$SB/"
mkdir -p "$SB/ontology"
sqlite3 .nutmeg-data/ontology/ontology.db ".backup '$SB/ontology/ontology.db'"   # 一致快照
export NUTMEG_DATA_DIR="$SB"          # 少了这行就是在写生产库
uv run nutmeg ontology status         # 必须报沙盒库；报错或指向生产就停下
```

沙盒约 450MB，后面所有命令都带 `--data-dir "$SB"`（或 `--output-dir "$SB/jczq"`）。
`D` 取最近一个有板面的日子（`ls "$SB/jczq/daily/$D/jczq-legs-base.json"` 存在）。

## 3. 判断层：研究刷新 → Read → 判决页

```bash
uv run nutmeg research refresh --day $D --data-dir "$SB"
uv run nutmeg research verdict --day $D --data-dir "$SB"     # → $SB/jczq/daily/$D/verdict.html
```

**看点**：refresh 回执「竞彩 Read N 条」与投影比对行；verdict.html 渲染、置顶「需要你裁决」。

## 4. 面板：当日报告

```bash
uv run nutmeg day run --job brief --date $D --data-dir "$SB"   # 不加 --with-logic（那会调 claude -p）
```

**看点**：`brief N 场 · 待人 K · 缺席输入 0 (exit=0)`；`$SB/daily/$D/brief.md` 与 `session.md`。

## 5. 审票：betslip preview

```bash
# 从登记簿取一张历史票的腿当样本
python3 -c "import json;r=[json.loads(l) for l in open('$SB/betslips.jsonl')][-1];json.dump(r['legs'],open('/tmp/legs.json','w'),ensure_ascii=False)"
uv run nutmeg betslip preview --channel jczq --placed-at $D --legs-file /tmp/legs.json \
  --combo 1 --data-dir "$SB"
```

**看点**：V1 期望回报、V2 共享裸单否决、刹车行（本月净 vs −3,000）。preview 只读，不登记。

## 6. 结算：内核 reconcile → calibrate → report

```bash
uv run nutmeg decision-settle --run-date $D --output-dir "$SB/jczq"     # 默认 dry-run，不推送
```

**看点**：`结算 N 场结果`、calibrate succeeded、`decision-report-v2-$D.md` 落盘。

## 7. 实验层与回放

```bash
uv run nutmeg rsi status --data-dir "$SB"          # n 与判决同源（grade 的 n_cum）
uv run nutmeg rsi loop --dry-run --data-dir "$SB"  # 只打印每步命令
uv run nutmeg gym verify --data-dir "$SB"          # 必须复现记分牌：差 +0
```

## 红线

- 验证一律在沙盒里做；任何 `--dispatch-telegram --no-dry-run` 推送都是对外动作，必须用户明确
  要求才加。
- 不在沙盒里跑 `research run`（每场一次 opus `claude -p`）与 `day run --with-logic`，除非改的
  就是它们。
- `.nutmeg-data` 是生产数据：验证时只读，不手改（修数据要留 note 字段）。
