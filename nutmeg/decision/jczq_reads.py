"""Intake JCZQ research by board code and build AI draft Read payloads."""
from __future__ import annotations

import json
from pathlib import Path

from nutmeg.decision.face_status import FaceStatusError, attach_face_status
from nutmeg.decision.research_intake import intake
from nutmeg.decision.stance import apply_tilt, validate_stance

FACES = ("home", "draw", "away")


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
        research = json.loads(research_path.read_text(encoding="utf-8"))
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


def build_jczq_reads(*, day: str, jczq_dir: Path, made_at: str) -> list[dict]:
    day_dir = Path(jczq_dir) / "daily" / day
    board = json.loads(
        (day_dir / "jczq-legs-base.json").read_text(encoding="utf-8")
    )
    reads: list[dict] = []
    for code, leg in board["legs"].items():
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
        if researched:
            alive = [
                face
                for face in FACES
                if leg["face_status"][face]["state"] == "alive"
            ]
            mass = sum(float(leg["fair"][face]) for face in alive)
            if mass <= 0:
                raise ValueError(f"{code} 没有可归一的活面")
            belief = {
                face: float(leg["fair"][face]) / mass if face in alive else 0.0
                for face in FACES
            }
        else:
            # 「跟市场」是宪法 §2 的明文判断：无命名理由即市场锚定。
            # 它是可被 Brier 评分的陈述，不是判断缺席；强度只决定结构。
            belief = dict(prior)
        # 表态块：有 tilt 则走 l 条拨动算术；三证判死的面优先于拨动——
        # 拨动作用在 prior 上，再把死面清零并在活面上归一。
        stance = leg.get("stance") if researched else None
        tilt_info: dict = {}
        if stance:
            result = apply_tilt(
                prior, stance.get("tilt"), kickoff=leg.get("kickoff_bj")
            )
            if not result.zeroed:
                tilted = {
                    face: (result.belief[face] if face in alive else 0.0)
                    for face in FACES
                }
                tilted_mass = sum(tilted.values()) or 1.0
                belief = {face: value / tilted_mass for face, value in tilted.items()}
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
        reads.append(
            {
                "read_id": f"R-{read_source}-jczq-{day}-{code}-had-{_rev(made_at)}",
                "match_id": leg["match_id"],
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
            }
        )
    (day_dir / "reads.json").write_text(
        json.dumps(reads, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return reads
