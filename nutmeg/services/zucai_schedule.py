from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from nutmeg.domain.zucai import ZucaiArtifacts, ZucaiDispatch
from nutmeg.domain.zucai_schedule import (
    ZucaiIssueRegistryEntry,
    ZucaiScheduledRunRecord,
    ZucaiScheduledRunResult,
    ZucaiScheduleSlot,
)
from nutmeg.services.zucai import ZucaiValidationError, ZucaiWorkflowService


class ZucaiScheduleValidationError(ValueError):
    pass


SCHEDULE_SLOTS: dict[str, ZucaiScheduleSlot] = {
    "afternoon": ZucaiScheduleSlot(
        name="afternoon", label="16:00首版分析", scheduled_time="16:00"
    ),
    "revision": ZucaiScheduleSlot(
        name="revision", label="18:30修正确认", scheduled_time="18:30"
    ),
}
COMPLETED_STATUSES = {"generated", "dry_run", "sent"}


class ZucaiScheduledDeliveryService:
    def __init__(self, *, workflow_service: ZucaiWorkflowService) -> None:
        self._workflow_service = workflow_service

    def run(
        self,
        *,
        run_date: str | None = None,
        slot: str,
        registry_file: Path | str,
        output_dir: Path | str,
        run_record_file: Path | str,
        dispatch_telegram: bool = False,
        dry_run: bool = True,
        force: bool = False,
    ) -> ZucaiScheduledRunResult:
        slot_def = self._slot(slot)
        resolved_run_date = _normalize_run_date(run_date)
        generated_at = _now_iso()
        registry_path = Path(registry_file)
        warnings: list[str] = []
        entries = self.load_registry(registry_path, warnings=warnings)
        active_entry = self.find_active_issue(entries, resolved_run_date, registry_path, warnings)
        if active_entry is None:
            return ZucaiScheduledRunResult(
                run_date=resolved_run_date,
                slot=slot_def.name,
                slot_label=slot_def.label,
                status="skipped_no_issue",
                generated_at=generated_at,
                skipped_reason="no active traditional Zucai issue for run date",
                warnings=warnings,
            )

        record_path = Path(run_record_file)
        existing_records = self._load_records(record_path)
        if not force and self._has_completed_record(
            existing_records,
            run_date=resolved_run_date,
            slot=slot_def.name,
            issue_id=active_entry.issue_id,
        ):
            return ZucaiScheduledRunResult(
                run_date=resolved_run_date,
                slot=slot_def.name,
                slot_label=slot_def.label,
                issue_id=active_entry.issue_id,
                status="skipped_duplicate",
                generated_at=generated_at,
                skipped_reason="completed run already exists for date, slot, and issue",
                warnings=warnings,
            )

        issue_file = self._resolve_path(active_entry.issue_file, registry_path)
        odds_file = self._slot_path(
            active_entry.revision_odds_file if slot_def.name == "revision" else None,
            active_entry.odds_file,
            registry_path,
        )
        overrides_file = self._slot_path(
            active_entry.revision_overrides_file if slot_def.name == "revision" else None,
            active_entry.overrides_file,
            registry_path,
        )
        slot_output_dir = (
            Path(output_dir) / active_entry.issue_id / f"{resolved_run_date}-{slot_def.name}"
        )
        caption = (
            f"Nutmeg 足彩第{active_entry.issue_id}期14场报告 - {slot_def.label}"
            "（分析辅助，不保证命中）"
        )
        try:
            report = self._workflow_service.build_report(
                issue_id=active_entry.issue_id,
                issue_file=issue_file,
                odds_file=odds_file,
                overrides_file=overrides_file,
                output_dir=slot_output_dir,
                render_pdf=True,
                dispatch_telegram=dispatch_telegram,
                dry_run=dry_run,
                dispatch_caption=caption,
            )
            status = report.dispatch.status if dispatch_telegram else "generated"
            run_warnings = [*warnings, *report.warnings]
        except ZucaiValidationError as exc:
            status = "failed"
            report = None
            run_warnings = [*warnings, str(exc)]

        artifacts = report.artifacts if report is not None else ZucaiArtifacts()
        dispatch = report.dispatch if report is not None else ZucaiDispatch(status="failed")
        result = ZucaiScheduledRunResult(
            run_date=resolved_run_date,
            slot=slot_def.name,
            slot_label=slot_def.label,
            issue_id=active_entry.issue_id,
            status=status,
            generated_at=generated_at,
            artifacts=artifacts,
            dispatch=dispatch,
            warnings=run_warnings,
            report=report,
        )
        if status != "failed":
            self._append_record(record_path, self._record_from_result(result))
        return result

    def load_registry(
        self, registry_file: Path, *, warnings: list[str]
    ) -> list[ZucaiIssueRegistryEntry]:
        if not registry_file.exists():
            warnings.append(f"registry missing: {registry_file}")
            return []
        try:
            payload = json.loads(registry_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"registry malformed: {exc}")
            return []
        entries: list[ZucaiIssueRegistryEntry] = []
        for item in payload.get("entries") or []:
            if not isinstance(item, dict):
                warnings.append("registry entry is not an object")
                continue
            if item.get("enabled") is False:
                continue
            issue_id = str(item.get("issue_id") or "").strip()
            issue_file = str(item.get("issue_file") or "").strip()
            if not issue_id:
                warnings.append("registry entry missing issue_id")
                continue
            if not issue_file:
                warnings.append(f"registry entry {issue_id} missing issue_file")
                continue
            entries.append(
                ZucaiIssueRegistryEntry(
                    issue_id=issue_id,
                    enabled=bool(item.get("enabled", True)),
                    active_dates=[str(value) for value in item.get("active_dates") or []],
                    issue_file=issue_file,
                    odds_file=_optional_str(item.get("odds_file")),
                    overrides_file=_optional_str(item.get("overrides_file")),
                    revision_odds_file=_optional_str(item.get("revision_odds_file")),
                    revision_overrides_file=_optional_str(item.get("revision_overrides_file")),
                    notes=_optional_str(item.get("notes")),
                )
            )
        return entries

    def find_active_issue(
        self,
        entries: list[ZucaiIssueRegistryEntry],
        run_date: str,
        registry_file: Path,
        warnings: list[str],
    ) -> ZucaiIssueRegistryEntry | None:
        for entry in entries:
            if entry.active_dates:
                if run_date in entry.active_dates:
                    return entry
                continue
            issue_path = self._resolve_path(entry.issue_file, registry_file)
            try:
                payload = json.loads(issue_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                warnings.append(f"unable to inspect issue {entry.issue_id}: {exc}")
                continue
            inferred_dates = {
                str(payload.get("sale_stop") or "")[:10],
                str(payload.get("draw_date") or "")[:10],
            }
            if run_date in inferred_dates:
                return entry
        return None

    def _slot(self, slot: str) -> ZucaiScheduleSlot:
        try:
            return SCHEDULE_SLOTS[slot]
        except KeyError as exc:
            choices = ", ".join(sorted(SCHEDULE_SLOTS))
            raise ZucaiScheduleValidationError(
                f"Unsupported Zucai schedule slot '{slot}'. Expected one of: {choices}."
            ) from exc

    def _resolve_path(self, raw: str, registry_file: Path) -> Path:
        path = Path(raw)
        if path.is_absolute():
            return path
        registry_relative = registry_file.parent / path
        if registry_relative.exists():
            return registry_relative
        return Path.cwd() / path

    def _slot_path(
        self, slot_raw: str | None, base_raw: str | None, registry_file: Path
    ) -> Path | None:
        raw = slot_raw or base_raw
        if raw is None:
            return None
        return self._resolve_path(raw, registry_file)

    def _load_records(self, run_record_file: Path) -> list[dict[str, Any]]:
        if not run_record_file.exists():
            return []
        try:
            payload = json.loads(run_record_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        records = payload.get("records") or []
        return [record for record in records if isinstance(record, dict)]

    def _has_completed_record(
        self,
        records: list[dict[str, Any]],
        *,
        run_date: str,
        slot: str,
        issue_id: str,
    ) -> bool:
        for record in records:
            if (
                record.get("run_date") == run_date
                and record.get("slot") == slot
                and record.get("issue_id") == issue_id
                and record.get("status") in COMPLETED_STATUSES
            ):
                return True
        return False

    def _append_record(self, run_record_file: Path, record: ZucaiScheduledRunRecord) -> None:
        records = self._load_records(run_record_file)
        records.append(record.to_dict())
        run_record_file.parent.mkdir(parents=True, exist_ok=True)
        run_record_file.write_text(
            json.dumps({"records": records}, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def _record_from_result(self, result: ZucaiScheduledRunResult) -> ZucaiScheduledRunRecord:
        return ZucaiScheduledRunRecord(
            run_date=result.run_date,
            slot=result.slot,
            issue_id=result.issue_id or "",
            status=result.status,
            generated_at=result.generated_at,
            report_json_path=result.artifacts.report_json_path,
            markdown_path=result.artifacts.markdown_path,
            pdf_path=result.artifacts.pdf_path,
            dispatch_status=result.dispatch.status,
            warnings=result.warnings,
        )


def _normalize_run_date(raw: str | None) -> str:
    if raw is None or raw == "today":
        return date.today().isoformat()
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise ZucaiScheduleValidationError("run date must be YYYY-MM-DD or 'today'") from exc


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
