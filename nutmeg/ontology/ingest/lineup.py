"""Parse an availability/lineup snapshot into typed inputs.

No real per-day availability/lineup payload ships in ``.nutmeg-data`` yet (only
sporttery/bold odds), so this parser targets a minimal, explicit shape: a snapshot
keyed by sporttery ``match_no`` with a ``players`` list. When a real adapter
payload (api-football / soccerdata) is wired for production, confirm its actual
structure and adapt this parser — do not guess unseen fields. The parser is pure
(no DB) and skips rows missing a name/availability rather than inventing them.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParsedAvailability:
    match_no: str
    team_name: str
    player_name: str
    provider_id: str | None
    availability: str
    status_kind: str


def parse_availability_snapshot(value: dict) -> list[ParsedAvailability]:
    match_no = str(value.get('match_no') or '')
    team_name = str(value.get('team') or '')
    rows: list[ParsedAvailability] = []
    for player in value.get('players') or []:
        name = str(player.get('name') or '')
        availability = str(player.get('availability') or '')
        if not name or not availability:
            continue
        provider_id = player.get('provider_id')
        rows.append(
            ParsedAvailability(
                match_no=match_no,
                team_name=team_name,
                player_name=name,
                provider_id=str(provider_id) if provider_id is not None else None,
                availability=availability,
                status_kind=str(player.get('status_kind') or 'selection'),
            )
        )
    return rows
