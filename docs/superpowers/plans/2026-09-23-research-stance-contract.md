# Research Stance Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让每场研究都带一个可证伪的表态（面 / 表达档 / 作废条件 / 为什么不跟市场），并让 A/B 类证据能把 belief 拨离市场且进 F9 记账；max turns 不再一次判永久。

**Architecture:** 新纯函数模块 `nutmeg/decision/stance.py` 负责校验与拨动算术；深研契约、runner 校验、`intake_board` 回填、`build_jczq_reads` 取 belief 四处接线；日报只是多显示一列。不改 `research_intake.py`（另一会话有未提交改动），表态校验从 `research_runner._validate` 与 `jczq_reads.intake_board` 调用。

**Tech Stack:** Python 3.12、pytest、既有 `claude -p` 注入模式。

**Spec:** `docs/superpowers/specs/2026-09-23-research-stance-contract-design.md`。

---

## File structure

| 文件 | 职责 |
| --- | --- |
| Create `nutmeg/decision/stance.py` | `TILT_KIND_LEXICON`、`TIER_PP`、`validate_stance`、`apply_tilt`、`stance_faces`、`TiltResult` |
| Modify `nutmeg/decision/research_runner.py` | `_REQUIRED` 加 `stance`；`_validate` 调 `validate_stance`；max-turns 带标记重试一次；`_claude_cli` 识别 `RETRY_MARKER` 把 `--max-turns` 提到 24 |
| Modify `nutmeg/decision/research_prompt.py`、`.claude/agents/jczq-match-analyst.md` | 契约与必答段 |
| Modify `nutmeg/decision/jczq_reads.py` | `intake_board` 校验死面并写回 `stance`/`faces`；`build_jczq_reads` 用 `apply_tilt` |
| Modify `nutmeg/decision/day_brief.py`、`day_session.py`、`static/decision/day.js` | 卡片 `stance` 块与显示 |
| Tests | `tests/decision/test_stance.py`；追加 `test_research_runner.py`、`test_jczq_reads.py`、`test_day_brief.py`、`test_day_session.py` |

---

### Task 1: `stance.py`（校验 + 拨动算术）

**Files:**
- Create: `nutmeg/decision/stance.py`
- Test: `tests/decision/test_stance.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_stance.py
from nutmeg.decision.stance import apply_tilt, stance_faces, validate_stance

PRIOR = {"home": 0.52, "draw": 0.26, "away": 0.22}
DEAD_AWAY = {"away": {"verdict": "dead", "a_no_scoring_mechanism": True,
                      "b_precedent_carrier_gone": True, "c_anchor_pass": True}}


def _stance(**over) -> dict:
    base = {"face": "3", "structure": "double", "cover": "1", "confidence": 3,
            "falsifier": "客队首发若有主力门将则本判断作废", "why_not_market": "none",
            "tilt": None, "alt_face": "1", "market_read": "agree"}
    base.update(over)
    return base


def test_stance_faces_orders_by_sporttery_convention():
    assert stance_faces(_stance()) == "31"
    assert stance_faces(_stance(structure="single")) == "3"
    assert stance_faces(_stance(structure="double", face="0", cover="1")) == "10"
    assert stance_faces(_stance(structure="full")) == "310"


def test_validate_accepts_market_follow_and_normalises():
    norm, issues = validate_stance(_stance(), confidence=3, death_three_proofs={})
    assert issues == [] and norm["faces"] == "31" and norm["tilt"] is None


def test_validate_flags_enum_cover_confidence_and_falsifier():
    _, issues = validate_stance(_stance(face="x", structure="double", cover="3", confidence=4,
                                        falsifier="短"), confidence=3, death_three_proofs={})
    msgs = " ".join(i.message for i in issues)
    assert "face" in msgs and "cover" in msgs and "confidence" in msgs and "falsifier" in msgs
    assert all(i.level == "ERROR" for i in issues)


def test_validate_requires_tilt_and_why_to_agree_and_forbids_dead_faces():
    _, issues = validate_stance(_stance(why_not_market="tilt_evidence"), confidence=3, death_three_proofs={})
    assert any("tilt" in i.message for i in issues)
    _, issues = validate_stance(_stance(why_not_market="structure"), confidence=3, death_three_proofs={})
    assert any("没有面被判死" in i.message for i in issues)
    _, issues = validate_stance(_stance(structure="double", face="3", cover="0"), confidence=3,
                                death_three_proofs=DEAD_AWAY)
    assert any("已判死" in i.message for i in issues)


def test_validate_tilt_rules_tier_range_kind_lexicon_and_will_only_toward_draw():
    tilt = {"face": "3", "expires_if": "官宣名单里 X 出场则撤回", "evidence": [
        {"tier": "official", "kind": "absence_official", "pp": 9, "source": "club", "captured_at": "2026-09-23T10:00:00+08:00"},
        {"tier": "will", "kind": "motivation_dead_rubber", "pp": 2, "source": "x", "captured_at": "2026-09-23T10:00:00+08:00"},
        {"tier": "inferred", "kind": "made_up_kind", "pp": 1, "source": "x", "captured_at": "2026-09-23T10:00:00+08:00"},
    ]}
    _, issues = validate_stance(_stance(why_not_market="tilt_evidence", tilt=tilt), confidence=3,
                                death_three_proofs={})
    msgs = [i.message for i in issues]
    assert any("pp 9" in m and "official" in m for m in msgs)
    assert any("will" in m and "朝平" in m for m in msgs)
    assert any("made_up_kind" in m for m in msgs)


def test_apply_tilt_zeroes_below_5pp_caps_and_drops_post_kickoff_evidence():
    ev = lambda tier, pp, at="2026-09-23T10:00:00+08:00": {  # noqa: E731
        "tier": tier, "kind": "absence_official", "pp": pp, "source": "s", "captured_at": at}
    small = {"face": "3", "expires_if": "", "evidence": [ev("inferred", 2), ev("inferred", 2)]}
    r = apply_tilt(PRIOR, small, kickoff="2026-09-23T19:30:00+08:00")
    assert r.zeroed and r.applied_pp == 0 and r.belief == PRIOR and "归零" in r.reason
    big = {"face": "3", "expires_if": "", "evidence": [ev("official", 8), ev("confirmed_structural", 6), ev("inferred", 2)]}
    r = apply_tilt(PRIOR, big, kickoff="2026-09-23T19:30:00+08:00")
    assert r.applied_pp == 15 and not r.zeroed and r.tiers == ["official", "confirmed_structural", "inferred"]
    assert round(r.belief["home"], 2) == 0.67 and round(sum(r.belief.values()), 6) == 1.0
    assert round(r.belief["draw"] / r.belief["away"], 3) == round(PRIOR["draw"] / PRIOR["away"], 3)
    late = {"face": "3", "expires_if": "", "evidence": [ev("official", 8, "2026-09-23T20:00:00+08:00")]}
    r = apply_tilt(PRIOR, late, kickoff="2026-09-23T19:30:00+08:00")
    assert r.zeroed and "开球后" in r.reason
    nooff = {"face": "1", "expires_if": "", "evidence": [ev("confirmed_structural", 6), ev("confirmed_structural", 6)]}
    assert apply_tilt(PRIOR, nooff).applied_pp == 10  # 无官宣封顶 10
```

- [ ] **Step 2: Run** `uv run pytest tests/decision/test_stance.py -q` → `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/stance.py
"""研究表态块：校验与拨动算术（设计 2026-09-23-research-stance-contract）。

判断由分析员出（押哪个面、给什么证据），判据入代码（区间、归零、上限、T12）。
⛔本模块不读市场之外的任何东西，不推荐面。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

FACES = ("3", "1", "0")
FACE_KEY = {"3": "home", "1": "draw", "0": "away"}
STRUCTURES = ("single", "double", "full")
WHY = ("none", "tilt_evidence", "structure")
TIER_PP = {"official": (4, 8), "confirmed_structural": (3, 6), "inferred": (0, 2), "will": (0, 2)}
"""RULEBOOK l-权重表：官宣 4–8 / 确证结构 3–6 / 推断 0–2 / 战意 0–2（只许朝平）。"""
TILT_KIND_LEXICON = frozenset({
    "absence_official", "suspension", "goalkeeper_change", "anchor_integrity_fail",
    "lineup_confirmed", "venue_anomaly", "precedent_carrier", "rotation_confirmed",
    "schedule_congestion", "motivation_dead_rubber",
})
ZERO_BELOW_PP = 5
CAP_WITH_OFFICIAL_PP = 15
CAP_WITHOUT_OFFICIAL_PP = 10
MIN_FALSIFIER_CHARS = 8
_BJ = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class StanceIssue:
    level: str
    field: str
    message: str


@dataclass(frozen=True)
class TiltResult:
    belief: dict
    applied_pp: int
    zeroed: bool
    reason: str
    tiers: list[str]


def stance_faces(stance: dict) -> str:
    structure = stance.get("structure")
    if structure == "full":
        return "310"
    if structure == "single":
        return str(stance.get("face"))
    chosen = {str(stance.get("face")), str(stance.get("cover"))}
    return "".join(f for f in FACES if f in chosen)


def _dead_faces(death_three_proofs: dict | None) -> set[str]:
    dead = set()
    for key, proofs in (death_three_proofs or {}).items():
        if isinstance(proofs, dict) and str(proofs.get("verdict", "alive")).lower() == "dead":
            face = {v: k for k, v in FACE_KEY.items()}.get(key, key)
            dead.add(str(face))
    return dead


def _parse(value) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=_BJ)


def validate_stance(stance, *, confidence, death_three_proofs) -> tuple[dict, list[StanceIssue]]:
    issues: list[StanceIssue] = []
    err = lambda field, msg: issues.append(StanceIssue("ERROR", field, msg))  # noqa: E731
    if not isinstance(stance, dict):
        err("stance", "缺 stance 表态块")
        return {}, issues
    face, structure, cover = str(stance.get("face")), stance.get("structure"), stance.get("cover")
    if face not in FACES:
        err("face", f"face `{face}` 不是 3/1/0")
    if structure not in STRUCTURES:
        err("structure", f"structure `{structure}` 不是 single/double/full")
    if structure == "double":
        if str(cover) not in FACES or str(cover) == face:
            err("cover", f"double 必须给一个不同于 face 的 cover，实得 `{cover}`")
    try:
        conf = int(stance.get("confidence"))
    except (TypeError, ValueError):
        conf = None
    if conf is None or not 1 <= conf <= 5:
        err("confidence", "stance.confidence 缺失或不在 1-5")
    elif confidence is not None and int(confidence) != conf:
        err("confidence", f"stance.confidence {conf} 与顶层 confidence {confidence} 不一致")
    falsifier = str(stance.get("falsifier") or "").strip()
    if len(falsifier) < MIN_FALSIFIER_CHARS:
        err("falsifier", f"falsifier 少于 {MIN_FALSIFIER_CHARS} 字（要一句赛后可核验的作废条件）")
    why = stance.get("why_not_market")
    tilt = stance.get("tilt")
    dead = _dead_faces(death_three_proofs)
    if why not in WHY:
        err("why_not_market", f"why_not_market `{why}` 不是 none/tilt_evidence/structure")
    if why == "tilt_evidence" and not tilt:
        err("tilt", "why_not_market=tilt_evidence 但没有 tilt")
    if why != "tilt_evidence" and tilt:
        err("tilt", "给了 tilt 就必须 why_not_market=tilt_evidence")
    if why == "structure" and not dead:
        err("why_not_market", "why_not_market=structure 但没有面被判死（三证）")
    faces = stance_faces(stance) if face in FACES and structure in STRUCTURES else ""
    if faces and dead & set(faces):
        err("structure", f"表态面集合 `{faces}` 含已判死的面 {sorted(dead & set(faces))}")
    tiers: list[str] = []
    if isinstance(tilt, dict):
        tface = str(tilt.get("face"))
        if tface not in FACES:
            err("tilt.face", f"tilt.face `{tface}` 不是 3/1/0")
        evidence = tilt.get("evidence") or []
        if not evidence:
            err("tilt.evidence", "tilt 至少要一条证据")
        for i, e in enumerate(evidence):
            tier, kind = e.get("tier"), e.get("kind")
            if tier not in TIER_PP:
                err(f"tilt.evidence.{i}", f"tier `{tier}` 不在 {sorted(TIER_PP)}")
                continue
            lo, hi = TIER_PP[tier]
            try:
                pp = int(e.get("pp"))
            except (TypeError, ValueError):
                pp = -1
            if not lo <= pp <= hi:
                err(f"tilt.evidence.{i}", f"{tier} 的 pp {pp} 不在 [{lo},{hi}]")
            if tier == "will" and tface != "1":
                err(f"tilt.evidence.{i}", "will（战意）只许朝平，tilt.face 必须是 1")
            if kind not in TILT_KIND_LEXICON:
                err(f"tilt.evidence.{i}", f"kind `{kind}` 不在词典")
            if _parse(e.get("captured_at")) is None:
                err(f"tilt.evidence.{i}", "captured_at 不是合法时间")
            tiers.append(str(tier))
    alt = stance.get("alt_face")
    if alt not in (None, *FACES):
        err("alt_face", f"alt_face `{alt}` 不是 3/1/0")
    mr = stance.get("market_read")
    if mr not in (None, "agree", "overpriced", "underpriced"):
        err("market_read", f"market_read `{mr}` 不合法")
    norm = {
        "face": face, "structure": structure, "cover": str(cover) if cover is not None else None,
        "confidence": conf, "falsifier": falsifier, "why_not_market": why,
        "tilt": tilt if isinstance(tilt, dict) else None, "alt_face": alt, "market_read": mr,
        "faces": faces, "tiers": tiers,
    }
    return norm, issues


def apply_tilt(prior: dict, tilt: dict | None, *, kickoff: str | None = None) -> TiltResult:
    prior = {k: float(prior[k]) for k in ("home", "draw", "away")}
    if not tilt:
        return TiltResult(dict(prior), 0, True, "无 tilt：跟市场", [])
    kick = _parse(kickoff) if kickoff else None
    kept, dropped, tiers = [], 0, []
    for e in tilt.get("evidence") or []:
        at = _parse(e.get("captured_at"))
        if kick and at and at >= kick:
            dropped += 1
            continue
        kept.append(e)
        tiers.append(str(e.get("tier")))
    net = sum(int(e.get("pp") or 0) for e in kept)
    if net < ZERO_BELOW_PP:
        why = f"净偏移 {net}pp <{ZERO_BELOW_PP}pp 归零跟市场" + (f"（{dropped} 条证据在开球后，作废）" if dropped else "")
        return TiltResult(dict(prior), 0, True, why, tiers)
    cap = CAP_WITH_OFFICIAL_PP if "official" in tiers else CAP_WITHOUT_OFFICIAL_PP
    applied = min(net, cap)
    key = FACE_KEY[str(tilt["face"])]
    target = min(0.98, max(0.01, prior[key] + applied / 100))
    rest = [k for k in prior if k != key]
    rest_mass = sum(prior[k] for k in rest) or 1.0
    belief = {k: (1 - target) * prior[k] / rest_mass for k in rest}
    belief[key] = target
    reason = f"拨 {applied}pp 向 {tilt['face']}" + (f"（上限 {cap}pp 截断自 {net}pp）" if applied < net else "")
    return TiltResult(belief, applied, False, reason, tiers)
```

- [ ] **Step 4: Run** → `6 passed`；`uv run ruff check nutmeg/decision/stance.py tests/decision/test_stance.py` clean（拆长行）。

- [ ] **Step 5: Commit** `git add nutmeg/decision/stance.py tests/decision/test_stance.py && git commit -m "feat(stance): stance block validation and evidence-tiered tilt arithmetic"`

---

### Task 2: max turns 不再一次判永久（带标记重试一次）

**Files:**
- Modify: `nutmeg/decision/research_runner.py`（`_claude_cli`、`_research_one`、`_load_rejected`）
- Modify: `tests/decision/test_research_runner.py::test_max_turns_is_permanent_without_resending_same_brief`

- [ ] **Step 1: 改测试为新政策**（同名测试改为下面这个，断言第二次调用的 brief 带标记且 `--max-turns` 提高，仍是 max turns 才 permanent）

```python
def test_max_turns_retries_once_with_marker_then_is_permanent(tmp_path):
    from nutmeg.decision.research_runner import RETRY_MARKER
    root = _board(tmp_path, n=1)
    calls = []
    now = datetime(2026, 9, 19, 10, 0, tzinfo=BJ)
    report = run_day(
        day="2026-09-19", jczq_dir=root, data_dir=tmp_path,
        claude=lambda system, brief: calls.append(brief) or (1, "Error: Reached max turns (12)"),
        fulfill=lambda argv: (0, ""), profile=lambda match_id: {}, budget=10, now=lambda: now,
    )
    assert len(calls) == 2 and RETRY_MARKER not in calls[0] and RETRY_MARKER in calls[1]
    assert report["used_attempts"] == 2 and report["written"] == 0
    rejected = json.loads((root / "daily" / "2026-09-19" / "research-周五001.rejected.json").read_text(encoding="utf-8"))
    assert rejected["attempts_total"] == 2 and rejected["permanent"] is True
    second = run_day(day="2026-09-19", jczq_dir=root, data_dir=tmp_path,
                     claude=lambda system, brief: (0, GOOD), fulfill=lambda argv: (0, ""),
                     profile=lambda match_id: {}, budget=10, now=lambda: now + timedelta(hours=6))
    assert second["matches"][0]["status"] == "skipped_permanent"


def test_max_turns_then_success_on_marked_retry(tmp_path):
    from nutmeg.decision.research_runner import RETRY_MARKER
    root = _board(tmp_path, n=1)
    def claude(system, brief):
        return (0, GOOD) if RETRY_MARKER in brief else (1, "Error: Reached max turns (12)")
    report = run_day(day="2026-09-19", jczq_dir=root, data_dir=tmp_path, claude=claude,
                     fulfill=lambda argv: (0, ""), profile=lambda match_id: {}, budget=10,
                     now=lambda: datetime(2026, 9, 19, 10, 0, tzinfo=BJ))
    assert report["matches"][0]["status"] == "done" and report["used_attempts"] == 2
```

（`GOOD` 是该测试文件里已有的合法研究 JSON 常量；Task 3 之后它必须含 `stance`，见 Task 3 Step 4。）

- [ ] **Step 2: Run** → 两个测试失败（第一次就 permanent / 只有 1 次调用）。

- [ ] **Step 3: Implement**

`research_runner.py` 顶部：

```python
RETRY_MARKER = "⚠️RETRY-AFTER-MAX-TURNS"
RETRY_MAX_TURNS = "24"
RETRY_NOTE = (
    f"\n\n{RETRY_MARKER}：上一次在 12 轮内没有产出 JSON。这次：最多 4 次检索，然后必须输出契约 JSON；"
    "查不到的字段写「未证实」，不要继续搜。"
)
```

`_claude_cli`：`"--max-turns", RETRY_MAX_TURNS if RETRY_MARKER in brief else "12"`。

`_research_one` 的循环：把「`Reached max turns` → `permanent=True; break`」改为：

```python
            if "Reached max turns" in last_text:
                if RETRY_MARKER in brief:      # 第二次仍 max turns → 永久
                    permanent = True
                    break
                brief = brief + RETRY_NOTE     # 第一次：带标记再试一次
                continue
```

`_load_rejected`：`if "Reached max turns" in raw_output` 这条只在 `attempts_total >= 2` 时判 permanent（旧 rejected 文件里 `attempts_total == 1` 的 max-turns 记录允许重试一次）。

- [ ] **Step 4: Run** `uv run pytest tests/decision/test_research_runner.py -q` → 全部通过（含旧测试）。ruff clean。

- [ ] **Step 5: Commit** `git add nutmeg/decision/research_runner.py tests/decision/test_research_runner.py && git commit -m "feat(research): retry once with a marked brief after max turns before marking permanent"`

---

### Task 3: 契约、分析员必答段、runner 校验、`intake_board` 回填

**Files:**
- Modify: `nutmeg/decision/research_prompt.py`（`RESEARCH_JSON_CONTRACT` 加 stance）
- Modify: `.claude/agents/jczq-match-analyst.md`（加「## ★表态块（必答）」段）
- Modify: `nutmeg/decision/research_runner.py`（`_REQUIRED` 加 `"stance"`；`_validate` 调 `validate_stance`）
- Modify: `nutmeg/decision/jczq_reads.py::intake_board`
- Tests: 追加 `tests/decision/test_research_runner.py`、`tests/decision/test_jczq_reads.py`

- [ ] **Step 1: Tests**

```python
# 追加 tests/decision/test_jczq_reads.py
STANCE = {"face": "3", "structure": "double", "cover": "1", "confidence": 3,
          "falsifier": "客队首发若有主力门将则本判断作废", "why_not_market": "structure",
          "tilt": None, "alt_face": "1", "market_read": "agree"}


def test_intake_writes_stance_and_derived_faces(tmp_path):
    root = _day(tmp_path)
    research = {**RESEARCH, "stance": STANCE}
    (root / "daily" / "2026-09-19" / "research-周五001.json").write_text(json.dumps(research), encoding="utf-8")
    report = intake_board(day="2026-09-19", jczq_dir=root, write=True)
    assert report["ok"] == ["周五001"]
    leg = json.loads((root / "daily" / "2026-09-19" / "jczq-legs-base.json").read_text(encoding="utf-8"))["legs"]["周五001"]
    assert leg["stance"]["faces"] == "31" and leg["faces"] == "31"


def test_intake_rejects_stance_covering_a_dead_face(tmp_path):
    root = _day(tmp_path)
    research = {**RESEARCH, "stance": {**STANCE, "cover": "0"}}   # away 已判死
    (root / "daily" / "2026-09-19" / "research-周五001.json").write_text(json.dumps(research), encoding="utf-8")
    report = intake_board(day="2026-09-19", jczq_dir=root, write=True)
    assert "周五001" in report["failed"] and any("已判死" in m for m in report["failed"]["周五001"])


def test_intake_without_stance_is_rejected(tmp_path):
    root = _day(tmp_path)
    report = intake_board(day="2026-09-19", jczq_dir=root, write=False)
    assert any("stance" in m for m in report["failed"].get("周五001", []))
```

```python
# 追加 tests/decision/test_research_runner.py
def test_missing_stance_is_rejected_by_validate(tmp_path):
    from nutmeg.decision.research_runner import _validate
    doc = json.loads(GOOD)
    doc.pop("stance")
    with pytest.raises(ValueError, match="stance"):
        _validate(json.dumps(doc), {"fair": {"home": .5, "draw": .3, "away": .2}, "match_no": 1})
```

同时把该文件的 `GOOD` 常量加上 `"stance": {...STANCE 同上...}`，并把 `tests/decision/test_jczq_reads.py` 里 `RESEARCH` 也加上 `"stance": STANCE`（既有测试从此都带表态；`_day` 写入的研究 JSON 也带）。

- [ ] **Step 2: Run** → 失败（`stance` 不在 `_REQUIRED`；intake 不写 stance）。

- [ ] **Step 3: Implement**

`research_prompt.py`：在 `"schedule": {...}, "market_snapshot": {...}}` 之后加：

```
 "stance": {"face": "3|1|0", "structure": "single|double|full", "cover": "3|1|0|null",
     "confidence": 1-5, "falsifier": "一句赛后可核验的作废条件",
     "why_not_market": "none|tilt_evidence|structure",
     "tilt": null | {"face": "3|1|0", "expires_if": str,
         "evidence": [{"tier": "official|confirmed_structural|inferred|will",
                       "kind": "absence_official|suspension|goalkeeper_change|anchor_integrity_fail|lineup_confirmed|venue_anomaly|precedent_carrier|rotation_confirmed|schedule_congestion|motivation_dead_rubber",
                       "pp": 0-8, "source": str, "captured_at": "ISO"}]},
     "alt_face": "3|1|0|null", "market_read": "agree|overpriced|underpriced|null"}}
表态块必答：每场押一个面 + 一个表达档 + 一句作废条件；跟市场也要填（why_not_market=none, tilt=null）。
tilt 只在有 A/B 类证据时给：official 4–8pp、confirmed_structural 3–6pp、inferred 0–2pp、will 0–2pp 且只许朝平；
净偏移 <5pp 会被机器归零；无官宣封顶 10pp、有官宣 15pp；开球后采集的证据作废。stance.confidence 必须等于顶层 confidence。
```

`.claude/agents/jczq-match-analyst.md` 在「## 收尾小结」之前加：

```markdown
## ★表态块（2026-09-23 落库，必答）
- 押**一个面**（3/1/0）+ 表达档（single/double/full，double 必给 cover）+ 一句**赛后可核验**的作废条件。跟市场也是判断：`why_not_market=none`。
- 想把 belief 拨离市场只有一条路：`tilt` 里列 A/B 类证据（官宣缺阵/停赛/门将/锚方完整度 FAIL/确认首发/赛地异常/先例载体/轮换确认/赛程拥塞/战意死局），每条给 tier、pp、来源、采集时间。机器按 RULEBOOK 权重表裁：<5pp 归零，封顶 10/15pp，开球后证据作废。
- `alt_face`（如果押错最可能开哪面）与 `market_read`（市场对这场 agree/overpriced/underpriced）只记录、不加权。
```

`research_runner.py`：`_REQUIRED += ("stance",)`；`_validate` 在 `intake(doc, dict(leg))` 之前：

```python
    from nutmeg.decision.stance import validate_stance

    _norm, stance_issues = validate_stance(
        doc.get("stance"), confidence=doc.get("confidence"),
        death_three_proofs=doc.get("death_three_proofs") or {},
    )
    if stance_issues:
        raise ValueError("stance: " + "; ".join(i.message for i in stance_issues))
```

`jczq_reads.py::intake_board`：在 `attach_face_status(...)` 成功之后、写回 leg 之前：

```python
        from nutmeg.decision.stance import validate_stance

        norm, stance_issues = validate_stance(
            research.get("stance"), confidence=research.get("confidence"),
            death_three_proofs=research.get("death_three_proofs") or {},
        )
        if stance_issues:
            failed[code] = [f"stance.{i.field}: {i.message}" for i in stance_issues]
            （与既有 intake ERROR 同一处理：write 时降 price_only、写 rejected 文件、删研究文件；continue）
        candidate["stance"] = norm
        candidate["faces"] = norm["faces"]
```

（`attach_face_status` 要求已写的 `faces` 与 face_status 一致——`validate_stance` 已拒绝含死面的集合，所以此处写 `faces` 不会与它冲突；若 `attach_face_status` 在写 faces 之后还会再校验一次，把 `candidate["faces"]` 的赋值放在它之后。）

- [ ] **Step 4: Run** `uv run pytest tests/decision/test_jczq_reads.py tests/decision/test_research_runner.py -q` → 全部通过；ruff clean。

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/research_prompt.py .claude/agents/jczq-match-analyst.md nutmeg/decision/research_runner.py nutmeg/decision/jczq_reads.py tests/decision/test_jczq_reads.py tests/decision/test_research_runner.py
git commit -m "feat(research): stance block is part of the contract; intake writes stance and derived faces"
```

---

### Task 4: `build_jczq_reads` 用表态定 belief / falsifier / confidence

**Files:**
- Modify: `nutmeg/decision/jczq_reads.py::build_jczq_reads`
- Test: 追加 `tests/decision/test_jczq_reads.py`

- [ ] **Step 1: Tests**

```python
def test_reads_take_belief_from_tilt_and_carry_stance(tmp_path):
    root = _day(tmp_path)
    tilt = {"face": "3", "expires_if": "X 出场则撤回", "evidence": [
        {"tier": "official", "kind": "absence_official", "pp": 6, "source": "club",
         "captured_at": "2026-09-19T10:00:00+08:00"}]}
    research = {**RESEARCH, "stance": {**STANCE, "why_not_market": "tilt_evidence", "tilt": tilt}}
    (root / "daily" / "2026-09-19" / "research-周五001.json").write_text(json.dumps(research), encoding="utf-8")
    intake_board(day="2026-09-19", jczq_dir=root, write=True)
    reads = build_jczq_reads(day="2026-09-19", jczq_dir=root, made_at="2026-09-19T12:00:00+08:00")
    r = reads[0]
    assert round(r["belief"]["home"] - r["prior"]["home"], 2) == 0.06
    assert r["adjustment_evidence_tiers"] == ["official"]
    assert r["falsifier"] == STANCE["falsifier"] and r["confidence"] == 3
    assert r["commitment_tier"] == "lean" and r["stance"]["faces"] == "31"
    assert r["stance"]["tilt_applied_pp"] == 6 and r["stance"]["tilt_zeroed"] is False


def test_reads_zero_small_tilt_and_keep_alive_normalisation(tmp_path):
    root = _day(tmp_path)
    tilt = {"face": "3", "expires_if": "", "evidence": [
        {"tier": "inferred", "kind": "rotation_confirmed", "pp": 2, "source": "s",
         "captured_at": "2026-09-19T10:00:00+08:00"}]}
    research = {**RESEARCH, "stance": {**STANCE, "why_not_market": "tilt_evidence", "tilt": tilt}}
    (root / "daily" / "2026-09-19" / "research-周五001.json").write_text(json.dumps(research), encoding="utf-8")
    intake_board(day="2026-09-19", jczq_dir=root, write=True)
    r = build_jczq_reads(day="2026-09-19", jczq_dir=root, made_at="2026-09-19T12:00:00+08:00")[0]
    assert r["belief"]["away"] == 0.0            # away 判死 → 活面归一仍生效
    assert r["stance"]["tilt_zeroed"] is True and "归零" in r["stance"]["tilt_reason"]
    assert r["adjustment_evidence_tiers"] == []
```

- [ ] **Step 2: Run** → 失败（Read 无 `stance`）。

- [ ] **Step 3: Implement**（`build_jczq_reads` 的 `if researched:` 分支之后）

```python
        stance = leg.get("stance") if researched else None
        tilt_info = {}
        if stance:
            from nutmeg.decision.stance import apply_tilt

            result = apply_tilt(prior, stance.get("tilt"), kickoff=leg.get("kickoff_bj"))
            if not result.zeroed:
                # 拨动作用在 prior 上，再把死面清零并归一（三证优先于拨动）
                alive_belief = {f: (result.belief[f] if f in alive else 0.0) for f in FACES}
                mass = sum(alive_belief.values()) or 1.0
                belief = {f: v / mass for f, v in alive_belief.items()}
            tilt_info = {"tilt_applied_pp": result.applied_pp, "tilt_zeroed": result.zeroed,
                         "tilt_reason": result.reason}
        commitment = {"single": "commit", "double": "lean", "full": "cover"}.get(
            (stance or {}).get("structure"), "lean")
```

Read 字典里：`"falsifier": stance["falsifier"] if stance else (...原来的...)`、`"confidence": stance["confidence"] if stance else (...)`、`"commitment_tier": commitment`、`"stance": {**stance, **tilt_info} if stance else None`、`"adjustment_evidence_tiers": (stance or {}).get("tiers", []) if stance and not tilt_info.get("tilt_zeroed", True) else []`。

- [ ] **Step 4: Run** `uv run pytest tests/decision/test_jczq_reads.py -q` → 通过；ruff clean。

- [ ] **Step 5: Commit** `git add nutmeg/decision/jczq_reads.py tests/decision/test_jczq_reads.py && git commit -m "feat(reads): belief, falsifier and commitment come from the stance; tilt goes through l-rule arithmetic"`

---

### Task 5: 日报与页面显示表态

**Files:**
- Modify: `nutmeg/decision/day_brief.py`（卡片 `stance`；表格加「表态」列；`_ladder` 用 `stance.why_not_market` 补「未表态」）
- Modify: `nutmeg/decision/day_session.py`（每场一行加 `面/档`）
- Modify: `nutmeg/interfaces/web/static/decision/day.js`（徽章 `押 3 · double(31)`、拨动原因）
- Tests: 追加 `tests/decision/test_day_brief.py`、`tests/decision/test_day_session.py`

- [ ] **Step 1: Tests**

```python
# test_day_brief.py 追加：在 _fixture 的 reads.json 第一条加
#   "stance": {"face": "3", "structure": "double", "cover": "1", "faces": "31", "why_not_market": "tilt_evidence",
#              "tilt_applied_pp": 6, "tilt_zeroed": False, "tilt_reason": "拨 6pp 向 3", "falsifier": "…"},
#   "adjustment_evidence_tiers": ["official"]
def test_card_carries_stance_and_md_shows_it(tmp_path: Path):
    data, root = _fixture(tmp_path)
    brief = compile_brief(data_dir=data, date="2026-09-23", root=root, now=NOW)
    a = brief["jczq"]["matches"][0]
    assert a["stance"]["faces"] == "31" and a["stance"]["tilt_applied_pp"] == 6
    assert a["read"]["tiers"] == ["official"]
    md = render_brief_md(brief)
    assert "押3·31" in md
```

```python
# test_day_session.py：现有 brief fixture 的 match 加 "stance": {"faces": "31", "face": "3", "why_not_market": "none"}，断言
    assert "押3·31" in md
```

- [ ] **Step 2: Run** → 失败。

- [ ] **Step 3: Implement**

`day_brief.py`：`read` dict 加 `"tiers": raw_read.get("adjustment_evidence_tiers") or []`；卡片加 `"stance": raw_read.get("stance") if raw_read else None`；`render_brief_md` 表头加「表态」列，值 `押{face}·{faces}`（无表态 `—`）；`_ladder`：`read is None → "未判"`；`stance` 存在且 `why_not_market == "none"` 且未拨 → `"跟市场"`（既有逻辑已覆盖，只加注释）。
`day_session.py`：每场一行在阶梯前插 `押{face}·{faces}`（无表态 `未表态`）。
`day.js` `card()`：`if (m.stance) badges.appendChild(el("span","day-badge","押 "+m.stance.face+" · "+m.stance.structure+"("+m.stance.faces+")"))`；`if (m.stance && m.stance.tilt_reason) c.appendChild(el("p","obs-muted","拨动："+m.stance.tilt_reason))`。

- [ ] **Step 4: Run** `uv run pytest tests/decision/test_day_brief.py tests/decision/test_day_session.py tests/test_decision_web_day.py -q` → 通过；ruff clean。

- [ ] **Step 5: Commit** `git add nutmeg/decision/day_brief.py nutmeg/decision/day_session.py nutmeg/interfaces/web/static/decision/day.js tests/decision/test_day_brief.py tests/decision/test_day_session.py && git commit -m "feat(day): show the stance (face / structure / tilt) on cards, brief and session"`

---

### Task 6: 证据

- [ ] `docs/superpowers/evidence/2026-09-23-research-stance-contract.md`：测试结果；`uv run nutmeg research run --day <明天> --code <一场>` 的真实产物里 `stance` 原文；`reads.json` 里首条 `belief ≠ prior` 的 Read；被 max turns 重试的场的 `attempt_errors`。未做：足彩泳道 `judgment-v1` 合流。
- [ ] Commit。

---

## Self-review

- Spec §3 全部字段有校验（T1）；§4 算术（T1）；§5 五处接线（T2–T5）；§6 边界：拨动只经 `apply_tilt`，C8 继续用 `adjustment_evidence_tiers`（T4 写入）。
- 类型一致：`validate_stance(stance, *, confidence, death_three_proofs) -> (norm, issues)`；`apply_tilt(prior, tilt, *, kickoff) -> TiltResult(belief, applied_pp, zeroed, reason, tiers)`；`norm["faces"]`、`norm["tiers"]` 被 T3/T4 使用；Read 的 `stance` 字段含 `tilt_applied_pp/tilt_zeroed/tilt_reason`，T5 读它们。
- 不触碰 `research_intake.py`。
