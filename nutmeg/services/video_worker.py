from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nutmeg.domain.video_worker import (
    DEFAULT_MPT_TERMS,
    MoneyPrinterTurboRequest,
    MoneyPrinterTurboTaskPacket,
    MoneyPrinterTurboTaskState,
    VideoWorkerPollResult,
    VideoWorkerSubmissionResult,
)
from nutmeg.services.content import SHORT_VIDEO_DISCLAIMER, ContentComplianceChecker
from nutmeg.services.moneyprinterturbo import MoneyPrinterTurboClient


class VideoWorkerValidationError(ValueError):
    pass


class VideoWorkerService:
    def __init__(self, *, client: MoneyPrinterTurboClient | None = None) -> None:
        self._client = client

    def build_packets_for_run(
        self,
        *,
        run_dir: Path | str,
        run_id: str | None = None,
        run_date: str | None = None,
    ) -> dict[str, Any]:
        root = Path(run_dir)
        if not root.exists():
            raise VideoWorkerValidationError(
                f"Run directory not found: {root}. Generate it with `nutmeg video-mpt-packet`."
            )
        matches_dir = root / "matches"
        if not matches_dir.exists():
            raise VideoWorkerValidationError(f"Run directory has no matches folder: {matches_dir}")

        resolved_run_id = run_id or root.name
        resolved_run_date = run_date or _run_date_from_path(root)
        manifest_tasks: list[dict[str, Any]] = []
        for match_dir in sorted(path for path in matches_dir.iterdir() if path.is_dir()):
            packet = self._build_match_packet(
                match_dir=match_dir,
                run_id=resolved_run_id,
                run_date=resolved_run_date,
            )
            mpt_dir = match_dir / "production-mpt"
            mpt_dir.mkdir(parents=True, exist_ok=True)
            task_path = mpt_dir / "mpt-task.json"
            request_path = mpt_dir / "request.json"
            quality_path = mpt_dir / "quality-report.json"
            _write_json(task_path, packet.to_dict())
            _write_json(request_path, packet.request.to_payload())
            _write_json(quality_path, _quality_report_for_packet(packet))
            manifest_tasks.append(
                {
                    "match_id": packet.match_id,
                    "status": packet.status,
                    "task_id": packet.task_id,
                    "task_path": str(task_path),
                    "request_path": str(request_path),
                    "quality_report_path": str(quality_path),
                }
            )

        manifest = {
            "run_id": resolved_run_id,
            "run_date": resolved_run_date,
            "worker": "moneyprinterturbo",
            "run_dir": str(root),
            "tasks": manifest_tasks,
        }
        manifest_path = root / "moneyprinterturbo-manifest.json"
        status_path = root / "moneyprinterturbo-status.json"
        _write_json(manifest_path, manifest)
        _write_json(status_path, {"run_id": resolved_run_id, "tasks": manifest_tasks})
        return {
            "manifest_path": str(manifest_path),
            "status_path": str(status_path),
            "tasks": len(manifest_tasks),
        }

    def submit_run(
        self,
        *,
        run_dir: Path | str,
        confirm: bool,
        match_id: str | None = None,
    ) -> VideoWorkerSubmissionResult:
        if not confirm:
            raise VideoWorkerValidationError(
                "MoneyPrinterTurbo video generation requires explicit --confirm."
            )
        client = self._require_client()
        root = Path(run_dir)
        manifest = _load_manifest(root)
        submitted = skipped = blocked = failed = 0
        task_rows: list[dict[str, Any]] = []
        for row in manifest.get("tasks") or []:
            if match_id and row.get("match_id") != match_id:
                skipped += 1
                continue
            task_path = Path(str(row["task_path"]))
            packet = MoneyPrinterTurboTaskPacket.from_dict(_read_json(task_path))
            if packet.status.startswith("blocked"):
                blocked += 1
                task_rows.append(_task_status_row(packet))
                continue
            if packet.task_id:
                skipped += 1
                task_rows.append(_task_status_row(packet))
                continue
            try:
                response = client.create_video(packet.request.to_payload())
            except Exception as exc:
                error = str(exc)
                failed += 1
                failed_packet = _replace_packet(
                    packet,
                    status="failed_submit",
                    error=error,
                )
                _write_json(task_path, failed_packet.to_dict())
                _write_json(
                    task_path.parent / "submit-result.json",
                    {"status": "failed", "error": error},
                )
                task_rows.append(_task_status_row(failed_packet))
                continue
            submitted += 1
            task_id = str(response["task_id"])
            submitted_packet = _replace_packet(
                packet,
                status="submitted",
                task_id=task_id,
                error=None,
            )
            _write_json(task_path, submitted_packet.to_dict())
            _write_json(task_path.parent / "submit-result.json", response)
            task_rows.append(_task_status_row(submitted_packet))

        status_path = root / "moneyprinterturbo-status.json"
        _write_json(status_path, {"run_id": manifest.get("run_id"), "tasks": task_rows})
        return VideoWorkerSubmissionResult(
            manifest_path=str(root / "moneyprinterturbo-manifest.json"),
            submitted=submitted,
            skipped=skipped,
            blocked=blocked,
            failed=failed,
            tasks=task_rows,
        )

    def poll_run(
        self,
        *,
        run_dir: Path | str,
        download: bool = False,
        match_id: str | None = None,
    ) -> VideoWorkerPollResult:
        client = self._require_client()
        root = Path(run_dir)
        manifest = _load_manifest(root)
        succeeded = running = failed = blocked = downloaded = 0
        task_rows: list[dict[str, Any]] = []
        for row in manifest.get("tasks") or []:
            if match_id and row.get("match_id") != match_id:
                continue
            task_path = Path(str(row["task_path"]))
            packet = MoneyPrinterTurboTaskPacket.from_dict(_read_json(task_path))
            if packet.status.startswith("blocked"):
                blocked += 1
                task_rows.append(_task_status_row(packet))
                continue
            if not packet.task_id:
                running += 1
                task_rows.append(
                    {
                        "match_id": packet.match_id,
                        "status": "not_submitted",
                        "task_id": None,
                    }
                )
                continue
            try:
                payload = client.query_task(packet.task_id)
                state = MoneyPrinterTurboTaskState.from_worker_payload(
                    match_id=packet.match_id,
                    task_id=packet.task_id,
                    payload=payload,
                )
                if download and state.status == "succeeded":
                    local_paths = self._download_state_videos(
                        client=client,
                        state=state,
                        mpt_dir=task_path.parent,
                    )
                    state = MoneyPrinterTurboTaskState(
                        match_id=state.match_id,
                        task_id=state.task_id,
                        status=state.status,
                        worker_state=state.worker_state,
                        progress=state.progress,
                        video_urls=state.video_urls,
                        combined_video_urls=state.combined_video_urls,
                        local_video_paths=local_paths,
                        raw=state.raw,
                        error=state.error,
                    )
                    downloaded += len(local_paths)
            except Exception as exc:
                state = MoneyPrinterTurboTaskState(
                    match_id=packet.match_id,
                    task_id=packet.task_id,
                    status="failed",
                    worker_state=None,
                    progress=None,
                    video_urls=[],
                    combined_video_urls=[],
                    raw={},
                    error=str(exc),
                )
            if state.status == "succeeded":
                succeeded += 1
            elif state.status == "failed":
                failed += 1
            else:
                running += 1
            _write_json(task_path.parent / "status.json", state.to_dict())
            _write_json(
                task_path.parent / "quality-report.json",
                _quality_report_for_state(packet=packet, state=state),
            )
            task_rows.append(state.to_dict())

        status_path = root / "moneyprinterturbo-status.json"
        _write_json(status_path, {"run_id": manifest.get("run_id"), "tasks": task_rows})
        return VideoWorkerPollResult(
            status_path=str(status_path),
            succeeded=succeeded,
            running=running,
            failed=failed,
            blocked=blocked,
            downloaded=downloaded,
            tasks=task_rows,
        )

    def _download_state_videos(
        self,
        *,
        client: MoneyPrinterTurboClient,
        state: MoneyPrinterTurboTaskState,
        mpt_dir: Path,
    ) -> list[str]:
        videos_dir = mpt_dir / "videos"
        local_paths: list[str] = []
        for index, url in enumerate(state.video_urls, start=1):
            path = client.download_video(
                url,
                output_path=videos_dir / f"final-{index}.mp4",
            )
            local_paths.append(str(path))
        for index, url in enumerate(state.combined_video_urls, start=1):
            path = client.download_video(
                url,
                output_path=videos_dir / f"combined-{index}.mp4",
            )
            local_paths.append(str(path))
        return local_paths

    def _require_client(self) -> MoneyPrinterTurboClient:
        if self._client is None:
            self._client = MoneyPrinterTurboClient()
        return self._client

    def _build_match_packet(
        self,
        *,
        match_dir: Path,
        run_id: str,
        run_date: str,
    ) -> MoneyPrinterTurboTaskPacket:
        match_id = match_dir.name
        production_dir = match_dir / "production-v2"
        voiceover_path = production_dir / "voiceover-script.md"
        brief_path = production_dir / "content-brief.json"
        compliance_path = match_dir / "compliance.json"
        script = _read_text(voiceover_path)
        brief = _read_json(brief_path)
        compliance = _read_json(compliance_path) if compliance_path.exists() else {}
        title = _title_from_brief(match_id=match_id, brief=brief)
        request = MoneyPrinterTurboRequest(
            video_subject=title,
            video_script=script,
            video_terms=list(DEFAULT_MPT_TERMS),
        )
        status = "draft"
        error = None
        risk_level = str(compliance.get("risk_level") or "UNKNOWN").upper()
        if risk_level in {"HIGH", "BLOCKED"}:
            status = "blocked_by_compliance"
            error = f"Compliance risk {risk_level} is not eligible for worker submission."
        elif SHORT_VIDEO_DISCLAIMER not in script:
            status = "blocked_by_disclaimer"
            error = "Missing required short-video disclaimer."
        else:
            assessment = ContentComplianceChecker().assess(
                titles=[title],
                short_video_script=script,
                long_article=script + SHORT_VIDEO_DISCLAIMER,
            )
            if assessment.risk_level in {"HIGH", "BLOCKED"}:
                status = "blocked_by_compliance"
                error = (
                    f"Compliance risk {assessment.risk_level} is not eligible "
                    "for worker submission."
                )

        return MoneyPrinterTurboTaskPacket(
            run_id=run_id,
            run_date=run_date,
            match_id=match_id,
            match_no=str(brief.get("match_no") or brief.get("match_id") or match_id),
            title=title,
            script=script,
            request=request,
            source_paths={
                "voiceover_script_path": str(voiceover_path),
                "content_brief_path": str(brief_path),
                "compliance_path": str(compliance_path),
            },
            compliance=compliance,
            status=status,
            error=error,
        )


def _title_from_brief(*, match_id: str, brief: dict[str, Any]) -> str:
    hook = str(brief.get("selected_hook") or brief.get("main_contradiction") or "赛前关键变量")
    hook = hook.strip().replace("\n", " ")
    if len(hook) > 36:
        hook = hook[:36]
    return f"{match_id}：{hook}"


def _run_date_from_path(root: Path) -> str:
    parent = root.parent.name
    if len(parent) == 8 and parent.isdigit():
        return f"{parent[:4]}-{parent[4:6]}-{parent[6:]}"
    return "unknown"


def _quality_report_for_packet(packet: MoneyPrinterTurboTaskPacket) -> dict[str, Any]:
    gates = [
        {
            "gate": "script_compliance",
            "status": "pass" if packet.status == "draft" else "blocked",
            "detail": packet.error or "Script is eligible for MoneyPrinterTurbo submission.",
        },
        {
            "gate": "artifact_lineage",
            "status": "pass",
            "detail": f"run_id={packet.run_id}; match_id={packet.match_id}",
        },
    ]
    return {"status": "review" if packet.status == "draft" else "blocked", "gates": gates}


def _read_text(path: Path) -> str:
    if not path.exists():
        raise VideoWorkerValidationError(f"Required video worker input missing: {path}")
    return path.read_text(encoding="utf-8").strip()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise VideoWorkerValidationError(f"Required video worker input missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise VideoWorkerValidationError(f"Invalid JSON artifact: {path}") from exc
    if not isinstance(payload, dict):
        raise VideoWorkerValidationError(f"JSON artifact must be an object: {path}")
    return payload


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / "moneyprinterturbo-manifest.json"
    if not manifest_path.exists():
        raise VideoWorkerValidationError(
            "MoneyPrinterTurbo manifest not found: "
            f"{manifest_path}. Run `nutmeg video-mpt-packet` first."
        )
    manifest = _read_json(manifest_path)
    if not isinstance(manifest.get("tasks"), list):
        raise VideoWorkerValidationError("MoneyPrinterTurbo manifest missing tasks list.")
    return manifest


def _replace_packet(
    packet: MoneyPrinterTurboTaskPacket,
    *,
    status: str,
    task_id: str | None = None,
    error: str | None = None,
) -> MoneyPrinterTurboTaskPacket:
    return MoneyPrinterTurboTaskPacket(
        run_id=packet.run_id,
        run_date=packet.run_date,
        match_id=packet.match_id,
        match_no=packet.match_no,
        title=packet.title,
        script=packet.script,
        request=packet.request,
        source_paths=packet.source_paths,
        compliance=packet.compliance,
        status=status,
        task_id=task_id if task_id is not None else packet.task_id,
        error=error,
    )


def _task_status_row(packet: MoneyPrinterTurboTaskPacket) -> dict[str, Any]:
    row: dict[str, Any] = {
        "match_id": packet.match_id,
        "status": packet.status,
        "task_id": packet.task_id,
    }
    if packet.error:
        row["error"] = packet.error
    return row


def _quality_report_for_state(
    *,
    packet: MoneyPrinterTurboTaskPacket,
    state: MoneyPrinterTurboTaskState,
) -> dict[str, Any]:
    has_remote_video = bool(state.video_urls or state.combined_video_urls)
    has_local_video = bool(state.local_video_paths)
    gates = [
        {
            "gate": "worker_contract",
            "status": "pass" if state.task_id else "fail",
            "detail": f"task_id={state.task_id}",
        },
        {
            "gate": "download_integrity",
            "status": (
                "pass"
                if has_local_video
                else "review"
                if has_remote_video
                else "pending"
            ),
            "detail": (
                ";".join(state.local_video_paths)
                if has_local_video
                else "No downloaded video yet."
            ),
        },
        {
            "gate": "artifact_lineage",
            "status": "pass",
            "detail": (
                f"run_id={packet.run_id}; match_id={packet.match_id}; "
                f"task_id={state.task_id}"
            ),
        },
    ]
    if state.error:
        gates.append({"gate": "worker_error", "status": "fail", "detail": state.error})
    return {
        "status": "pass" if has_local_video and not state.error else "review",
        "gates": gates,
    }
