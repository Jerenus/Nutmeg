"""Explicit local operations for governed scoreboard authority."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import nutmeg.interfaces.cli as _cli
from nutmeg.analytics.calibrate_flow import CalibrateRequest
from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.models import ActorRole, ObjectRef, canonical_json
from nutmeg.ontology.actions.scoreboard_actions import (
    RecordScoreboardObservationRequest,
)
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.scoreboard.authority import (
    ScoreboardAuthorityError,
    ScoreboardAuthorityService,
)

scoreboard_app = _cli.typer.Typer(help="Governed scoreboard authority operations")
_cli.app.add_typer(scoreboard_app, name="scoreboard")

_DATA_DIR_OPTION = _cli.typer.Option(..., "--data-dir")
_LEGACY_FILE_OPTION = _cli.typer.Option(..., "--legacy-file")
_CLASSIFICATION_FILE_OPTION = _cli.typer.Option(..., "--classification-file")
_PROJECTION_VERSION_OPTION = _cli.typer.Option(..., "--projection-version")
_SOURCE_HIGH_WATERMARK_OPTION = _cli.typer.Option(
    ..., "--source-high-watermark", min=0
)
_REQUESTED_AT_OPTION = _cli.typer.Option(..., "--requested-at")
_ACKNOWLEDGE_MANUAL_SOURCE_OPTION = _cli.typer.Option(
    False, "--acknowledge-manual-source"
)
_EXPECTED_AUTHORITY_VERSION_OPTION = _cli.typer.Option(
    ..., "--expected-authority-version", min=1
)
_SOP_FILES_OPTION = _cli.typer.Option(..., "--sop-file")
_APPROVE_OPTION = _cli.typer.Option(False, "--approve")
_DESTINATION_OPTION = _cli.typer.Option(..., "--destination")
_SETTLE_SCOREBOARD_FILE_OPTION = _cli.typer.Option(
    ..., "--scoreboard-file", help="权威 scoreboard.json（影子期唯一事实源）")
_SETTLE_METRIC_OPTION = _cli.typer.Option(
    [], "--metric", help="限定 group/metric（可重复）；省略=全部有改动的指标")
_SETTLE_DRY_RUN_OPTION = _cli.typer.Option(True, "--dry-run/--no-dry-run")


def _at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ScoreboardAuthorityError("timestamp must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ScoreboardAuthorityError("timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def _kernel(data_dir: Path):
    resolved = Path(data_dir).expanduser().resolve()
    kernel = _cli.build_ontology_kernel(AppSettings(data_dir=resolved))
    status = kernel.status()
    if not status.initialized or status.integrity_check != "ok" or status.pending_migrations:
        raise ScoreboardAuthorityError(
            "ontology must be initialized, healthy, and current"
        )
    return kernel, resolved


def _emit(payload: dict[str, object]) -> None:
    _cli.typer.echo(canonical_json(payload))


def _fail(error: Exception) -> None:
    _emit({"code": "scoreboard_operation_blocked", "message": str(error)})
    raise _cli.typer.Exit(code=1)


def _outcome(
    outcome, *, targets: dict[str, object] | None = None
) -> dict[str, object]:
    result: dict[str, object] = {
        "action_id": outcome.action_id,
        "action_type": outcome.action_type,
        "status": outcome.status.value,
        "result_refs": [ref.to_dict() for ref in outcome.result_refs],
        "error_code": outcome.error_code,
    }
    if targets is not None:
        result["targets"] = targets
    return result


@scoreboard_app.command("status")
def scoreboard_status(
    data_dir: Path = _DATA_DIR_OPTION,
) -> None:
    try:
        kernel, resolved = _kernel(data_dir)
        with OntologyUnitOfWork(kernel.engine) as uow:
            authority = uow.scoreboard.authority()
            review = uow.scoreboard.latest_shadow_review()
        _emit(
            {
                "authority": _cli.asdict(authority),
                "latest_shadow_review": _cli.asdict(review) if review else None,
                "targets": {
                    "data_dir": str(resolved),
                    "ontology_db": str(kernel.paths.database),
                    "analytics_db": str(kernel.paths.analytics),
                    "artifact_store": str(kernel.paths.artifacts),
                },
            }
        )
    except (ScoreboardAuthorityError, ValueError) as error:
        _fail(error)


@scoreboard_app.command("observe")
def scoreboard_observe(
    data_dir: Path = _DATA_DIR_OPTION,
    group_key: str = _cli.typer.Option(..., "--group-key"),
    metric_key: str = _cli.typer.Option(..., "--metric-key"),
    tally: str = _cli.typer.Option(..., "--tally"),
    detail: str = _cli.typer.Option(..., "--detail"),
    status: str = _cli.typer.Option(..., "--status"),
    evidence_type: str = _cli.typer.Option(..., "--evidence-type"),
    evidence_id: str = _cli.typer.Option(..., "--evidence-id"),
    effective_at: str = _cli.typer.Option(..., "--effective-at"),
    requested_at: str = _REQUESTED_AT_OPTION,
    numerator: float | None = _cli.typer.Option(None, "--numerator"),
    denominator: float | None = _cli.typer.Option(None, "--denominator"),
    value: float | None = _cli.typer.Option(None, "--value"),
    unit: str | None = _cli.typer.Option(None, "--unit"),
    supersedes: str | None = _cli.typer.Option(None, "--supersedes"),
    acknowledge_manual_source: bool = _ACKNOWLEDGE_MANUAL_SOURCE_OPTION,
) -> None:
    try:
        if not acknowledge_manual_source:
            raise ScoreboardAuthorityError(
                "observe requires --acknowledge-manual-source"
            )
        kernel, resolved = _kernel(data_dir)
        outcome = kernel.scoreboard_actions.record_observation(
            RecordScoreboardObservationRequest(
                group_key=group_key,
                metric_key=metric_key,
                tally=tally,
                detail=detail,
                status=status,
                numerator=numerator,
                denominator=denominator,
                value=value,
                unit=unit,
                evidence_refs=[ObjectRef(evidence_type, evidence_id)],
                effective_at=_at(effective_at),
                supersedes_observation_id=supersedes,
                actor_id="operator:scoreboard-observation",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key=(
                    f"scoreboard:observe:{group_key}:{metric_key}:"
                    f"{hashlib.sha256(detail.encode()).hexdigest()}"
                ),
                requested_at=_at(requested_at),
            )
        )
        _emit(_outcome(outcome, targets={"data_dir": str(resolved)}))
    except (ScoreboardAuthorityError, ValueError) as error:
        _fail(error)


@scoreboard_app.command("rebuild-projection")
def scoreboard_rebuild_projection(
    data_dir: Path = _DATA_DIR_OPTION,
    as_of: str = _cli.typer.Option(..., "--as-of"),
    built_at: str = _cli.typer.Option(..., "--built-at"),
) -> None:
    try:
        kernel, resolved = _kernel(data_dir)
        result = kernel.calibrate.build(
            CalibrateRequest(
                as_of=_at(as_of).isoformat(),
                built_at=_at(built_at).isoformat(),
            )
        )
        if result.status != "succeeded":
            raise ScoreboardAuthorityError(
                f"scoreboard projection rebuild failed: {result.run_id}"
            )
        _emit(
            {
                "status": result.status,
                "run_id": result.run_id,
                "projection_version": "sb-v1",
                "source_high_watermark": result.high_watermark,
                "counts": {
                    "scorecards": result.scorecard_count,
                    "factor_estimates": result.factor_estimate_count,
                    "lifecycle_proposals": result.lifecycle_proposal_count,
                    "regime_vectors": result.regime_vector_count,
                },
                "targets": {
                    "data_dir": str(resolved),
                    "ontology_db": str(kernel.paths.database),
                    "analytics_db": str(kernel.paths.analytics),
                },
            }
        )
    except (ScoreboardAuthorityError, ValueError) as error:
        _fail(error)


@scoreboard_app.command("shadow")
def scoreboard_shadow(
    data_dir: Path = _DATA_DIR_OPTION,
    legacy_file: Path = _LEGACY_FILE_OPTION,
    classification_file: Path = _CLASSIFICATION_FILE_OPTION,
    projection_version: str = _PROJECTION_VERSION_OPTION,
    source_high_watermark: int = _SOURCE_HIGH_WATERMARK_OPTION,
    requested_at: str = _REQUESTED_AT_OPTION,
    acknowledge_manual_source: bool = _ACKNOWLEDGE_MANUAL_SOURCE_OPTION,
) -> None:
    try:
        kernel, resolved = _kernel(data_dir)
        legacy_path = Path(legacy_file).expanduser().resolve()
        classification_path = Path(classification_file).expanduser().resolve()
        classification = json.loads(
            classification_path.read_text(encoding="utf-8")
        )
        if not isinstance(classification, list) or not all(
            isinstance(item, dict) for item in classification
        ):
            raise ScoreboardAuthorityError(
                "classification file must contain a JSON list"
            )
        outcome = ScoreboardAuthorityService(kernel).shadow(
            legacy_path=legacy_path,
            classification=classification,
            projection_version=projection_version,
            source_high_watermark=source_high_watermark,
            acknowledge_manual_source=acknowledge_manual_source,
            requested_at=_at(requested_at),
        )
        _emit(
            _outcome(
                outcome,
                targets={
                    "classification_file": str(classification_path),
                    "data_dir": str(resolved),
                    "legacy_file": str(legacy_path),
                },
            )
        )
    except (OSError, json.JSONDecodeError, ScoreboardAuthorityError, ValueError) as error:
        _fail(error)


@scoreboard_app.command("cutover")
def scoreboard_cutover(
    data_dir: Path = _DATA_DIR_OPTION,
    legacy_file: Path = _LEGACY_FILE_OPTION,
    review_id: str = _cli.typer.Option(..., "--review-id"),
    expected_authority_version: int = _EXPECTED_AUTHORITY_VERSION_OPTION,
    projection_version: str = _PROJECTION_VERSION_OPTION,
    source_high_watermark: int = _SOURCE_HIGH_WATERMARK_OPTION,
    sop_files: list[Path] = _SOP_FILES_OPTION,
    requested_at: str = _REQUESTED_AT_OPTION,
    approve: bool = _APPROVE_OPTION,
) -> None:
    try:
        kernel, resolved = _kernel(data_dir)
        legacy_path = Path(legacy_file).expanduser().resolve()
        resolved_sop_files = [Path(path).expanduser().resolve() for path in sop_files]
        with OntologyUnitOfWork(kernel.engine) as uow:
            review = uow.scoreboard.shadow_review(review_id)
        if review is None:
            raise ScoreboardAuthorityError(
                f"scoreboard shadow review {review_id} is absent"
            )
        if (
            review.projection_version != projection_version
            or review.source_high_watermark != source_high_watermark
        ):
            raise ScoreboardAuthorityError(
                "supplied projection identity does not match the shadow review"
            )
        outcome = ScoreboardAuthorityService(kernel).cutover(
            legacy_path=legacy_path,
            shadow_review_id=review_id,
            expected_authority_version=expected_authority_version,
            sop_paths=resolved_sop_files,
            approve=approve,
            requested_at=_at(requested_at),
        )
        _emit(
            _outcome(
                outcome,
                targets={
                    "data_dir": str(resolved),
                    "legacy_file": str(legacy_path),
                    "sop_files": [str(path) for path in resolved_sop_files],
                },
            )
        )
    except (OSError, ScoreboardAuthorityError, ValueError) as error:
        _fail(error)


@scoreboard_app.command("export")
def scoreboard_export(
    data_dir: Path = _DATA_DIR_OPTION,
    destination: Path = _DESTINATION_OPTION,
    expected_authority_version: int = _EXPECTED_AUTHORITY_VERSION_OPTION,
    requested_at: str = _REQUESTED_AT_OPTION,
) -> None:
    try:
        kernel, resolved = _kernel(data_dir)
        destination_path = Path(destination).expanduser().resolve()
        with OntologyUnitOfWork(kernel.engine) as uow:
            authority = uow.scoreboard.authority()
        if authority.version != expected_authority_version:
            raise ScoreboardAuthorityError(
                f"authority is at version {authority.version}, "
                f"expected {expected_authority_version}"
            )
        result = ScoreboardAuthorityService(kernel).export(
            destination_path, requested_at=_at(requested_at)
        )
        _emit(
            {
                "action_id": result.action_id,
                "path": str(result.path),
                "sha256": result.sha256,
                "status": "exported",
                "targets": {
                    "data_dir": str(resolved),
                    "destination": str(destination_path),
                },
            }
        )
    except (OSError, ScoreboardAuthorityError, ValueError) as error:
        _fail(error)


@scoreboard_app.command("verify-export")
def scoreboard_verify_export(
    data_dir: Path = _DATA_DIR_OPTION,
    destination: Path = _DESTINATION_OPTION,
) -> None:
    try:
        kernel, resolved = _kernel(data_dir)
        with OntologyUnitOfWork(kernel.engine) as uow:
            authority = uow.scoreboard.authority()
        path = Path(destination).expanduser().resolve()
        if not path.is_file() or authority.compatibility_export_sha256 is None:
            raise ScoreboardAuthorityError(
                "recorded compatibility export is unavailable"
            )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != authority.compatibility_export_sha256:
            raise ScoreboardAuthorityError("scoreboard_export_drift")
        _emit(
            {
                "path": str(path),
                "sha256": digest,
                "status": "verified",
                "targets": {
                    "data_dir": str(resolved),
                    "destination": str(path),
                },
            }
        )
    except (OSError, ScoreboardAuthorityError, ValueError) as error:
        _fail(error)


def _current_leaf(kernel, group_key: str, metric_key: str) -> str | None:
    """该指标当前的叶子观察 id（未被任何观察 supersede 的那一条）。"""
    from sqlalchemy import text as _text

    with OntologyUnitOfWork(kernel.engine) as uow:
        row = uow.connection.execute(_text("""
            SELECT o.scoreboard_observation_id FROM scoreboard_observations o
            WHERE o.group_key = :g AND o.metric_key = :m
              AND NOT EXISTS (SELECT 1 FROM scoreboard_observations x
                              WHERE x.supersedes_observation_id
                                    = o.scoreboard_observation_id)
            ORDER BY o.recorded_at DESC LIMIT 1
        """), {"g": group_key, "m": metric_key}).fetchone()
    return row[0] if row else None


@scoreboard_app.command("settle-issue")
def scoreboard_settle_issue(
    data_dir: Path = _DATA_DIR_OPTION,
    scoreboard_file: Path = _SETTLE_SCOREBOARD_FILE_OPTION,
    evidence_type: str = _cli.typer.Option(..., "--evidence-type"),
    evidence_id: str = _cli.typer.Option(..., "--evidence-id"),
    effective_at: str = _cli.typer.Option(..., "--effective-at"),
    requested_at: str = _REQUESTED_AT_OPTION,
    metric: list[str] = _SETTLE_METRIC_OPTION,
    dry_run: bool = _SETTLE_DRY_RUN_OPTION,
    acknowledge_manual_source: bool = _ACKNOWLEDGE_MANUAL_SOURCE_OPTION,
) -> None:
    """把 scoreboard.json 的本期改动**一次性**镜像成 observe（自动找 leaf + supersedes）。

    出生事故 2026-09-11：26121 复盘改了 12 个指标，手工镜像跑了三轮才成——第一轮
    12 条全被 "must supersede the current leaf" 挡下，第二轮补了 supersedes 又被幂等键
    挡下（失败的尝试占住了键）。**治理动作本身不能比它要治理的事还费劲**，否则影子期
    双轨就会退化成"只改 JSON 不镜像"，而那是 M5 明令禁止的无声双权威。
    """
    try:
        if not acknowledge_manual_source:
            raise ScoreboardAuthorityError(
                "settle-issue requires --acknowledge-manual-source")
        kernel, resolved = _kernel(data_dir)
        board = json.loads(Path(scoreboard_file).read_text("utf-8"))
        wanted = {tuple(m.split("/", 1)) for m in metric} if metric else None

        planned: list[dict[str, object]] = []
        for group_key, metrics in board.items():
            if not isinstance(metrics, dict):
                continue
            for metric_key, entry in metrics.items():
                if not isinstance(entry, dict) or "tally" not in entry:
                    continue
                if wanted is not None and (group_key, metric_key) not in wanted:
                    continue
                leaf = _current_leaf(kernel, group_key, metric_key)
                detail = str(entry.get("detail", ""))
                # 只镜像**最新一段** detail：整段重发会让每次复盘的观察越来越长,
                # 而观察的价值在于"这一期改了什么"。
                latest = detail.split(" ‖ ")[-1].strip()
                planned.append({
                    "group_key": group_key, "metric_key": metric_key,
                    "tally": str(entry.get("tally", "")), "detail": latest,
                    "status": str(entry.get("status", "")), "supersedes": leaf,
                })

        if dry_run:
            _emit({"mode": "dry_run", "planned": planned,
                   "targets": {"data_dir": str(resolved)}})
            return

        results = []
        for plan in planned:
            request = RecordScoreboardObservationRequest(
                group_key=str(plan["group_key"]), metric_key=str(plan["metric_key"]),
                tally=str(plan["tally"]), detail=str(plan["detail"]),
                status=str(plan["status"]),
                numerator=None, denominator=None, value=None, unit=None,
                evidence_refs=[ObjectRef(evidence_type, evidence_id)],
                effective_at=_at(effective_at),
                supersedes_observation_id=plan["supersedes"],
                actor_id="operator:scoreboard-observation",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key=(
                    f"scoreboard:settle:{evidence_id}:{plan['group_key']}:"
                    f"{plan['metric_key']}:"
                    f"{hashlib.sha256(str(plan['detail']).encode()).hexdigest()}"),
                requested_at=_at(requested_at),
            )
            outcome = kernel.scoreboard_actions.record_observation(request)
            results.append({"group_key": plan["group_key"],
                            "metric_key": plan["metric_key"],
                            "status": outcome.status.value,
                            "action_id": outcome.action_id})
        _emit({"mode": "committed", "mirrored": len(results), "results": results,
               "targets": {"data_dir": str(resolved)}})
    except (ScoreboardAuthorityError, ValueError) as error:
        _fail(error)


@scoreboard_app.command("cutover-readiness")
def scoreboard_cutover_readiness(
    data_dir: Path = _DATA_DIR_OPTION,
    scoreboard_file: Path = _SETTLE_SCOREBOARD_FILE_OPTION,
) -> None:
    """权威切换前的**只读**体检：还差哪些门、哪些指标还没有观察。

    ⚠️本命令**不切换任何东西**。M5 的权威切换是四道用户行权门（影子对账、SOP 文件、
    期望版本号、显式 --approve），不能由程序代劳；这里只把"现在离得多远"算清楚，
    免得影子期因为"不知道还差什么"无限期拖下去——26111 起跑到 26122 已经 12 期，
    `unexplained` 一直挂着 17 条没人消化。
    """
    from sqlalchemy import text as _text

    try:
        kernel, resolved = _kernel(data_dir)
        board = json.loads(Path(scoreboard_file).read_text("utf-8"))
        metrics = {(g, m) for g, rows in board.items() if isinstance(rows, dict)
                   for m, e in rows.items() if isinstance(e, dict) and "tally" in e}
        with OntologyUnitOfWork(kernel.engine) as uow:
            observed = {
                (row[0], row[1]) for row in uow.connection.execute(_text(
                    "SELECT DISTINCT group_key, metric_key FROM scoreboard_observations"
                )).fetchall()
            }
            authority = uow.scoreboard.authority()
            review = uow.scoreboard.latest_shadow_review()
        missing = sorted(metrics - observed)
        _emit({
            "authority_state": authority.state,
            "authority_version": authority.version,
            "metrics_in_json": len(metrics),
            "metrics_with_observation": len(metrics & observed),
            "metrics_never_observed": [f"{g}/{m}" for g, m in missing],
            "latest_review": None if review is None else {
                "review_id": review.scoreboard_shadow_review_id,
                "status": review.status,
                "matched": review.matched_count,
                "unexplained": review.unexplained_count,
                "manual": review.manual_count,
                "reviewed_at": review.reviewed_at,
            },
            "gates_remaining": [
                "①每个指标至少一条观察（当前缺 "
                f"{len(missing)} 个）",
                "②最近一次 shadow review 的 unexplained 归零或全部显式归类",
                "③SOP 文件与期望权威版本号由 Jun 给定",
                "④`scoreboard cutover --approve` 显式行权",
            ],
            "targets": {"data_dir": str(resolved)},
        })
    except (ScoreboardAuthorityError, ValueError) as error:
        _fail(error)
