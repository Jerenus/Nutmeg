# Kernel 落库-报告对账设计

日期：2026-08-28
状态：已批准实施（开发交接 T7；用户要求连续实施全部任务）

## 1. 问题与目标

26110-26111 的 Zucai kernel 感知曾把 rejected snapshot 当成成功计数，导致 prep 有
14 场、命令声称入库 14 场，但 actions 真相层没有对应 committed Action。当前
`ZucaiIssueIngestService` 已避免直接计 rejected，仍缺第二条独立断言：服务返回值一旦
以后回归，CLI 仍会照样把虚报写进 shadow 证据。

T7 在 `decision-am --issue` 的 Zucai kernel 步骤后查询 actions 表，并把“本期 prep
报告的场数、服务本次返回数、本期 committed snapshot Action 数”同时输出。真正的
硬判据是：本期应有的 prep 场数必须等于本期作用域内 committed
`build_market_snapshot` Action 数。不相等即该 step 为 failed，`decision-am` 退出 1。

## 2. 方案选择

考虑三种做法：

1. 继续信任 `ZucaiIssueIngestResult.snapshots`。改动最小，但与事故根因相同，不能形成
   独立防线。
2. 查询 `market_snapshots` 业务表。能证明对象存在，却绕过了“所有后果必须有 Action”
   的本体不变量。
3. 查询 actions 表（采用）。用 `action_type/status` 和结构化 Action payload 锁定当前
   prep 各 canonical match 的 Zucai snapshot Action，既证明对象通过 typed Action，
   又与服务内存计数独立。

## 3. 作用域与判据

Zucai snapshot Action 的既有幂等键为：

```text
zucai:snapshot:<issue>:<match_no>:<snapshot_kind>:<as_of>
```

ActionRepository 新增只读计数方法。adapter 先由 prep 行的队名+日期解析当前
canonical match IDs，再按以下条件统计 distinct `payload.match_id`：

- `action_type == "build_market_snapshot"`；
- `status == "committed"`；
- `payload.match_id` 属于当前 prep match IDs；
- `payload.provider == "zucai"`；
- `payload.snapshot_kind == "read_time"`。

prep 报告数取 `_default_loader` 返回的本期 matches 数量。它与 prep 的 `n_matches`
同源，代表应形成 shadow 市场锚的板面场数。无源文件仍沿用现有“源快照缺失”可见降级，
不进入对账；有源文件但缺 odds/date、Action rejected/failed 或服务误报均会造成实际
committed 数小于 prep 报告数，从而报警。

同一期幂等重跑以及跨期同一 canonical match 复用首个 read-time anchor 时，原始
committed Action 仍能被 payload match ID 找到，不会把“本次新建为 0”误判成失败。
service 本次数只作为诊断字段，不参与硬判据。

## 4. 错误与输出

新增 `KernelCountMismatch`，消息使用稳定代码：

```text
kernel_snapshot_count_mismatch issue=26111 actions=0 prep=14 service=0
```

成功消息追加：

```text
kernel对账 Snapshot: actions落库 14 / prep报告 14 / service本次 14
```

`run_decision_am_v2` 继续由 `_compose` 捕获异常并生成 failed step，CLI 既输出证据又
退出 1，不使整个进程无报告崩溃。

## 5. 文件与测试

- `nutmeg/ontology/repository/actions.py`：通用只读 `count` 过滤器。
- `nutmeg/decision/ontology_adapter.py`：Zucai issue 对账与稳定错误。
- `tests/ontology/test_action_repository.py`：Action 计数过滤合同。
- `tests/decision/test_ontology_adapter.py`：正常三数输出、rejected 注入报警、CLI 非零。

## 6. 显式排除

- 不改 legacy JSONL `decision-am`；只有 ontology v2 kernel 有 actions 真相层。
- 不把 `zucai-prep` 接入写库；prep 仍只产事实报告。
- 不修复或重试 rejected Action，不改变权限和 Action 状态机。
- 不查询或修改生产 ontology；真实验证使用生产 Zucai 源快照复制到临时 kernel。
- 不把缺失锚解释成任何投注判断。
