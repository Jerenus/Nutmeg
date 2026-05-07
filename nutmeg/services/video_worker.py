from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nutmeg.domain.video_worker import (
    DEFAULT_MPT_TERMS,
    MoneyPrinterTurboRequest,
    MoneyPrinterTurboTaskPacket,
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
