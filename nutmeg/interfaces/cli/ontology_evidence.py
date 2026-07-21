"""``nutmeg ontology ingest-evidence-day`` — parse a saved evidence day into facts.

Reads an availability JSON (and optional weather/news JSON), initializes the kernel
if needed, and ingests the day as a connector: upserted persons + observation-backed
person match statuses, weather observations, and AI-extracted provisional claims.

Standalone, the ``match_no -> match_id`` map is empty (no prior market-day ingest in
this invocation), so availability rows are **counted as skipped and printed** — never
silently dropped. Package 3 chains market-day and evidence-day and passes the in-memory
map so evidence attaches to real matches.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import nutmeg.interfaces.cli as _cli
from nutmeg.interfaces.cli.ontology import ontology_app
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.ingest.evidence_day import EvidenceDayIngestRequest


@ontology_app.command('ingest-evidence-day')
def ingest_evidence_day(
    business_date: str = _cli.typer.Option(..., '--business-date', help='YYYY-MM-DD'),
    availability: str = _cli.typer.Option(..., '--availability', help='path to availability JSON'),
    weather: str = _cli.typer.Option(None, '--weather', help='path to weather JSON'),
    news: str = _cli.typer.Option(None, '--news', help='path to news JSON'),
    format: str = _cli.typer.Option('text', '--format', help='text or json'),
) -> None:
    if format not in ('text', 'json'):
        _cli.typer.echo(f"invalid --format {format!r}: expected 'text' or 'json'", err=True)
        raise _cli.typer.Exit(code=2)

    settings = _cli.get_settings()
    kernel = _cli.build_ontology_kernel(settings)
    kernel.initialize()

    result = kernel.evidence_day_ingest.ingest(
        EvidenceDayIngestRequest(
            business_date=business_date,
            match_no_to_id={},
            availability=json.loads(Path(availability).read_text(encoding='utf-8')),
            weather=json.loads(Path(weather).read_text(encoding='utf-8')) if weather else [],
            news=json.loads(Path(news).read_text(encoding='utf-8')) if news else [],
            actor_id='source:api',
            actor_role=ActorRole.CONNECTOR,
            requested_at=datetime.now(UTC),
        )
    )

    if format == 'json':
        _cli.typer.echo(
            _cli.json.dumps(
                {
                    'business_date': business_date,
                    'person_statuses': result.person_statuses,
                    'observations': result.observations,
                    'claims': result.claims,
                    'skipped': result.skipped,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    _cli.console.print(
        f'ingested evidence {business_date}: person_statuses={result.person_statuses} '
        f'observations={result.observations} claims={result.claims} skipped={result.skipped}'
    )
