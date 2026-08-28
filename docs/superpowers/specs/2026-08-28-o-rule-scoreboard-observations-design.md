# o 条分型 Scoreboard 观察设计

日期：2026-08-28
状态：已批准实施（开发交接 T8；用户要求连续实施全部任务）

## 1. 现状与目标

生产 legacy `scoreboard.json` 把 o 条两个不同样本机制揉在一个 metric：

- 持平开平分型累计 3/6，26111 P1 falsifier 后已 retired；
- 首回合 1 球差分型累计 5/5 分胜负，独立保留观察。

生产 ontology 已有 `chains/suspended_tie_sandwich_o` observation，numerator=3、
denominator=6；首次 shadow review 已把该 legacy key 认定为唯一一个
`formal_manual`。因此本包不得重复创建父 observation，也不得声称它仍 unexplained。

T8 把两种机制拆成两个独立的 ratio metric：修订现有 key，使其只表达持平开平；新增
1 球差 key。这样后续样本各走自己的 numerator/denominator revision 链，不再在 detail
散文里混合 tally。

## 2. 结构化映射

| group_key | metric_key | tally | numerator/denominator | value/unit | status |
| --- | --- | --- | ---: | --- | --- |
| chains | suspended_tie_sandwich_o | 3/6开平 | 3/6 | 0.5 ratio | retired |
| chains | suspended_one_goal_margin_o | 5/5分胜负 | 5/5 | 1.0 ratio | watch |

第一行通过 `scoreboard observe --supersedes <current observation id>` 形成 revision，保留
legacy key，因而 shadow classification 仍可使用 `formal_manual`。第二行是新的独立 manual
plane metric，不改变 legacy JSON 的 classification coverage；权威切换前只存在 ontology
影子侧。

## 3. 写入与证据

两次写入都必须：

- 使用现有 `nutmeg scoreboard observe`；
- 带 `--acknowledge-manual-source`，actor 固定为 judge operator；
- evidence ref 指向被拆分的原 scoreboard observation，保留谱系；
- numerator、denominator、value、unit 全部显式给出；
- effective_at 沿用 2026-08-27 的业务判定日，requested_at 使用实际执行时刻。

现有 Action idempotency key由 group/metric/detail hash 生成。重复执行相同命令只 replay；
任何不同 revision 必须显式 supersede 当前叶节点，禁止平行分叉。

## 4. 验收链

临时 kernel 先在没有 observation 时对 legacy o metric 申请 `formal_manual`，必须被拒绝；
随后经 typed Actions 写入两个分型、重建 analytics projection，再跑相同 shadow：

- parent metric 可分类 `formal_manual`；
- review `manual_count == 1`、`unexplained_count == 0`；
- manual projection 同时有两个 ratio 行及精确 3/6、5/5 字段。

生产验收只执行两次 `scoreboard observe` 并查询 ontology 行，不运行 cutover。新增 Actions
会使当前 projection 变 stale，这是正确行为；投影重建与下一轮完整 classification review
分别由 T1 命令及运营流程处理。

## 5. 仓库产物

- `tests/scoreboard/test_o_rule_observations.py`：上述 RED→GREEN 状态链的回归验收。
- `docs/superpowers/plans/2026-08-28-o-rule-scoreboard-observations.md`：命令、证据和偏离。
- 不新增生产模块：现有 typed Action/CLI 已完整覆盖需求，新增平行接口会重复治理边界。

## 6. 显式排除

- 不直接改 `.nutmeg-data/scoreboard.json`。
- 不执行 `scoreboard cutover`、ReleaseApproval、soak 或 launchd 操作。
- 不改变 o 条业务结论，不从新赛果自动推导状态。
- 不把 1 球差 5/5 升格为 active 规则；`watch` 只表示保留观察。
- 不替其他 17 条 legacy metric 做 classification 裁决。
