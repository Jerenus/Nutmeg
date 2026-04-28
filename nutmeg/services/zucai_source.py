from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from html import unescape
from pathlib import Path
from typing import Any

import httpx

from nutmeg.domain.zucai import ZucaiIssue, ZucaiMatch
from nutmeg.domain.zucai_source import ParsedZucaiIssue, ZucaiSourceSyncResult


class ZucaiSourceValidationError(ValueError):
    pass


ISSUE_ANCHOR_RE = re.compile(r"足球彩票胜负游戏（14场和任选9场）第(\d+)期")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_CAPTURE = r"([0-9]{4}-[0-9]{2}-[0-9]{2}(?:\s+[0-9]{2}:[0-9]{2})?)"
TIMING_PATTERNS = {
    "sale_start": re.compile(rf"开售时间[:：]\s*{DATETIME_CAPTURE}"),
    "sale_stop": re.compile(rf"停售时间[:：]\s*{DATETIME_CAPTURE}"),
    "draw_date": re.compile(r"开奖日期[:：]\s*([0-9]{4}-[0-9]{2}-[0-9]{2})"),
}
HEADER_TOKENS = {
    "期号",
    "赛制",
    "序号",
    "主队",
    "客队",
    "比赛日期",
    "开售时间",
    "停售时间",
    "开奖日期",
}
PRESERVED_REGISTRY_FIELDS = [
    "odds_file",
    "overrides_file",
    "revision_odds_file",
    "revision_overrides_file",
    "notes",
]


class ZucaiSourceSyncService:
    def sync(
        self,
        *,
        source_file: Path | str | None = None,
        source_url: str | None = None,
        live_fetch: bool = False,
        run_date: str | None = None,
        output_dir: Path | str,
        registry_file: Path | str,
        source_label: str = "Zucai schedule source",
        timeout_seconds: float = 5.0,
        max_bytes: int = 524_288,
    ) -> ZucaiSourceSyncResult:
        resolved_run_date = _normalize_run_date(run_date)
        content, source_path = self._load_source(
            source_file=source_file,
            source_url=source_url,
            live_fetch=live_fetch,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
        )
        parsed, warnings = self.parse_source_text(
            content,
            source_label=source_label,
            source_url=source_url,
        )
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        written: dict[str, str] = {}
        for item in parsed:
            issue_path = output_path / f"{item.issue_id}-issue.json"
            issue_path.write_text(
                json.dumps(item.issue.to_dict(), ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            written[item.issue_id] = str(issue_path)
        active_ids = self._write_registry(
            registry_file=Path(registry_file),
            output_dir=output_path,
            parsed=parsed,
            written=written,
            run_date=resolved_run_date,
        )
        return ZucaiSourceSyncResult(
            generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
            run_date=resolved_run_date,
            source_label=source_label,
            source_url=source_url,
            source_path=str(source_path) if source_path is not None else None,
            parsed_count=len(parsed),
            written_issue_paths=written,
            registry_path=str(registry_file),
            active_issue_ids=active_ids,
            warnings=warnings,
        )

    def parse_source_file(
        self,
        source_file: Path | str,
        *,
        source_label: str = "Zucai schedule source",
        source_url: str | None = None,
    ) -> list[ParsedZucaiIssue]:
        content = Path(source_file).read_text(encoding="utf-8")
        parsed, _warnings = self.parse_source_text(
            content,
            source_label=source_label,
            source_url=source_url,
        )
        return parsed

    def parse_source_text(
        self,
        content: str,
        *,
        source_label: str,
        source_url: str | None,
    ) -> tuple[list[ParsedZucaiIssue], list[str]]:
        lines = _normalize_lines(content)
        warnings: list[str] = []
        parsed: list[ParsedZucaiIssue] = []
        for issue_id, section in _iter_issue_sections(lines):
            item = self._parse_section(
                issue_id=issue_id,
                section=section,
                source_label=source_label,
                source_url=source_url,
                warnings=warnings,
            )
            if item is not None:
                parsed.append(item)
        if not parsed:
            warnings.append("no valid traditional Zucai 14-match issues parsed")
        return parsed, warnings

    def _parse_section(
        self,
        *,
        issue_id: str,
        section: list[str],
        source_label: str,
        source_url: str | None,
        warnings: list[str],
    ) -> ParsedZucaiIssue | None:
        text = "\n".join(section)
        timing = {
            name: match.group(1) if (match := pattern.search(text)) else None
            for name, pattern in TIMING_PATTERNS.items()
        }
        body = self._match_body(section, issue_id)
        matches: list[ZucaiMatch] = []
        current_competition = ""
        index = 0
        while index < len(body):
            token = body[index].strip()
            if not token or token in HEADER_TOKENS or token.startswith("附件"):
                index += 1
                continue
            if re.fullmatch(r"\d{1,2}", token):
                match_no = int(token)
                if not (1 <= match_no <= 14):
                    index += 1
                    continue
                if index + 3 >= len(body):
                    warnings.append(f"issue {issue_id} row {match_no} is incomplete")
                    break
                home = body[index + 1].strip()
                away = body[index + 2].strip()
                match_date = body[index + 3].strip()
                if not DATE_RE.match(match_date):
                    warnings.append(f"issue {issue_id} row {match_no} missing match date")
                    index += 1
                    continue
                matches.append(
                    ZucaiMatch(
                        match_no=match_no,
                        competition=current_competition,
                        home_team=home,
                        away_team=away,
                        match_date=match_date,
                    )
                )
                index += 4
                continue
            if not DATE_RE.match(token) and not token.startswith(("开售", "停售", "开奖")):
                current_competition = token
            index += 1
        numbers = [match.match_no for match in matches]
        if len(matches) != 14 or sorted(numbers) != list(range(1, 15)):
            warnings.append(f"issue {issue_id} skipped: expected exactly 14 matches")
            return None
        issue = ZucaiIssue(
            issue_id=issue_id,
            game_type="sfc14",
            sale_start=timing["sale_start"],
            sale_stop=timing["sale_stop"],
            draw_date=timing["draw_date"],
            sources=[{"label": source_label, "url": source_url or ""}],
            matches=sorted(matches, key=lambda match: match.match_no),
        )
        return ParsedZucaiIssue(
            issue_id=issue_id,
            issue=issue,
            source_label=source_label,
            source_url=source_url,
        )

    def _match_body(self, section: list[str], issue_id: str) -> list[str]:
        start = 0
        for idx, line in enumerate(section):
            if line == f"第{issue_id}期":
                start = idx + 1
                break
        body: list[str] = []
        for line in section[start:]:
            if line.startswith(("开售时间", "停售时间", "开奖日期")):
                continue
            body.append(line)
        return body

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
                raise ZucaiSourceValidationError(f"unable to read source file: {exc}") from exc
        if source_url is None:
            raise ZucaiSourceValidationError("--source-file or --source-url is required")
        if not live_fetch:
            raise ZucaiSourceValidationError("--source-url requires --live-fetch")
        try:
            response = httpx.get(source_url, timeout=timeout_seconds)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ZucaiSourceValidationError(f"source fetch failed: {exc}") from exc
        content = response.content[:max_bytes]
        encoding = response.encoding or "utf-8"
        return content.decode(encoding, errors="replace"), None

    def _write_registry(
        self,
        *,
        registry_file: Path,
        output_dir: Path,
        parsed: list[ParsedZucaiIssue],
        written: dict[str, str],
        run_date: str,
    ) -> list[str]:
        existing_entries = _load_registry_entries(registry_file)
        existing_by_issue = {str(item.get("issue_id")): item for item in existing_entries}
        parsed_ids = {item.issue_id for item in parsed}
        new_entries: list[dict[str, Any]] = []
        active_ids: list[str] = []
        for item in parsed:
            active_dates = _active_dates_for_issue(item.issue)
            if run_date in active_dates:
                active_ids.append(item.issue_id)
            entry: dict[str, Any] = {
                "issue_id": item.issue_id,
                "enabled": True,
                "active_dates": active_dates,
                "issue_file": _relative_to(output_dir, Path(written[item.issue_id])),
                "notes": f"Generated by zucai-source-sync from {item.source_label}",
            }
            previous = existing_by_issue.get(item.issue_id) or {}
            for field in PRESERVED_REGISTRY_FIELDS:
                if previous.get(field):
                    entry[field] = previous[field]
            new_entries.append(entry)
        for entry in existing_entries:
            issue_id = str(entry.get("issue_id") or "")
            if issue_id and issue_id not in parsed_ids:
                new_entries.append(entry)
        registry_file.parent.mkdir(parents=True, exist_ok=True)
        registry_file.write_text(
            json.dumps({"entries": new_entries}, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return active_ids


def _normalize_lines(content: str) -> list[str]:
    text = re.sub(r"(?is)<script.*?</script>", "\n", content)
    text = re.sub(r"(?is)<style.*?</style>", "\n", text)
    text = re.sub(r"(?i)</(?:td|th|tr|p|h\d|section|div|li)>", "\n", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = unescape(text).replace("\xa0", " ")
    lines = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if line:
            lines.append(line)
    return lines


def _iter_issue_sections(lines: list[str]):
    anchors: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = ISSUE_ANCHOR_RE.search(line)
        if match:
            issue_id = match.group(1)
            next_lines = lines[index : min(index + 20, len(lines))]
            has_detail_marker = f"第{issue_id}期" in next_lines or any(
                "序号" in item for item in next_lines
            )
            if has_detail_marker:
                anchors.append((index, issue_id))
    for pos, (start, issue_id) in enumerate(anchors):
        end = anchors[pos + 1][0] if pos + 1 < len(anchors) else len(lines)
        yield issue_id, lines[start:end]


def _load_registry_entries(registry_file: Path) -> list[dict[str, Any]]:
    if not registry_file.exists():
        return []
    try:
        payload = json.loads(registry_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in payload.get("entries") or [] if isinstance(item, dict)]


def _active_dates_for_issue(issue: ZucaiIssue) -> list[str]:
    for value in [issue.sale_stop, issue.draw_date]:
        if value and len(value) >= 10:
            return [value[:10]]
    dates = sorted({match.match_date for match in issue.matches if match.match_date})
    return dates[:1]


def _relative_to(base_dir: Path, path: Path) -> str:
    try:
        return str(path.relative_to(base_dir))
    except ValueError:
        return str(path)


def _normalize_run_date(raw: str | None) -> str:
    if raw is None or raw == "today":
        return date.today().isoformat()
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise ZucaiSourceValidationError("run date must be YYYY-MM-DD or 'today'") from exc
