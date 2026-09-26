# strength-v2：判断层改为「强弱天平」、规则降为提示 · 实施方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Nutmeg 的判断目标从「逐面生死（310）」改为「两队最终强度对比」，赔率降为噪声识别器与情绪参考，规则体系只保留有死亡记录的硬门，其余降为提示。

**批准：** Jun 2026-09-26 口头批准「1、2 都做，不用影子跑，直接按最终目标改造」。宪法变更由此授权。

**Architecture:** 判断仍由主循环/深研 agent 产出（判断永不入脚本），代码只改三处判据：①Read 拨动算术不再 <5pp 归零、允许多面位移；②审计门 ERROR 只留硬门（C1 + 新 C19），其余降 WARN；③事实层面集不再强制写入票面，前沿新增 `belief` 模式按判断概率在帽内最大化 P。

**Tech Stack:** Python 3.13 / typer CLI / pytest；数据在 `.nutmeg-data/`。

---

## 背景与证据（为什么改）

- 宪法第一序「机制活→盖住或丢整场」+ 死亡三证 3/3 几乎凑不齐 → 26125–26128、26132、26133 连续帽内零解；规则只在说「不能打」。
- 已被自家闭环证伪立论、动作仍在否决的码：C5/C13（锚方完整度 n=70 零预测力）、C4（conf 控价后各档 CI 含 0）、C7（训练+12pp→测试−0.7pp）、C17（「第三面更容易开」n=130 证伪）。
- l-归零（<5pp 归零）+ form=0pp → 深研每期「同意市场」，belief≡prior，F9 测不出任何东西（RUNBOOK：「BSS 恒为 0 不是没技艺是没表达」）。
- 保留的硬门都有死亡记录：研究点名保险却裸单（26128 场14、26132 场2/场11）、方向旗裸单（26098/26101/26102/26103 四票）、多票共享裸单/被排面（26118/26122/26129）。

## 新判断口径（写进宪法 §2）

1. **第一序·强弱天平**：每场产出双方本场真实强度（阵容/状态）、风格对位、战术剧本、**弱势方取胜路径是否成立（路径/强度）**、利好利空事件分级（事件、受益方、程度、是否已被价格吸收）。结论 = 方向 + 程度。
2. **赔率是噪声识别器**：判断与价格一致 → 正常表达；不一致 → 追问「市场看到了什么」，查因后认定情绪则坚持、认定信息则修正；已被位移吸收的事件不重复计。
3. **第二序·P 定结构**：帽内按**判断概率**最大化 P(全对)；EV 仍禁入决策层。
4. **第三序不变**：奖池只破平局。
5. 空仓仍合法；注金与刹车、数据纪律、裁决协议不变。

## 文件结构

| 文件 | 职责 | 改动 |
|---|---|---|
| `nutmeg/decision/stance.py` | 表态校验与拨动算术 | 去掉 <5pp 归零；新增 `shift` 多面位移；词典加强弱类事件 kind；新增 `state` 档（0–3pp） |
| `nutmeg/decision/legs_audit.py` | 审计门 | C2/C3/C4/C5/C17 降 WARN；新增 C19 `research_cover_naked`（ERROR） |
| `nutmeg/decision/research_intake.py` | 深研→legs 入库桥 | 转录 `research_stance` 与 `strength_balance` |
| `nutmeg/decision/face_status.py` | 第一序面状态 | 书面 faces 与活面集不一致不再抛错，改记 `faces_vs_alive` |
| `nutmeg/decision/structure_space.py` + `plan_flow.py` | 前沿枚举 | 新增 `belief` 模式（硬门过滤 + 判断概率），`plan frontier` 默认用它，旧 matrix/strict 作对照 |
| `nutmeg/decision/research_prompt.py` + `.claude/agents/jczq-match-analyst.md` | 深研契约 | 加强弱天平块 |
| `docs/sop/CONSTITUTION.md` / `RULEBOOK.md` / `RUNBOOK.md` | SOP 三件套 | 按上述口径改写；RULEBOOK 规则三分（硬门/提示/退休） |

## 任务

### Task 1: 拨动算术去归零 + 多面位移（stance.py）

- [ ] 测试 `tests/decision/test_stance.py` 新增：
  - `apply_tilt(prior, {"face":"3","evidence":[{"tier":"inferred","kind":"style_matchup","pp":2,...}]})` → `applied_pp == 2`、`zeroed is False`、主胜 +2pp。
  - `apply_tilt(prior, {"shift":{"3":-1,"1":3,"0":-2},"evidence":[...]})` → belief = prior + shift/100，和为 1。
  - shift 不和为 0 → `validate_stance` 报 ERROR；单面 |shift| 超上限（无官宣 10 / 有官宣 15）→ 截断并在 reason 注明。
- [ ] 实现：删除 `ZERO_BELOW_PP` 归零分支（常量保留为 0 以兼容引用）；`TIER_PP` 加 `"state": (0, 3)`；`TILT_KIND_LEXICON` 加 `style_matchup / underdog_path / form_state / travel_fatigue / coach_debut / pitch_condition / squad_depth / priced_drift`；`apply_tilt` 支持 `shift`。
- [ ] 跑 `uv run pytest tests/decision/test_stance.py -q` 全绿；提交。

### Task 2: 审计门三分（legs_audit.py）

- [ ] 测试 `tests/decision/test_legs_audit_strength_v2.py`：
  - conf3 裸单 → `low_conf_single` 级别 WARN（原 ERROR）。
  - 锚方 FAIL 裸单 → `broken_anchor_single` WARN；弃模态 → `modal_face_dropped` WARN；旗面未盖 → `flag_face_uncovered` WARN；C17 → WARN。
  - 方向旗裸单 → `flagged_naked_single` 仍 ERROR。
  - legs 带 `research_stance.structure in ("double","full")` 且票面裸单 → 新码 `research_cover_naked` ERROR；structure=single 裸单不报。
- [ ] 实现：上述码级别改 WARN；新增 C19 检查（缺 `research_stance` 字段不报，只 INFO）。
- [ ] 回归 `uv run pytest tests -q -k "audit or legs"`；修正依赖旧级别的断言（只改级别断言，不删测试）；提交。

### Task 3: 入库桥转录研究表态与强弱天平（research_intake.py）

- [ ] 测试：研究 JSON 带 `stance` 与 `strength_balance` → 写入 legs 的 `research_stance={face,structure,cover,confidence}` 与 `strength_balance`（原样）。
- [ ] 实现并提交。

### Task 4: 事实层面集不再强制票面（face_status.py）

- [ ] 测试：书面 faces=`31` 而活面集 `310` → 不抛错，legs 保留 `31`，`faces_vs_alive = {"written":"31","alive":"310"}`。
- [ ] 实现：`attach_face_status` 不再 raise，记录后以书面为准（无书面则用活面集）；提交。

### Task 5: 前沿 belief 模式（structure_space.py / plan_flow.py / CLI）

- [ ] 测试：belief 模式下每场选项 = 全部非空面子集，裸单只在 `research_stance.structure=="single"` 且无方向旗时出现；覆盖率用 legs `fair`（=belief）；不受 `TIER_MAX_NARROWINGS`/`TICKET_MAX_NARROWINGS` 约束；帽内按 P 降序、第三序破平。
- [ ] 实现：`cover_options(mode="belief")`；`enumerate_frontier` 在 belief 模式跳过 narrowing 计数；`run_frontier` 输出 `belief` 前沿为主，并附 `matrix/strict` 的 max_p 作旧规则对照；提交。

### Task 6: 深研契约加强弱天平块

- [ ] `research_prompt.RESEARCH_JSON_CONTRACT` 与 `.claude/agents/jczq-match-analyst.md` 增加：
  `"strength_balance": {"verdict": "home_clear|home_edge|even|away_edge|away_clear", "home_state": str, "away_state": str, "style_matchup": str, "tactical_scenarios": [str], "underdog_path": {"side": "home|away", "exists": bool, "routes": [str], "strength": "none|weak|real|strong"}, "events": [{"event": str, "side": "home|away", "direction": "up|down", "grade": "minor|moderate|major", "pp": int, "priced_in": bool, "source": str}]}`；
  stance.tilt 可用 `shift` 表达多面位移；form/状态可计 `state` 档 0–3pp。
- [ ] 契约测试（若有 `tests/decision/test_research_prompt.py`）更新；提交。

### Task 7: SOP 三件套改写

- [ ] CONSTITUTION §2 按「新判断口径」改写；§6 裁决协议删「WARN 逐条裁决」要求（WARN 只记账）。
- [ ] RULEBOOK 新增「规则三分表」：硬门 ERROR（C1、C19、C15/C15b 保持 WARN 但列为重点）；提示 WARN（C2–C14、C17、C18、l-权重表上限）；退休（l-归零、死亡三证作为排面前置、B5c 矩阵作为出票前置）。每条注明依据（闭环证伪/死亡记录）。
- [ ] RUNBOOK B3/B4/B5/B5c/B6、A2–A5 改为：深研产强弱天平 → 主循环写 belief（事件分级）→ `plan frontier`（belief 模式）→ 审计门只拦 ERROR。
- [ ] 提交。

### Task 8: 26133 按新框架重跑

- [ ] 判读文件写 belief（强弱天平结论）→ `zucai-build-reads` → `zucai-research-intake --write` → `decision-read` → `plan frontier`（belief）→ 审计 V2 票面 0 ERROR。
- [ ] 票面待 Jun 裁决；入账与 rx 预注册在出票后。

## 自查

- 覆盖：宪法口径（T7）、归零（T1）、规则三分（T2/T7）、强弱输出（T3/T6）、票面自由度（T4/T5）、当期应用（T8）。
- 测量：belief≠prior 自然进入 F9 与语料 v2；不设影子期（Jun 裁定）。
