# 审查意见 · 第二轮：每场都必须有判断（R2 / R3 / F8 / F9）

> 审查者：Claude Opus 5，2026-09-19。用户裁定：**每一场比赛都需要有判断，不能因为没有线索就放弃，否则实验的意义就没了。**
> spec 已更新于提交 `2d33411`：`docs/superpowers/specs/2026-09-19-jczq-board-research-bridge-design.md`（R2/R3）、
> `docs/superpowers/specs/2026-09-19-zucai-structure-lane-design.md`（§4.2.1 更正、§6 新增 F8）。
> 阶段一、二已验收通过；阶段三 Task 1 已通过。**这三条插在阶段三之前做**，因为 R2 决定明天起每天入样是 26 条还是 1 条。

## 数据依据（先看这个，别跳过）

```
竞彩板 2026-09-19：26 场，judgment_tier = {price_only: 25, deep_research: 1}
                   reads.json 条数 = 1   → 25 场一条判断都没有
历史判死面：294 个面里判死 10 个 = 3.4%
            26122/26123/26124/26126/26129 五期 = 0，而 26129 那 14 场是全部深研过的
```

---

## R2 每场都出 Read（阻塞，最重要）

**文件**：`nutmeg/decision/jczq_reads.py::build_jczq_reads`

现状：只为 `judgment_tier == "deep_research"` 且有 `face_status` 的 leg 产 Read，
于是 25 场被预算/开球/拒收挡掉的比赛**没有任何判断**，判读层实验对它们永远零贡献。

**改**：为板上**每一场**产一条 Read。

| 情形 | judge | belief | confidence | judgment_tier |
|---|---|---|---|---|
| 研到且 intake 通过 | `ai:jczq-analyst` | 活面按 fair 归一（现状不变） | 研究给的 | `deep_research` |
| 没研到 / 被拒 / 超预算 / 过开球 | `market-anchor` | **= prior（原样跟市场）** | `1` | `price_only` |

两者 `status` 均为 `"draft"`，都经 `ontology_adapter` 落库等人 approve。
`market-anchor` 不以 `ai:` 开头，按你已写的分流会走 `commit_forecast` + `JUDGE_OPERATOR`——
**这不对**，它同样是机器产物、同样该等人批。请把分流条件改成 `status == "draft"`（判据只看 status，
不看 judge 前缀），并把 `market-anchor` 的 actor 也设成 `ActorRole.AI_ANALYST`。

⛔**理由写进代码注释**：「跟市场」是宪法 §2 推论明文的判断——「市场锚定（无命名理由＝跟市场）」——
它是一句可被 Brier 评分的可证伪陈述，不是判断的缺席。判断永远存在，变的是**强度**；
强度决定结构（能不能收窄），不决定要不要判。

**补测试**（`tests/decision/test_jczq_reads.py`）：
```python
def test_every_board_match_gets_a_read_even_without_research():
    # 板上 3 场，只有 1 场有 research-<code>.json
    reads = build_jczq_reads(day=..., jczq_dir=..., made_at=...)
    assert len(reads) == 3
    researched = [r for r in reads if r["judge"] == "ai:jczq-analyst"]
    anchored = [r for r in reads if r["judge"] == "market-anchor"]
    assert len(researched) == 1 and len(anchored) == 2
    assert all(r["status"] == "draft" for r in reads)
    a = anchored[0]
    assert a["belief"] == a["prior"] and a["confidence"] == 1 and a["judgment_tier"] == "price_only"
```
`tests/decision/test_read_adapter.py` 补一条：`judge="market-anchor"` + `status="draft"` → 走
`draft_forecast` + `AI_ANALYST`（不是 commit）。

---

## R3 `face_status.basis`（阻塞）

**文件**：`nutmeg/decision/face_status.py::attach_face_status`

加字段 `basis ∈ {"researched", "default"}`：
- `attach_face_status(leg, research, source=..., basis="researched")`——由 intake 路径传入。
- 没有研究产物时由调用方写 `basis="default"`（或函数在 `research` 为空字典时自动判 `default`）。

⛔**为什么**：此前「研究过、机制上杀不掉任何面」与「压根没看」字段完全一样，
F6 统计「T3 必全包」时会把两类混成一格，样本被污染。实验按 `basis` 分层，**不许合并**。

**补测试**：研究为空 → 三面 `basis == "default"`；有研究 → `"researched"`；
`derive_faces` 与 dead 判定逻辑不受 basis 影响。

---

## F8 死亡三证门槛实验（阻塞的只是"登记"，重放留待样本成形）

**新建** `experiments/registry/F8.json`：

```json
{
  "exp_id": "F8",
  "claim": "死亡三证要求 3/3 的门槛过严，使第一序几乎不产生结构；放宽到「两证 + 被排面 fair ≤ X%」不会让被排面兑现率显著变差。",
  "mechanism": "三证齐是 26118 之后立的高标准，本意是防「崩塌叙述越完整越不崩」。但全历史 294 个面只判死 10 个(3.4%)，26122-26126/26129 五期为 0，而 26129 那 14 场是全部深研过的——门槛高到任九恒空前沿（票级上限 3 下最省 2³×3⁶=5,832 注）。",
  "tier": "candidate", "layer": "structural", "population": "zucai", "min_tier": "deep_research",
  "window": {"date_from": "2026-09-20", "n_min": 120},
  "falsifier": {"metric": "excluded_face_hit_resid_pp", "stratum": "zucai", "n_min": 120,
                "bound": "ci_upper", "threshold_pp": 2.0, "direction": "gt_means_falsified"},
  "stop_rule": "放宽档的被排面兑现率 ci_upper 高于现行档 +2pp 即证伪（说明放宽会多杀活面）。⛔在此之前不得改三证定义。",
  "quota_slot": false,
  "buckets": ["三证 3/3（现行）", "两证 + fair≤10%", "两证 + fair≤15%"],
  "rule_ids": ["C14"],
  "replay_spec": {"harness": "nutmeg.decision.rsi_grading:death_proof_threshold_harness",
                  "corpus": ".nutmeg-data/zucai/*-legs-base.json",
                  "variants": [{"proofs": 3, "max_fair": 1.0},
                               {"proofs": 2, "max_fair": 0.10},
                               {"proofs": 2, "max_fair": 0.15}]},
  "source_doc": "docs/superpowers/specs/2026-09-19-zucai-structure-lane-design.md",
  "registered_at": "2026-09-19"
}
```

**只做登记 + 一个 harness 桩**，重放等历史 legs-base 带上 `face_status` 后再接：
`nutmeg/decision/rsi_grading.py` 加 `death_proof_threshold_harness(rows, variant) -> ResidualCI`——
对每个「按变体判死的面」算 `(实开 − fair)`，没有匹配行时返回 `ResidualCI(0,0,0,0)`。
补测试：三个变体在构造样本上 `variants_tried == 3` 且判死集合随变体单调变大。

⛔**F8 是实验不是修补**：在它给出前瞻证据并经 `rsi deploy` 之前，
`face_status` 的 dead 判定（三证 3/3）与 `TICKET_MAX_NARROWINGS = 3` **一个字都不许改**。

---

## F9 天平位移账（阻塞；用户 2026-09-19 裁定新立）

**数据依据（先看）**：
```
446 场判读，belief 拨离 prior 的只有 40 场 = 9.0%
26110 之后 22 期、308 场 —— 一次都没拨动过
26129 全部 14 场深研，belief 与 prior 逐场完全相等
```
后果：Brier vs 市场恒等于 0——不是没技艺，是**没有表达**；F1c/F2 测的其实是市场结构不是我们的判断力。
用户的目标是「做天平强弱的判断」，那么**天平被拨动了几次、拨对没有**就必须有账。

**新建** `experiments/registry/F9.json`：
```json
{
  "exp_id": "F9",
  "claim": "判读层拨动天平（belief ≠ prior）的场次，其 Brier 优于直接跟市场。",
  "mechanism": "拨动是判读层唯一能表达强弱的通道；若拨动无价值，则整套证据工厂对天平没有贡献，判读层实验测的只是市场结构。",
  "tier": "observation", "layer": "judgment", "population": "both", "min_tier": "price_only",
  "window": {"date_from": "2026-09-20", "n_min": 60},
  "falsifier": {"metric": "brier_delta_vs_market_moved_pp", "stratum": "pooled", "n_min": 60,
                "bound": "ci_upper", "threshold_pp": 0.0, "direction": "lt_means_falsified"},
  "stop_rule": "累计拨动场 n>=60 结账；ci_upper < 0 即证伪（拨动是负价值）。拨动数今天是 0，n 要靠以后真的拨动才涨——这正是本实验的意义。",
  "quota_slot": false,
  "buckets": [], "rule_ids": [],
  "source_doc": "docs/superpowers/specs/2026-09-19-zucai-structure-lane-design.md",
  "registered_at": "2026-09-19",
  "duties": [{"name": "balance-ledger", "scope": "day", "deadline_rule": "earliest_kickoff",
              "instrument": ["uv", "run", "nutmeg", "rsi", "balance", "--issue", "{issue}"],
              "artifact_glob": ".nutmeg-data/zucai/{issue}-balance.json",
              "description": "F9：每期天平位移账"}]
}
```

**实现**：
1. `nutmeg/decision/balance_ledger.py`（纯函数，零 IO）：
```python
BALANCE_MOVE_EPS_PP = 0.05          # 冻结常量；改动走 rsi deploy

def balance_row(read: dict) -> dict:
    """单条 Read 的天平位移：shift_pp / moved / moved_face。belief 或 prior 缺就 moved=False。"""

def balance_ledger(reads: list[dict], outcomes: dict | None = None) -> dict:
    """{n_matches, n_moved, moved_pct, mean_abs_shift_pp, max_shift_pp,
        brier_vs_market_moved, brier_vs_market_all, direction_right_n, direction_wrong_n}
       outcomes 为 None（未开奖）时后四项为 None。"""
```
   Brier 相对市场 = `brier(belief, actual) - brier(prior, actual)`，**负数=比市场好**。
2. CLI `nutmeg rsi balance --issue <期> [--day <日>]`：读 `<issue>-reads.json`（+ `official-results.json` 若已开奖）
   → 写 `<issue>-balance.json` → 调 `rsi fulfill --exp F9`。竞彩用 `--day` 读当日 `reads.json`。
3. 接线：`after_settle` 里在 `rsi grade` 之前先跑一次 `rsi balance`（结算当期就有带赛果的账）。
4. 观察台全景页 **首屏第一个数字**就是它：`本期天平 n_moved/n_matches · 平均偏移 X.XXpp · 方向 对/错`；
   无数据时显示「本期天平未拨动（0/14）」——**这个零要显眼，不要藏**。

**补测试**（`tests/decision/test_balance_ledger.py`）：
- `belief == prior` 逐场 → `n_moved == 0`、`moved_pct == 0.0`、`max_shift_pp == 0.0`；
- 构造 1 场偏移 6pp 且该面开出 → `direction_right_n == 1`、`brier_vs_market_moved < 0`；
- 偏移 6pp 但该面没开 → `direction_wrong_n == 1`、`brier_vs_market_moved > 0`；
- `outcomes=None` → 后四项为 `None` 而不是 0；
- 真数据冒烟：`balance_ledger(json.load(open('.nutmeg-data/zucai/26129-reads.json')))` → `n_moved == 0, n_matches == 14`。

⛔**F9 只记账不判断**：它不建议该不该拨，只回答「这一期我们有没有说出一句市场没说的话、说对没有」。

## 完成后

```bash
uv run pytest tests/decision/ tests/ontology/ tests/test_cli_research.py tests/test_cli_plan.py \
  tests/test_cli_rsi.py tests/test_rsi_migrate_preregs.py -q
uv run nutmeg rsi register experiments/registry/F8.json
uv run nutmeg rsi register experiments/registry/F9.json
uv run nutmeg rsi balance --issue 26129                  # 应报 0/14 拨动
uv run nutmeg jczq-build-reads --day 2026-09-19        # reads.json 条数应 == 板面场数(26)
uv run nutmeg rsi status                                # 应出现 F8
```
把 `reads.json` 的 `judge` 分布与 `rsi balance --issue 26129` 的输出贴回报告。
**四条**做完再继续阶段三 Task 3。
