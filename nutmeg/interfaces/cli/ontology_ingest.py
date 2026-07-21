"""``nutmeg ontology ingest-market-day`` — parse a saved market day into facts.

Reads a sporttery markets JSON (and optional international odds JSON), initializes
the kernel if needed (idempotent), and ingests the day as a connector: resolved
teams, matches with real schedules, and de-vigged had snapshots. Idempotent on
rerun.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import nutmeg.interfaces.cli as _cli
from nutmeg.interfaces.cli.ontology import ontology_app
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.ingest.market_day import MarketDayIngestRequest


@ontology_app.command('ingest-market-day')
def ingest_market_day(
    business_date: str = _cli.typer.Option(..., '--business-date', help='YYYY-MM-DD'),
    sporttery: str = _cli.typer.Option(..., '--sporttery', help='path to sporttery markets JSON'),
    intl: str = _cli.typer.Option(None, '--intl', help='path to international odds JSON'),
    format: str = _cli.typer.Option('text', '--format', help='text or json'),
) -> None:
    if format not in ('text', 'json'):
        _cli.typer.echo(f"invalid --format {format!r}: expected 'text' or 'json'", err=True)
        raise _cli.typer.Exit(code=2)

    settings = _cli.get_settings()
    kernel = _cli.build_ontology_kernel(settings)
    kernel.initialize()

    sporttery_value = json.loads(Path(sporttery).read_text(encoding='utf-8'))
    intl_value = json.loads(Path(intl).read_text(encoding='utf-8')) if intl else None

    result = kernel.market_day_ingest.ingest(
        MarketDayIngestRequest(
            business_date=business_date,
            sporttery_value=sporttery_value,
            intl_value=intl_value,
            actor_id='source:sporttery',
            actor_role=ActorRole.CONNECTOR,
            requested_at=datetime.now(UTC),
        )
    )

    if format == 'json':
        _cli.typer.echo(
            _cli.json.dumps(
                {
                    'business_date': business_date,
                    'matches': result.matches,
                    'snapshots': result.snapshots,
                    'teams': result.teams,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    _cli.console.print(
        f'ingested {business_date}: matches={result.matches} '
        f'snapshots={result.snapshots} teams={result.teams}'
    )
