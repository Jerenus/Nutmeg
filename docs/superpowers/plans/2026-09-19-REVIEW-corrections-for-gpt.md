# 审查意见 · 给 GPT 5.6 sol（传统足彩专项，Task 1–10 交付后）

> 审查者：Claude Opus 5，2026-09-19。**这四条必须全部完成才算交付；在它们完成前不要开始阶段二（竞彩深研桥）。**
> spec 已按①②更新于提交 `a40dab4`，以新版 `docs/superpowers/specs/2026-09-19-zucai-structure-lane-design.md` 为准。
> 已确认通过：Task 1–10 的功能与测试全绿、`schema v30`、`zucai_commit_capital_plan` 权限只有 `judge_operator`、
> `record_verdict` 仍只读 prospective、`rsi dream` 真跑出三个变体排序、26129 回填幂等（方案 1 条、裁决 2 行）。
> 下面四条是这些之外的缺陷，其中①②③阻塞。

---

## ① `tier_of` 非单调（阻塞）

**文件**：`nutmeg/decision/structure_tiers.py:40`

现状 `if score == 3 and integrity in ("pass", "symmetric_damage"): return "T2"`。
后果：`score=4 + symmetric_damage` 落到 T3（必全包），比 `score=3 + symmetric_damage` 的 T2 **更差**——
牌照四问拿满分的场反因完整度被降级。26129 最高分只有 3，所以没暴露。

**改**：`score >= 3`。

**补测试**（`tests/decision/test_structure_tiers.py`）：
```python
def test_tier_is_monotonic_in_license_score():
    assert tier_of(_leg(lq=LQ4, integrity="symmetric_damage")) == "T2"   # 满分不得因完整度降到 T3
    assert tier_of(_leg(lq=LQ4)) == "T1"                                  # pass + 无 crash 仍是 T1
    assert tier_of(_leg(lq=LQ4, crash=["opening_new_coach_debut"])) == "T3"
```

---

## ② 票级收窄上限缺失（阻塞）

**文件**：`nutmeg/decision/structure_tiers.py`（加常量）、`nutmeg/decision/structure_space.py`（DP 剪枝）

C17 铁律是**票级**「标记 ≤3」，但枚举器只按每场 `TIER_MAX_NARROWINGS` 限制，全票不限。
实测（每场 2 个可收窄面、全 T1 的 14 场稠密板）：`¥400` 前沿 25 点、`¥1200` 前沿 35 点，
**最大收窄数均为 18**。这些点在 B6 `decision-audit-legs` 必然触发 C17 ERROR——
前沿在提供必然被拒的票，「机器枚举、人在前沿上挑」这条链就断了。

**改**：
```python
# structure_tiers.py，与其它矩阵常量同级；不开成参数，改动走 rsi deploy
TICKET_MAX_NARROWINGS = 3
```
```python
# structure_space.py，enumerate_frontier 的 DP 内层
if cell[0] > cap_notes or cell[1] > TICKET_MAX_NARROWINGS:
    continue
```
（`cell` 第二维已经是累计收窄数；原型 `experiments/exp-strict-space.py::enumerate_space` 的 `max_marks` 就是它。）

**补测试**（`tests/decision/test_structure_space.py`）：
```python
def test_frontier_respects_the_ticket_level_narrowing_cap():
    legs = {str(i): _leg((0.72, 0.14, 0.14), d3={"draw": 2, "away": 2}) for i in range(1, 15)}
    for cap in (400, 1200):
        fr = enumerate_frontier(legs, channel="renjiu", cap_yuan=cap, mode="matrix")
        assert fr["points"], f"cap={cap} 不该是空前沿"
        assert max(len(p["narrowings"]) for p in fr["points"]) <= 3
```

---

## ③ `adjudication_ref` 挂空（阻塞，已在真库上验证）

**文件**：`scripts/plan_backfill_26129.py`、`nutmeg/ontology/actions/capital_actions.py`

`record_adjudication` **自己生成** `adjudication_id`；脚本却把 `adj_id`（`override-renjiu-1000-26129`）
同时当 `subject_id` 和资金方案的 `adjudication_ref`。真库实测：

```
adj-157c618a0028435fa9f648a499164fcd   subject=override-renjiu-1000-26129
adj-8726ec0df8ed444db33bfe2a07dfa19f   subject=standing-renjiu-1200
plan.adjudication_ref = "override-renjiu-1000-26129"   → get_adjudication() 抛 NoResultFound
```

「override 必带 `adjudication_ref`」的全部意义是行权要有账可查；引用解析不出东西，规矩就成了装饰。

**改**：
1. `backfill()` 接住每次 `record_adjudication(...)` 返回的 `ActionOutcome`，从 `outcome.result_refs`
   取真正的 `adjudication_id`，用它填 `capital_plan.adjudication_ref` 与 `verdict_refs`；
   `report["adjudications"]` 返回 `{subject_id: adjudication_id}` 映射。
2. 真库那条已写错的方案：用 `supersedes=<旧 plan_id>` **追加一条修正版**，不要改旧行（只追加原则）。
3. `capital_actions.commit_capital_plan` 的 handler 里加一条校验，让这个洞以后开不了：
```python
if request.cap_source == "override":
    uow.workflow.get_adjudication(request.adjudication_ref)   # 取不到就抛，向上变成 ValueError
```
   若 `get_adjudication` 抛的不是 `ValueError` 子类，捕获后 `raise ValueError("adjudication_ref 不指向任何裁决") from exc`。

**补测试**：
- `tests/test_plan_backfill_26129.py`：断言 `report` 里的 ref 能被 `uow.workflow.get_adjudication(ref)` 取到，
  且 `uow.capital.latest_plan("26129").adjudication_ref` 与之相等。
- `tests/ontology/test_capital_plan_actions.py`：`cap_source="override"` 且 `adjudication_ref` 指向不存在的 id
  → `pytest.raises(ValueError)`；指向真裁决 → COMMITTED。

---

## ④ `run_tiers` 不幂等（非阻塞，顺手改）

**文件**：`nutmeg/decision/plan_flow.py::run_tiers`

重复跑 `plan tiers` 会往事件流重复追加同哈希的 `tiers@<hash>` 根节点。
真库 `.nutmeg-data/jczq/daily/2026-09-19/workbench.jsonl` 里 `tiers@70c769afa46f` 已堆到 **4 份**。

**改**：写根节点前扫一遍当天 `candidate` 事件，同 `version` 已存在就跳过（`run_frontier` 的前沿层同理，
同 `frontier_hash` 重复跑不该重复追加）。

**补测试**：同一 `data_dir` 连跑两次 `run_tiers`，断言当天 `tiers@` 事件只有 1 条。

---

## 完成后

```bash
uv run pytest tests/decision/ tests/ontology/ tests/test_cli_plan.py tests/test_cli_rsi.py \
  tests/test_plan_backfill_26129.py tests/test_rsi_migrate_preregs.py -q
```
然后把交接提示词 §3 的全部验收命令输出贴回给用户。四条各自单独提交或合并成一条
`fix(plan): 审查四条——定级单调 / 票级收窄上限 / 裁决引用 / tiers 幂等` 都可以。
