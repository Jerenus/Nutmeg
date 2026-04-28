from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from nutmeg.domain.information import (
    FixtureInformationDigest,
    InformationCacheEntry,
    InformationItem,
    InformationReliability,
    InformationSourceDefinition,
    InformationSourceHealth,
)
from nutmeg.services.information import (
    FixtureInformationService,
    HttpFetchResult,
    LiveInformationProvider,
    LocalInformationProvider,
    load_information_source_manifest,
)


def _write_json(tmp_path: Path, payload: dict | list) -> Path:
    path = tmp_path / 'information.json'
    path.write_text(json.dumps(payload))
    return path


def test_information_domain_serializes_digest_contract() -> None:
    item = InformationItem(
        item_id='i1',
        source_name='Club official',
        source_type='json',
        title='Fullback returns',
        summary='A starter returned to training.',
        url='https://example.test/news',
        reliability=InformationReliability.OFFICIAL,
        fixture_ids=['epl-001'],
        teams=['Arsenal'],
        tags=['injury'],
    )
    health = InformationSourceHealth(
        source_name='Club official',
        source_type='json',
        status='complete',
        item_count=1,
        warnings=[],
    )
    digest = FixtureInformationDigest(
        fixture_id='epl-001',
        status='complete',
        summary='1 relevant update from 1 source.',
        items=[item],
        source_count=1,
        warnings=[],
        source_health=[health],
    )

    payload = digest.to_dict()

    assert payload['items'][0]['reliability'] == 'official'
    assert payload['source_health'][0]['status'] == 'complete'


def test_local_information_provider_discovers_bundled_sample() -> None:
    service = FixtureInformationService(provider=LocalInformationProvider())

    digest = service.build_digest(
        fixture_id='epl-001',
        home_team='Arsenal',
        away_team='Tottenham Hotspur',
    )

    assert digest.status == 'complete'
    assert len(digest.items) == 3
    assert digest.source_count >= 3


def test_fixture_information_service_normalizes_json_reliability(tmp_path: Path) -> None:
    sources_file = _write_json(
        tmp_path,
        {
            'source_name': 'Local Desk',
            'items': [
                {
                    'item_id': 'official-1',
                    'source_name': 'Club official',
                    'title': 'Arsenal defender fit for derby',
                    'summary': 'Official club note says the defender trained fully.',
                    'url': 'https://example.test/official-1',
                    'published_at': '2026-04-26T09:00:00+00:00',
                    'reliability': 'official',
                    'fixture_ids': ['epl-001'],
                    'teams': ['Arsenal'],
                    'tags': ['injury'],
                    'provider_extra': 'kept',
                },
                {
                    'item_id': 'other',
                    'source_name': 'Other',
                    'title': 'Liverpool team news',
                    'summary': 'Unrelated update.',
                    'fixture_ids': ['epl-999'],
                    'teams': ['Liverpool'],
                },
                {
                    'item_id': 'rumor-1',
                    'source_name': 'Supporter Wire',
                    'title': 'Rumor of late Spurs change',
                    'summary': 'Unverified late change rumor.',
                    'url': 'https://example.test/rumor-1',
                    'published_at': '2026-04-26T08:00:00+00:00',
                    'reliability': 'rumor',
                    'teams': ['Tottenham Hotspur'],
                    'tags': ['lineup'],
                },
            ],
        },
    )
    service = FixtureInformationService(provider=LocalInformationProvider())

    digest = service.build_digest(
        fixture_id='epl-001',
        home_team='Arsenal',
        away_team='Tottenham Hotspur',
        sources_file=sources_file,
    )

    assert digest.status == 'complete'
    assert [item.item_id for item in digest.items] == ['official-1', 'rumor-1']
    assert digest.items[0].reliability == InformationReliability.OFFICIAL
    assert digest.items[0].metadata['provider_extra'] == 'kept'
    assert any('Rumor/unverified' in warning for warning in digest.warnings)


def test_fixture_information_service_deduplicates_by_url_and_title_source(tmp_path: Path) -> None:
    sources_file = _write_json(
        tmp_path,
        {
            'items': [
                {
                    'item_id': 'old',
                    'source_name': 'Beat Writer',
                    'title': 'Same update',
                    'summary': 'Older copy.',
                    'url': 'https://example.test/same',
                    'published_at': '2026-04-26T07:00:00+00:00',
                    'fixture_ids': ['epl-001'],
                },
                {
                    'item_id': 'new',
                    'source_name': 'Beat Writer',
                    'title': 'Same update',
                    'summary': 'Newer copy.',
                    'url': 'https://example.test/same',
                    'published_at': '2026-04-26T09:00:00+00:00',
                    'fixture_ids': ['epl-001'],
                },
            ]
        },
    )
    service = FixtureInformationService(provider=LocalInformationProvider())

    digest = service.build_digest(fixture_id='epl-001', sources_file=sources_file)

    assert len(digest.items) == 1
    assert digest.items[0].item_id == 'new'
    assert 'Newer copy.' in digest.items[0].summary


def test_fixture_information_service_unavailable_for_bad_sources(tmp_path: Path) -> None:
    service = FixtureInformationService(provider=LocalInformationProvider())
    empty = _write_json(tmp_path, [])
    malformed = tmp_path / 'malformed.json'
    malformed.write_text('{bad-json')

    missing = service.build_digest(fixture_id='epl-001', sources_file=tmp_path / 'missing.json')
    empty_digest = service.build_digest(fixture_id='epl-001', sources_file=empty)
    malformed_digest = service.build_digest(fixture_id='epl-001', sources_file=malformed)

    assert missing.status == 'unavailable'
    assert empty_digest.status == 'unavailable'
    assert malformed_digest.status == 'unavailable'
    assert missing.items == []
    assert any('malformed' in warning for warning in malformed_digest.warnings)


def test_fixture_information_service_parses_local_rss_items(tmp_path: Path) -> None:
    rss = tmp_path / 'feed.xml'
    rss.write_text(
        '''<?xml version="1.0"?>
        <rss version="2.0"><channel><title>North London Feed</title>
        <item><title>Arsenal lineup note</title><link>https://example.test/rss-1</link>
        <description>Arsenal expected to keep the same XI.</description>
        <pubDate>Sun, 26 Apr 2026 09:00:00 GMT</pubDate>
        <category>lineup</category></item></channel></rss>'''
    )
    service = FixtureInformationService(provider=LocalInformationProvider())

    digest = service.build_digest(fixture_id='epl-001', home_team='Arsenal', sources_file=rss)

    assert digest.status == 'complete'
    assert digest.items[0].source_type == 'rss'
    assert digest.items[0].url == 'https://example.test/rss-1'
    assert digest.items[0].published_at is not None



def _write_manifest(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / 'sources.json'
    path.write_text(json.dumps(payload))
    return path


def test_information_source_definition_and_cache_entry_serialize() -> None:
    source = InformationSourceDefinition(
        source_name='Club RSS',
        kind='remote_rss',
        url='https://example.test/rss.xml',
        reliability=InformationReliability.OFFICIAL,
        teams=['Arsenal'],
        tags=['team_news'],
        cache_ttl_seconds=900,
    )
    entry = InformationCacheEntry(
        cache_key='abc123',
        url='https://example.test/rss.xml',
        content_type='application/rss+xml',
        status_code=200,
        fetched_at=datetime(2026, 4, 26, 9, 0, tzinfo=UTC),
        body='<rss />',
        warnings=['using fresh cache'],
    )

    assert source.to_dict()['reliability'] == 'official'
    assert source.to_dict()['teams'] == ['Arsenal']
    assert entry.to_dict()['fetched_at'] == '2026-04-26T09:00:00+00:00'
    assert entry.to_dict()['warnings'] == ['using fresh cache']


def test_live_information_manifest_loads_defaults_and_warnings(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        {
            'cache_ttl_seconds': 600,
            'sources': [
                {
                    'source_name': 'Bundled sample',
                    'kind': 'local_json',
                    'path': 'nutmeg/information/samples/epl-001-information.json',
                    'reliability': 'credible',
                },
                {'source_name': 'Disabled', 'kind': 'remote_rss', 'enabled': False},
                {'source_name': 'Broken', 'kind': 'remote_rss'},
                {'source_name': 'Unsupported', 'kind': 'web_page', 'url': 'https://example.test'},
            ],
        },
    )

    sources, warnings, defaults = load_information_source_manifest(manifest)

    assert defaults['cache_ttl_seconds'] == 600
    assert [source.source_name for source in sources] == ['Bundled sample']
    assert sources[0].path == Path('nutmeg/information/samples/epl-001-information.json')
    assert any('missing url' in warning for warning in warnings)
    assert any('unsupported source kind' in warning for warning in warnings)


def test_live_information_provider_loads_manifest_sources(tmp_path: Path) -> None:
    local = _write_json(
        tmp_path,
        {
            'items': [
                {
                    'title': 'Arsenal official local note',
                    'summary': 'Arsenal local update.',
                    'fixture_ids': ['epl-001'],
                }
            ]
        },
    )
    manifest = _write_manifest(
        tmp_path,
        {
            'sources': [
                {
                    'source_name': 'Local official',
                    'kind': 'local_json',
                    'path': str(local),
                    'reliability': 'official',
                    'teams': ['Arsenal'],
                    'tags': ['official'],
                },
                {
                    'source_name': 'Remote credible',
                    'kind': 'remote_json',
                    'url': 'https://example.test/feed.json',
                    'reliability': 'credible',
                    'fixture_ids': ['epl-001'],
                },
            ]
        },
    )
    calls = []

    def fake_fetch(url: str, timeout_seconds: float, max_bytes: int) -> HttpFetchResult:
        calls.append((url, timeout_seconds, max_bytes))
        return HttpFetchResult(
            status_code=200,
            content_type='application/json',
            body=json.dumps(
                {
                    'items': [
                        {
                            'title': 'Remote Arsenal team news',
                            'summary': 'Remote source says Arsenal trained normally.',
                            'fixture_ids': ['epl-001'],
                        }
                    ]
                }
            ),
        )

    provider = LiveInformationProvider(
        manifest_path=manifest,
        cache_dir=tmp_path / 'cache',
        live_fetch=True,
        fetcher=fake_fetch,
    )
    digest = FixtureInformationService(provider=provider).build_digest(
        fixture_id='epl-001',
        home_team='Arsenal',
    )

    assert calls[0][0] == 'https://example.test/feed.json'
    assert digest.status == 'complete'
    assert {item.source_name for item in digest.items} == {'Local official', 'Remote credible'}
    assert {item.reliability for item in digest.items} == {
        InformationReliability.OFFICIAL,
        InformationReliability.CREDIBLE,
    }


def test_live_information_provider_warns_for_bad_sources(tmp_path: Path) -> None:
    local = _write_json(
        tmp_path,
        {
            'items': [
                {
                    'title': 'Valid Arsenal note',
                    'summary': 'Arsenal.',
                    'fixture_ids': ['epl-001'],
                }
            ]
        },
    )
    manifest = _write_manifest(
        tmp_path,
        {
            'sources': [
                {'source_name': 'Valid', 'kind': 'local_json', 'path': str(local)},
                {
                    'source_name': 'Disabled',
                    'kind': 'local_json',
                    'path': str(local),
                    'enabled': False,
                },
                {'source_name': 'Broken remote', 'kind': 'remote_rss'},
            ]
        },
    )

    provider = LiveInformationProvider(manifest_path=manifest, cache_dir=tmp_path / 'cache')
    digest = FixtureInformationService(provider=provider).build_digest(fixture_id='epl-001')

    assert digest.status == 'partial'
    assert [item.source_name for item in digest.items] == ['Valid']
    assert any('missing url' in warning for warning in digest.warnings)


def test_live_information_provider_preserves_local_sample_without_manifest() -> None:
    digest = FixtureInformationService(provider=LocalInformationProvider()).build_digest(
        fixture_id='epl-001',
        home_team='Arsenal',
        away_team='Tottenham Hotspur',
    )

    assert digest.status == 'complete'
    assert len(digest.items) == 3


def test_live_information_provider_does_not_fetch_remote_without_live_flag(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        {
            'sources': [
                {
                    'source_name': 'Remote RSS',
                    'kind': 'remote_rss',
                    'url': 'https://example.test/rss.xml',
                    'fixture_ids': ['epl-001'],
                }
            ]
        },
    )

    def forbidden_fetch(url: str, timeout_seconds: float, max_bytes: int) -> HttpFetchResult:
        raise AssertionError('remote fetch should not be called')

    provider = LiveInformationProvider(
        manifest_path=manifest,
        cache_dir=tmp_path / 'cache',
        live_fetch=False,
        fetcher=forbidden_fetch,
    )
    digest = FixtureInformationService(provider=provider).build_digest(fixture_id='epl-001')

    assert digest.status == 'unavailable'
    assert digest.items == []
    assert any('remote fetch disabled' in warning for warning in digest.warnings)


def test_live_information_provider_fetches_remote_rss_and_writes_cache(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        {
            'sources': [
                {
                    'source_name': 'Club RSS',
                    'kind': 'remote_rss',
                    'url': 'https://example.test/rss.xml',
                    'reliability': 'official',
                    'teams': ['Arsenal'],
                }
            ]
        },
    )

    def fake_fetch(url: str, timeout_seconds: float, max_bytes: int) -> HttpFetchResult:
        return HttpFetchResult(
            status_code=200,
            content_type='application/rss+xml',
            body=(
                '<rss><channel><title>Club RSS</title><item>'
                '<title>Arsenal team news</title>'
                '<link>https://example.test/item</link>'
                '<description>Arsenal lineup confirmed.</description>'
                '<pubDate>Sun, 26 Apr 2026 09:00:00 GMT</pubDate>'
                '</item></channel></rss>'
            ),
        )

    cache_dir = tmp_path / 'cache'
    provider = LiveInformationProvider(
        manifest_path=manifest,
        cache_dir=cache_dir,
        live_fetch=True,
        fetcher=fake_fetch,
    )
    digest = FixtureInformationService(provider=provider).build_digest(
        fixture_id='epl-001',
        home_team='Arsenal',
    )

    assert digest.status == 'complete'
    assert digest.items[0].source_name == 'Club RSS'
    assert digest.items[0].reliability == InformationReliability.OFFICIAL
    assert list(cache_dir.glob('*.json'))


def test_live_information_provider_uses_fresh_cache_without_fetch(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        {
            'cache_ttl_seconds': 3600,
            'sources': [
                {
                    'source_name': 'Cached JSON',
                    'kind': 'remote_json',
                    'url': 'https://example.test/feed.json',
                    'fixture_ids': ['epl-001'],
                }
            ],
        },
    )
    provider = LiveInformationProvider(manifest_path=manifest, cache_dir=tmp_path / 'cache')
    provider.write_cache_entry(
        'https://example.test/feed.json',
        HttpFetchResult(
            status_code=200,
            content_type='application/json',
            body=json.dumps(
                {
                    'items': [
                        {
                            'title': 'Cached Arsenal note',
                            'summary': 'Cached.',
                            'fixture_ids': ['epl-001'],
                        }
                    ]
                }
            ),
        ),
        fetched_at=datetime.now(UTC).replace(microsecond=0),
    )

    def forbidden_fetch(url: str, timeout_seconds: float, max_bytes: int) -> HttpFetchResult:
        raise AssertionError('fresh cache should avoid fetch')

    provider = LiveInformationProvider(
        manifest_path=manifest,
        cache_dir=tmp_path / 'cache',
        fetcher=forbidden_fetch,
    )
    digest = FixtureInformationService(provider=provider).build_digest(fixture_id='epl-001')

    assert digest.status == 'complete'
    assert digest.items[0].title == 'Cached Arsenal note'
    assert digest.source_health[0].warnings == ['using fresh cache']


def test_live_information_provider_uses_stale_cache_after_fetch_failure(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        {
            'cache_ttl_seconds': 1,
            'sources': [
                {
                    'source_name': 'Stale JSON',
                    'kind': 'remote_json',
                    'url': 'https://example.test/feed.json',
                    'fixture_ids': ['epl-001'],
                }
            ],
        },
    )
    seed = LiveInformationProvider(manifest_path=manifest, cache_dir=tmp_path / 'cache')
    seed.write_cache_entry(
        'https://example.test/feed.json',
        HttpFetchResult(
            status_code=200,
            content_type='application/json',
            body=json.dumps(
                {
                    'items': [
                        {
                            'title': 'Stale Arsenal note',
                            'summary': 'Stale.',
                            'fixture_ids': ['epl-001'],
                        }
                    ]
                }
            ),
        ),
        fetched_at=datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=30),
    )

    def failing_fetch(url: str, timeout_seconds: float, max_bytes: int) -> HttpFetchResult:
        raise TimeoutError('timed out')

    provider = LiveInformationProvider(
        manifest_path=manifest,
        cache_dir=tmp_path / 'cache',
        live_fetch=True,
        fetcher=failing_fetch,
    )
    digest = FixtureInformationService(provider=provider).build_digest(fixture_id='epl-001')

    assert digest.status == 'partial'
    assert digest.items[0].title == 'Stale Arsenal note'
    assert any('using stale cache after fetch failure' in warning for warning in digest.warnings)


def test_live_information_provider_reports_remote_failures(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        {
            'sources': [
                {
                    'source_name': 'Huge JSON',
                    'kind': 'remote_json',
                    'url': 'https://example.test/huge.json',
                    'max_bytes': 5,
                },
                {
                    'source_name': 'Bad RSS',
                    'kind': 'remote_rss',
                    'url': 'https://example.test/bad.xml',
                },
            ]
        },
    )

    def fake_fetch(url: str, timeout_seconds: float, max_bytes: int) -> HttpFetchResult:
        if url.endswith('huge.json'):
            return HttpFetchResult(
                status_code=200,
                content_type='application/json',
                body='x' * 10,
            )
        raise TimeoutError('timed out')

    provider = LiveInformationProvider(
        manifest_path=manifest,
        cache_dir=tmp_path / 'cache',
        live_fetch=True,
        fetcher=fake_fetch,
    )
    digest = FixtureInformationService(provider=provider).build_digest(fixture_id='epl-001')

    assert digest.status == 'unavailable'
    assert digest.items == []
    assert any('exceeded max bytes' in warning for warning in digest.warnings)
    assert any('timed out' in warning for warning in digest.warnings)


def test_live_information_source_defaults_do_not_retag_explicit_fixture(tmp_path: Path) -> None:
    local = _write_json(
        tmp_path,
        {
            'items': [
                {
                    'title': 'Arsenal valid note',
                    'summary': 'Applies to Arsenal.',
                    'fixture_ids': ['epl-001'],
                    'teams': ['Arsenal'],
                },
                {
                    'title': 'Liverpool unrelated note',
                    'summary': 'Should remain unrelated.',
                    'fixture_ids': ['epl-999'],
                    'teams': ['Liverpool'],
                },
            ]
        },
    )
    manifest = _write_manifest(
        tmp_path,
        {
            'sources': [
                {
                    'source_name': 'Local source with defaults',
                    'kind': 'local_json',
                    'path': str(local),
                    'fixture_ids': ['epl-001'],
                    'teams': ['Arsenal'],
                }
            ]
        },
    )

    provider = LiveInformationProvider(manifest_path=manifest, cache_dir=tmp_path / 'cache')
    digest = FixtureInformationService(provider=provider).build_digest(
        fixture_id='epl-001',
        home_team='Arsenal',
    )

    assert [item.title for item in digest.items] == ['Arsenal valid note']
