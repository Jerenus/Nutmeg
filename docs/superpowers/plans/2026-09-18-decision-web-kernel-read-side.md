# 判读工作台接内核（读侧）— 2026-09-18

## 出生事故
`decision-read` 在 `NUTMEG_ONTOLOGY_V2=1` 下把 Read 提交为内核 ForecastRevision，而 `decision_web.py`
仍读旧 `DecisionStore`（`.nutmeg-data/jczq/decision/reads.jsonl`，最后一条 2026-08-24）。
结果：判读工作台从 8/24 起看不到任何一条新 Read；26129 今天 14/14 条 Read 入了内核，页面仍显示
「今日 agent 尚未开工」。这不是"都裁决完了"，是读侧没跟着写侧切换。

## 目标（本刀只做读侧）
1. `/api/workbench?date=` 与 `/` 的 **matches / snapshots** 来自内核（`ProductReadRepository.board_matches`
   + `latest_snapshot(md-had)`），按上海日界切窗，与 `ProductQueryService.board()` 同口径。
2. **Reads** 来自内核已提交 ForecastRevision（`forecasts_for_match`，status=committed），并合成
   `attention` 议程事件，使左栏「今日议程 / 待裁决」有条目可点。
3. 开关与写侧同一个：`settings.ontology_v2`（env `NUTMEG_ONTOLOGY_V2`）。开则内核为唯一读侧权威，
   关则旧路径一字不变。**不双写**（M5 禁无声双权威）。
4. `approve-read / reject-read / confirm-legs / thread / betslips` 本刀不动（仍走旧 store 与 workbench.jsonl）。
   动作侧接内核是下一刀（approve = 内核 commit 已存在，需重新定义语义）。

## 非目标
- objects / calibration / ledger 三页仍读旧 store（各自的内核读模型已在 `ProductQueryService` 里，另开一刀）。
- 不改模板；只让 `state.events` 里多出内核合成的 `attention` 项。

## 步骤（TDD）
1. `tests/test_decision_web_kernel.py`：假仓库（duck-typed）→ `kernel_day_state()` 出 matches/snapshots/reads/events；
   `create_decision_app(kernel_state=…)` → `/api/workbench` 含内核场次与 reads，`/` 渲染议程行；旧测试全绿。
2. `nutmeg/interfaces/decision_web_kernel.py`：`kernel_day_state(repository, date, *, as_of)`。
3. `decision_web.create_decision_app(..., kernel_state=None)`；`_day_state` 在给定 kernel_state 时以内核为准。
4. CLI `decision-web`：`ontology_v2` 为真时装配内核仓库并注入 `kernel_state`。
5. 验证：`uv run nutmeg decision-web` → `/api/workbench?date=2026-09-19` 应见 26129 的 14 场 + 14 条 Read。
