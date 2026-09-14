from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from typing import Any

import httpx

from nutmeg.domain.zucai_odds_source import ZucaiOddsSyncResult
from nutmeg.services.zucai_source import _load_registry_entries


class ZucaiOddsSourceValidationError(ValueError):
    pass


VALID_SLOTS = {"afternoon", "revision"}
ISSUE_RE = re.compile(r"第(\d+)期")
CAPTURE_RE = re.compile(r"采集时间[:：]\s*([^\n]+)")
PRESERVED_FIELDS = [
    "enabled",
    "active_dates",
    "issue_file",
    "overrides_file",
    "revision_overrides_file",
    "notes",
]


class ZucaiOddsSyncService:
    def sync(
        self,
        *,
        source_file: Path | str | None = None,
        source_url: str | None = None,
        live_fetch: bool = False,
        issue_id: str | None,
        slot: str,
        captured_at: str | None,
        output_dir: Path | str,
        registry_file: Path | str,
        source_label: str = "Zucai odds source",
        timeout_seconds: float = 5.0,
        max_bytes: int = 524_288,
    ) -> ZucaiOddsSyncResult:
        if slot not in VALID_SLOTS:
            raise ZucaiOddsSourceValidationError("slot must be afternoon or revision")
        content, source_path = self._load_source(
            source_file=source_file,
            source_url=source_url,
            live_fetch=live_fetch,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
        )
        snapshot, warnings = self.parse_source_text(
            content,
            issue_id=issue_id,
            captured_at=captured_at,
            source_label=source_label,
            source_url=source_url,
        )
        if snapshot is None:
            raise ZucaiOddsSourceValidationError("unable to build complete odds snapshot")
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        resolved_issue_id = str(snapshot["issue_id"])
        filename = (
            f"{resolved_issue_id}-odds.json"
            if slot == "afternoon"
            else f"{resolved_issue_id}-odds-revision.json"
        )
        odds_path = output_path / filename
        payload = json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)
        odds_path.write_text(payload, encoding="utf-8")
        # append-only 存档:每次抓取各留一份,规范文件仍是最新一份。
        # 位移特征(伤停/战意的无泄漏代理)依赖跨时点快照;原地覆盖会把历史抹掉。
        archive_path = self._archive_snapshot(output_path, resolved_issue_id, snapshot, payload)
        self._update_registry(
            registry_file=Path(registry_file),
            output_dir=output_path,
            issue_id=resolved_issue_id,
            slot=slot,
            odds_path=odds_path,
        )
        return ZucaiOddsSyncResult(
            generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
            issue_id=resolved_issue_id,
            slot=slot,
            captured_at=str(snapshot["captured_at"]),
            source_label=source_label,
            source_url=source_url,
            source_path=str(source_path) if source_path is not None else None,
            parsed_count=len(snapshot["matches"]),
            odds_path=str(odds_path),
            archive_path=str(archive_path),
            registry_path=str(registry_file),
            warnings=warnings,
        )

    def parse_source_file(
        self,
        source_file: Path | str,
        *,
        issue_id: str | None,
        captured_at: str | None,
        source_label: str,
        source_url: str | None = None,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        content = Path(source_file).read_text(encoding="utf-8")
        return self.parse_source_text(
            content,
            issue_id=issue_id,
            captured_at=captured_at,
            source_label=source_label,
            source_url=source_url,
        )

    def parse_source_text(
        self,
        content: str,
        *,
        issue_id: str | None,
        captured_at: str | None,
        source_label: str,
        source_url: str | None,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        lines = _normalize_lines(content)
        text = "\n".join(lines)
        resolved_issue_id = issue_id or _first_match(ISSUE_RE, text)
        resolved_captured_at = captured_at or _first_match(CAPTURE_RE, text) or "unknown"
        warnings: list[str] = []
        rows: list[dict[str, Any]] = []
        index = 0
        while index < len(lines):
            token = lines[index]
            if re.fullmatch(r"\d{1,2}", token):
                match_no = int(token)
                if 1 <= match_no <= 14 and index + 3 < len(lines):
                    home = _positive_float(lines[index + 1])
                    draw = _positive_float(lines[index + 2])
                    away = _positive_float(lines[index + 3])
                    provider = lines[index + 4] if index + 4 < len(lines) else None
                    if home is None or draw is None or away is None:
                        warnings.append(f"invalid odds row for match {match_no}")
                        index += 1
                        continue
                    row: dict[str, Any] = {
                        "match_no": match_no,
                        "home": home,
                        "draw": draw,
                        "away": away,
                    }
                    if (
                        provider
                        and not _looks_numeric(provider)
                        and not provider.startswith("场次")
                    ):
                        row["providers"] = [{"name": provider}]
                        index += 5
                    else:
                        index += 4
                    rows.append(row)
                    continue
            index += 1
        rows_by_match = {row["match_no"]: row for row in rows}
        ordered = [rows_by_match[number] for number in sorted(rows_by_match)]
        if resolved_issue_id is None:
            warnings.append("missing issue id")
        if len(ordered) != 14 or [row["match_no"] for row in ordered] != list(range(1, 15)):
            warnings.append("expected exactly 14 valid odds rows")
            return None, warnings
        return (
            {
                "issue_id": resolved_issue_id,
                "captured_at": resolved_captured_at,
                "sources": [{"label": source_label, "url": source_url or ""}],
                "matches": ordered,
            },
            warnings,
        )

    def _load_source(
        self,
        *,
        source_file: Path | str | None,
        source_url: str | None,
        live_fetch: bool,
        timeout_seconds: float,
        max_bytes: int,
    ) -> tuple[str, Path | None]:
        if source_file is not None:
            path = Path(source_file)
            try:
                return path.read_text(encoding="utf-8"), path
            except OSError as exc:
                raise ZucaiOddsSourceValidationError(f"unable to read source file: {exc}") from exc
        if source_url is None:
            raise ZucaiOddsSourceValidationError("--source-file or --source-url is required")
        if not live_fetch:
            raise ZucaiOddsSourceValidationError("--source-url requires --live-fetch")
        try:
            response = httpx.get(source_url, timeout=timeout_seconds)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ZucaiOddsSourceValidationError(f"odds source fetch failed: {exc}") from exc
        content = response.content[:max_bytes]
        encoding = response.encoding or "utf-8"
        return content.decode(encoding, errors="replace"), None

    @staticmethod
    def _archive_snapshot(
        output_path: Path, issue_id: str, snapshot: dict, payload: str
    ) -> Path:
        """把本次抓取原样存进 snapshots/,文件名带采集时刻,永不覆盖。"""
        snap_dir = output_path / "snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        stamp = re.sub(r"[^0-9A-Za-z]+", "-", str(snapshot.get("captured_at") or "")).strip("-")
        if not stamp:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        path = snap_dir / f"{issue_id}-odds-{stamp}.json"
        if not path.exists():
            path.write_text(payload, encoding="utf-8")
        return path

    def _update_registry(
        self,
        *,
        registry_file: Path,
        output_dir: Path,
        issue_id: str,
        slot: str,
        odds_path: Path,
    ) -> None:
        entries = _load_registry_entries(registry_file)
        field = "odds_file" if slot == "afternoon" else "revision_odds_file"
        odds_value = _relative_to(output_dir, odds_path)
        found = False
        updated: list[dict[str, Any]] = []
        for entry in entries:
            if str(entry.get("issue_id") or "") == issue_id:
                merged = dict(entry)
                merged[field] = odds_value
                found = True
                updated.append(merged)
            else:
                updated.append(entry)
        if not found:
            updated.append(
                {
                    "issue_id": issue_id,
                    "enabled": True,
                    field: odds_value,
                    "notes": "Generated by zucai-odds-sync",
                }
            )
        registry_file.parent.mkdir(parents=True, exist_ok=True)
        registry_file.write_text(
            json.dumps({"entries": updated}, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )


def _normalize_lines(content: str) -> list[str]:
    text = re.sub(r"(?is)<script.*?</script>", "\n", content)
    text = re.sub(r"(?is)<style.*?</style>", "\n", text)
    text = re.sub(r"(?i)</(?:td|th|tr|p|h\d|section|div|li)>", "\n", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = unescape(text).replace("\xa0", " ")
    lines: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if line:
            lines.append(line)
    return lines


def _positive_float(value: str) -> float | None:
    normalized = value.replace(",", "").strip()
    try:
        number = float(normalized)
    except ValueError:
        return None
    return number if number > 0 else None


def _looks_numeric(value: str) -> bool:
    return _positive_float(value) is not None or re.fullmatch(r"\d{1,2}", value) is not None


def _first_match(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1).strip() if match else None


def _relative_to(base_dir: Path, path: Path) -> str:
    try:
        return str(path.relative_to(base_dir))
    except ValueError:
        return str(path)
