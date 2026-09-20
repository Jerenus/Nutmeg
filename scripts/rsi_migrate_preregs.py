"""五份旧 prereg 归一化摄入内核 + 回填已有观察。只增不改；可重跑（幂等键按 exp_id / day）。

- registered_at 取原登记日（写在 experiments/registry/*.json 里，不是摄入日）；
- F2 ledger 里 26126/27/28 → 三条 observation；ledger 还没收进（未 grade）但已在开球前落盘的
  {issue}-f2-observation.json（26129）也算一条，否则真履行过的义务会被记成 gap；
- t7-dispersion 里 26129 → 一条 F1c observation；
- F1c 在 26125–26128 真缺 → 由 schedule + 无 fulfill 自然投影成 gap（不造数据）。

时刻纪律：issue.json 的 kickoff_bj 是北京时间（"2026-09-14 18:00" 这种无秒、空格分隔的写法也有），
一律归一成带 +08:00 的完整 ISO 串——repository.gaps() 是按字符串比 due_at <= now 的。
t7-dispersion 不记采样时刻，F1c 的 captured_at 用「最早开球前一个 19:30」作近似（26129 开球
00:30，采集实际落在前一晚 19:30，见 prereg 的 2026-09-18T19:30 修正案）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.decision.rsi_prereg import load_registry_doc
from nutmeg.ontology import build_ontology_kernel
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.rsi_actions import (
    FulfillDutyRequest,
    RegisterExperimentRequest,
    ScheduleDutiesRequest,
)
from nutmeg.ontology.repository.rsi import DutyRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

BJ = timezone(timedelta(hours=8))
HUMAN = dict(
    actor_id="operator:rsi-migrate",
    actor_role=ActorRole.JUDGE_OPERATOR,
    acted_by="unattributed",
)
SYSTEM = dict(actor_id="system:rsi-migrate", actor_role=ActorRole.DETERMINISTIC_SYSTEM)
BACKFILL_ISSUES = ("26125", "26126", "26127", "26128", "26129")
F1C_WINDOW_FROM = "26129"


def _bj(raw: str) -> datetime:
    """北京时间字串 → aware datetime（无 tz 视为 +08:00）。"""
    dt = datetime.fromisoformat(raw)
    return dt.replace(tzinfo=BJ) if dt.tzinfo is None else dt.astimezone(BJ)


def _day_of(issue: str, zucai_dir: Path) -> tuple[str, str] | None:
    """(开球日 YYYY-MM-DD, 最早开球 ISO+08:00)；没有 issue.json 或没有开球时间 → None。"""
    p = zucai_dir / f"{issue}-issue.json"
    if not p.exists():
        return None
    matches = json.loads(p.read_text("utf-8"))["matches"]
    kos = sorted(_bj(str(m["kickoff_bj"])) for m in matches if m.get("kickoff_bj"))
    if not kos:
        return None
    ko = kos[0]
    return ko.date().isoformat(), ko.isoformat(timespec="seconds")


def _approx_capture_before(ko_iso: str) -> datetime:
    """最早开球之前最近的一个 19:30（北京时间）。"""
    ko = _bj(ko_iso)
    cand = ko.replace(hour=19, minute=30, second=0, microsecond=0)
    if cand >= ko:
        cand -= timedelta(days=1)
    return cand


def ensure_duties(kernel, exp_id: str, doc: dict) -> None:
    """Backfill newly declared non-frozen duties for an already registered experiment."""
    with OntologyUnitOfWork(kernel.engine) as uow:
        existing = {duty.duty_id for duty in uow.rsi.duties(exp_id)}
        for duty in doc.get("duties") or []:
            duty_id = f"{exp_id}:{duty['name']}"
            row = DutyRow(
                duty_id=duty_id,
                exp_id=exp_id,
                recurrence="per_day",
                scope=duty.get("scope", "day"),
                deadline_rule=duty["deadline_rule"],
                instrument=list(duty["instrument"]),
                artifact_glob=duty["artifact_glob"],
                description=duty.get("description", ""),
                status=duty.get("status", "active"),
            )
            if duty_id in existing:
                uow.rsi.update_duty_definition(row)
            else:
                uow.rsi.insert_duty(row)


def migrate(*, data_dir: Path, registry_dir: Path, f2_ledger: Path, dispersion_file: Path,
            now: str) -> dict:
    kernel = build_ontology_kernel(AppSettings(data_dir=Path(data_dir).resolve()))
    kernel.initialize()
    zucai_dir = Path(data_dir) / "zucai"
    ts = datetime.fromisoformat(now)
    report: dict = {"registered": []}

    for p in sorted(registry_dir.glob("*.json")):
        if p.name.startswith("_draft_"):
            continue
        doc = load_registry_doc(p)
        with OntologyUnitOfWork(kernel.engine) as uow:
            already = uow.rsi.experiment(doc["exp_id"]) is not None
        if not already:
            kernel.rsi_actions.register_experiment(RegisterExperimentRequest(
                doc=doc, idempotency_key=f"rsi-migrate-reg:{doc['exp_id']}",
                requested_at=ts, **HUMAN))
        ensure_duties(kernel, doc["exp_id"], doc)
        report["registered"].append(doc["exp_id"])

    with OntologyUnitOfWork(kernel.engine) as uow:
        duty_material = "\n".join(duty.duty_id for duty in uow.rsi.all_duties())
    duty_set_hash = hashlib.sha256(duty_material.encode()).hexdigest()[:12]

    # 为 26125–26129 排义务（有 issue.json 的期才排：拿不到开球就不造数据）
    scheduled: list[str] = []
    for issue in BACKFILL_ISSUES:
        dk = _day_of(issue, zucai_dir)
        if dk is None:
            continue
        day, ko = dk
        kernel.rsi_actions.schedule_duties(ScheduleDutiesRequest(
            day=day, earliest_kickoff=ko, issue=issue,
            idempotency_key=f"rsi-migrate-sched:{day}:{duty_set_hash}",
            requested_at=ts, **SYSTEM))
        scheduled.append(f"{issue}@{day}")
    report["scheduled"] = scheduled

    # F2：ledger 里的前瞻期 → observation
    ledger = json.loads(Path(f2_ledger).read_text("utf-8"))
    f2_obs = 0
    for issue, entry in ledger.get("issues", {}).items():
        dk = _day_of(issue, zucai_dir)
        if dk is None or not entry.get("prospective", True):
            continue
        day, ko = dk
        n = len(entry["rows"])
        kernel.rsi_actions.fulfill_duty(FulfillDutyRequest(
            exp_id="F2", duty_name="f2-observation", day=day, artifact_path=str(f2_ledger),
            artifact_bytes=json.dumps(entry, ensure_ascii=False).encode(), n_rows=n,
            population_stratum="zucai", judgment_tier_hist={"price_only": n},
            captured_at=_bj(entry["captured_at"]), earliest_kickoff=ko,
            idempotency_key=f"rsi-migrate-ful:F2:{day}", requested_at=ts, **SYSTEM))
        f2_obs += 1

    # F2：已落盘、尚未 grade 进 ledger 的前瞻观察单 → observation（同 obs_id 幂等）
    for issue in BACKFILL_ISSUES:
        if issue in ledger.get("issues", {}):
            continue
        obs_path = zucai_dir / f"{issue}-f2-observation.json"
        dk = _day_of(issue, zucai_dir)
        if dk is None or not obs_path.exists():
            continue
        obs = json.loads(obs_path.read_text("utf-8"))
        if not obs.get("prospective", False) or not obs.get("captured_at"):
            continue
        day, ko = dk
        n = len(obs.get("observations") or {})
        kernel.rsi_actions.fulfill_duty(FulfillDutyRequest(
            exp_id="F2", duty_name="f2-observation", day=day, artifact_path=str(obs_path),
            artifact_bytes=obs_path.read_bytes(), n_rows=n,
            population_stratum="zucai", judgment_tier_hist={"price_only": n},
            captured_at=_bj(obs["captured_at"]), earliest_kickoff=ko,
            idempotency_key=f"rsi-migrate-ful:F2:{day}", requested_at=ts, **SYSTEM))
        f2_obs += 1

    # F1c：t7-dispersion 里落在窗口内的期 → observation
    disp = json.loads(Path(dispersion_file).read_text("utf-8"))
    f1c_obs = 0
    for issue, cells in disp.items():
        if issue < F1C_WINDOW_FROM:
            continue                        # 26128 及以前不在 F1c 窗口（2026-09-18 修正案）
        dk = _day_of(issue, zucai_dir)
        if dk is None:
            continue
        day, ko = dk
        kernel.rsi_actions.fulfill_duty(FulfillDutyRequest(
            exp_id="F1c", duty_name="dispersion-observation", day=day,
            artifact_path=str(dispersion_file),
            artifact_bytes=json.dumps(cells, ensure_ascii=False).encode(), n_rows=len(cells),
            population_stratum="zucai", judgment_tier_hist={"price_only": len(cells)},
            captured_at=_approx_capture_before(ko), earliest_kickoff=ko,
            idempotency_key=f"rsi-migrate-ful:F1c:{day}", requested_at=ts, **SYSTEM))
        f1c_obs += 1

    with OntologyUnitOfWork(kernel.engine) as uow:
        report["F2"] = {"observations": f2_obs, "gaps": uow.rsi.gaps("F2", now=now)}
        report["F1c"] = {"observations": f1c_obs, "gaps": uow.rsi.gaps("F1c", now=now)}
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", type=Path, default=Path(".nutmeg-data"))
    ap.add_argument("--registry-dir", type=Path, default=Path("experiments/registry"))
    ap.add_argument("--f2-ledger", type=Path,
                    default=Path("experiments/prereg-26126-F2-ledger.json"))
    ap.add_argument("--dispersion-file", type=Path,
                    default=Path(".nutmeg-data/zucai/t7-dispersion.json"))
    a = ap.parse_args()
    rep = migrate(data_dir=a.data_dir, registry_dir=a.registry_dir, f2_ledger=a.f2_ledger,
                  dispersion_file=a.dispersion_file,
                  now=datetime.now(BJ).isoformat(timespec="seconds"))
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
