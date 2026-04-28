from __future__ import annotations

import json
from pathlib import Path

from nutmeg.domain.event_data import (
    EventDataQuality,
    EventTacticalReport,
    FootballEvent,
)
from nutmeg.services.event_data import EventTacticalModelService, LocalEventDataProvider


def _write_events(tmp_path: Path, events: list[dict]) -> Path:
    path = tmp_path / 'events.json'
    path.write_text(json.dumps(events))
    return path


def _seed_events() -> list[dict]:
    return [
        {
            'id': 'p1',
            'fixture_id': 'epl-001',
            'period': 1,
            'minute': 3,
            'second': 4,
            'type': {'name': 'Pass'},
            'team': {'name': 'Arsenal'},
            'player': {'name': 'Arsenal 6'},
            'location': [30, 40],
            'pass': {'recipient': {'name': 'Arsenal 8'}, 'end_location': [50, 42]},
            'custom_provider_field': {'kept': True},
        },
        {
            'id': 'p2',
            'fixture_id': 'epl-001',
            'period': 1,
            'minute': 3,
            'second': 9,
            'type': {'name': 'Pass'},
            'team': {'name': 'Arsenal'},
            'player': {'name': 'Arsenal 8'},
            'location': [50, 42],
            'pass': {'recipient': {'name': 'Arsenal 10'}, 'end_location': [78, 35]},
        },
        {
            'id': 'c1',
            'fixture_id': 'epl-001',
            'period': 1,
            'minute': 3,
            'second': 14,
            'type': {'name': 'Carry'},
            'team': {'name': 'Arsenal'},
            'player': {'name': 'Arsenal 10'},
            'location': [78, 35],
            'carry': {'end_location': [96, 33]},
        },
        {
            'id': 's1',
            'fixture_id': 'epl-001',
            'period': 1,
            'minute': 3,
            'second': 18,
            'type': {'name': 'Shot'},
            'team': {'name': 'Arsenal'},
            'player': {'name': 'Arsenal 9'},
            'location': [103, 34],
            'shot': {'statsbomb_xg': 0.23, 'outcome': {'name': 'Saved'}},
        },
        {
            'id': 'd1',
            'fixture_id': 'epl-001',
            'period': 1,
            'minute': 8,
            'second': 1,
            'type': {'name': 'Interception'},
            'team': {'name': 'Tottenham Hotspur'},
            'player': {'name': 'Spurs 6'},
            'location': [62, 38],
            'interception': {'outcome': {'name': 'Won'}},
        },
    ]


def test_event_data_domain_serializes_report_contract() -> None:
    event = FootballEvent(
        event_id='e1',
        fixture_id='epl-001',
        provider='test-provider',
        team='Arsenal',
        player='Arsenal 6',
        event_type='pass',
        period=1,
        minute=2,
        second=10,
        x=34.0,
        y=42.0,
        end_x=48.0,
        end_y=39.0,
        outcome='complete',
        metadata={'recipient': 'Arsenal 8'},
    )
    quality = EventDataQuality(
        fixture_id='epl-001',
        provider='test-provider',
        status='complete',
        event_count=1,
        teams=['Arsenal'],
        players=['Arsenal 6'],
        warnings=[],
    )
    report = EventTacticalReport.empty(fixture_id='epl-001', quality=quality)

    assert event.to_dict()['end_x'] == 48.0
    assert report.to_dict()['quality']['status'] == 'complete'
    assert report.to_dict()['pass_network']['model_label'] == 'pass-network-from-events-v0'


def test_local_event_provider_discovers_bundled_sample() -> None:
    provider = LocalEventDataProvider()

    events, quality = provider.load_fixture_events('epl-001')

    assert quality.status == 'complete'
    assert quality.event_count >= 10
    assert events[0].fixture_id == 'epl-001'


def test_local_event_provider_normalizes_statsbomb_like_records(tmp_path: Path) -> None:
    provider = LocalEventDataProvider()
    path = _write_events(tmp_path, _seed_events())

    events, quality = provider.load_fixture_events('epl-001', events_file=path)

    assert quality.status == 'complete'
    assert len(events) == 5
    assert {event.event_type for event in events} >= {'pass', 'shot', 'carry', 'interception'}
    assert events[0].team == 'Arsenal'
    assert events[0].player == 'Arsenal 6'
    assert events[0].end_x == 50
    assert events[0].outcome == 'complete'
    assert events[3].xg == 0.23


def test_local_event_provider_unavailable_quality_for_missing_empty_and_malformed(
    tmp_path: Path,
) -> None:
    provider = LocalEventDataProvider()
    empty = tmp_path / 'empty.json'
    empty.write_text('[]')
    malformed = tmp_path / 'malformed.json'
    malformed.write_text('{not-json')

    missing_events, missing_quality = provider.load_fixture_events(
        'epl-001',
        events_file=tmp_path / 'missing.json',
    )
    empty_events, empty_quality = provider.load_fixture_events('epl-001', events_file=empty)
    bad_events, bad_quality = provider.load_fixture_events('epl-001', events_file=malformed)

    assert missing_events == []
    assert empty_events == []
    assert bad_events == []
    assert missing_quality.status == 'unavailable'
    assert empty_quality.status == 'unavailable'
    assert bad_quality.status == 'unavailable'
    assert any('malformed' in warning for warning in bad_quality.warnings)


def test_local_event_provider_preserves_unknown_fields_in_metadata(tmp_path: Path) -> None:
    provider = LocalEventDataProvider()
    path = _write_events(tmp_path, _seed_events())

    events, _quality = provider.load_fixture_events('epl-001', events_file=path)

    assert events[0].metadata['custom_provider_field'] == {'kept': True}
    assert events[0].metadata['recipient'] == 'Arsenal 8'


def test_event_tactical_service_builds_pass_network_from_completed_passes(tmp_path: Path) -> None:
    service = EventTacticalModelService(event_provider=LocalEventDataProvider())
    path = _write_events(tmp_path, _seed_events())

    report = service.build_report(fixture_id='epl-001', events_file=path)

    assert report.pass_network.model_label == 'pass-network-from-events-v0'
    assert len(report.pass_network.nodes) >= 3
    assert report.pass_network.edges[0]['pass_count'] == 1
    assert report.pass_network.edges[0]['from_player'] == 'Arsenal 6'
    assert report.pass_network.edges[0]['to_player'] == 'Arsenal 8'


def test_event_tactical_service_computes_xt_lite_progression(tmp_path: Path) -> None:
    service = EventTacticalModelService(event_provider=LocalEventDataProvider())
    path = _write_events(tmp_path, _seed_events())

    report = service.build_report(fixture_id='epl-001', events_file=path)

    assert report.spatial_value.model_label == 'xT-lite-v0'
    assert report.spatial_value.pitch == {'length': 120, 'width': 80}
    assert report.spatial_value.actions
    assert report.spatial_value.actions[0]['value_delta'] > 0
    assert report.spatial_value.players[0]['player'] in {'Arsenal 10', 'Arsenal 8', 'Arsenal 6'}


def test_event_tactical_service_computes_vaep_lite_with_warning(tmp_path: Path) -> None:
    service = EventTacticalModelService(event_provider=LocalEventDataProvider())
    path = _write_events(tmp_path, _seed_events())

    report = service.build_report(fixture_id='epl-001', events_file=path)

    assert report.player_contributions.model_label == 'VAEP-lite-heuristic-v0'
    assert report.player_contributions.players[0]['total_value'] > 0
    assert any('not trained VAEP' in warning for warning in report.player_contributions.warnings)


def test_event_tactical_service_reports_sparse_data_without_fabricating_sections(
    tmp_path: Path,
) -> None:
    service = EventTacticalModelService(event_provider=LocalEventDataProvider())
    path = _write_events(tmp_path, [])

    report = service.build_report(fixture_id='epl-001', events_file=path)

    assert report.quality.status == 'unavailable'
    assert report.quality.event_count == 0
    assert 'pass_network' in report.unavailable_sections
    assert report.pass_network.nodes == []
    assert report.artifacts == []


def test_event_tactical_service_writes_deterministic_svg_artifacts(tmp_path: Path) -> None:
    service = EventTacticalModelService(event_provider=LocalEventDataProvider())
    events_file = _write_events(tmp_path, _seed_events())
    output_dir = tmp_path / 'artifacts'

    report = service.build_report(
        fixture_id='epl-001',
        events_file=events_file,
        output_dir=output_dir,
    )

    assert {artifact.kind for artifact in report.artifacts} == {
        'pass_network',
        'xt_heatmap',
        'contribution_bars',
    }
    assert all(artifact.svg.startswith('<svg') for artifact in report.artifacts)
    assert all(artifact.file_path for artifact in report.artifacts)
    assert (output_dir / 'epl-001-pass-network.svg').read_text().startswith('<svg')
