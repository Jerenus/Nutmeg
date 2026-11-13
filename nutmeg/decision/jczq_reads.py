"""Intake JCZQ research by board code and build AI draft Read payloads."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from nutmeg.decision.face_status import FaceStatusError, attach_face_status
from nutmeg.decision.overrides import effective_research
from nutmeg.decision.research_intake import intake
from nutmeg.decision.stance import research_belief, validate_stance


def _quarantine(
    leg: dict, research_path: Path, code: str, errors: list[str], research: dict
) -> None:
    """研究被拒：腿降回 price_only、写 .rejected.json、删研究文件。"""
    leg["judgment_tier"] = "price_only"
    leg.pop("face_status", None)
    rejected_path = research_path.with_name(f"research-{code}.rejected.json")
    rejected_path.write_text(
        json.dumps(
            {
                "code": code,
                "status": "rejected",
                "errors": errors,
                "research": research,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    research_path.unlink()


def intake_board(*, day: str, jczq_dir: Path, write: bool) -> dict:
    day_dir = Path(jczq_dir) / "daily" / day
    board_path = day_dir / "jczq-legs-base.json"
    board = json.loads(board_path.read_text(encoding="utf-8"))
    ok: list[str] = []
    failed: dict[str, list[str]] = {}
    for code, original_leg in board["legs"].items():
        research_path = day_dir / f"research-{code}.json"
        if not research_path.exists():
            continue
        # 研究原件只读；主循环改判从 overrides.jsonl 叠加（2026-09-27）
        research = effective_research(research_path)
        result = intake(research, dict(original_leg))
        errors = [issue.message for issue in result.issues if issue.level == "ERROR"]
        if errors:
            failed[code] = errors
            if write:
                _quarantine(original_leg, research_path, code, errors, research)
            continue
        candidate = result.leg
        candidate.pop("faces", None)
        try:
            attach_face_status(
                candidate,
                research,
                source=research_path.name,
                basis="researched",
            )
        except FaceStatusError as exc:
            failed[code] = [str(exc)]
            continue
        # 表态块：面集合不得含已判死的面；派生 faces 覆盖 face_status 推出的活面集合
        # （validate_stance 已拒绝含死面的集合，所以此处写 faces 与 face_status 不冲突）
        norm, stance_issues = validate_stance(
            research.get("stance"),
            confidence=research.get("confidence"),
            death_three_proofs=research.get("death_three_proofs") or {},
        )
        if stance_issues:
            errors = [f"stance.{i.field}: {i.message}" for i in stance_issues]
            failed[code] = errors
            if write:
                _quarantine(original_leg, research_path, code, errors, research)
            continue
        candidate["stance"] = norm
        candidate["faces"] = norm["faces"]
        board["legs"][code] = candidate
        ok.append(code)
    if write:
        board_path.write_text(
            json.dumps(board, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        run_report_path = day_dir / f"research-run-{day}.json"
        if run_report_path.exists() and failed:
            run_report = json.loads(run_report_path.read_text(encoding="utf-8"))
            for row in run_report.get("matches") or []:
                if row.get("code") in failed:
                    row["status"] = "rejected"
                    row["intake_errors"] = failed[row["code"]]
            run_report_path.write_text(
                json.dumps(run_report, ensure_ascii=False, indent=1), encoding="utf-8"
            )
    return {"ok": ok, "failed": failed}


def _rev(made_at: str) -> str:
    """草稿 Read 的版本后缀（HHMM）。

    同一天多次落 Read 内容会变，键不变会撞幂等冲突（2026-09-19 早/午两版）。
    """
    digits = "".join(ch for ch in made_at if ch.isdigit())
    return digits[8:12] if len(digits) >= 12 else "0000"


def rubric_read_view(rubric: dict | None, stance: dict | None) -> dict | None:
    """Read 里的 rubric 账：版本、逐项答案（去掉 note）、派生 tilt 的逐项 pp、读者整体概率。"""
    if not isinstance(rubric, dict) or not rubric.get("items"):
        return None
    items = {k: {f: v.get(f) for f in ("answer", "p", "abstain", "coerced")}
             for k, v in rubric["items"].items() if isinstance(v, dict)}
    tilt = (stance or {}).get("tilt") or {}
    item_pp = {e["item"]: e["pp"] for e in (tilt.get("evidence") or []) if e.get("item")} \
        if tilt.get("derived_from") else {}
    return {"version": rubric.get("version"), "items": items, "item_pp": item_pp,
            "shift": tilt.get("shift") if tilt.get("derived_from") else None,
            "reader_belief": rubric.get("belief"), "coerced": list(rubric.get("coerced") or [])}


def build_jczq_reads(*, day: str, jczq_dir: Path, made_at: str) -> list[dict]:
    from nutmeg.decision.overrides import load_overrides

    day_dir = Path(jczq_dir) / "daily" / day
    board = json.loads(
        (day_dir / "jczq-legs-base.json").read_text(encoding="utf-8")
    )
    # 改判账：有一行就把这条 Read 标成 kind=override（判断唯一事实 P1：改判＝新 revision）
    overrides = {row["research"]: row for row in load_overrides(day_dir)}
    reads_path = day_dir / "reads.json"
    previous_by_match = {
        read["match_id"]: read
        for read in (
            json.loads(reads_path.read_text(encoding="utf-8")) if reads_path.exists() else []
        )
        if read.get("match_id")
    }
    built_at = datetime.fromisoformat(made_at)
    reads: list[dict] = []
    for code, leg in board["legs"].items():
        # 已开球：保留赛前最后一版 Read，不用赛后价格/赛后改判重算（语料与 F9 的前瞻性）
        previous = previous_by_match.get(leg["match_id"])
        if previous is not None and datetime.fromisoformat(leg["kickoff_bj"]) <= built_at:
            reads.append(previous)
            continue
        face_status = leg.get("face_status") or {}
        researched_basis = bool(face_status) and all(
            row.get("basis") == "researched" for row in face_status.values()
        )
        researched = (
            bool(face_status)
            and (
                leg.get("judgment_tier") == "deep_research"
                or researched_basis
            )
        )
        prior = dict(leg["fair"])
        # 表态块：有 tilt 则走 l 条拨动算术；三证判死的面只记在 face_status，不清零。
        # 「跟市场」是宪法 §2 的明文判断：无命名理由即市场锚定。
        # 它是可被 Brier 评分的陈述，不是判断缺席；强度只决定结构。
        stance = leg.get("stance") if researched else None
        belief = dict(prior)
        result = None
        if researched:
            belief, result = research_belief(
                prior, (stance or {}).get("tilt"), kickoff=leg.get("kickoff_bj"))
        tilt_info: dict = {}
        if stance:
            tilt_info = {
                "tilt_applied_pp": result.applied_pp,
                "tilt_zeroed": result.zeroed,
                "tilt_reason": result.reason,
            }
        commitment = {"single": "commit", "double": "lean", "full": "cover"}.get(
            (stance or {}).get("structure"), "lean"
        )
        tilt_applied = bool(stance) and not tilt_info.get("tilt_zeroed", True)
        judge = "ai:jczq-analyst" if researched else "market-anchor"
        read_source = "ai" if researched else "market-anchor"
        tier = "deep_research" if researched else "price_only"
        override = overrides.get(f"research-{code}.json") if researched else None
        reads.append(
            {
                "read_id": f"R-{read_source}-jczq-{day}-{code}-had-{_rev(made_at)}",
                "match_id": leg["match_id"],
                "code": code,
                "board_key": f"jczq:{day}",
                "kind": (
                    "override" if override else ("research" if researched else "market")
                ),
                "override": (
                    {key: override.get(key) for key in ("at", "note", "judge")}
                    if override else None
                ),
                "snapshot_id": leg.get("snapshot_id"),
                "made_at": made_at,
                "judge": judge,
                "market": "had",
                "prior": prior,
                "belief": belief,
                "factors": [],
                "falsifier": (
                    stance["falsifier"]
                    if stance
                    else (
                        f"{code}: 被排死面开出则记录三证失效"
                        if researched
                        else f"{code}: 市场锚定按赛果计 Brier"
                    )
                ),
                "confidence": (
                    stance["confidence"]
                    if stance
                    else (leg.get("confidence", 3) if researched else 1)
                ),
                "shadow": False,
                "note": f"[{code}|{leg['name']}|{tier}] {leg.get('note', '')}",
                "status": "draft",
                "commitment_tier": commitment,
                "judgment_tier": tier,
                "flags": {
                    "directional": leg.get("directional_flags", []),
                    "nondirectional": leg.get("nondirectional_flags", []),
                },
                "stance": {**stance, **tilt_info} if stance else None,
                "adjustment_evidence_tiers": (
                    list(result.tiers) if tilt_applied else []
                ),
                "rubric": rubric_read_view(leg.get("rubric"), stance) if researched else None,
            }
        )
    (day_dir / "reads.json").write_text(
        json.dumps(reads, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return reads
