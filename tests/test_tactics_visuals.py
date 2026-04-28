from __future__ import annotations

from datetime import UTC, datetime

from nutmeg.domain.fixtures import Fixture, FixtureStatus
from nutmeg.domain.snapshot import (
    FixtureSnapshot,
    LineupPlayer,
    MatchupTrendContext,
    TeamEnrichment,
    TeamLineup,
    TeamShotSummary,
    TeamTrendSummary,
)
from nutmeg.services.tactics import TacticalVisualService


def _fixture() -> Fixture:
    return Fixture(
        fixture_id='fx-visual',
        league_code='epl',
        provider_league_id=39,
        season=2025,
        kickoff_at=datetime(2026, 4, 25, 15, 0, tzinfo=UTC),
        home_team_id=1,
        away_team_id=2,
        home_team='Arsenal',
        away_team='Tottenham Hotspur',
        source='test',
        status=FixtureStatus.SCHEDULED,
    )


def _team(name: str, *, with_context: bool = True) -> TeamEnrichment:
    return TeamEnrichment(
        canonical_name=name,
        source_names={'test': name},
        season_metrics=None,
        recent_form=None,
        shot_summary=TeamShotSummary(
            shots=12,
            goals=2,
            total_xg=1.8,
            open_play_shots=9,
        )
        if with_context
        else None,
        market_value=None,
        injuries=[],
        lineup=TeamLineup(
            status='probable',
            source='test-lineups',
            formation='4-3-3',
            players=[
                LineupPlayer(
                    player_name=f'{name} Player {index}',
                    position='M',
                    shirt_number=str(index),
                    role='starter',
                    captain=index == 1,
                )
                for index in range(1, 12)
            ],
        )
        if with_context
        else None,
    )


def _snapshot(*, with_context: bool = True) -> FixtureSnapshot:
    fixture = _fixture()
    return FixtureSnapshot(
        fixture=fixture,
        home=_team(fixture.home_team, with_context=with_context),
        away=_team(fixture.away_team, with_context=with_context),
        deferred_sections=[],
        generated_at=datetime(2026, 4, 25, 10, 0, tzinfo=UTC),
        matchup=MatchupTrendContext(
            head_to_head=None,
            home_split=None,
            away_split=None,
            home_trend=TeamTrendSummary(
                sample_size=5,
                goals_for_per_match=2.0,
                xg_for_per_match=1.9,
                goals_against_per_match=0.8,
                xg_against_per_match=0.7,
                set_piece_shot_share=0.22,
                source='test',
            )
            if with_context
            else None,
            away_trend=TeamTrendSummary(
                sample_size=5,
                goals_for_per_match=1.1,
                xg_for_per_match=1.0,
                goals_against_per_match=1.6,
                xg_against_per_match=1.7,
                set_piece_shot_share=0.15,
                source='test',
            )
            if with_context
            else None,
        ),
    )


class FakeSnapshotService:
    def __init__(self, snapshot: FixtureSnapshot) -> None:
        self._snapshot = snapshot
        self.live_context: bool | None = None

    def build_snapshot(
        self,
        fixture_id: str,
        *,
        recent_matches: int = 5,
        live_context: bool = True,
    ) -> FixtureSnapshot:
        assert fixture_id == self._snapshot.fixture.fixture_id
        assert recent_matches == 5
        self.live_context = live_context
        return self._snapshot


def test_tactical_visual_service_builds_svg_pack_and_writes_artifacts(tmp_path) -> None:
    snapshot_service = FakeSnapshotService(_snapshot())
    service = TacticalVisualService(snapshot_service=snapshot_service)

    pack = service.build_pack('fx-visual', output_dir=tmp_path)

    assert pack.fixture.fixture_id == 'fx-visual'
    assert snapshot_service.live_context is False
    assert len(pack.artifacts) == 3
    assert {artifact.name for artifact in pack.artifacts} == {
        'shot-map',
        'lineup-network',
        'xg-trend',
    }
    assert all('<svg' in artifact.svg for artifact in pack.artifacts)
    assert all(artifact.path is not None for artifact in pack.artifacts)
    assert all((tmp_path / artifact.path).exists() for artifact in pack.artifacts)
    assert pack.unavailable_sections == []
    assert pack.insights


def test_tactical_visual_service_marks_unavailable_sections() -> None:
    service = TacticalVisualService(
        snapshot_service=FakeSnapshotService(_snapshot(with_context=False))
    )

    pack = service.build_pack('fx-visual')

    assert pack.artifacts == []
    assert set(pack.unavailable_sections) == {
        'shot_map',
        'lineup_network',
        'xg_trend',
    }
