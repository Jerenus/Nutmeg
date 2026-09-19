"""Intake JCZQ research by board code and build AI draft Read payloads."""
from __future__ import annotations

import json
from pathlib import Path

from nutmeg.decision.face_status import FaceStatusError, attach_face_status
from nutmeg.decision.research_intake import intake

FACES = ("home", "draw", "away")


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
                original_leg["judgment_tier"] = "price_only"
                original_leg.pop("face_status", None)
                rejected_path = day_dir / f"research-{code}.rejected.json"
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
        judge = "ai:jczq-analyst" if researched else "market-anchor"
        read_source = "ai" if researched else "market-anchor"
        tier = "deep_research" if researched else "price_only"
        reads.append(
            {
                "read_id": f"R-{read_source}-jczq-{day}-{code}-had",
                "match_id": leg["match_id"],
                "snapshot_id": leg.get("snapshot_id"),
                "made_at": made_at,
                "judge": judge,
                "market": "had",
                "prior": prior,
                "belief": belief,
                "factors": [],
                "falsifier": (
                    f"{code}: 被排死面开出则记录三证失效"
                    if researched
                    else f"{code}: 市场锚定按赛果计 Brier"
                ),
                "confidence": leg.get("confidence", 3) if researched else 1,
                "shadow": False,
                "note": f"[{code}|{leg['name']}|{tier}] {leg.get('note', '')}",
                "status": "draft",
                "commitment_tier": "lean",
                "judgment_tier": tier,
                "flags": {
                    "directional": leg.get("directional_flags", []),
                    "nondirectional": leg.get("nondirectional_flags", []),
                },
            }
        )
    (day_dir / "reads.json").write_text(
        json.dumps(reads, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return reads
