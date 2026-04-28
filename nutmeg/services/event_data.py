from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nutmeg.domain.event_data import (
    EventDataQuality,
    EventTacticalReport,
    EventVisualArtifact,
    FootballEvent,
    PassNetwork,
    PlayerContributionSummary,
    SpatialValueSummary,
)

PITCH_LENGTH = 120
PITCH_WIDTH = 80


class LocalEventDataProvider:
    def __init__(
        self,
        *,
        sample_dir: Path | None = None,
        provider: str = 'statsbomb-open-local',
    ) -> None:
        self.sample_dir = sample_dir or Path(__file__).parents[1] / 'event_data' / 'samples'
        self.provider = provider

    def load_fixture_events(
        self,
        fixture_id: str,
        *,
        events_file: str | Path | None = None,
    ) -> tuple[list[FootballEvent], EventDataQuality]:
        path = (
            Path(events_file)
            if events_file is not None
            else self.sample_dir / f'{fixture_id}-events.json'
        )
        generated_at = datetime.now(UTC).replace(microsecond=0)
        if not path.exists():
            return [], self._quality(
                fixture_id=fixture_id,
                status='unavailable',
                warnings=[f'event data file not found: {path}'],
                generated_at=generated_at,
            )
        try:
            raw = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            return [], self._quality(
                fixture_id=fixture_id,
                status='unavailable',
                warnings=[f'malformed event data: {exc.msg}'],
                generated_at=generated_at,
            )
        records = raw.get('events') if isinstance(raw, dict) else raw
        if not isinstance(records, list) or not records:
            return [], self._quality(
                fixture_id=fixture_id,
                status='unavailable',
                warnings=['event data unavailable or empty'],
                generated_at=generated_at,
            )

        warnings: list[str] = []
        events = [
            event
            for index, record in enumerate(records)
            if isinstance(record, dict)
            if (event := self._normalize_event(fixture_id, record, index, warnings)) is not None
        ]
        if not events:
            return [], self._quality(
                fixture_id=fixture_id,
                status='unavailable',
                warnings=[*warnings, 'no events matched fixture id'],
                generated_at=generated_at,
            )
        teams = sorted({event.team for event in events if event.team})
        players = sorted({event.player for event in events if event.player})
        return events, EventDataQuality(
            fixture_id=fixture_id,
            provider=self.provider,
            status='partial' if warnings else 'complete',
            event_count=len(events),
            teams=teams,
            players=players,
            warnings=warnings,
            generated_at=generated_at,
        )

    def _quality(
        self,
        *,
        fixture_id: str,
        status: str,
        warnings: list[str],
        generated_at: datetime,
    ) -> EventDataQuality:
        return EventDataQuality(
            fixture_id=fixture_id,
            provider=self.provider,
            status=status,
            event_count=0,
            teams=[],
            players=[],
            warnings=warnings,
            generated_at=generated_at,
        )

    def _normalize_event(
        self,
        fixture_id: str,
        record: dict[str, Any],
        index: int,
        warnings: list[str],
    ) -> FootballEvent | None:
        record_fixture_id = record.get('fixture_id')
        if record_fixture_id is not None and str(record_fixture_id) != fixture_id:
            return None
        event_type = (
            (_name(record.get('type') or record.get('event_type')) or 'unknown')
            .casefold()
            .replace(' ', '_')
        )
        location = _location(record.get('location'), record.get('x'), record.get('y'), warnings)
        nested = record.get(event_type) if isinstance(record.get(event_type), dict) else {}
        if event_type == 'pass':
            nested = record.get('pass') if isinstance(record.get('pass'), dict) else nested
        if event_type == 'carry':
            nested = record.get('carry') if isinstance(record.get('carry'), dict) else nested
        end_location = _location(
            nested.get('end_location') if isinstance(nested, dict) else None,
            record.get('end_x'),
            record.get('end_y'),
            warnings,
        )
        xg = _shot_xg(record)
        metadata = _metadata(record)
        if event_type == 'pass':
            recipient = _name((record.get('pass') or {}).get('recipient'))
            if recipient:
                metadata['recipient'] = recipient
        return FootballEvent(
            event_id=str(record.get('id') or record.get('event_id') or f'{fixture_id}-{index + 1}'),
            fixture_id=fixture_id,
            provider=self.provider,
            team=_name(record.get('team')),
            player=_name(record.get('player')),
            event_type=event_type or 'unknown',
            period=int(record.get('period') or 1),
            minute=int(record.get('minute') or 0),
            second=int(record.get('second') or 0),
            x=location[0],
            y=location[1],
            end_x=end_location[0],
            end_y=end_location[1],
            outcome=_outcome(record, event_type),
            xg=xg,
            metadata=metadata,
        )


class EventTacticalModelService:
    def __init__(self, *, event_provider: LocalEventDataProvider | None = None) -> None:
        self._event_provider = event_provider or LocalEventDataProvider()

    def build_report(
        self,
        *,
        fixture_id: str,
        events_file: str | Path | None = None,
        output_dir: str | Path | None = None,
    ) -> EventTacticalReport:
        events, quality = self._event_provider.load_fixture_events(
            fixture_id,
            events_file=events_file,
        )
        if not events:
            return EventTacticalReport.empty(fixture_id=fixture_id, quality=quality)

        pass_network = _build_pass_network(events)
        spatial_value = _build_spatial_value(events)
        player_contributions = _build_player_contributions(events, spatial_value)
        unavailable_sections = []
        if not pass_network.edges:
            unavailable_sections.append('pass_network')
        if not spatial_value.actions:
            unavailable_sections.append('spatial_value')
        if not player_contributions.players:
            unavailable_sections.append('player_contributions')
        warnings = [
            *quality.warnings,
            *pass_network.warnings,
            *spatial_value.warnings,
            *player_contributions.warnings,
        ]
        artifacts = _build_artifacts(
            fixture_id=fixture_id,
            pass_network=pass_network,
            spatial_value=spatial_value,
            player_contributions=player_contributions,
            output_dir=Path(output_dir) if output_dir is not None else None,
        )
        return EventTacticalReport(
            fixture_id=fixture_id,
            quality=quality,
            pass_network=pass_network,
            spatial_value=spatial_value,
            player_contributions=player_contributions,
            artifacts=artifacts,
            unavailable_sections=unavailable_sections,
            warnings=warnings,
        )


def _build_pass_network(events: list[FootballEvent]) -> PassNetwork:
    node_locations: dict[tuple[str | None, str], list[tuple[float, float]]] = defaultdict(list)
    edge_locations: dict[tuple[str | None, str, str], list[tuple[float, float, float, float]]] = (
        defaultdict(list)
    )
    for event in events:
        if (
            event.event_type != 'pass'
            or event.outcome != 'complete'
            or event.x is None
            or event.y is None
            or event.end_x is None
            or event.end_y is None
            or not event.player
        ):
            continue
        recipient = event.metadata.get('recipient')
        if not recipient:
            continue
        node_locations[(event.team, event.player)].append((event.x, event.y))
        node_locations[(event.team, str(recipient))].append((event.end_x, event.end_y))
        edge_locations[(event.team, event.player, str(recipient))].append(
            (event.x, event.y, event.end_x, event.end_y)
        )
    nodes = [
        {
            'team': team,
            'player': player,
            'avg_x': round(sum(x for x, _y in values) / len(values), 2),
            'avg_y': round(sum(y for _x, y in values) / len(values), 2),
            'touch_count': len(values),
        }
        for (team, player), values in node_locations.items()
    ]
    edges = [
        {
            'team': team,
            'from_player': from_player,
            'to_player': to_player,
            'pass_count': len(values),
            'avg_start_x': round(sum(x1 for x1, _y1, _x2, _y2 in values) / len(values), 2),
            'avg_start_y': round(sum(y1 for _x1, y1, _x2, _y2 in values) / len(values), 2),
            'avg_end_x': round(sum(x2 for _x1, _y1, x2, _y2 in values) / len(values), 2),
            'avg_end_y': round(sum(y2 for _x1, _y1, _x2, y2 in values) / len(values), 2),
        }
        for (team, from_player, to_player), values in edge_locations.items()
    ]
    nodes.sort(key=lambda item: (str(item['team']), str(item['player'])))
    edges.sort(key=lambda item: (-int(item['pass_count']), str(item['from_player'])))
    warnings = [] if edges else ['completed pass data is too sparse for pass network']
    return PassNetwork(nodes=nodes, edges=edges, warnings=warnings)


def _build_spatial_value(events: list[FootballEvent]) -> SpatialValueSummary:
    grid = [
        {'zone_x': zone_x, 'zone_y': zone_y, 'value': _zone_value(zone_x, zone_y)}
        for zone_y in range(8)
        for zone_x in range(12)
    ]
    actions = []
    player_totals: dict[tuple[str | None, str], float] = defaultdict(float)
    for event in events:
        if (
            event.event_type not in {'pass', 'carry'}
            or event.outcome != 'complete'
            or event.x is None
            or event.y is None
            or event.end_x is None
            or event.end_y is None
            or not event.player
        ):
            continue
        start_zone = _zone_for(event.x, event.y)
        end_zone = _zone_for(event.end_x, event.end_y)
        delta = round(_zone_value(*end_zone) - _zone_value(*start_zone), 4)
        if delta == 0:
            continue
        actions.append(
            {
                'event_id': event.event_id,
                'team': event.team,
                'player': event.player,
                'event_type': event.event_type,
                'start_zone': {'zone_x': start_zone[0], 'zone_y': start_zone[1]},
                'end_zone': {'zone_x': end_zone[0], 'zone_y': end_zone[1]},
                'value_delta': delta,
            }
        )
        player_totals[(event.team, event.player)] += delta
    players = [
        {'team': team, 'player': player, 'xt_lite': round(value, 4)}
        for (team, player), value in player_totals.items()
    ]
    players.sort(key=lambda item: (-float(item['xt_lite']), str(item['player'])))
    warnings = ['xT-lite-v0 is deterministic heuristic, not trained xT.']
    if not actions:
        warnings.append('successful progressive pass/carry data is unavailable')
    return SpatialValueSummary(grid=grid, actions=actions, players=players, warnings=warnings)


def _build_player_contributions(
    events: list[FootballEvent],
    spatial_value: SpatialValueSummary,
) -> PlayerContributionSummary:
    totals: dict[tuple[str | None, str], dict[str, float]] = defaultdict(
        lambda: {'offensive_value': 0.0, 'defensive_value': 0.0, 'xg': 0.0, 'xt': 0.0}
    )
    for player in spatial_value.players:
        key = (player.get('team'), str(player.get('player')))
        xt = float(player.get('xt_lite') or 0.0)
        totals[key]['xt'] += xt
        totals[key]['offensive_value'] += max(xt, 0.0)
    for event in events:
        if not event.player:
            continue
        key = (event.team, event.player)
        if event.event_type == 'shot' and event.xg is not None:
            shot_value = float(event.xg) + (0.2 if event.outcome == 'goal' else 0.0)
            totals[key]['xg'] += float(event.xg)
            totals[key]['offensive_value'] += shot_value
        if event.event_type in {'interception', 'tackle', 'duel'} and event.outcome in {
            'won',
            'success',
            'complete',
        }:
            totals[key]['defensive_value'] += 0.03
    players = [
        {
            'team': team,
            'player': player,
            'offensive_value': round(values['offensive_value'], 4),
            'defensive_value': round(values['defensive_value'], 4),
            'xg': round(values['xg'], 4),
            'xt_lite': round(values['xt'], 4),
            'total_value': round(values['offensive_value'] + values['defensive_value'], 4),
        }
        for (team, player), values in totals.items()
        if values['offensive_value'] or values['defensive_value']
    ]
    players.sort(key=lambda item: (-float(item['total_value']), str(item['player'])))
    warnings = ['VAEP-lite-heuristic-v0 is not trained VAEP; use as directional context only.']
    if not players:
        warnings.append('event data is too sparse for VAEP-lite contributions')
    return PlayerContributionSummary(players=players, warnings=warnings)


def _build_artifacts(
    *,
    fixture_id: str,
    pass_network: PassNetwork,
    spatial_value: SpatialValueSummary,
    player_contributions: PlayerContributionSummary,
    output_dir: Path | None,
) -> list[EventVisualArtifact]:
    specs: list[tuple[str, str, str, str, str]] = []
    if pass_network.edges:
        specs.append(
            (
                'pass-network',
                'Pass Network',
                'pass_network',
                'Completed pass network from event data.',
                _pass_network_svg(pass_network),
            )
        )
    if spatial_value.actions:
        specs.append(
            (
                'xt-heatmap',
                'xT-lite Heatmap',
                'xt_heatmap',
                'Deterministic xT-lite zone values and action deltas.',
                _xt_heatmap_svg(spatial_value),
            )
        )
    if player_contributions.players:
        specs.append(
            (
                'contribution-bars',
                'VAEP-lite Contributions',
                'contribution_bars',
                'Heuristic player contribution bars from event data.',
                _contribution_svg(player_contributions),
            )
        )
    if output_dir is not None and specs:
        output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for suffix, title, kind, description, svg in specs:
        file_path = None
        if output_dir is not None:
            path = output_dir / f'{fixture_id}-{suffix}.svg'
            path.write_text(svg)
            file_path = str(path)
        artifacts.append(
            EventVisualArtifact(
                artifact_id=f'{fixture_id}-{suffix}',
                title=title,
                kind=kind,
                description=description,
                svg=svg,
                file_path=file_path,
            )
        )
    return artifacts


def _pass_network_svg(pass_network: PassNetwork) -> str:
    lines = []
    for edge in pass_network.edges:
        lines.append(
            '<line '
            f'x1="{edge["avg_start_x"]}" y1="{edge["avg_start_y"]}" '
            f'x2="{edge["avg_end_x"]}" y2="{edge["avg_end_y"]}" '
            'stroke="#0f6b4f" stroke-width="2" opacity="0.7" />'
        )
    nodes = [
        f'<circle cx="{node["avg_x"]}" cy="{node["avg_y"]}" r="3" fill="#b24125" />'
        for node in pass_network.nodes
    ]
    return _svg('\n'.join([*lines, *nodes]))


def _xt_heatmap_svg(spatial_value: SpatialValueSummary) -> str:
    rects = []
    for zone in spatial_value.grid:
        value = float(zone['value'])
        green = min(180, 40 + int(value * 420))
        rects.append(
            f'<rect x="{zone["zone_x"] * 10}" y="{zone["zone_y"] * 10}" '
            f'width="10" height="10" fill="rgb(20,{green},90)" opacity="0.78" />'
        )
    return _svg('\n'.join(rects))


def _contribution_svg(summary: PlayerContributionSummary) -> str:
    bars = []
    for index, player in enumerate(summary.players[:6]):
        width = max(2, int(float(player['total_value']) * 180))
        y = 8 + index * 11
        bars.append(f'<rect x="4" y="{y}" width="{width}" height="7" fill="#0f6b4f" />')
        bars.append(
            f'<text x="{width + 8}" y="{y + 6}" font-size="5" fill="#251810">'
            f'{player["player"]}</text>'
        )
    return _svg('\n'.join(bars))


def _svg(body: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 80" '
        'role="img" aria-label="Nutmeg event tactical model">'
        '<rect width="120" height="80" fill="#fffaf0" />'
        f'{body}</svg>'
    )


def _zone_for(x: float, y: float) -> tuple[int, int]:
    return min(11, max(0, int(x // 10))), min(7, max(0, int(y // 10)))


def _zone_value(zone_x: int, zone_y: int) -> float:
    x_factor = ((zone_x + 0.5) / 12) ** 1.7
    centrality = 1 - abs((zone_y + 0.5) - 4) / 8
    return round(x_factor * (0.75 + 0.25 * centrality), 4)


def _name(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return str(value.get('name') or value.get('id') or '').strip() or None
    return str(value).strip() or None


def _location(
    value: Any,
    x_value: Any,
    y_value: Any,
    warnings: list[str],
) -> tuple[float | None, float | None]:
    if isinstance(value, list | tuple) and len(value) >= 2:
        x_value, y_value = value[0], value[1]
    if x_value is None or y_value is None:
        return None, None
    x = _number(x_value)
    y = _number(y_value)
    if x is None or y is None:
        return None, None
    clamped_x = min(PITCH_LENGTH, max(0.0, x))
    clamped_y = min(PITCH_WIDTH, max(0.0, y))
    if not math.isclose(x, clamped_x) or not math.isclose(y, clamped_y):
        warnings.append('coordinate outside 120x80 pitch was clamped')
    return clamped_x, clamped_y


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _outcome(record: dict[str, Any], event_type: str) -> str:
    if 'outcome' in record:
        return (_name(record.get('outcome')) or 'unknown').casefold().replace(' ', '_')
    nested = record.get(event_type)
    if event_type == 'pass':
        nested = record.get('pass')
        if isinstance(nested, dict) and not nested.get('outcome'):
            return 'complete'
    if event_type == 'carry':
        return 'complete'
    if event_type == 'shot':
        nested = record.get('shot')
    if isinstance(nested, dict):
        return (_name(nested.get('outcome')) or 'unknown').casefold().replace(' ', '_')
    return 'unknown'


def _shot_xg(record: dict[str, Any]) -> float | None:
    shot = record.get('shot')
    if isinstance(shot, dict):
        return _number(shot.get('statsbomb_xg') or shot.get('xg'))
    return _number(record.get('xg'))


def _metadata(record: dict[str, Any]) -> dict[str, Any]:
    standard = {
        'id',
        'event_id',
        'fixture_id',
        'period',
        'minute',
        'second',
        'type',
        'event_type',
        'team',
        'player',
        'location',
        'x',
        'y',
        'end_x',
        'end_y',
        'outcome',
        'xg',
        'pass',
        'shot',
        'carry',
        'duel',
        'interception',
        'tackle',
    }
    return {key: value for key, value in record.items() if key not in standard}
