# 足彩候选票优化器设计

日期：2026-08-28  
状态：已批准实施（开发交接 T6；用户要求连续实施全部任务）  
上位约束：`docs/sop/CONSTITUTION.md` 元原则一、T6 验收口径

## 1. 目标

新增 `nutmeg zucai-optimize --input-file <json>`，把每期反复手算的候选票比较收编为
确定性 CLI。主循环负责给出 fair、候选面集合、注金帽和需要联合比较的版本组；程序只计算
注数、票价、P(全对)、期望断腿、帽内排序、多票联合命中率与共同死面。

本功能不生成候选票，不判断该砍哪场、换哪面或是否出票，也不写 rx、ledger、ontology、
scoreboard。输出是供人和主循环裁决的比较证据，不是出票指令。

## 2. 输入合同

输入为一个 JSON 对象：

```json
{
  "issue": "26111",
  "price_per_note": 2,
  "budget_yuan": 1296,
  "baseline_id": "U864用户版",
  "fair": {
    "1": {"home": 0.631, "draw": 0.193, "away": 0.176}
  },
  "versions": [
    {"id": "U864用户版", "faces": {"1": "310"}}
  ],
  "groups": [
    {"id": "双票组合", "version_ids": ["U864用户版", "U864优化版"]}
  ]
}
```

- `issue`、`fair`、`versions` 必填；`price_per_note` 默认 2；`budget_yuan`、
  `baseline_id`、`groups` 可省略。
- fair 的键只允许 `home/draw/away`，值须在 `[0, 1]`，三面合计容许千分之一的
  四舍五入误差。计算保留输入值，不暗中重新归一化。
- 每个版本至少一场，场号必须存在于 fair；faces 只允许不重复的 `3/1/0`。
- 版本 ID 和组 ID 唯一；baseline 与组成员必须引用已声明版本。
- JSON 解析或结构校验失败时，CLI 在 stderr 输出 `输入错误：...` 并以退出码 2 结束。

## 3. 确定性算术

每场覆盖概率是所选面的 fair 之和。假定各场独立：

- 注数 = 各场所选面数的乘积；票价 = 注数 × `price_per_note`。
- P(全对) = 各场覆盖概率的乘积。
- 期望断腿 = 各场未覆盖概率之和。
- 帽内榜只纳入 `cost_yuan <= budget_yuan` 的候选，按 P 降序、票价升序、版本 ID
  升序稳定排序。结果只标出 `best_within_cap_id`，不产生投注建议。
- 与 baseline 的变化量按原始高精度值计算，输出注数、票价、百分点和期望断腿差值。

多票联合命中率表示“组内至少一票全对”。计算使用 inclusion-exclusion：任一版本子集的
交集事件，对每场取该子集中所有约束该场的版本之 faces 交集，再把逐场概率相乘；某版本
未包含的场视为无约束。任一场交集为空时该子集概率为零。

共同死面只在组内每票都包含的场上报告：三面中未被任何票覆盖的面即为共同死面。
若某场并非全组共同腿，则不报告，避免把未参赛场误写成结构漏洞。

## 4. 模块与输出

- `nutmeg/decision/zucai_optimizer.py`：输入校验、纯计算、JSON DTO 与文本渲染。
- `nutmeg/interfaces/cli/decision.py`：注册 `zucai-optimize`，只负责读文件、选择文本或
  `--json` 输出及稳定退出码。
- `tests/decision/test_zucai_optimizer.py`：纯函数、边界、26111 三版本回放。
- `tests/decision/test_zucai_optimizer_cli.py`：CLI 文本、JSON 和坏输入。

JSON 输出包含输入期号、注金帽、按输入顺序的 versions、帽内 ranking、
`best_within_cap_id` 和 groups。概率用 0..1 数值，文本表用百分比显示两位小数；JSON
保留足够精度，避免显示舍入反过来影响排序或联合概率。

## 5. 26111 验收锚

使用 26111 已落盘 fair 回放下列候选：

| 版本 | 注数 | 票价 | P(全对) |
| --- | ---: | ---: | ---: |
| U864用户版 | 432 | ¥864 | 24.49% |
| U864优化版 | 432 | ¥864 | 27.96% |
| U1296 | 648 | ¥1,296 | 33.65% |

`budget_yuan=864` 时帽内第一名应为 U864优化版；`budget_yuan=1296` 时应为 U1296。

## 6. 显式排除

- 不搜索组合空间、不自动换血、不从赔率推导 fair。
- 不计算 EV、奖金预测、部署门或投注规模建议。
- 不把“帽内最优”解释为“应该出票”，也不引入空仓判断。
- 不读写生产 `.nutmeg-data`；真实回放只把已有文件中的 fair 复制到临时输入。
- 不改变 `zucai-ticket` 既有算术和审计链。
