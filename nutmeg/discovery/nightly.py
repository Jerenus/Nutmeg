"""夜间 Dream 录制（Jun 2026-09-28，常设批准至 2026-10-31）。

一晚一个世界：常设批准校验 → day 源（开球过滤 + 票面引用）→ 录制并封存 → 报告。
报告顺带用同一冻结快照算好次日对照料（赔率簿、决策规则最优、世界各档最优）。
⛔不写批准文件、不写生产目录、不跑锦标赛/晋级/部署。
设计：docs/superpowers/specs/2026-09-28-dream-nightly-recording-design.md §3.4。
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from nutmeg.discovery.contracts import load_pilot_contract
from nutmeg.discovery.day_inputs import (
    DayBoardTooSmall,
    day_tickets,
    read_structural_input_from_day,
    tickets_digest,
)
from nutmeg.discovery.dream_compare import candidate_tickets, decision_rule_best, offer_book
from nutmeg.discovery.online_adapter import best_candidates_by_band
from nutmeg.discovery.standing_approval import (
    BJ,
    POLICY_REVISION_ID,
    StandingApprovalError,
    approval_references,
    authorize_nightly,
    days_left,
    load_standing_approval,
)

PILOT_PATH = (
    Path(__file__).resolve().parents[2]
    / "experiments/discovery/structural-candidate-v1.contract.json"
)
RETRY_MARKERS = ("protected source changed",)
UNSEALED_MARKERS = ("sealing blocked", "remains unsealed")


@dataclass
class NightlyResult:
    status: str  # recorded | skipped | unsealed | dry_run | failed
    reason: str | None = None
    report_path: Path | None = None
    payload: dict = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        return 1 if self.status == "failed" else 0


def _read_only_engine(shadow_db: Path):
    from sqlalchemy import create_engine

    uri = f"file:{quote(str(shadow_db), safe='/')}?mode=ro"
    return create_engine("sqlite+pysqlite://", creator=lambda: sqlite3.connect(uri, uri=True))


def baseline_owner(shadow_db: Path) -> str | None:
    from nutmeg.ontology.discovery.read_service import DiscoveryReadService

    engine = _read_only_engine(shadow_db)
    try:
        lineage = DiscoveryReadService(engine).policy_lineage(POLICY_REVISION_ID)
        return lineage["policy"]["created_by"]
    except KeyError:
        return None
    finally:
        engine.dispose()


def shard_summary(shadow_db: Path, world_id: str) -> list[dict]:
    from nutmeg.ontology.discovery.read_service import DiscoveryReadService

    engine = _read_only_engine(shadow_db)
    try:
        detail = DiscoveryReadService(engine).world_detail(world_id)
    finally:
        engine.dispose()
    rows = []
    for node in detail.get("nodes", []):
        manifest = node.get("artifact_manifest") or {}
        if not manifest.get("template_ids") or ":attempt:" not in str(node.get("node_id")):
            continue
        rows.append(
            {
                "template": manifest["template_ids"][0],
                "status": node.get("execution_status"),
                "diagnostics": list(node.get("diagnostic_codes") or []),
                "wall_ms": (node.get("resource_cost") or {}).get("wall_ms"),
                "band_candidate_counts": manifest.get("band_candidate_counts"),
            }
        )
    return rows


def _recorded_dates(reports_dir: Path, standing_id: str) -> set[str]:
    dates: set[str] = set()
    for path in reports_dir.glob("*.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        standing = doc.get("standing_approval") or {}
        if doc.get("status") == "recorded" and standing.get("id") == standing_id:
            dates.add(str(doc["day"]))
    return dates


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def _band_best(snapshot, pilot) -> dict:
    return {
        band: {
            "tickets": candidate_tickets(candidate),
            "p_belief": candidate.objective_probability_decimal,
            "combined_odds": candidate.combined_decimal_odds,
            "stake_minor": candidate.stake_minor,
        }
        for band, candidate in best_candidates_by_band(snapshot, pilot=pilot).items()
    }


def run_nightly(
    *,
    day: str,
    jczq_dir: Path,
    shadow_db: Path,
    standing_path: Path,
    reports_dir: Path,
    tickets_dir: Path,
    now: Callable[[], datetime],
    dry_run: bool = False,
    record_fn: Callable | None = None,
    owner_fn: Callable[[Path], str | None] = baseline_owner,
    shard_fn: Callable[[Path, str], list[dict]] = shard_summary,
    engine_fn: Callable | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> NightlyResult:
    if record_fn is None:
        from nutmeg.discovery.online_recorder import record_shadow_world as record_fn
    if engine_fn is None:
        from nutmeg.ontology.repository.connection import build_ontology_engine as engine_fn
    source = Path(jczq_dir) / "daily" / day
    base: dict = {"day": day, "shadow_db": str(Path(shadow_db).resolve())}
    try:
        standing = load_standing_approval(standing_path)
    except StandingApprovalError as exc:
        return NightlyResult("skipped", exc.reason, payload={**base, "detail": str(exc)})
    base["standing_approval"] = {
        "id": standing.approval_id,
        "sha256": standing.sha256,
        "days_left": days_left(standing, now()),
    }
    if not Path(shadow_db).is_file():
        return NightlyResult("failed", "shadow_store_missing", payload=base)
    owner = owner_fn(Path(shadow_db))
    pilot = load_pilot_contract(PILOT_PATH)

    def prepare():
        cutoff = now().astimezone(BJ).replace(microsecond=0)
        approval = authorize_nightly(
            standing,
            business_date=day,
            cutoff=cutoff,
            jczq_dir=Path(jczq_dir),
            shadow_db=Path(shadow_db),
            baseline_owner=owner,
            recorded_dates=_recorded_dates(Path(reports_dir), standing.approval_id),
        )
        snapshot = read_structural_input_from_day(
            jczq_dir,
            day,
            cutoff_at=cutoff.isoformat(),
            extra_references=approval_references(approval),
        )
        return approval, snapshot

    def skipped(exc: Exception) -> NightlyResult:
        reason = exc.reason if isinstance(exc, StandingApprovalError) else "board_too_small"
        return NightlyResult("skipped", reason, payload={**base, "detail": str(exc)})

    try:
        approval, snapshot = prepare()
    except (StandingApprovalError, DayBoardTooSmall) as exc:
        return skipped(exc)

    offers = [offer.official_match_no for offer in snapshot.candidate_input.offers]
    excluded = [
        {"code": ref.id, "kickoff": ref.source_revision.removeprefix("kickoff:")}
        for ref in snapshot.references
        if ref.kind == "excluded_started"
    ]
    if dry_run:
        return NightlyResult(
            "dry_run",
            payload={
                **base,
                "cutoff_at": snapshot.cutoff_at,
                "offers": offers,
                "excluded": excluded,
                "templates": list(snapshot.template_ids),
            },
        )

    recorded = None
    for attempt in range(2):
        engine = engine_fn(Path(shadow_db))
        try:
            recorded = record_fn(
                snapshot,
                engine=engine,
                shadow_database=Path(shadow_db),
                source_database=source,
                policy_revision_id=POLICY_REVISION_ID,
                generation_request_id=f"day:{day}",
                requested_at=datetime.now(UTC),
                approval=approval,
            )
            break
        except ValueError as exc:
            message = str(exc)
            if attempt == 0 and any(marker in message for marker in RETRY_MARKERS):
                sleep(60)
                try:
                    approval, snapshot = prepare()
                except (StandingApprovalError, DayBoardTooSmall) as again:
                    return skipped(again)
                continue
            unsealed = any(m in message for m in UNSEALED_MARKERS + RETRY_MARKERS)
            status = "unsealed" if unsealed else "failed"
            payload = {
                **base, "status": status, "detail": message, "cutoff_at": snapshot.cutoff_at,
            }
            path = _write_json(Path(reports_dir) / f"{day}.json", payload)
            return NightlyResult(status, "recording_error", path, payload)
        finally:
            if engine is not None:
                engine.dispose()

    tickets = day_tickets(source)
    digest = tickets_digest(tickets)
    ticket_path = _write_json(Path(tickets_dir) / f"{day}-{digest[:16]}.json", tickets)
    book = offer_book(snapshot)
    payload = {
        **base,
        "status": "recorded",
        "cutoff_at": snapshot.cutoff_at,
        "world_id": recorded.world_id,
        "sealed_manifest_hash": recorded.sealed_manifest_hash,
        "manifest_hash": snapshot.manifest_hash,
        "offers": offers,
        "excluded": excluded,
        "shards": shard_fn(Path(shadow_db), recorded.world_id),
        "ticket_digest": digest,
        "ticket_snapshot_path": str(ticket_path),
        "ticket_snapshot": tickets,
        "offer_book": book,
        "decision_rule_best": decision_rule_best(book),
        "band_best": _band_best(snapshot, pilot),
    }
    path = _write_json(Path(reports_dir) / f"{day}.json", payload)
    return NightlyResult("recorded", None, path, payload)
