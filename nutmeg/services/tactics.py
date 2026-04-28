from __future__ import annotations

from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Protocol

from nutmeg.domain.tactics import TacticalVisualArtifact, TacticalVisualPack


class SnapshotService(Protocol):
    def build_snapshot(
        self,
        fixture_id: str,
        *,
        recent_matches: int = 5,
        live_context: bool = True,
    ):
        ...


class TacticalVisualService:
    def __init__(self, *, snapshot_service: SnapshotService) -> None:
        self._snapshot_service = snapshot_service

    def build_pack(
        self,
        fixture_id: str,
        *,
        output_dir: Path | str | None = None,
    ) -> TacticalVisualPack:
        snapshot = self._snapshot_service.build_snapshot(
            fixture_id,
            recent_matches=5,
            live_context=False,
        )
        output_path = Path(output_dir) if output_dir is not None else None
        if output_path is not None:
            output_path.mkdir(parents=True, exist_ok=True)

        artifacts: list[TacticalVisualArtifact] = []
        unavailable: list[str] = []

        shot_map = self._shot_map_artifact(snapshot)
        if shot_map is None:
            unavailable.append('shot_map')
        else:
            artifacts.append(self._maybe_write(snapshot.fixture.fixture_id, shot_map, output_path))

        lineup_network = self._lineup_network_artifact(snapshot)
        if lineup_network is None:
            unavailable.append('lineup_network')
        else:
            artifacts.append(
                self._maybe_write(snapshot.fixture.fixture_id, lineup_network, output_path)
            )

        xg_trend = self._xg_trend_artifact(snapshot)
        if xg_trend is None:
            unavailable.append('xg_trend')
        else:
            artifacts.append(self._maybe_write(snapshot.fixture.fixture_id, xg_trend, output_path))

        return TacticalVisualPack(
            fixture=snapshot.fixture,
            generated_at=datetime.now(UTC).replace(microsecond=0),
            artifacts=artifacts,
            insights=self._insights(snapshot),
            unavailable_sections=unavailable,
        )

    def _maybe_write(
        self,
        fixture_id: str,
        artifact: TacticalVisualArtifact,
        output_dir: Path | None,
    ) -> TacticalVisualArtifact:
        if output_dir is None:
            return artifact
        filename = f"{_safe_slug(fixture_id)}-{artifact.name}.svg"
        (output_dir / filename).write_text(artifact.svg, encoding='utf-8')
        return TacticalVisualArtifact(
            name=artifact.name,
            title=artifact.title,
            status=artifact.status,
            format=artifact.format,
            svg=artifact.svg,
            source=artifact.source,
            description=artifact.description,
            path=filename,
        )

    def _shot_map_artifact(self, snapshot) -> TacticalVisualArtifact | None:
        if snapshot.home.shot_summary is None or snapshot.away.shot_summary is None:
            return None
        home = snapshot.home.shot_summary
        away = snapshot.away.shot_summary
        home_points = _shot_points(home.shots, left_to_right=True)
        away_points = _shot_points(away.shots, left_to_right=False)
        home_circles = '\n'.join(
            f'<circle cx="{x}" cy="{y}" r="3.2" fill="#d24b35" opacity="0.70" />'
            for x, y in home_points
        )
        away_circles = '\n'.join(
            f'<circle cx="{x}" cy="{y}" r="3.2" fill="#2563eb" opacity="0.70" />'
            for x, y in away_points
        )
        home_label = (
            f'{escape(snapshot.fixture.home_team)}: '
            f'{home.shots} shots, {home.total_xg:.2f} xG'
        )
        away_label = (
            f'{escape(snapshot.fixture.away_team)}: '
            f'{away.shots} shots, {away.total_xg:.2f} xG'
        )
        note = 'Aggregate proxy: deterministic density markers, not event coordinates.'
        svg = _svg_frame(
            'Shot Map Proxy',
            f'''
            {_pitch()}
            {home_circles}
            {away_circles}
            <text x="22" y="24" class="label">{home_label}</text>
            <text x="22" y="44" class="label">{away_label}</text>
            <text x="22" y="286" class="note">{note}</text>
            ''',
        )
        return TacticalVisualArtifact(
            name='shot-map',
            title='Shot Map Proxy',
            status='proxy',
            format='svg',
            svg=svg,
            source='snapshot-shot-summary',
            description='Shot map style SVG from aggregate shot counts and xG.',
        )

    def _lineup_network_artifact(self, snapshot) -> TacticalVisualArtifact | None:
        if snapshot.home.lineup is None or snapshot.away.lineup is None:
            return None
        home_nodes = _lineup_nodes(snapshot.home.lineup.players[:11], x_offset=120)
        away_nodes = _lineup_nodes(snapshot.away.lineup.players[:11], x_offset=480)
        home_svg = _network_svg(home_nodes, '#d24b35')
        away_svg = _network_svg(away_nodes, '#2563eb')
        home_label = (
            f'{escape(snapshot.fixture.home_team)} '
            f'{escape(snapshot.home.lineup.formation or "shape n/a")}'
        )
        away_label = (
            f'{escape(snapshot.fixture.away_team)} '
            f'{escape(snapshot.away.lineup.formation or "shape n/a")}'
        )
        note = 'Proxy network: nominal starter structure, not pass-event volume.'
        svg = _svg_frame(
            'Lineup Network Proxy',
            f'''
            {_pitch()}
            {home_svg}
            {away_svg}
            <text x="22" y="24" class="label">{home_label}</text>
            <text x="370" y="24" class="label">{away_label}</text>
            <text x="22" y="286" class="note">{note}</text>
            ''',
        )
        return TacticalVisualArtifact(
            name='lineup-network',
            title='Lineup Network Proxy',
            status='proxy',
            format='svg',
            svg=svg,
            source='snapshot-lineups',
            description='Lineup network proxy from confirmed or probable lineup structure.',
        )

    def _xg_trend_artifact(self, snapshot) -> TacticalVisualArtifact | None:
        matchup = snapshot.matchup
        if matchup is None or matchup.home_trend is None or matchup.away_trend is None:
            return None
        home_xg = matchup.home_trend.xg_for_per_match
        away_xg = matchup.away_trend.xg_for_per_match
        home_xga = matchup.home_trend.xg_against_per_match
        away_xga = matchup.away_trend.xg_against_per_match
        if None in (home_xg, away_xg, home_xga, away_xga):
            return None
        bars = _bar(90, 210, home_xg, '#d24b35', 'home xG') + _bar(
            220, 210, away_xg, '#2563eb', 'away xG'
        ) + _bar(350, 210, home_xga, '#f59e0b', 'home xGA') + _bar(
            480, 210, away_xga, '#10b981', 'away xGA'
        )
        svg = _svg_frame(
            'Recent xG Trend',
            f'''
            <line x1="60" y1="230" x2="620" y2="230" stroke="#1f2937" stroke-width="2" />
            {bars}
            <text x="22" y="24" class="label">{_xg_sample_label(matchup)}</text>
            <text x="22" y="286" class="note">Trend proxy from snapshot recent xG aggregates.</text>
            ''',
        )
        return TacticalVisualArtifact(
            name='xg-trend',
            title='Recent xG Trend',
            status='derived',
            format='svg',
            svg=svg,
            source='snapshot-matchup-trends',
            description='Recent xG/xGA bar visual from matchup trend context.',
        )

    def _insights(self, snapshot) -> list[str]:
        insights: list[str] = []
        matchup = snapshot.matchup
        if matchup and matchup.home_trend and matchup.away_trend:
            home_xg = matchup.home_trend.xg_for_per_match
            away_xg = matchup.away_trend.xg_for_per_match
            if home_xg is not None and away_xg is not None:
                if home_xg >= away_xg:
                    leader = snapshot.fixture.home_team
                else:
                    leader = snapshot.fixture.away_team
                insights.append(f'{leader} carry the stronger recent xG creation trend.')
        if snapshot.home.lineup and snapshot.away.lineup:
            insights.append(
                f'{snapshot.fixture.home_team} shape {snapshot.home.lineup.formation or "n/a"} '
                f'vs {snapshot.fixture.away_team} shape {snapshot.away.lineup.formation or "n/a"}.'
            )
        return insights


def _safe_slug(value: str) -> str:
    return ''.join(ch if ch.isalnum() else '-' for ch in value.lower()).strip('-')


def _svg_frame(title: str, body: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="680" height="310"
viewBox="0 0 680 310" role="img" aria-label="{escape(title)}">
<style>
.label {{ font: 13px sans-serif; fill: #111827; font-weight: 700; }}
.note {{ font: 11px sans-serif; fill: #4b5563; }}
.small {{ font: 10px sans-serif; fill: #111827; }}
</style>
<rect x="0" y="0" width="680" height="310" fill="#f8fafc" />
{body}
</svg>'''


def _pitch() -> str:
    return '''
    <rect x="40" y="60" width="600" height="200" rx="10"
      fill="#dff3df" stroke="#2f7d32" stroke-width="2" />
    <line x1="340" y1="60" x2="340" y2="260"
      stroke="#2f7d32" stroke-width="1.5" />
    <circle cx="340" cy="160" r="34" fill="none"
      stroke="#2f7d32" stroke-width="1.5" />
    <rect x="40" y="105" width="70" height="110" fill="none"
      stroke="#2f7d32" stroke-width="1.5" />
    <rect x="570" y="105" width="70" height="110" fill="none"
      stroke="#2f7d32" stroke-width="1.5" />
    '''


def _shot_points(count: int, *, left_to_right: bool) -> list[tuple[int, int]]:
    points = []
    capped = max(0, min(count, 24))
    base_x = 520 if left_to_right else 160
    for index in range(capped):
        x = base_x + ((index % 4) * 14 * (1 if left_to_right else -1))
        y = 95 + ((index * 23) % 130)
        points.append((x, y))
    return points


def _lineup_nodes(players, *, x_offset: int) -> list[tuple[int, int, str]]:
    rows = [1, 4, 3, 3]
    nodes = []
    index = 0
    for row_index, row_count in enumerate(rows):
        x = x_offset + (row_index * 42 if x_offset < 340 else -row_index * 42)
        gap = 150 / max(row_count, 1)
        for item in range(row_count):
            if index >= len(players):
                break
            y = int(88 + (item + 0.5) * gap)
            label = players[index].shirt_number or str(index + 1)
            nodes.append((x, y, label))
            index += 1
    return nodes


def _network_svg(nodes: list[tuple[int, int, str]], color: str) -> str:
    if not nodes:
        return ''
    lines = []
    for left, right in zip(nodes, nodes[1:], strict=False):
        lines.append(
            '<line '
            f'x1="{left[0]}" y1="{left[1]}" '
            f'x2="{right[0]}" y2="{right[1]}" '
            f'stroke="{color}" stroke-width="1.2" opacity="0.35" />'
        )
    circles = [
        f'<circle cx="{x}" cy="{y}" r="9" fill="{color}" opacity="0.85" />'
        f'<text x="{x - 4}" y="{y + 4}" class="small" fill="#fff">'
        f'{escape(label)}</text>'
        for x, y, label in nodes
    ]
    return '\n'.join([*lines, *circles])


def _xg_sample_label(matchup) -> str:
    return (
        'Recent xG trend, sample '
        f'{matchup.home_trend.sample_size} / {matchup.away_trend.sample_size}'
    )


def _bar(x: int, baseline: int, value: float, color: str, label: str) -> str:
    height = int(min(max(value, 0), 3.5) * 45)
    y = baseline - height
    return (
        f'<rect x="{x}" y="{y}" width="70" height="{height}" fill="{color}" opacity="0.82" />'
        f'<text x="{x}" y="{baseline + 18}" class="small">{escape(label)}</text>'
        f'<text x="{x}" y="{y - 6}" class="small">{value:.2f}</text>'
    )
