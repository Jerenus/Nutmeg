"""Backfill the 26129 candidate tree, capital plan, and two cap adjudications.

The operation is append-only and idempotent. Intermediate SFC faces were not
recorded outside chat, so those nodes remain empty; final faces come from the
registered betslips.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.decision.rsi_wiring import after_capital_plan
from nutmeg.decision.workbench import append_candidate, read_events
from nutmeg.ontology import build_ontology_kernel
from nutmeg.ontology.actions.capital_actions import CommitCapitalPlanRequest
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.workflow_actions import RecordAdjudicationRequest
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

HUMAN = {"actor_id": "operator:plan-backfill", "actor_role": ActorRole.JUDGE_OPERATOR}
DAY = "2026-09-19"
ISSUE = "26129"
VERSIONS = [
    ("SFC-B", None, 128, 256, 0.0038, "rejected", "三处 C2（旗面没盖住）"),
    ("SFC-C", "SFC-B", 128, 256, None, "rejected", "平局太少（受前一日票面影响）"),
    ("SFC-D", "SFC-C", 128, 256, None, "rejected", "全选 3 无必要（集中度）"),
    ("SFC-E", "SFC-D", 128, 256, 0.001271, "chosen", "综合裁定终版"),
    (
        "RJ9-final",
        None,
        384,
        768,
        0.161188,
        "chosen",
        "9/10/11/12 两双两单裁定；14/13 防平裁定",
    ),
]


def _slips(data_dir: Path) -> dict[str, dict]:
    slips = {}
    for line in (data_dir / "betslips.jsonl").read_text("utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            slips[row["slip_id"]] = row
    return slips


def _frontier_values(data_dir: Path) -> tuple[dict, float | None, float | None]:
    path = data_dir / "zucai" / f"{ISSUE}-frontier-renjiu.json"
    if not path.exists():
        return {}, 0.1609, None
    frontier = json.loads(path.read_text("utf-8"))
    refs = {"renjiu": frontier["frontier_hash"]}
    return refs, frontier.get("max_p"), frontier.get("strict_max_p")


def backfill(*, data_dir: Path) -> dict:
    data_dir = Path(data_dir)
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir.resolve()))
    kernel.initialize()
    now = datetime.now().astimezone()
    slips = _slips(data_dir)
    final_faces = {
        "SFC-E": dict(slips.get("26129-SFC", {}).get("faces") or {}),
        "RJ9-final": dict(slips.get("26129-RJ9", {}).get("faces") or {}),
    }
    existing = {
        event["payload"]["version"]
        for event in read_events(data_dir / "jczq", DAY)
        if event.get("kind") == "candidate"
    }
    for version, parent, notes, stake, probability, verdict, reason in VERSIONS:
        if version in existing:
            continue
        has_recorded_faces = version in final_faces and bool(final_faces[version])
        append_candidate(
            data_dir / "jczq",
            DAY,
            obj_id=f"ticket:{ISSUE}",
            version=version,
            parent_version=parent,
            faces=final_faces.get(version, {}),
            notes=notes,
            stake_yuan=stake,
            p_all=probability,
            verdict=verdict,
            reason=(reason if has_recorded_faces else reason + "（faces 当时只在聊天里，未记录）"),
        )

    adjudication_ids = {}
    for subject_id, reason, alternative in (
        (
            "override-renjiu-1000-26129",
            "用户 2026-09-18 裁定：选9 成本控制在 ¥1,000 以内（覆盖 ¥400 基线与刹车）",
            {"cap_yuan": 1000, "channel": "renjiu", "issue": ISSUE},
        ),
        (
            "standing-renjiu-1200",
            "用户 2026-09-19 常设行权：任九帽 <= ¥1,200（spec Z5）",
            {"cap_yuan": 1200, "channel": "renjiu", "standing": True},
        ),
    ):
        outcome = kernel.workflow.record_adjudication(
            RecordAdjudicationRequest(
                subject_type="capital_cap",
                subject_id=subject_id,
                decision="override",
                reason=reason,
                evidence_rejected=[],
                alternative=alternative,
                supersedes_adjudication_id=None,
                idempotency_key=f"adj:{subject_id}",
                requested_at=now,
                **HUMAN,
            )
        )
        if outcome.status is not ActionStatus.COMMITTED:
            raise RuntimeError(f"adjudication {subject_id} rejected: {outcome.error_detail}")
        adjudication_ids[subject_id] = outcome.result_refs[0].object_id

    jczq_used = sum(
        int(slip.get("stake_yuan") or 0)
        for slip in slips.values()
        if slip.get("channel") == "jczq"
        and (
            str(slip.get("issue") or "") == ISSUE
            or str(slip.get("slip_id") or "").startswith(f"{ISSUE}-")
        )
    )
    chosen = [
        {
            "channel": "renjiu",
            "candidate_node": "RJ9-final",
            "legs_file_hash": "backfill",
            "notes": 384,
            "stake_yuan": 768,
            "p_all": 0.161188,
            "slip_id": "26129-RJ9",
        },
        {
            "channel": "shengfucai",
            "candidate_node": "SFC-E",
            "legs_file_hash": "backfill",
            "notes": 128,
            "stake_yuan": 256,
            "p_all": 0.001271,
            "slip_id": "26129-SFC",
        },
    ]
    frontier_refs, max_p_matrix, max_p_strict = _frontier_values(data_dir)
    with OntologyUnitOfWork(kernel.engine) as uow:
        existing_plan = uow.capital.latest_plan(ISSUE)
    override_ref = adjudication_ids["override-renjiu-1000-26129"]
    if existing_plan is None or existing_plan.adjudication_ref != override_ref:
        outcome = kernel.capital_actions.commit_capital_plan(
            CommitCapitalPlanRequest(
                issue=ISSUE,
                day=DAY,
                cap_source="override",
                adjudication_ref=override_ref,
                caps={"renjiu": 1000, "shengfucai": 500, "total": 1500},
                jczq_used_today=jczq_used,
                frontier_refs=frontier_refs,
                max_p_matrix=max_p_matrix,
                max_p_strict=max_p_strict,
                chosen_p=0.161188,
                chosen=chosen,
                verdict_refs=list(adjudication_ids.values()),
                supersedes=existing_plan.plan_id if existing_plan else None,
                idempotency_key=(
                    f"zcp:{ISSUE}:backfill:adjudication-ref-v2"
                    if existing_plan
                    else f"zcp:{ISSUE}:backfill"
                ),
                requested_at=now,
                **HUMAN,
            )
        )
        if outcome.status is not ActionStatus.COMMITTED:
            raise RuntimeError(f"capital plan rejected: {outcome.error_detail}")
    with OntologyUnitOfWork(kernel.engine) as uow:
        plan = uow.capital.latest_plan(ISSUE)
        f4_instance = uow.rsi.duty_instance("F4:capital-plan", DAY)
        f4_observation = uow.rsi.observation(f"F4:{DAY}")
    if f4_instance is not None and f4_observation is None:
        after_capital_plan(
            exp="F4",
            issue=ISSUE,
            day=DAY,
            plan_id=plan.plan_id,
            data_dir=data_dir,
            captured_at=datetime.fromisoformat("2026-09-18T20:00:00+08:00"),
        )
    return {
        "plan": {
            "plan_id": plan.plan_id,
            "cap_source": plan.cap_source,
            "caps": plan.caps,
            "chosen": plan.chosen,
            "gate_cost_pp": plan.gate_cost_pp,
        },
        "adjudications": adjudication_ids,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path(".nutmeg-data"))
    args = parser.parse_args()
    print(json.dumps(backfill(data_dir=args.data_dir), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
