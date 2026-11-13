"""足彩侧的并集样本池：研究表态 → judgment-v1 → Read（Jun 2026-09-27）。

足彩 Read 原本只能由主循环手写 judgment-v1 生成，没人跑 B 泳道的期次整期不进 F9。
本模块只做**转录**，与竞彩泳道同一口径（研究 stance → tilt 算术 → belief）：

- 主循环写了 `{issue}-judgment-v1.json` 的场次：原样用主循环的（永远优先）；
- 有深研的场次：转录研究表态（足彩独有场次读 `{issue}-research-m{n}.json`，
  已对到竞彩的场次读竞彩的 `research-{code}.json`）；
- 两者都没有：市场锚定（belief = prior，confidence 1）。

⛔判断永不入脚本：这里不产生任何判断，只搬运 agent 表态与确定性算术。
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path

from nutmeg.decision.bj_time import aware
from nutmeg.decision.overrides import effective_research
from nutmeg.decision.read_builder import build
from nutmeg.decision.stance import research_belief, validate_stance
from nutmeg.decision.zucai_identity import load_channel_map

JUDGE = "ai-pool"
_TRANSCRIBED = ("directional_flags", "nondirectional_flags", "anchor_integrity",
                "license_questions", "crash_markers", "tracking_tags", "team_tags")


def _load(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _jczq_research_by_match_id(data_dir: Path, deadline_day: str) -> dict[str, Path]:
    """对到竞彩的场次：到截止日前后一天的竞彩腿表里按 match_id 找研究文件。"""
    out: dict[str, Path] = {}
    base = date.fromisoformat(deadline_day)
    for offset in (-1, 0, 1, 2):
        day_dir = Path(data_dir) / "jczq" / "daily" / (base + timedelta(days=offset)).isoformat()
        legs = (_load(day_dir / "jczq-legs-base.json", {}) or {}).get("legs") or {}
        for code, leg in legs.items():
            path = day_dir / f"research-{code}.json"
            if isinstance(leg, dict) and leg.get("match_id") and path.exists():
                out.setdefault(str(leg["match_id"]), path)
    return out


def _research_path(zucai_dir: Path, issue: str, no: str, mapped: dict[int, str],
                   jczq_research: dict[str, Path]) -> Path | None:
    own = zucai_dir / f"{issue}-research-m{no}.json"
    if own.exists():
        return own
    match_id = mapped.get(int(no))
    return jczq_research.get(match_id) if match_id else None


def _from_research(research: dict, prior: dict, kickoff: str) -> dict | None:
    from nutmeg.decision.jczq_reads import rubric_read_view

    norm, issues = validate_stance(
        research.get("stance"), confidence=research.get("confidence"),
        death_three_proofs=research.get("death_three_proofs") or {},
    )
    if any(issue.level == "ERROR" for issue in issues):
        return None
    # 三证判死的面不清零（2026-11-13，P-70233890；见 `stance.research_belief`）
    belief, tilt = research_belief(prior, norm.get("tilt"), kickoff=kickoff)
    moved = not tilt.zeroed
    entry = {key: research[key] for key in _TRANSCRIBED if key in research}
    entry.update({
        "action": norm["faces"],
        "prescription": norm["faces"],
        "confidence": int(research["confidence"]),
        "precedents": [p for p in research.get("precedents") or [] if isinstance(p, list)],
        "falsifier": norm["falsifier"],
        "stance": norm,
        "note": f"【并集池·研究转录】{str(research.get('summary') or '')[:300]}",
        "belief": belief,
        "adjustment_evidence_tiers": list(tilt.tiers) if moved else [],
        "source": "research",
        "rubric": rubric_read_view(research.get("rubric"), norm),
    })
    return entry


def market_gaps(*, issue: str, data_dir: Path) -> dict[str, str]:
    """逐场列报价/身份缺口，不补价；供刷新回执和交付检查使用。"""
    zdir = Path(data_dir) / "zucai"
    store = _load(zdir / f"{issue}-store-ids.json", {}) or {}
    issue_doc = _load(zdir / f"{issue}-issue.json", {}) or {}
    expected = {str(m["match_no"]) for m in issue_doc.get("matches") or []} or set(store)
    gaps = {}
    for no in sorted(expected | set(store), key=int):
        ids = store.get(no) or {}
        missing = [key for key in ("match_id", "snapshot_id") if not ids.get(key)]
        fair = ids.get("fair")
        try:
            values = [fair[f] for f in ("home", "draw", "away")]
            valid = all(isinstance(v, (int, float)) and not isinstance(v, bool)
                        and math.isfinite(v) and 0 <= v <= 1 for v in values)
            valid = valid and abs(sum(values) - 1) < .001
        except (TypeError, KeyError):
            valid = False
        if not valid:
            missing.append("fair")
        if missing:
            gaps[no] = "缺/无效 " + "、".join(missing)
    return gaps


def auto_judgment(*, issue: str, data_dir: Path) -> dict:
    zucai_dir = Path(data_dir) / "zucai"
    issue_doc = _load(zucai_dir / f"{issue}-issue.json", {})
    store = _load(zucai_dir / f"{issue}-store-ids.json", {})
    manual = _load(zucai_dir / f"{issue}-judgment-v1.json", {}) or {}
    mapped = {no: mid for mid, no in load_channel_map(zucai_dir, issue).items()}
    deadline_day = str(issue_doc.get("sale_deadline") or "")[:10]
    jczq_research = _jczq_research_by_match_id(Path(data_dir), deadline_day) if deadline_day else {}
    kickoffs = {str(m["match_no"]): str(m.get("kickoff_bj") or "")
                for m in issue_doc.get("matches") or []}
    judgment: dict[str, dict] = {}
    gaps = market_gaps(issue=issue, data_dir=data_dir)
    for no, ids in store.items():
        if no in gaps:
            continue
        if no in manual:
            judgment[no] = {**manual[no], "source": "main_loop"}
            continue
        prior = dict(ids["fair"])
        kickoff = aware(kickoffs[no]).isoformat() if kickoffs.get(no) else None
        path = _research_path(zucai_dir, issue, no, mapped, jczq_research)
        entry = _from_research(effective_research(path), prior, kickoff) if path else None
        judgment[no] = entry or {
            "action": "310", "prescription": "310", "confidence": 1,
            "belief": prior, "adjustment_evidence_tiers": [],
            "note": "【并集池·市场锚定】无深研", "source": "market_anchor",
        }
    return judgment


def build_auto_reads(*, issue: str, data_dir: Path, made_at: str) -> list[dict]:
    """并集池足彩 Read：主循环 Read 永不覆盖；已开球场次保留旧 Read（前瞻性）。"""
    zucai_dir = Path(data_dir) / "zucai"
    store = _load(zucai_dir / f"{issue}-store-ids.json", {})
    issue_doc = _load(zucai_dir / f"{issue}-issue.json", {})
    kickoffs = {str(m["match_no"]): aware(str(m["kickoff_bj"]))
                for m in issue_doc.get("matches") or [] if m.get("kickoff_bj")}
    reads_path = zucai_dir / f"{issue}-reads.json"
    existing = {read["match_id"]: read for read in _load(reads_path, []) or []}
    built_at = datetime.fromisoformat(made_at)
    judgment = auto_judgment(issue=issue, data_dir=data_dir)
    rebuild = {
        no: entry for no, entry in judgment.items()
        if not (
            store[no]["match_id"] in existing
            and (existing[store[no]["match_id"]].get("judge") != JUDGE
                 or kickoffs.get(no, built_at) <= built_at)
        )
    }
    revision = int("".join(ch for ch in made_at if ch.isdigit())[8:12] or 0)
    fresh = build(
        rebuild, issue=issue, store_ids=store,
        fair={no: store[no]["fair"] for no in rebuild}, made_at=made_at,
        judge=JUDGE, revision=revision,
    ).reads if rebuild else []
    by_match = dict(existing)
    kinds = {"main_loop": "manual", "research": "research", "market_anchor": "market"}
    for read in fresh:
        no = next(no for no in rebuild if store[no]["match_id"] == read["match_id"])
        source = judgment[no]["source"]
        read["judgment_tier"] = source
        # 判断唯一事实 P0：Read 自报板与种类，内核按 board_key 投影
        read["code"] = str(no)
        read["board_key"] = f"zucai:{issue}"
        read["kind"] = kinds.get(source, source)
        by_match[read["match_id"]] = read
    order = [store[no]["match_id"] for no in sorted(store, key=int)
             if (store[no] or {}).get("match_id")]
    reads = [by_match[mid] for mid in order if mid in by_match]
    reads_path.write_text(json.dumps(reads, ensure_ascii=False, indent=1), encoding="utf-8")
    return reads


AUTO_MARK = "zucai_auto_judgment"


def ensure_auto_legs_base(*, issue: str, data_dir: Path, made_at: str) -> dict:
    """足彩 legs-base 自动版（2026-10-02，Jun「解决剩余的问题」）：机器初稿依赖它，
    以前只有主循环手跑 B4（zucai-research-intake / zucai-build-reads）才有。

    判断来源与 Read 相同（`auto_judgment`：主循环 judgment-v1 永远优先 → 研究表态转录 →
    市场锚定），fair 用 store-ids 里同一份；每场再把研究的结构字段（表态、rubric、旗、
    三证、强弱天平）经 `research_intake.intake` 转录进 leg 并挂 face_status。
    ⛔绝不覆盖主循环手工建的 legs-base（没有 `auto` 标记的一律不动）。
    → {"status": "written"|"kept_manual"|"skipped", ...}
    """
    from nutmeg.decision.face_status import FaceStatusError, attach_face_status
    from nutmeg.decision.research_intake import intake

    zucai_dir = Path(data_dir) / "zucai"
    legs_path = zucai_dir / f"{issue}-legs-base.json"
    existing = _load(legs_path, None)
    if existing is not None and not (existing.get("auto") or {}).get("source") == AUTO_MARK:
        return {"status": "kept_manual", "path": str(legs_path)}
    store = _load(zucai_dir / f"{issue}-store-ids.json", {})
    if not store:
        return {"status": "skipped", "reason": "无 store-ids"}
    issue_doc = _load(zucai_dir / f"{issue}-issue.json", {})
    mapped = {no: mid for mid, no in load_channel_map(zucai_dir, issue).items()}
    deadline_day = str(issue_doc.get("sale_deadline") or "")[:10]
    jczq_research = _jczq_research_by_match_id(Path(data_dir), deadline_day) if deadline_day else {}
    judgment = auto_judgment(issue=issue, data_dir=data_dir)
    result = build(judgment, issue=issue, store_ids=store,
                   fair={no: store[no]["fair"] for no in judgment}, made_at=made_at,
                   judge=JUDGE)
    doc = result.legs
    notes: list[str] = []
    for no, leg in doc["legs"].items():
        path = _research_path(zucai_dir, issue, no, mapped, jczq_research)
        research = effective_research(path) if path else {}
        if research:
            transcribed = intake(research, leg, match_no=int(no))
            if transcribed.blocked:
                errors = "; ".join(i.message for i in transcribed.issues if i.level == "ERROR")
                notes.append(f"场{no} 研究入库被拦：{errors[:120]}")
            else:
                leg.update(transcribed.leg)
            if research.get("rubric"):
                leg["rubric"] = research["rubric"]
        try:
            attach_face_status(leg, research, source=path.name if path else "market")
        except FaceStatusError as exc:
            notes.append(f"场{no} face_status：{exc}")
    gaps = market_gaps(issue=issue, data_dir=data_dir)
    doc["auto"] = {"source": AUTO_MARK, "built_at": made_at, "notes": notes,
                   "complete": not gaps, "missing": gaps}
    legs_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"status": "partial" if gaps else "written", "path": str(legs_path),
            "legs": len(doc["legs"]), "notes": notes, "missing": gaps}
