# RSI 判决协议 v2 与实验组合重整 · 执行计划（2026-10-19）

来源：2026-10-19 RSI 深度审核（证据 `docs/superpowers/evidence/2026-10-19-rsi-protocol-v2.md`）。
Jun 同日裁定（原话）：「1，冻结原文为准。2，可以。3，可以。4，也需要登记，作为正样本。 开始工作」。

| 裁定 | 含义 | 落点 |
|---|---|---|
| 1 冻结原文为准 | `Falsifier.evaluate` 按登记的 `bound` 判；「累计 n 场结账」＝在首次够数那一份 grade 上判一次 | A1/A2 |
| 2 rubric r2 | 9 项 propose_zero + F_rotation（反号）上限退役，只记录不拨动；F_suspension 保留 | C |
| 3 实验组合重整 | 审核报告 WP3 表 | B |
| 4 出口登记 | 登记原件写 `exits`（on_survived / on_falsified / on_expired）；**没写出口的照样登记**，标「观察型」作为正样本积累；判决触发出口动作本身也记作 RSI 闭环的正样本 | D |

## A 判决协议 v2（代码）

- A1 `Falsifier.evaluate` 读 `bound`：`lt` → 证伪 ⇔ CI[bound] < t，成立 ⇔ 下界 ≥ t；`gt` → 证伪 ⇔ CI[bound] > t，成立 ⇔ 上界 ≤ t；其余跨线（bound 落在「成立」那一边时自然变二分）。
- A2 单次结账：`record_verdict` 取**首次 n ≥ n_min 的 prospective grade**（结算 grade）判一次，快照写 `protocol=v2-frozen-text` + 结算 grade；已有 v2 判决 → 拒绝；旧协议（每日重判）的判决行保留作历史。幂等键 `rsi-verdict-v2:<exp>`。
- A3 CI 确定性：残差先排序再自助、`_rows_hash` 按 key 排序——同一批样本永远同一个 CI。
- A4 前瞻门：依赖判断的实验（F9/F11/F13/F14/F18/K1 及新登记）只收 `provably_prospective is True` 的行（K1 收 `rubric_b.prospective`）。纯市场残差实验（F10/F15/F16/F17）不需要。
- A5 F9 竞彩泳道 `belief_moved` 改为 belief vs Read 的 prior（不是当前 fair）。
- A6 闭环：F18 进结账清单；已结账实验不再判；只有 `MONITORS`（F9）结账后继续每日 grade；判决行带实验号；judgment 层不再提示 deploy；覆盖测试——每个未退役的登记实验要么在结账清单，要么在 `UNGRADED` 里写明原因。
- A7 grade 幂等键加上 `computed_by` 与指标值摘要（适配器改了不再重放旧 grade）。

## B 实验组合（内核动作，Jun 授权、主循环代执行，`--by Jun`）

| 实验 | 动作 |
|---|---|
| F14 | v2 重判：10-12 首次够数 n=77 CI[−3.61,+14.05] → falsified；另立 **F14b**（表态 − 市场同尺寸 top-k 逐场配对，按日聚类） |
| F11 | v2 重判：10-17 n=80 CI[−35.14,+0.07] → falsified → 按原文 C19 永久退休（RULEBOOK/分析员定义） |
| F9 | v2 结账＝10-10 inconclusive（不变）；之后只做有害监测（MONITORS） |
| K1 | v2 结账＝10-08 survived（合并 κ，不变）；另立 **K2**（逐项 κ） |
| F13 / F15 / F16 / F8 / G1 | 退役（F16 保留台账义务——损耗列要用） |
| F5 | 冻结原文窗口 26129–26140 已过、n<120 → 退役（保留 price-band 义务——日报漂移列要用） |
| R0 / R1 | 不退役（义务驱动每日深研）；修正案记「运维覆盖率指标，不判决」，进 `UNGRADED` |
| F18 | 接进结账清单（只差一行）；分析包许可证列标「未证」 |
| F19 | 价内/未价未对象化 → `UNGRADED`（待 packet §1 列入库） |
| F10 / F17 / CR2 | 保留 |

退役需要「保留义务」：`rsi deploy --retire --keep-duties`（理由里写明哪个产物还在被谁读）。

## C rubric r2

- `Item.cap_until`：上限退役的版本；`cap_at(version)`；`DIRECTIONAL_ITEMS` 只算当前版本 cap>0 的项（聚合用），`EFFECT_ITEMS` 算有效应的项（T13 逐项结账继续测）。
- `RUBRIC_VERSION=r2`，`SUPPORTED_VERSIONS=(r1,r2)`（问题表一字未改，答案可比）；changelog 一条；RULEBOOK「九」表与说明更新。

## D 出口与收件箱

- 登记原件可选字段 `exits`（不进冻结哈希）：`on_survived / on_falsified / on_expired` 各一个动作（`rubric_cap:<id>` / `rule:<id>` / `packet_column:<col>` / `display_only` / `retire_rule:<id>` / `none`）；缺 → 登记照收，打印「观察型」并在 status 标注。
- 现役实验补 `exits`（非冻结字段，加修正案留痕）。
- 待决收件箱：`rsi inbox`——固定 ID、起始日、积压天数、默认动作、可执行命令；闭环报告「待人决定」改读它；只列能执行的动作。
- T13：rubric 因子 propose_zero → 若该项当前版本 cap>0 生成「cap→0」提案；往上调的提案标「不可执行（只许下调）」。

## E 工程收敛（后续批次）

闭环步骤依赖门控、F1c/F2 死代码、过期告警去重、`as_of` 时区比较、样本账只追加+锁、语料不每日进 git、`decision_samples_build` 走单一来源、ARCHITECTURE §5 / /observe / method 页刷新。
