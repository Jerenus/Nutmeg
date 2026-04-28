from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

from nutmeg.domain.information import (
    FixtureInformationDigest,
    InformationCacheEntry,
    InformationItem,
    InformationReliability,
    InformationSourceDefinition,
    InformationSourceHealth,
)

SUPPORTED_SOURCE_KINDS = {'local_json', 'local_rss', 'remote_json', 'remote_rss'}
DEFAULT_CACHE_TTL_SECONDS = 900
DEFAULT_TIMEOUT_SECONDS = 3.0
DEFAULT_MAX_BYTES = 262_144


@dataclass(slots=True, frozen=True)
class HttpFetchResult:
    status_code: int
    content_type: str
    body: str


class LocalInformationProvider:
    def __init__(self, *, sample_dir: Path | None = None) -> None:
        self.sample_dir = sample_dir or Path(__file__).parents[1] / 'information' / 'samples'

    def default_source_path(self, fixture_id: str) -> Path:
        return self.sample_dir / f'{fixture_id}-information.json'

    def load_items(
        self,
        *,
        fixture_id: str,
        sources_file: str | Path | None = None,
    ) -> tuple[list[InformationItem], list[InformationSourceHealth], list[str]]:
        path = (
            Path(sources_file)
            if sources_file is not None
            else self.default_source_path(fixture_id)
        )
        retrieved_at = datetime.now(UTC).replace(microsecond=0)
        if not path.exists():
            warning = f'information source file not found: {path}'
            return [], [
                InformationSourceHealth(
                    source_name=str(path),
                    source_type='local',
                    status='unavailable',
                    item_count=0,
                    warnings=[warning],
                    retrieved_at=retrieved_at,
                )
            ], [warning]
        if not path.read_text().strip():
            warning = 'information source file is empty'
            return [], [
                InformationSourceHealth(
                    source_name=str(path),
                    source_type='local',
                    status='unavailable',
                    item_count=0,
                    warnings=[warning],
                    retrieved_at=retrieved_at,
                )
            ], [warning]
        try:
            if path.suffix.lower() in {'.xml', '.rss', '.atom'}:
                items = self._parse_rss(path, fixture_id=fixture_id, retrieved_at=retrieved_at)
                source_type = 'rss'
                source_name = path.name
            else:
                items, source_name, source_type = self._parse_json(
                    path,
                    fixture_id=fixture_id,
                    retrieved_at=retrieved_at,
                )
        except (json.JSONDecodeError, ET.ParseError) as exc:
            warning = f'malformed information source: {exc}'
            return [], [
                InformationSourceHealth(
                    source_name=path.name,
                    source_type='local',
                    status='unavailable',
                    item_count=0,
                    warnings=[warning],
                    retrieved_at=retrieved_at,
                )
            ], [warning]
        if not items:
            warning = 'information source unavailable or empty'
            return [], [
                InformationSourceHealth(
                    source_name=source_name,
                    source_type=source_type,
                    status='unavailable',
                    item_count=0,
                    warnings=[warning],
                    retrieved_at=retrieved_at,
                )
            ], [warning]
        return items, [
            InformationSourceHealth(
                source_name=source_name,
                source_type=source_type,
                status='complete',
                item_count=len(items),
                warnings=[],
                retrieved_at=retrieved_at,
            )
        ], []

    def _parse_json(
        self,
        path: Path,
        *,
        fixture_id: str,
        retrieved_at: datetime,
    ) -> tuple[list[InformationItem], str, str]:
        payload = json.loads(path.read_text())
        source_name = (
            str(payload.get('source_name') or path.name)
            if isinstance(payload, dict)
            else path.name
        )
        source_type = (
            str(payload.get('source_type') or 'json')
            if isinstance(payload, dict)
            else 'json'
        )
        return _parse_json_payload(
            payload,
            fixture_id=fixture_id,
            fallback_source_name=source_name,
            source_type=source_type,
            retrieved_at=retrieved_at,
        ), source_name, source_type

    def _parse_rss(
        self,
        path: Path,
        *,
        fixture_id: str,
        retrieved_at: datetime,
    ) -> list[InformationItem]:
        return _parse_rss_payload(
            path.read_text(),
            fixture_id=fixture_id,
            fallback_source_name=path.name,
            retrieved_at=retrieved_at,
        )


class LiveInformationProvider:
    def __init__(
        self,
        *,
        manifest_path: str | Path | None,
        cache_dir: str | Path,
        live_fetch: bool = False,
        fetcher=None,
        default_cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        default_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        default_max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> None:
        self.manifest_path = Path(manifest_path) if manifest_path is not None else None
        self.cache_dir = Path(cache_dir)
        self.live_fetch = live_fetch
        self.fetcher = fetcher or _default_http_fetch
        self.default_cache_ttl_seconds = default_cache_ttl_seconds
        self.default_timeout_seconds = default_timeout_seconds
        self.default_max_bytes = default_max_bytes

    def load_items(
        self,
        *,
        fixture_id: str,
        sources_file: str | Path | None = None,
    ) -> tuple[list[InformationItem], list[InformationSourceHealth], list[str]]:
        manifest_path = Path(sources_file) if sources_file is not None else self.manifest_path
        retrieved_at = datetime.now(UTC).replace(microsecond=0)
        if manifest_path is None:
            warning = 'information source manifest not configured'
            return [], [
                InformationSourceHealth(
                    source_name='information manifest',
                    source_type='manifest',
                    status='unavailable',
                    item_count=0,
                    warnings=[warning],
                    retrieved_at=retrieved_at,
                )
            ], [warning]

        sources, manifest_warnings, defaults = load_information_source_manifest(manifest_path)
        all_items: list[InformationItem] = []
        health: list[InformationSourceHealth] = []
        warnings = list(manifest_warnings)
        for source in sources:
            items, source_health, source_warnings = self._load_source(
                source,
                fixture_id=fixture_id,
                retrieved_at=retrieved_at,
                defaults=defaults,
            )
            all_items.extend(items)
            health.append(source_health)
            warnings.extend(source_warnings)
        if manifest_warnings:
            health.append(
                InformationSourceHealth(
                    source_name=str(manifest_path),
                    source_type='manifest',
                    status='partial' if sources else 'unavailable',
                    item_count=0,
                    warnings=manifest_warnings,
                    retrieved_at=retrieved_at,
                )
            )
        return all_items, health, warnings

    def write_cache_entry(
        self,
        url: str,
        result: HttpFetchResult,
        *,
        fetched_at: datetime | None = None,
    ) -> InformationCacheEntry:
        fetched = fetched_at or datetime.now(UTC).replace(microsecond=0)
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=UTC)
        entry = InformationCacheEntry(
            cache_key=_cache_key(url),
            url=url,
            content_type=result.content_type,
            status_code=result.status_code,
            fetched_at=fetched.astimezone(UTC).replace(microsecond=0),
            body=result.body,
            warnings=[],
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path(url).write_text(json.dumps(entry.to_dict(), indent=2, sort_keys=True))
        return entry

    def _load_source(
        self,
        source: InformationSourceDefinition,
        *,
        fixture_id: str,
        retrieved_at: datetime,
        defaults: dict[str, int | float | None],
    ) -> tuple[list[InformationItem], InformationSourceHealth, list[str]]:
        if source.kind.startswith('local_'):
            return self._load_local_source(source, fixture_id=fixture_id, retrieved_at=retrieved_at)
        return self._load_remote_source(
            source,
            fixture_id=fixture_id,
            retrieved_at=retrieved_at,
            defaults=defaults,
        )

    def _load_local_source(
        self,
        source: InformationSourceDefinition,
        *,
        fixture_id: str,
        retrieved_at: datetime,
    ) -> tuple[list[InformationItem], InformationSourceHealth, list[str]]:
        if source.path is None:
            warning = f'information source {source.source_name} missing path'
            return [], _source_health(source, 'unavailable', 0, [warning], retrieved_at), [warning]
        path = Path(source.path)
        if not path.exists() or not path.read_text().strip():
            warning = f'information source file unavailable: {path}'
            return [], _source_health(source, 'unavailable', 0, [warning], retrieved_at), [warning]
        try:
            if source.kind == 'local_rss':
                items = _parse_rss_payload(
                    path.read_text(),
                    fixture_id=fixture_id,
                    fallback_source_name=source.source_name,
                    retrieved_at=retrieved_at,
                )
            else:
                items = _parse_json_payload(
                    json.loads(path.read_text()),
                    fixture_id=fixture_id,
                    fallback_source_name=source.source_name,
                    source_type='json',
                    retrieved_at=retrieved_at,
                )
        except (json.JSONDecodeError, ET.ParseError) as exc:
            warning = f'malformed information source: {exc}'
            return [], _source_health(source, 'unavailable', 0, [warning], retrieved_at), [warning]
        items = [_apply_source_defaults(item, source) for item in items]
        return items, _source_health(source, 'complete', len(items), [], retrieved_at), []

    def _load_remote_source(
        self,
        source: InformationSourceDefinition,
        *,
        fixture_id: str,
        retrieved_at: datetime,
        defaults: dict[str, int | float | None],
    ) -> tuple[list[InformationItem], InformationSourceHealth, list[str]]:
        if source.url is None:
            warning = f'information source {source.source_name} missing url'
            return [], _source_health(source, 'unavailable', 0, [warning], retrieved_at), [warning]
        ttl = int(
            source.cache_ttl_seconds
            or defaults.get('cache_ttl_seconds')
            or self.default_cache_ttl_seconds
        )
        timeout = float(
            source.timeout_seconds
            or defaults.get('timeout_seconds')
            or self.default_timeout_seconds
        )
        max_bytes = int(source.max_bytes or defaults.get('max_bytes') or self.default_max_bytes)
        cached = self._read_cache_entry(source.url)
        if cached is not None and _is_cache_fresh(cached, ttl) and not self.live_fetch:
            items = self._parse_remote_entry(
                source,
                cached,
                fixture_id=fixture_id,
                retrieved_at=retrieved_at,
            )
            return items, _source_health(
                source,
                'complete',
                len(items),
                ['using fresh cache'],
                retrieved_at,
            ), []
        if not self.live_fetch:
            warning = f'remote fetch disabled and no fresh cache: {source.url}'
            return [], _source_health(source, 'unavailable', 0, [warning], retrieved_at), [warning]
        try:
            result = self.fetcher(source.url, timeout, max_bytes)
            if result.status_code >= 400:
                raise RuntimeError(f'HTTP {result.status_code}')
            if len(result.body.encode('utf-8')) > max_bytes:
                raise RuntimeError('remote response exceeded max bytes')
            cached = self.write_cache_entry(source.url, result, fetched_at=retrieved_at)
            items = self._parse_remote_entry(
                source,
                cached,
                fixture_id=fixture_id,
                retrieved_at=retrieved_at,
            )
            return items, _source_health(source, 'complete', len(items), [], retrieved_at), []
        except (RuntimeError, TimeoutError, ValueError, ET.ParseError, json.JSONDecodeError) as exc:
            if cached is not None:
                warning = f'using stale cache after fetch failure: {exc}'
                items = self._parse_remote_entry(
                    source,
                    cached,
                    fixture_id=fixture_id,
                    retrieved_at=retrieved_at,
                )
                return items, _source_health(
                    source,
                    'partial',
                    len(items),
                    [warning],
                    retrieved_at,
                ), [warning]
            warning = f'remote fetch failed: {exc}'
            return [], _source_health(source, 'unavailable', 0, [warning], retrieved_at), [warning]

    def _parse_remote_entry(
        self,
        source: InformationSourceDefinition,
        entry: InformationCacheEntry,
        *,
        fixture_id: str,
        retrieved_at: datetime,
    ) -> list[InformationItem]:
        if source.kind == 'remote_rss':
            items = _parse_rss_payload(
                entry.body,
                fixture_id=fixture_id,
                fallback_source_name=source.source_name,
                retrieved_at=retrieved_at,
            )
        else:
            items = _parse_json_payload(
                json.loads(entry.body),
                fixture_id=fixture_id,
                fallback_source_name=source.source_name,
                source_type='json',
                retrieved_at=retrieved_at,
            )
        return [_apply_source_defaults(item, source) for item in items]

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / f'{_cache_key(url)}.json'

    def _read_cache_entry(self, url: str) -> InformationCacheEntry | None:
        path = self._cache_path(url)
        if not path.exists():
            return None
        try:
            return InformationCacheEntry.from_dict(json.loads(path.read_text()))
        except (json.JSONDecodeError, TypeError, ValueError):
            return None


def _parse_rss_payload(
    text: str,
    *,
    fixture_id: str,
    fallback_source_name: str,
    retrieved_at: datetime,
) -> list[InformationItem]:
    root = ET.fromstring(text)
    channel_title = root.findtext('./channel/title') or fallback_source_name
    rss_items = root.findall('./channel/item')
    if not rss_items and _strip_ns(root.tag) == 'feed':
        channel_title = root.findtext('./{*}title') or fallback_source_name
        rss_items = root.findall('./{*}entry')
    items = []
    for index, node in enumerate(rss_items):
        title = _node_text(node, 'title') or 'Untitled information item'
        summary = _node_text(node, 'description') or _node_text(node, 'summary') or title
        link = _node_text(node, 'link')
        if link is None:
            link_node = node.find('./{*}link')
            link = link_node.get('href') if link_node is not None else None
        published = _node_text(node, 'pubDate') or _node_text(node, 'published') or _node_text(
            node,
            'updated',
        )
        tags = [_node_text(category, None) for category in node.findall('./category')]
        tags = [tag for tag in tags if tag]
        items.append(
            InformationItem(
                item_id=f'{_slug(channel_title) or "rss"}-{index + 1}',
                source_name=channel_title,
                source_type='rss',
                title=title,
                summary=summary,
                url=link,
                published_at=_parse_datetime(published),
                retrieved_at=retrieved_at,
                reliability=InformationReliability.UNVERIFIED,
                fixture_ids=[fixture_id] if fixture_id in f'{title} {summary}' else [],
                teams=[],
                tags=tags,
                metadata={},
            )
        )
    return items


class FixtureInformationService:
    def __init__(self, *, provider: LocalInformationProvider | None = None) -> None:
        self._provider = provider or LocalInformationProvider()

    def build_digest(
        self,
        *,
        fixture_id: str,
        home_team: str | None = None,
        away_team: str | None = None,
        sources_file: str | Path | None = None,
        max_items: int = 5,
    ) -> FixtureInformationDigest:
        items, source_health, warnings = self._provider.load_items(
            fixture_id=fixture_id,
            sources_file=sources_file,
        )
        if not items:
            return FixtureInformationDigest.unavailable(
                fixture_id=fixture_id,
                warnings=warnings,
                source_health=source_health,
            )
        teams = [team for team in [home_team, away_team] if team]
        matched = [
            item
            for item in items
            if _matches_item(item, fixture_id=fixture_id, teams=teams)
        ]
        deduped = _dedupe_items(matched)
        deduped.sort(key=lambda item: item.published_at or item.retrieved_at, reverse=True)
        selected = deduped[:max_items]
        digest_warnings = list(warnings)
        if any(
            item.reliability in {InformationReliability.RUMOR, InformationReliability.UNVERIFIED}
            for item in selected
        ):
            digest_warnings.append('Rumor/unverified information is not confirmed.')
        if not selected:
            return FixtureInformationDigest.unavailable(
                fixture_id=fixture_id,
                warnings=[*digest_warnings, 'no matching information items'],
                source_health=source_health,
            )
        latest = max(
            (item.published_at for item in selected if item.published_at is not None),
            default=None,
        )
        sources = sorted({item.source_name for item in selected})
        summary = (
            f'{len(selected)} relevant updates from {len(sources)} sources. '
            f'Latest: {selected[0].title}'
        )
        status = (
            'partial'
            if any(health.status != 'complete' for health in source_health)
            else 'complete'
        )
        return FixtureInformationDigest(
            fixture_id=fixture_id,
            status=status,
            summary=summary,
            items=selected,
            source_count=len(sources),
            latest_published_at=latest,
            warnings=digest_warnings,
            source_health=source_health,
        )

    def build_information(
        self,
        fixture_id: str,
        *,
        home_team: str | None = None,
        away_team: str | None = None,
    ) -> dict[str, object]:
        digest = self.build_digest(
            fixture_id=fixture_id,
            home_team=home_team,
            away_team=away_team,
        )
        payload = digest.to_dict()
        return {
            'source_name': 'Nutmeg information provider',
            'summary': digest.summary,
            'staleness': 'unavailable' if digest.status == 'unavailable' else 'fresh',
            'status': digest.status,
            'latest_published_at': payload['latest_published_at'],
            'source_count': digest.source_count,
            'items': payload['items'],
            'warnings': digest.warnings,
        }


def _item_from_mapping(
    record: dict[str, object],
    *,
    fixture_id: str,
    fallback_source_name: str,
    source_type: str,
    index: int,
    retrieved_at: datetime,
) -> InformationItem | None:
    title = str(record.get('title') or '').strip()
    summary = str(record.get('summary') or record.get('description') or title).strip()
    if not title and not summary:
        return None
    metadata_keys = {
        'item_id',
        'id',
        'source_name',
        'source_type',
        'title',
        'summary',
        'description',
        'url',
        'link',
        'published_at',
        'pubDate',
        'reliability',
        'fixture_ids',
        'teams',
        'tags',
    }
    return InformationItem(
        item_id=str(record.get('item_id') or record.get('id') or f'{fixture_id}-info-{index + 1}'),
        source_name=str(record.get('source_name') or fallback_source_name),
        source_type=str(record.get('source_type') or source_type),
        title=title or summary,
        summary=summary or title,
        url=_optional_str(record.get('url') or record.get('link')),
        published_at=_parse_datetime(record.get('published_at') or record.get('pubDate')),
        retrieved_at=retrieved_at,
        reliability=_parse_reliability(record.get('reliability')),
        fixture_ids=_list_str(record.get('fixture_ids')),
        teams=_list_str(record.get('teams')),
        tags=_list_str(record.get('tags')),
        metadata={key: value for key, value in record.items() if key not in metadata_keys},
    )


def _parse_json_payload(
    payload: object,
    *,
    fixture_id: str,
    fallback_source_name: str,
    source_type: str,
    retrieved_at: datetime,
) -> list[InformationItem]:
    records = payload.get('items') if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        return []
    return [
        item
        for index, record in enumerate(records)
        if isinstance(record, dict)
        if (
            item := _item_from_mapping(
                record,
                fixture_id=fixture_id,
                fallback_source_name=fallback_source_name,
                source_type=source_type,
                index=index,
                retrieved_at=retrieved_at,
            )
        )
        is not None
    ]


def load_information_source_manifest(
    manifest_path: str | Path,
) -> tuple[list[InformationSourceDefinition], list[str], dict[str, int | float | None]]:
    path = Path(manifest_path)
    defaults: dict[str, int | float | None] = {
        'cache_ttl_seconds': DEFAULT_CACHE_TTL_SECONDS,
        'timeout_seconds': DEFAULT_TIMEOUT_SECONDS,
        'max_bytes': DEFAULT_MAX_BYTES,
    }
    if not path.exists() or not path.read_text().strip():
        return [], [f'information source manifest unavailable: {path}'], defaults
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [], [f'malformed information source manifest: {exc}'], defaults
    if not isinstance(payload, dict):
        return [], ['information source manifest must be an object'], defaults
    defaults['cache_ttl_seconds'] = _positive_int(
        payload.get('cache_ttl_seconds'),
        DEFAULT_CACHE_TTL_SECONDS,
    )
    defaults['timeout_seconds'] = _positive_float(
        payload.get('timeout_seconds'),
        DEFAULT_TIMEOUT_SECONDS,
    )
    defaults['max_bytes'] = _positive_int(payload.get('max_bytes'), DEFAULT_MAX_BYTES)
    records = payload.get('sources')
    if not isinstance(records, list):
        return [], ['information source manifest missing sources list'], defaults
    sources: list[InformationSourceDefinition] = []
    warnings: list[str] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            warnings.append(f'information source #{index + 1} is not an object')
            continue
        if record.get('enabled') is False:
            continue
        source_name = str(record.get('source_name') or f'information source #{index + 1}')
        kind = str(record.get('kind') or '').strip()
        if kind not in SUPPORTED_SOURCE_KINDS:
            warnings.append(f'unsupported source kind for {source_name}: {kind or "missing"}')
            continue
        path_value = _optional_str(record.get('path'))
        url_value = _optional_str(record.get('url'))
        if kind.startswith('local_') and path_value is None:
            warnings.append(f'information source {source_name} missing path')
            continue
        if kind.startswith('remote_') and url_value is None:
            warnings.append(f'information source {source_name} missing url')
            continue
        metadata_keys = {
            'source_name',
            'kind',
            'enabled',
            'path',
            'url',
            'reliability',
            'fixture_ids',
            'teams',
            'tags',
            'cache_ttl_seconds',
            'timeout_seconds',
            'max_bytes',
        }
        sources.append(
            InformationSourceDefinition(
                source_name=source_name,
                kind=kind,
                enabled=True,
                path=Path(path_value) if path_value is not None else None,
                url=url_value,
                reliability=_parse_reliability(record.get('reliability')),
                fixture_ids=_list_str(record.get('fixture_ids')),
                teams=_list_str(record.get('teams')),
                tags=_list_str(record.get('tags')),
                cache_ttl_seconds=_optional_positive_int(record.get('cache_ttl_seconds')),
                timeout_seconds=_optional_positive_float(record.get('timeout_seconds')),
                max_bytes=_optional_positive_int(record.get('max_bytes')),
                metadata={key: value for key, value in record.items() if key not in metadata_keys},
            )
        )
    return sources, warnings, defaults


def _source_health(
    source: InformationSourceDefinition,
    status: str,
    item_count: int,
    warnings: list[str],
    retrieved_at: datetime,
) -> InformationSourceHealth:
    return InformationSourceHealth(
        source_name=source.source_name,
        source_type=source.kind,
        status=status,
        item_count=item_count,
        warnings=warnings,
        retrieved_at=retrieved_at,
    )


def _apply_source_defaults(
    item: InformationItem,
    source: InformationSourceDefinition,
) -> InformationItem:
    fixture_ids = item.fixture_ids or list(source.fixture_ids)
    teams = item.teams or list(source.teams)
    tags = _merge_strings(item.tags, source.tags)
    reliability = item.reliability
    if reliability == InformationReliability.UNVERIFIED:
        reliability = source.reliability
    return replace(
        item,
        source_name=(
            item.source_name
            if item.source_name != 'information.json'
            else source.source_name
        ),
        reliability=reliability,
        fixture_ids=fixture_ids,
        teams=teams,
        tags=tags,
    )


def _merge_strings(primary: list[str], defaults: list[str]) -> list[str]:
    merged: list[str] = []
    for value in [*primary, *defaults]:
        if value and value not in merged:
            merged.append(value)
    return merged


def _cache_key(url: str) -> str:
    return hashlib.sha256(url.encode('utf-8')).hexdigest()


def _is_cache_fresh(entry: InformationCacheEntry, ttl_seconds: int) -> bool:
    age = datetime.now(UTC) - entry.fetched_at.astimezone(UTC)
    return age.total_seconds() <= ttl_seconds


def _default_http_fetch(url: str, timeout_seconds: float, max_bytes: int) -> HttpFetchResult:
    response = httpx.get(url, timeout=timeout_seconds)
    body_bytes = response.content
    if len(body_bytes) > max_bytes:
        raise RuntimeError('remote response exceeded max bytes')
    return HttpFetchResult(
        status_code=response.status_code,
        content_type=response.headers.get('content-type', ''),
        body=body_bytes.decode(response.encoding or 'utf-8', errors='replace'),
    )


def _optional_positive_int(value: object) -> int | None:
    if value is None:
        return None
    return _positive_int(value, 0) or None


def _optional_positive_float(value: object) -> float | None:
    if value is None:
        return None
    return _positive_float(value, 0.0) or None


def _positive_int(value: object, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _positive_float(value: object, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _matches_item(item: InformationItem, *, fixture_id: str, teams: list[str]) -> bool:
    if fixture_id in item.fixture_ids:
        return True
    text = f'{item.title} {item.summary}'.casefold()
    item_teams = {team.casefold() for team in item.teams}
    for team in teams:
        normalized = team.casefold()
        if normalized in item_teams or normalized in text:
            return True
    return False


def _dedupe_items(items: list[InformationItem]) -> list[InformationItem]:
    by_key: dict[str, InformationItem] = {}
    for item in items:
        key = item.url or f'{_slug(item.source_name)}:{_slug(item.title)}'
        existing = by_key.get(key)
        if existing is None or (item.published_at or item.retrieved_at) > (
            existing.published_at or existing.retrieved_at
        ):
            by_key[key] = item
    return list(by_key.values())


def _parse_reliability(value: object) -> InformationReliability:
    try:
        return InformationReliability(str(value or 'unverified').casefold())
    except ValueError:
        return InformationReliability.UNVERIFIED


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(microsecond=0)


def _optional_str(value: object) -> str | None:
    return str(value).strip() if value is not None and str(value).strip() else None


def _list_str(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _slug(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', value.casefold()).strip('-')


def _node_text(node: ET.Element, name: str | None) -> str | None:
    if name is None:
        return (node.text or '').strip() or None
    child = node.find(f'./{name}')
    if child is None:
        child = node.find(f'./{{*}}{name}')
    return (child.text or '').strip() if child is not None and child.text else None


def _strip_ns(tag: str) -> str:
    return tag.rsplit('}', 1)[-1]
