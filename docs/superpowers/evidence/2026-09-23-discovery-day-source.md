# Discovery day 源 · 证据（2026-09-23）

计划：`docs/superpowers/plans/2026-09-23-discovery-day-source.md`（Task 1–3 落地；Task 4 真实世界待一块合格的板）。
提交：c8f3013（spec/计划）→ 813a094（`day_inputs`）→ 1f9a42a（录制器 day 源）→ 15904ba（CLI `--source-day`）→ dd23234（处方时间戳改用最晚 Read）。

## 落地了什么

- `nutmeg/discovery/day_inputs.py`：`jczq-legs-base.json` + `reads.json` + `sporttery_markets.json` → `StructuralInputSnapshot`。面码 3/1/0；市场 id `md-had`（与审计器的结算市场表同口径）；概率量化到 6 位、余数补最大面（生成器要求和恰为 1）；处方 = 表态面集合 + 每个单面 + 丢场，规则名 `stance`（否则审计器对任何偏离抛错）；模板 `pass-N-1`，N=2…min(场数, 5)。
- 录制器 `source_kind="day"`：目录指纹 = 三份文件 sha256；独立复核 = 同 cutoff 重读比对 manifest；数据库分支逐字未变（27 个旧测试原样通过）。
- CLI：`nutmeg discovery shadow-run --source-day <日> [--jczq-dir] --shadow-db <仓外> --cutoff-at <ISO> --approval-file <json>`；与 `--source-db` 二选一。测试里已端到端真录一个 day 世界（真实分片生成，无 mock）并 `status` 见 `sealed worlds: 1`。

## 子代理在实现中抓到的三处

1. 审计器 `_audit_candidate` 对「候选偏离处方且 `rule_ids` 为空」直接抛错，导致所有分片 `adapter_error`、世界封存为 `no_solution`——处方集合与规则名按上面修正后消失。
2. 处方引用时间戳原用文件 mtime，跟墙钟走，过了 cutoff 就「reference exceeds cutoff」——改用最晚一条 Read 的 `made_at`。
3. 市场 id 用 `had` 会被 `_SUPPORTED_SETTLEMENT_MARKETS` 判为不支持——改 `md-had`。

## 真实首个世界（待）

前提：当天 ≥2 场同时有 Read 与体彩 had 报价。2026-09-23 只有 1 场（日本 U21 只开让球盘），所以今天录不了；下一块合格的板按 `plans/…day-source.md` Task 4 的命令跑，把 `world_id`、`sealed_manifest_hash`、`discovery status`、三份文件 sha256 前后一致补到这里。

## 测试

`tests/discovery` 231 + `tests/test_cli_discovery.py` 20 通过（含 day 源两条录制测试与三条 CLI 测试）；ruff 干净。

## 后续（spec §5）

首个真实世界封存后：退役 operator_v2 内核残余（`product/jczq_*`、`operator_{contracts,lanes,artifacts,legacy_import}`、`workflow jczq-*`），把生成器与审计器搬进 `nutmeg/discovery/`，契约 `authoritative_workflow.generator` 走 D7 修订重冻结。
