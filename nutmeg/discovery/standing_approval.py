"""常设批准（Jun 2026-09-28，至 2026-10-31）：一次签字覆盖一段日期的夜间 Dream 录制。

设计：docs/superpowers/specs/2026-09-28-dream-nightly-recording-design.md §3.3。
⛔程序只读批准文件；校验通过后派生的单次批准只在内存里交给现有 `_validate_recording`，
每个世界都带一条 `kind="approval"` 引用，回溯到签字文件与它当时的字节。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

BJ = timezone(timedelta(hours=8))
POLICY_REVISION_ID = "structural-baseline-v1"
DEFAULT_STANDING_PATH = (
    Path(__file__).resolve().parents[2]
    / "experiments/discovery/approvals/standing-dream-nightly-2026-10.json"
)
_REQUIRED = (
    "approval_id",
    "approved_by",
    "approved_at",
    "valid_from",
    "valid_until",
    "scope_template",
)


class StandingApprovalError(ValueError):
    """这份批准不能用于这一次录制；`reason` 是写进夜间报告的机器可读原因。"""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason


@dataclass(frozen=True)
class StandingApproval:
    document: dict
    sha256: str

    @property
    def approval_id(self) -> str:
        return str(self.document["approval_id"])

    @property
    def approved_by(self) -> str:
        return str(self.document["approved_by"])

    @property
    def valid_until(self) -> datetime:
        return datetime.fromisoformat(str(self.document["valid_until"]))


def load_standing_approval(path: Path) -> StandingApproval:
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError as exc:
        raise StandingApprovalError("approval_missing", str(path)) from exc
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StandingApprovalError("approval_unreadable", str(exc)) from exc
    missing = [key for key in _REQUIRED if not document.get(key)]
    if missing or document.get("kind") != "standing":
        raise StandingApprovalError(
            "approval_unreadable", f"missing={missing} kind={document.get('kind')!r}"
        )
    return StandingApproval(document, hashlib.sha256(raw).hexdigest())


def authorize_nightly(
    standing: StandingApproval,
    *,
    business_date: str,
    cutoff: datetime,
    jczq_dir: Path,
    shadow_db: Path,
    baseline_owner: str | None,
    recorded_dates: set[str],
) -> dict:
    """逐条校验，通过则返回现有 `_validate_recording` 认的单次批准字典。"""
    doc = standing.document
    scope = doc["scope_template"]
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise StandingApprovalError("approval_unreadable", "cutoff must be timezone-aware")
    if doc.get("revoked_at"):
        raise StandingApprovalError("approval_revoked", str(doc["revoked_at"]))
    approved_at = datetime.fromisoformat(str(doc["approved_at"]))
    if cutoff < datetime.fromisoformat(str(doc["valid_from"])) or approved_at > cutoff:
        raise StandingApprovalError("approval_not_yet_valid", cutoff.isoformat())
    if cutoff > standing.valid_until:
        raise StandingApprovalError("approval_expired", str(doc["valid_until"]))
    local = cutoff.astimezone(BJ)
    start, end = (time.fromisoformat(value) for value in scope["cutoff_window_bjt"])
    if not start <= local.time().replace(second=0, microsecond=0) <= end:
        raise StandingApprovalError("outside_window", local.isoformat())
    if local.date().isoformat() != business_date:
        raise StandingApprovalError("outside_window", f"{business_date} != {local.date()}")
    if (
        scope.get("source_kind") != "day"
        or scope.get("policy_revision_id") != POLICY_REVISION_ID
        or Path(scope["jczq_dir"]).resolve() != Path(jczq_dir).resolve()
        or Path(scope["shadow_db"]).resolve() != Path(shadow_db).resolve()
    ):
        raise StandingApprovalError("scope_mismatch", json.dumps(scope, ensure_ascii=False))
    if baseline_owner != standing.approved_by:
        raise StandingApprovalError("owner_mismatch", f"baseline owner {baseline_owner!r}")
    if business_date in recorded_dates:
        raise StandingApprovalError("already_recorded", business_date)
    return {
        "approval_id": f"{standing.approval_id}:{business_date}",
        "approved_by": standing.approved_by,
        "approved_at": str(doc["approved_at"]),
        "standing_approval": {"id": standing.approval_id, "sha256": standing.sha256},
        "scope": {
            "source_db": str((Path(jczq_dir) / "daily" / business_date).resolve()),
            "shadow_db": str(Path(shadow_db).resolve()),
            "generation_request_id": f"day:{business_date}",
            "cutoff_at": cutoff.isoformat(),
            "policy_revision_id": POLICY_REVISION_ID,
        },
    }


def approval_references(approval: Mapping) -> tuple[dict, ...]:
    """派生批准 → 世界 manifest 里的一条 `approval` 引用；单次批准 → 空。"""
    standing = approval.get("standing_approval")
    if not standing:
        return ()
    return (
        {
            "kind": "approval",
            "id": str(standing["id"]),
            "source_revision": str(standing["sha256"]),
            "captured_at": str(approval["approved_at"]),
        },
    )


def days_left(standing: StandingApproval, now: datetime) -> int:
    return (standing.valid_until.astimezone(BJ).date() - now.astimezone(BJ).date()).days
