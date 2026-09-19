# 传统足彩专项（结构层）Implementation Plan · Part 1（Task 1–5）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把泳道 B 的 B5–B9 做成对象流：`face_status`（第一序）→ 定级与风向（B5c 矩阵）→ 枚举前沿（第二序）→ 人挑 → `zucai_capital_plan`（内核）→ F4 自动结账；聊天窗口里不再出现票面。

**Architecture:** 三个纯函数模块（`face_status.py` / `structure_tiers.py` / `structure_space.py`，零 IO，最重的测试在这里）+ 一个内核 typed Action（`zucai_commit_capital_plan`，仅 judge_operator）+ CLI 子组 `nutmeg plan`（tiers / frontier / choose / commit / status）+ 候选树自动生长（既有 `append_candidate(parent_version=…)`）+ F4 适配器接进 `rsi grade`。矩阵阈值是模块常量，只能经 `rsi deploy` 改。

**Tech Stack:** Python 3.13 / SQLAlchemy Core / typer / pytest。Spec：`docs/superpowers/specs/2026-09-19-zucai-structure-lane-design.md`。RSI 层已落地（`nutmeg/ontology/rsi`, `actions/rsi_actions.py`, `cli/rsi.py`, `decision/rsi_grading.py`）。

**仓库纪律（每任务适用）：** `git add` 只用显式路径；提交不接管道，`echo "EXIT=$?"` 后 `git log --oneline -1` 复验；提交期间不编辑文件；碰 `nutmeg/ontology/**`/`nutmeg/interfaces/web/**`/`nutmeg/product/**` 的提交钩子要跑数分钟，提交前 `memory_pressure` 看内存；测试一律 `tmp_path`，不碰 `.nutmeg-data/`。

---

## 文件结构

- Create `nutmeg/decision/face_status.py` — 三态派生（研究 JSON + judgment-v1 → `face_status`），`faces` 一致性校验
- Modify `nutmeg/interfaces/cli/zucai.py::zucai_build_reads` — 写 legs-base 前调用 `attach_face_status`
- Create `nutmeg/decision/structure_tiers.py` — B5c 矩阵常量、每场定级、可收窄面、今日风向
- Create `nutmeg/decision/structure_space.py` — 枚举器（矩阵模式 / strict 模式）、前沿、hash、第三序排序 key
- Create `nutmeg/decision/plan_flow.py` — tiers / frontier / choose 的文件与候选树写入（薄编排层）
- Create `nutmeg/interfaces/cli/plan.py`；Modify `nutmeg/interfaces/cli/__init__.py`
- Part 2：`schema_capital.py` + 迁移 v30 + `repository/capital.py` + `actions/capital_actions.py` + `plan commit/status` + F4 适配器 + `rsi dream` CLI + sopbar + 26129 回填 + RUNBOOK
- Tests：`tests/decision/test_face_status.py`、`test_structure_tiers.py`、`test_structure_space.py`、`test_plan_flow.py`、`tests/test_cli_plan.py`

---

### Task 1: `face_status` —— 第一序落成字段

**Files:**
- Create: `nutmeg/decision/face_status.py`
- Modify: `nutmeg/interfaces/cli/zucai.py`（`zucai_build_reads`，在写 legs-base 之前）
- Test: `tests/decision/test_face_status.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_face_status.py
import pytest

from nutmeg.decision.face_status import FaceStatusError, attach_face_status, derive_faces

_PROOFS_ALIVE = {"a_no_scoring_mechanism": False, "b_precedent_carrier_gone": False,
                 "c_anchor_pass": False, "proof_count": "0/3", "verdict": "alive", "detail": "…"}
_PROOFS_DEAD = {"a_no_scoring_mechanism": True, "b_precedent_carrier_gone": True,
                "c_anchor_pass": True, "proof_count": "3/3", "verdict": "dead", "detail": "…"}
_PROOFS_2OF3_DEAD_CLAIM = {**_PROOFS_DEAD, "b_precedent_carrier_gone": False,
                           "proof_count": "2/3", "verdict": "dead"}


def _research(**faces):
    return {"death_three_proofs": {f: faces.get(f, _PROOFS_ALIVE) for f in ("home", "draw", "away")}}


def _leg(faces="310", precedents=None, never=None):
    leg = {"faces": faces, "fair": {"home": 0.5, "draw": 0.25, "away": 0.25},
           "precedents": precedents or []}
    if never is not None:
        leg["never_faces"] = never
    return leg


def test_dead_requires_three_proofs_and_faces_becomes_derived():
    leg = _leg(faces="31")
    attach_face_status(leg, _research(away=_PROOFS_DEAD), source="26129-research-m3.json")
    fs = leg["face_status"]
    assert fs["away"]["state"] == "dead" and fs["home"]["state"] == "alive"
    assert fs["away"]["source"] == "26129-research-m3.json#death_three_proofs.away"
    assert derive_faces(fs) == "31" and leg["faces"] == "31"


def test_dead_claim_without_three_proofs_is_an_error_not_a_downgrade():
    leg = _leg(faces="31")
    with pytest.raises(FaceStatusError, match="3/3"):
        attach_face_status(leg, _research(away=_PROOFS_2OF3_DEAD_CLAIM), source="x")


def test_missing_proofs_mean_alive_burden_is_on_death():
    leg = _leg(faces="310")
    attach_face_status(leg, {"death_three_proofs": {}}, source="x")
    assert all(v["state"] == "alive" for v in leg["face_status"].values())


def test_never_only_from_explicit_declaration_not_from_no_precedent():
    leg = _leg(faces="31", precedents=[["0", "查无先例", "none"]])
    attach_face_status(leg, _research(), source="x")
    assert leg["face_status"]["away"]["state"] == "alive"           # none ≠ never
    assert leg["face_status"]["away"]["precedent"] == "none"
    leg2 = _leg(faces="31", never=["away"])
    attach_face_status(leg2, _research(), source="x")
    assert leg2["face_status"]["away"]["state"] == "never"


def test_hand_written_faces_that_disagree_with_derivation_are_an_error():
    leg = _leg(faces="3")                                            # 人写裸单
    with pytest.raises(FaceStatusError, match="faces"):
        attach_face_status(leg, _research(), source="x")             # 但三面全活 → 派生 310
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_face_status.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nutmeg.decision.face_status'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/face_status.py
"""第一序落成字段：每场每面 alive / dead / never。

规则（spec §4.1）：
- dead ⇔ 研究 verdict == "dead" 且三证 3/3；宣告死但三证不齐 → 错，不是降级。
- never 只许 judgment-v1 显式声明（leg["never_faces"]），不从任何字段推导——
  尤其不从 precedent == "none"（C14：查无先例是举证缺席，不是死亡证明）。
- 其余一律 alive；字段缺失 = alive（举证责任在死的一方）。
- faces 变派生；人写的 faces 与派生值不一致 → 错（26114：改买面违 C8 该在这里被拦）。
"""
from __future__ import annotations

FACES = ("home", "draw", "away")
FACE_DIGIT = {"home": "3", "draw": "1", "away": "0"}
_PROOF_KEYS = (("a_no_scoring_mechanism", "a"), ("b_precedent_carrier_gone", "b"), ("c_anchor_pass", "c"))


class FaceStatusError(ValueError):
    pass


def _proofs(doc: dict | None) -> dict[str, bool]:
    doc = doc or {}
    return {short: bool(doc.get(long, doc.get(short, False))) for long, short in _PROOF_KEYS}


def _precedent_status(leg: dict, face: str) -> str:
    digit = FACE_DIGIT[face]
    statuses = {str(p[2]) for p in leg.get("precedents") or []
                if len(p) >= 3 and str(p[0]) == digit}
    if "alive" in statuses:
        return "alive"
    if "dead" in statuses:
        return "dead"
    return "none"


def derive_faces(face_status: dict) -> str:
    return "".join(FACE_DIGIT[f] for f in FACES if face_status[f]["state"] == "alive")


def attach_face_status(leg: dict, research: dict, *, source: str) -> dict:
    """就地给 leg 加 face_status，并把 faces 校验为派生值。返回 face_status。"""
    d3 = (research or {}).get("death_three_proofs") or {}
    never = set(leg.get("never_faces") or [])
    out: dict[str, dict] = {}
    for face in FACES:
        doc = d3.get(face)
        proofs = _proofs(doc)
        count = sum(proofs.values())
        verdict = str((doc or {}).get("verdict") or "alive").lower()
        if face in never:
            state = "never"
        elif verdict == "dead":
            if count < 3:
                raise FaceStatusError(
                    f"{face} 宣告 dead 但三证只 {count}/3——死面必须三证齐，不齐只能叫被削弱")
            state = "dead"
        else:
            state = "alive"
        out[face] = {"state": state, "proofs": proofs,
                     "precedent": _precedent_status(leg, face),
                     "source": f"{source}#death_three_proofs.{face}"}
    derived = derive_faces(out)
    written = str(leg.get("faces") or "")
    if written and "".join(sorted(written)) != "".join(sorted(derived)):
        raise FaceStatusError(
            f"人写的 faces={written!r} 与三态派生 {derived!r} 不一致——改买面必须先改判读")
    leg["face_status"] = out
    leg["faces"] = derived
    return out
```

在 `nutmeg/interfaces/cli/zucai.py::zucai_build_reads` 里，找到写 legs-base 的那行（`grep -n "legs-base" nutmeg/interfaces/cli/zucai.py`），在它之前加：

```python
    # 第一序落成字段（spec 2026-09-19 §4.1）：从研究 JSON 派生三态，并把 faces 校验为派生值
    from nutmeg.decision.face_status import FaceStatusError, attach_face_status
    research_dir = Path(store_ids_file).parent
    for no, leg in result.legs_base["legs"].items():
        rp = research_dir / f"{issue}-research-m{no}.json"
        research = _json.loads(rp.read_text("utf-8")) if rp.exists() else {}
        try:
            attach_face_status(leg, research, source=rp.name)
        except FaceStatusError as exc:
            _cli.typer.echo(f"❌ 场{no}: {exc}")
            raise _cli.typer.Exit(code=1) from exc
```
（`result.legs_base` 是 `read_builder.build` 返回体里的 legs-base 字典；若属性名不同，用 `grep -n "legs_base" nutmeg/decision/read_builder.py` 找真名。`store_ids_file`、`issue`、`_json` 都是该命令已有的局部名。）

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_face_status.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
uv run ruff check nutmeg/decision/face_status.py nutmeg/interfaces/cli/zucai.py tests/decision/test_face_status.py
git add nutmeg/decision/face_status.py nutmeg/interfaces/cli/zucai.py tests/decision/test_face_status.py
git commit -m "feat(plan): face_status——第一序落成字段，dead 必三证齐，faces 变派生"
```

---

### Task 2: 定级与今日风向（B5c 矩阵的机器读法）

**Files:**
- Create: `nutmeg/decision/structure_tiers.py`
- Test: `tests/decision/test_structure_tiers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_structure_tiers.py
from nutmeg.decision.structure_tiers import (
    C14_CHEAP_LINE,
    C14_VARIANCE_LINE,
    board_wind,
    license_score,
    narrowable_faces,
    tier_of,
)

LQ4 = {"q1_spine": True, "q2_route": True, "q3a_opponent_scores": False, "q4_no_context_flag": True}
LQ3 = {**LQ4, "q4_no_context_flag": False}


def _fs(**states):
    return {f: {"state": states.get(f, "alive"), "proofs": {"a": False, "b": False, "c": False},
                "precedent": "none", "source": "x"} for f in ("home", "draw", "away")}


def _leg(lq=LQ4, integrity="pass", crash=(), fair=(0.6, 0.25, 0.15), d3=None, fs=None):
    d3 = d3 or {}
    return {"license_questions": lq, "anchor_integrity": integrity, "crash_markers": list(crash),
            "fair": dict(zip(("home", "draw", "away"), fair)),
            "_d3": {f: {"a": c >= 1, "b": c >= 2, "c": c >= 3} for f, c in d3.items()},
            "face_status": fs or _fs()}


def test_license_score_reads_four_questions_not_q3b():
    assert license_score(LQ4) == 4 and license_score(LQ3) == 3
    assert license_score({**LQ4, "q3a_opponent_scores": True}) == 3      # 对手能进球 → ③不成立


def test_tiers_follow_the_b5c_matrix():
    assert tier_of(_leg()) == "T1"
    assert tier_of(_leg(crash=["opening_new_coach_debut"])) == "T3"        # 有翻车标记不许裸单
    assert tier_of(_leg(lq=LQ3)) == "T2"
    assert tier_of(_leg(lq=LQ3, integrity="symmetric_damage")) == "T2"
    assert tier_of(_leg(lq=LQ3, integrity="fail")) == "T3"
    assert tier_of(_leg(lq=LQ3, fair=(0.40, 0.30, 0.30), integrity="fail")) == "T4"   # 硬币且无支撑


def test_narrowable_face_needs_two_proofs_and_cheap_price():
    leg = _leg(fair=(0.6, 0.25, 0.15), d3={"away": 2})
    assert narrowable_faces(leg) == ["away"]                                 # 2/3 ∧ ≤15%
    assert narrowable_faces(_leg(fair=(0.6, 0.25, 0.15), d3={"away": 1})) == []
    assert narrowable_faces(_leg(fair=(0.6, 0.22, 0.18), d3={"away": 2})) == []   # 灰带不可
    assert narrowable_faces(_leg(fair=(0.5, 0.25, 0.25), d3={"away": 2})) == []   # >20% 买方差
    assert C14_CHEAP_LINE == 0.15 and C14_VARIANCE_LINE == 0.20
    dead = _leg(fair=(0.6, 0.25, 0.15), d3={"away": 3}, fs=_fs(away="dead"))
    assert narrowable_faces(dead) == []                                      # 死面不是收窄，是第一序


def test_board_wind_counts_tiers_and_names_the_regime():
    legs = {str(i): _leg(fair=(0.65, 0.2, 0.15)) for i in range(1, 6)}
    legs.update({str(i): _leg(lq=LQ3, integrity="fail", fair=(0.4, 0.3, 0.3)) for i in range(6, 15)})
    w = board_wind(legs)
    assert w["regime"] == "hot" and w["tiers"]["T1"] == 5 and w["tiers"]["T4"] == 9
    assert w["cap_band"] in ("low", "mid", "full")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_structure_tiers.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/structure_tiers.py
"""B5c 决策矩阵的机器读法：每场定级（T1–T4）、可收窄面、今日风向。零判断、零 IO。

⛔下面的常量是 RULEBOOK B5c（probation）的机器翻译。它们不是参数：改它们的唯一路径是
   把变体登记成 structural 实验、前瞻验证后 `rsi deploy`，再改这里、下一期生效。
"""
from __future__ import annotations

FACES = ("home", "draw", "away")

# ── RULEBOOK 常量（B5c 矩阵 / C14 价格带）──────────────────────────────
C14_CHEAP_LINE = 0.15        # ≤15% 才算「省钱」，可排
C14_VARIANCE_LINE = 0.20     # >20% 是买方差，永不可排
NARROW_MIN_PROOFS = 2        # 「2/3 且被排面 ≤15% 可排」
TIER_MAX_NARROWINGS = {"T1": 2, "T2": 1, "T3": 0, "T4": 0}
COIN_TOP1 = 0.45             # top1 < 45% = 硬币场
HOT_TOP1 = 0.60
COLD_DRAW = 0.29


def license_score(lq: dict | None) -> int:
    """牌照四问 0–4：中轴 / 正路破门机制 / 对手破门机制缺席 / 无情境旗。q3b 不在四问里。"""
    lq = lq or {}
    return int(bool(lq.get("q1_spine"))) + int(bool(lq.get("q2_route"))) \
        + int(not lq.get("q3a_opponent_scores", True)) + int(bool(lq.get("q4_no_context_flag")))


def _alive(leg: dict) -> list[str]:
    fs = leg.get("face_status") or {}
    return [f for f in FACES if (fs.get(f) or {}).get("state", "alive") == "alive"]


def tier_of(leg: dict) -> str:
    score = license_score(leg.get("license_questions"))
    integrity = str(leg.get("anchor_integrity") or "").lower()
    crash = bool(leg.get("crash_markers"))
    if score == 4 and integrity == "pass" and not crash:
        return "T1"
    if score == 3 and integrity in ("pass", "symmetric_damage"):
        return "T2"
    fair = leg.get("fair") or {}
    if len(_alive(leg)) == 3 and fair and max(fair.values()) < COIN_TOP1:
        return "T4"
    return "T3"


def _d3_count(leg: dict, face: str) -> int:
    doc = (leg.get("_d3") or {}).get(face) or {}
    return sum(int(bool(doc.get(k))) for k in ("a", "b", "c"))


def narrowable_faces(leg: dict) -> list[str]:
    """alive 面里可被收窄的：三证 ≥2 且 fair ≤ 省钱线。死面不在这里——那是第一序。"""
    fair = leg.get("fair") or {}
    out = []
    for face in _alive(leg):
        p = float(fair.get(face, 1.0))
        if p > C14_VARIANCE_LINE or p > C14_CHEAP_LINE:
            continue
        if _d3_count(leg, face) >= NARROW_MIN_PROOFS:
            out.append(face)
    return out


def board_wind(legs: dict[str, dict]) -> dict:
    tiers = {"T1": 0, "T2": 0, "T3": 0, "T4": 0}
    hot = cold = coin = 0
    narrowable = 0
    for leg in legs.values():
        tiers[tier_of(leg)] += 1
        fair = leg.get("fair") or {}
        top1 = max(fair.values()) if fair else 0.0
        hot += top1 >= HOT_TOP1
        cold += float(fair.get("draw", 0.0)) >= COLD_DRAW
        coin += top1 < COIN_TOP1
        narrowable += len(narrowable_faces(leg))
    regime = "hot" if hot >= 5 else "cold" if cold >= 5 else "coin" if coin >= 6 else "mixed"
    cap_band = "full" if narrowable >= 6 else "mid" if narrowable >= 3 else "low"
    return {"regime": regime, "tiers": tiers, "narrowable_faces": narrowable, "cap_band": cap_band,
            "note": "风向只读：回答「今天值得下多少判断」，不替人选面"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_structure_tiers.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
uv run ruff check nutmeg/decision/structure_tiers.py tests/decision/test_structure_tiers.py
git add nutmeg/decision/structure_tiers.py tests/decision/test_structure_tiers.py
git commit -m "feat(plan): B5c 矩阵机器读法——定级 T1–T4、可收窄面、今日风向（常量非参数）"
```

---

### Task 3: 枚举器（矩阵模式 / strict 地板 / 前沿 / hash / 第三序排序）

**Files:**
- Create: `nutmeg/decision/structure_space.py`
- Test: `tests/decision/test_structure_space.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_structure_space.py
import pytest

from nutmeg.decision.structure_space import (
    NoFaceStatusError,
    cover_options,
    enumerate_frontier,
    frontier_hash,
)

LQ4 = {"q1_spine": True, "q2_route": True, "q3a_opponent_scores": False, "q4_no_context_flag": True}
LQ3 = {**LQ4, "q4_no_context_flag": False}


def _leg(fair, *, lq=LQ4, integrity="pass", d3=None, dead=()):
    d3 = d3 or {}
    fs = {f: {"state": "dead" if f in dead else "alive", "proofs": {}, "precedent": "none", "source": "x"}
          for f in ("home", "draw", "away")}
    return {"license_questions": lq, "anchor_integrity": integrity, "crash_markers": [],
            "fair": dict(zip(("home", "draw", "away"), fair)),
            "_d3": {f: {"a": c >= 1, "b": c >= 2, "c": c >= 3} for f, c in d3.items()},
            "face_status": fs}


def test_t3_match_only_offers_full_cover_and_t1_narrows_only_cheap_proven_faces():
    t3 = _leg((0.4, 0.3, 0.3), lq=LQ3, integrity="fail")
    assert cover_options(t3, mode="matrix") == [("310", 1.0)]
    t1 = _leg((0.6, 0.25, 0.15), d3={"away": 2, "draw": 2})           # draw 25% 不可排
    opts = {faces for faces, _ in cover_options(t1, mode="matrix")}
    assert opts == {"310", "31"}
    strict = {faces for faces, _ in cover_options(t1, mode="strict")}
    assert strict == {"310"}                                            # 宪法地板：三活只全包


def test_dead_face_is_never_covered_in_either_mode():
    leg = _leg((0.6, 0.25, 0.15), dead=("away",))
    assert {f for f, _ in cover_options(leg, mode="strict")} == {"31"}
    assert "310" not in {f for f, _ in cover_options(leg, mode="matrix")}


def test_frontier_is_deterministic_bounded_by_cap_and_reports_shape():
    legs = {str(i): _leg((0.6, 0.25, 0.15), d3={"away": 2}) for i in range(1, 15)}
    fr = enumerate_frontier(legs, channel="renjiu", cap_yuan=400, mode="matrix")
    assert fr["max_p"] is not None and all(p["stake_yuan"] <= 400 for p in fr["points"])
    assert all(set(p["shape"]) == {"singles", "doubles", "fulls"} for p in fr["points"])
    assert all(n["excluded_face"] == "away" for p in fr["points"] for n in p["narrowings"])
    again = enumerate_frontier(legs, channel="renjiu", cap_yuan=400, mode="matrix")
    assert fr["frontier_hash"] == again["frontier_hash"]
    assert frontier_hash(legs, channel="renjiu", cap_yuan=400, mode="matrix") == fr["frontier_hash"]


def test_shengfucai_covers_all_fourteen_and_empty_frontier_is_none_not_error():
    legs = {str(i): _leg((0.4, 0.3, 0.3), lq=LQ3, integrity="fail") for i in range(1, 15)}   # 14 场 T3 全包
    fr = enumerate_frontier(legs, channel="shengfucai", cap_yuan=400, mode="matrix")
    assert fr["max_p"] is None and fr["points"] == []                    # 3^14 注远超帽 → 空前沿
    fr2 = enumerate_frontier(legs, channel="shengfucai", cap_yuan=3 ** 14 * 2, mode="matrix")
    assert len(fr2["points"]) == 1 and fr2["points"][0]["notes"] == 3 ** 14


def test_refuses_legs_without_face_status():
    legs = {"1": {"fair": {"home": 0.5, "draw": 0.3, "away": 0.2}}}
    with pytest.raises(NoFaceStatusError):
        enumerate_frontier(legs, channel="renjiu", cap_yuan=400, mode="matrix")


def test_third_order_sort_key_prefers_full_cover_on_lowest_top1_among_equal_p():
    from nutmeg.decision.structure_space import third_order_key
    a = {"p_all": 0.10, "chosen": (("1", "310"), ("2", "3")), "top1": {"1": 0.40, "2": 0.70}}
    b = {"p_all": 0.10, "chosen": (("1", "3"), ("2", "310")), "top1": {"1": 0.40, "2": 0.70}}
    assert third_order_key(a) < third_order_key(b)                       # 全包给了 top1 更低的场 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_structure_space.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/structure_space.py
"""第二序的机器化：在每场允许的盖法内枚举帽内 Pareto 前沿。零判断。

- matrix 模式 = 操作空间（B5c 矩阵允许的收窄）；strict 模式 = 宪法地板（三活只全包），只用来算 F4。
- DP 沿用 experiments/exp-strict-space.py::enumerate_space：每个 (注数, 收窄数) 格保留 P 最大者。
- 同输入同输出：frontier_hash 覆盖 legs（含 face_status）+ channel + cap + mode。
"""
from __future__ import annotations

import hashlib
import itertools
import json

from nutmeg.decision.structure_tiers import (
    TIER_MAX_NARROWINGS,
    C14_CHEAP_LINE,
    C14_VARIANCE_LINE,
    narrowable_faces,
    tier_of,
)

FACES = ("home", "draw", "away")
DIGIT = {"home": "3", "draw": "1", "away": "0"}
RENJIU_PICK = 9


class NoFaceStatusError(ValueError):
    pass


def _alive(leg: dict) -> list[str]:
    fs = leg.get("face_status")
    if not fs:
        raise NoFaceStatusError("legs-base 没有 face_status——先跑 B4 zucai-build-reads")
    return [f for f in FACES if fs[f]["state"] == "alive"]


def _faces_str(faces: list[str]) -> str:
    return "".join(DIGIT[f] for f in FACES if f in faces)


def cover_options(leg: dict, *, mode: str) -> list[tuple[str, float]]:
    """该场允许的盖法 → [(faces_str, coverage_prob)]。不含「丢」，丢在枚举层处理。"""
    alive = _alive(leg)
    fair = leg["fair"]
    full = (_faces_str(alive), sum(float(fair[f]) for f in alive))
    if mode == "strict" or not alive:
        return [full] if alive else []
    limit = TIER_MAX_NARROWINGS[tier_of(leg)]
    narrowable = narrowable_faces(leg)
    out = [full]
    for k in range(1, min(limit, len(narrowable), len(alive) - 1) + 1):
        for excluded in itertools.combinations(narrowable, k):
            keep = [f for f in alive if f not in excluded]
            out.append((_faces_str(keep), sum(float(fair[f]) for f in keep)))
    return out


def _c14_band(p: float) -> str:
    return "cheap" if p <= C14_CHEAP_LINE else "grey" if p <= C14_VARIANCE_LINE else "variance"


def frontier_hash(legs: dict, *, channel: str, cap_yuan: int, mode: str) -> str:
    material = json.dumps({"legs": legs, "channel": channel, "cap": cap_yuan, "mode": mode},
                          ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def third_order_key(point: dict) -> tuple:
    """第三序 = 排序 key，不是过滤：等 P 时全包给 top1 最低的场。返回越小越优先。"""
    fulls = [no for no, faces in point["chosen"] if len(faces) == 3]
    lowest_top1_full = min((point["top1"][no] for no in fulls), default=1.0)
    return (-round(point["p_all"], 12), lowest_top1_full)


def enumerate_frontier(legs: dict[str, dict], *, channel: str, cap_yuan: int, mode: str) -> dict:
    if channel not in ("renjiu", "shengfucai"):
        raise ValueError("channel 必须是 renjiu / shengfucai")
    cap_notes = cap_yuan // 2
    opts = {no: cover_options(leg, mode=mode) for no, leg in legs.items()}
    alive_sets = {no: _alive(leg) for no, leg in legs.items()}
    combos = (itertools.combinations(sorted(opts, key=int), RENJIU_PICK)
              if channel == "renjiu" else [tuple(sorted(opts, key=int))])
    sols: dict[tuple, tuple[float, tuple]] = {}
    for combo in combos:
        states = {(1, 0): (1.0, ())}
        for no in combo:
            nxt: dict = {}
            for (notes, marks), (p, chosen) in states.items():
                for faces, cover in opts[no]:
                    k = len(faces)
                    m = len(alive_sets[no]) - k
                    nn, mm = notes * k, marks + m
                    if nn > cap_notes:
                        continue
                    key = (nn, mm)
                    if key not in nxt or p * cover > nxt[key][0]:
                        nxt[key] = (p * cover, chosen + ((no, faces),))
            states = nxt
            if not states:
                break
        for (notes, marks), (p, chosen) in states.items():
            key = (notes, marks, chosen)
            if key not in sols or p > sols[key][0]:
                sols[key] = (p, chosen)
    points = []
    for (notes, marks, chosen), (p, _) in sols.items():
        shape = {"singles": sum(1 for _, f in chosen if len(f) == 1),
                 "doubles": sum(1 for _, f in chosen if len(f) == 2),
                 "fulls": sum(1 for _, f in chosen if len(f) == 3)}
        narrowings = []
        for no, faces in chosen:
            for face in alive_sets[no]:
                if DIGIT[face] not in faces:
                    p_face = float(legs[no]["fair"][face])
                    d3 = (legs[no].get("_d3") or {}).get(face) or {}
                    narrowings.append({"match_no": no, "excluded_face": face, "fair": p_face,
                                       "d3_count": sum(int(bool(d3.get(k))) for k in ("a", "b", "c")),
                                       "c14_band": _c14_band(p_face)})
        top1 = {no: max(float(v) for v in legs[no]["fair"].values()) for no, _ in chosen}
        points.append({"faces": dict(chosen), "chosen": chosen, "notes": notes,
                       "stake_yuan": notes * 2, "p_all": p, "shape": shape,
                       "narrowings": narrowings, "top1": top1})
    points.sort(key=third_order_key)
    for k, pt in enumerate(points):
        pt["k"] = k
        pt.pop("top1"); pt.pop("chosen")
    return {"frontier_hash": frontier_hash(legs, channel=channel, cap_yuan=cap_yuan, mode=mode),
            "channel": channel, "mode": mode, "cap_yuan": cap_yuan,
            "max_p": points[0]["p_all"] if points else None, "n_points": len(points),
            "points": points}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_structure_space.py -v`
Expected: 6 passed（`test_shengfucai_…` 里 3^14 注的前沿只有一个点，DP 在 14 场上仍是秒级）

- [ ] **Step 5: Commit**

```bash
uv run ruff check nutmeg/decision/structure_space.py tests/decision/test_structure_space.py
git add nutmeg/decision/structure_space.py tests/decision/test_structure_space.py
git commit -m "feat(plan): 枚举器——矩阵模式前沿 / strict 地板 / 确定性 hash / 第三序排序"
```

---

### Task 4: 编排层——tiers / frontier / choose 写文件与候选树

**Files:**
- Create: `nutmeg/decision/plan_flow.py`
- Test: `tests/decision/test_plan_flow.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_plan_flow.py
import json

import pytest

from nutmeg.decision.plan_flow import run_choose, run_frontier, run_tiers
from nutmeg.decision.workbench import read_events

LQ4 = {"q1_spine": True, "q2_route": True, "q3a_opponent_scores": False, "q4_no_context_flag": True}


def _data_dir(tmp_path):
    z = tmp_path / "zucai"; z.mkdir(); (tmp_path / "jczq").mkdir()
    legs = {str(i): {"name": f"m{i}", "license_questions": LQ4, "anchor_integrity": "pass",
                     "crash_markers": [], "fair": {"home": 0.6, "draw": 0.25, "away": 0.15},
                     "_d3": {"away": {"a": True, "b": True, "c": False}},
                     "face_status": {f: {"state": "alive", "proofs": {}, "precedent": "none", "source": "x"}
                                     for f in ("home", "draw", "away")}}
            for i in range(1, 15)}
    (z / "26130-legs-base.json").write_text(json.dumps({"issue": "26130", "legs": legs}), encoding="utf-8")
    (z / "26130-issue.json").write_text(json.dumps({"issue_id": "26130", "matches": [
        {"match_no": i, "kickoff_bj": "2026-09-26 02:00"} for i in range(1, 15)]}), encoding="utf-8")
    return tmp_path


def test_tiers_writes_file_and_root_candidate_node(tmp_path):
    d = _data_dir(tmp_path)
    out = run_tiers(issue="26130", data_dir=d)
    doc = json.loads((d / "zucai" / "26130-tiers.json").read_text("utf-8"))
    assert doc["tiers"]["1"] == "T1" and doc["wind"]["regime"] in ("hot", "mixed", "cold", "coin")
    evs = read_events(d / "jczq", "2026-09-26")
    assert evs[-1]["kind"] == "candidate" and evs[-1]["payload"]["version"].startswith("tiers@")
    assert out["tiers_hash"] == evs[-1]["payload"]["version"].split("@")[1]


def test_frontier_writes_points_as_children_of_tiers_root(tmp_path):
    d = _data_dir(tmp_path)
    run_tiers(issue="26130", data_dir=d)
    fr = run_frontier(issue="26130", channel="renjiu", cap_yuan=400, data_dir=d)
    doc = json.loads((d / "zucai" / "26130-frontier-renjiu.json").read_text("utf-8"))
    assert doc["max_p"] == fr["max_p"] and doc["strict_max_p"] is not None
    evs = [e for e in read_events(d / "jczq", "2026-09-26") if e["kind"] == "candidate"]
    kids = [e for e in evs if e["payload"]["version"].startswith("frontier#")]
    assert kids and all(e["payload"]["parent_version"].startswith("tiers@") for e in kids)
    assert all(e["payload"]["verdict"] == "considered" for e in kids)


def test_choose_writes_legs_file_and_hangs_node_under_the_point(tmp_path):
    d = _data_dir(tmp_path)
    run_tiers(issue="26130", data_dir=d)
    run_frontier(issue="26130", channel="renjiu", cap_yuan=400, data_dir=d)
    res = run_choose(issue="26130", channel="renjiu", point=0, data_dir=d)
    legs = json.loads((d / "zucai" / "26130-legs-renjiu.json").read_text("utf-8"))
    assert len(legs["legs"]) == 9 and res["candidate_node"] == "chosen#0@renjiu"
    ev = read_events(d / "jczq", "2026-09-26")[-1]
    assert ev["payload"]["parent_version"] == "frontier#0@¥400" and ev["payload"]["verdict"] == "chosen"


def test_choose_with_edit_hangs_under_the_point_and_records_the_edit(tmp_path):
    d = _data_dir(tmp_path)
    run_tiers(issue="26130", data_dir=d)
    run_frontier(issue="26130", channel="renjiu", cap_yuan=400, data_dir=d)
    edit = d / "edit.json"
    edit.write_text(json.dumps({"1": "3", "2": "31", "3": "310", "4": "31", "5": "31",
                                "6": "3", "7": "31", "8": "31", "9": "310"}), encoding="utf-8")
    res = run_choose(issue="26130", channel="renjiu", point=0, edit_file=edit, data_dir=d)
    ev = read_events(d / "jczq", "2026-09-26")[-1]
    assert ev["payload"]["parent_version"] == "frontier#0@¥400"
    assert ev["payload"]["version"] == "edit#1@renjiu" and res["candidate_node"] == "edit#1@renjiu"


def test_frontier_refuses_without_tiers(tmp_path):
    d = _data_dir(tmp_path)
    with pytest.raises(FileNotFoundError, match="tiers"):
        run_frontier(issue="26130", channel="renjiu", cap_yuan=400, data_dir=d)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_plan_flow.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/plan_flow.py
"""tiers / frontier / choose 的编排：读 legs-base，写产物文件，候选树自动生长。

树：tiers@<hash>（根）→ frontier#k@¥cap（前沿层，considered）→ chosen#k / edit#n（人的分叉）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from nutmeg.decision.structure_space import enumerate_frontier
from nutmeg.decision.structure_tiers import board_wind, tier_of
from nutmeg.decision.workbench import append_candidate, read_events

DIGIT_FACE = {"3": "home", "1": "draw", "0": "away"}


def _zucai(data_dir: Path) -> Path:
    return Path(data_dir) / "zucai"


def _day_of(issue: str, data_dir: Path) -> str:
    doc = json.loads((_zucai(data_dir) / f"{issue}-issue.json").read_text("utf-8"))
    kos = sorted(str(m["kickoff_bj"]) for m in doc["matches"] if m.get("kickoff_bj"))
    return kos[0][:10]


def _legs(issue: str, data_dir: Path) -> dict:
    return json.loads((_zucai(data_dir) / f"{issue}-legs-base.json").read_text("utf-8"))["legs"]


def run_tiers(*, issue: str, data_dir: Path) -> dict:
    legs = _legs(issue, data_dir)
    tiers = {no: tier_of(leg) for no, leg in legs.items()}
    wind = board_wind(legs)
    doc = {"issue": issue, "tiers": tiers, "wind": wind}
    raw = json.dumps(doc, ensure_ascii=False, sort_keys=True)
    tiers_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    doc["tiers_hash"] = tiers_hash
    (_zucai(data_dir) / f"{issue}-tiers.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    append_candidate(Path(data_dir) / "jczq", _day_of(issue, data_dir), obj_id=f"ticket:{issue}",
                     version=f"tiers@{tiers_hash}", faces={}, notes=0, stake_yuan=0, p_all=None,
                     verdict="considered", reason=f"风向 {wind['regime']} · {wind['tiers']}")
    return doc


def run_frontier(*, issue: str, channel: str, cap_yuan: int, data_dir: Path) -> dict:
    tiers_path = _zucai(data_dir) / f"{issue}-tiers.json"
    if not tiers_path.exists():
        raise FileNotFoundError(f"{tiers_path.name} 不存在——先跑 plan tiers")
    tiers_hash = json.loads(tiers_path.read_text("utf-8"))["tiers_hash"]
    legs = _legs(issue, data_dir)
    fr = enumerate_frontier(legs, channel=channel, cap_yuan=cap_yuan, mode="matrix")
    strict = enumerate_frontier(legs, channel=channel, cap_yuan=cap_yuan, mode="strict")
    fr["strict_max_p"] = strict["max_p"]
    fr["tiers_hash"] = tiers_hash
    (_zucai(data_dir) / f"{issue}-frontier-{channel}.json").write_text(
        json.dumps(fr, ensure_ascii=False, indent=1), encoding="utf-8")
    day = _day_of(issue, data_dir)
    for pt in fr["points"]:
        append_candidate(Path(data_dir) / "jczq", day, obj_id=f"ticket:{issue}",
                         version=f"frontier#{pt['k']}@¥{cap_yuan}", parent_version=f"tiers@{tiers_hash}",
                         faces=pt["faces"], notes=pt["notes"], stake_yuan=pt["stake_yuan"],
                         p_all=pt["p_all"], verdict="considered",
                         reason=f"{channel} 前沿 · 形状 {pt['shape']} · 收窄 {len(pt['narrowings'])}")
    return fr


def _legs_file_from_faces(legs: dict, faces: dict, issue: str, channel: str) -> dict:
    out = {}
    for no, fstr in faces.items():
        leg = legs[no]
        out[no] = {**{k: v for k, v in leg.items() if not k.startswith("_")},
                   "faces": fstr, "selections": [DIGIT_FACE[c] for c in fstr]}
    return {"issue": issue, "channel": channel, "legs": out}


def run_choose(*, issue: str, channel: str, point: int, data_dir: Path,
               edit_file: Path | None = None) -> dict:
    fr = json.loads((_zucai(data_dir) / f"{issue}-frontier-{channel}.json").read_text("utf-8"))
    pt = next(p for p in fr["points"] if p["k"] == point)
    legs = _legs(issue, data_dir)
    day = _day_of(issue, data_dir)
    parent = f"frontier#{point}@¥{fr['cap_yuan']}"
    if edit_file is None:
        faces, version, verdict = pt["faces"], f"chosen#{point}@{channel}", "chosen"
    else:
        faces = json.loads(Path(edit_file).read_text("utf-8"))
        n_edits = 1 + sum(1 for e in read_events(Path(data_dir) / "jczq", day)
                          if e.get("kind") == "candidate"
                          and str(e["payload"].get("version", "")).startswith("edit#")
                          and str(e["payload"].get("version", "")).endswith(f"@{channel}"))
        version, verdict = f"edit#{n_edits}@{channel}", "chosen"
    notes = 1
    for f in faces.values():
        notes *= len(f)
    p_all = 1.0
    for no, f in faces.items():
        p_all *= sum(float(legs[no]["fair"][DIGIT_FACE[c]]) for c in f)
    doc = _legs_file_from_faces(legs, faces, issue, channel)
    (_zucai(data_dir) / f"{issue}-legs-{channel}.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    append_candidate(Path(data_dir) / "jczq", day, obj_id=f"ticket:{issue}", version=version,
                     parent_version=parent, faces=faces, notes=notes, stake_yuan=notes * 2,
                     p_all=p_all, verdict=verdict,
                     reason="人挑前沿点" if edit_file is None else f"人改版，基于 {parent}")
    return {"candidate_node": version, "parent": parent, "notes": notes, "stake_yuan": notes * 2,
            "p_all": p_all, "legs_file": str(_zucai(data_dir) / f"{issue}-legs-{channel}.json")}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_plan_flow.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
uv run ruff check nutmeg/decision/plan_flow.py tests/decision/test_plan_flow.py
git add nutmeg/decision/plan_flow.py tests/decision/test_plan_flow.py
git commit -m "feat(plan): tiers/frontier/choose 编排——产物落盘，候选树自动生长"
```

---

### Task 5: CLI `nutmeg plan tiers | frontier | choose`

**Files:**
- Create: `nutmeg/interfaces/cli/plan.py`
- Modify: `nutmeg/interfaces/cli/__init__.py`（底部 import 区按字母序加 `from nutmeg.interfaces.cli import plan as plan  # noqa: E402`，在 `ontology_ingest` 与 `product` 之间）
- Test: `tests/test_cli_plan.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_plan.py
import json

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app

LQ4 = {"q1_spine": True, "q2_route": True, "q3a_opponent_scores": False, "q4_no_context_flag": True}


def _data_dir(tmp_path):
    z = tmp_path / "zucai"; z.mkdir(); (tmp_path / "jczq").mkdir()
    legs = {str(i): {"name": f"m{i}", "license_questions": LQ4, "anchor_integrity": "pass",
                     "crash_markers": [], "fair": {"home": 0.6, "draw": 0.25, "away": 0.15},
                     "_d3": {"away": {"a": True, "b": True, "c": False}},
                     "face_status": {f: {"state": "alive", "proofs": {}, "precedent": "none", "source": "x"}
                                     for f in ("home", "draw", "away")}} for i in range(1, 15)}
    (z / "26130-legs-base.json").write_text(json.dumps({"issue": "26130", "legs": legs}), encoding="utf-8")
    (z / "26130-issue.json").write_text(json.dumps({"issue_id": "26130", "matches": [
        {"match_no": i, "kickoff_bj": "2026-09-26 02:00"} for i in range(1, 15)]}), encoding="utf-8")
    return tmp_path


def test_tiers_frontier_choose_round_trip(tmp_path):
    d = _data_dir(tmp_path); r = CliRunner()
    out = r.invoke(app, ["plan", "tiers", "--issue", "26130", "--data-dir", str(d)])
    assert out.exit_code == 0 and "风向" in out.output and "T1" in out.output
    out = r.invoke(app, ["plan", "frontier", "--issue", "26130", "--channel", "renjiu", "--cap", "400",
                         "--data-dir", str(d)])
    assert out.exit_code == 0 and "max P" in out.output and "strict" in out.output
    out = r.invoke(app, ["plan", "choose", "--issue", "26130", "--channel", "renjiu", "--point", "0",
                         "--data-dir", str(d)])
    assert out.exit_code == 0 and "26130-legs-renjiu.json" in out.output


def test_frontier_without_tiers_exits_one(tmp_path):
    d = _data_dir(tmp_path)
    out = CliRunner().invoke(app, ["plan", "frontier", "--issue", "26130", "--channel", "renjiu",
                                   "--data-dir", str(d)])
    assert out.exit_code == 1 and "tiers" in out.output


def test_frontier_refuses_legs_without_face_status(tmp_path):
    d = _data_dir(tmp_path)
    p = d / "zucai" / "26130-legs-base.json"
    doc = json.loads(p.read_text("utf-8"))
    for leg in doc["legs"].values():
        leg.pop("face_status")
    p.write_text(json.dumps(doc), encoding="utf-8")
    r = CliRunner()
    r.invoke(app, ["plan", "tiers", "--issue", "26130", "--data-dir", str(d)])
    out = r.invoke(app, ["plan", "frontier", "--issue", "26130", "--channel", "renjiu", "--data-dir", str(d)])
    assert out.exit_code == 1 and "face_status" in out.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_plan.py -v`
Expected: FAIL — `No such command 'plan'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/interfaces/cli/plan.py
"""`nutmeg plan …`：传统足彩专项（结构层）的命令面。B5c→B5→B9。零判断——只算、只落盘、只校验。"""
from __future__ import annotations

from pathlib import Path

import typer

import nutmeg.interfaces.cli as _cli

plan_app = typer.Typer(help="传统足彩专项：定级/风向 → 前沿 → 人挑 → 定案 → 对账")
_cli.app.add_typer(plan_app, name="plan")

_DATA_DIR = typer.Option(Path(".nutmeg-data"), "--data-dir")
_ISSUE = typer.Option(..., "--issue")
_CHANNEL = typer.Option(..., "--channel", help="renjiu | shengfucai")
_CAP = typer.Option(None, "--cap", help="¥ 帽；不给＝宪法基线 400")
_POINT = typer.Option(..., "--point", help="前沿点 k")
_EDIT = typer.Option(None, "--edit", help="人改过的 {场号: faces} JSON")


def _fail(msg: str) -> None:
    typer.echo(f"plan error: {msg}")
    raise typer.Exit(code=1)


@plan_app.command("tiers")
def tiers(issue: str = _ISSUE, data_dir: Path = _DATA_DIR) -> None:
    """B5c 矩阵定级 + 今日风向（只读判读字段）。"""
    from nutmeg.decision.plan_flow import run_tiers

    try:
        doc = run_tiers(issue=issue, data_dir=data_dir)
    except FileNotFoundError as exc:
        _fail(str(exc))
    w = doc["wind"]
    typer.echo(f"{issue} 风向 {w['regime']} · 各级 {w['tiers']} · 可收窄面 {w['narrowable_faces']} "
               f"· 建议帽档 {w['cap_band']}")
    for no, t in sorted(doc["tiers"].items(), key=lambda kv: int(kv[0])):
        typer.echo(f"  场{no:>2} {t}")


@plan_app.command("frontier")
def frontier(issue: str = _ISSUE, channel: str = _CHANNEL, cap: int | None = _CAP,
             data_dir: Path = _DATA_DIR) -> None:
    """帽内 Pareto 前沿（矩阵模式）+ strict 地板 max P（F4 用）。"""
    from nutmeg.decision.plan_flow import run_frontier
    from nutmeg.decision.structure_space import NoFaceStatusError

    cap_yuan = cap or 400
    try:
        fr = run_frontier(issue=issue, channel=channel, cap_yuan=cap_yuan, data_dir=data_dir)
    except (FileNotFoundError, NoFaceStatusError, ValueError) as exc:
        _fail(str(exc))
    mp = "空前沿" if fr["max_p"] is None else f"{fr['max_p'] * 100:.2f}%"
    sp = "空" if fr["strict_max_p"] is None else f"{fr['strict_max_p'] * 100:.2f}%"
    typer.echo(f"{issue} {channel} ¥{cap_yuan}：前沿 {fr['n_points']} 点 · 帽内 max P {mp} · strict 地板 {sp}")
    for pt in fr["points"][:12]:
        faces = " ".join(f"{no}:{f}" for no, f in sorted(pt["faces"].items(), key=lambda kv: int(kv[0])))
        typer.echo(f"  #{pt['k']:<3} {pt['notes']:>5}注 ¥{pt['stake_yuan']:<5} P {pt['p_all'] * 100:6.2f}% "
                   f"{pt['shape']['singles']}单{pt['shape']['doubles']}双{pt['shape']['fulls']}包  {faces}")


@plan_app.command("choose")
def choose(issue: str = _ISSUE, channel: str = _CHANNEL, point: int = _POINT,
           edit: Path | None = _EDIT, data_dir: Path = _DATA_DIR) -> None:
    """取前沿点为票面（--edit 挂人改版），产 legs 文件给 B6 审计门。"""
    from nutmeg.decision.plan_flow import run_choose

    try:
        res = run_choose(issue=issue, channel=channel, point=point, data_dir=data_dir, edit_file=edit)
    except (FileNotFoundError, StopIteration, KeyError) as exc:
        _fail(f"前沿点不存在或文件缺失：{exc}")
    typer.echo(f"{res['candidate_node']} ← {res['parent']} · {res['notes']} 注 ¥{res['stake_yuan']} "
               f"· P {res['p_all'] * 100:.2f}%\n  → {res['legs_file']}（下一步 B6：decision-audit-legs）")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_plan.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
uv run ruff check nutmeg/interfaces/cli/plan.py nutmeg/interfaces/cli/__init__.py tests/test_cli_plan.py
git add nutmeg/interfaces/cli/plan.py nutmeg/interfaces/cli/__init__.py tests/test_cli_plan.py
git commit -m "feat(cli): nutmeg plan tiers/frontier/choose"
```

（Task 6–10 见 `2026-09-19-zucai-structure-lane-part2.md`：资金方案内核对象与迁移 v30、`plan commit/status`、F4 适配器 + `rsi dream`、sopbar、26129 回填与 RUNBOOK。）
