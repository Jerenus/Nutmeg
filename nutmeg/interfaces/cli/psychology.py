"""Psychology-signal and inspiration CLI commands.

Command functions live here and register on the shared
``nutmeg.interfaces.cli.app`` via ``@_cli.app.command()``. Every CLI-package
global (factories, helpers, options, re-exported imports) is reached through
``_cli`` so behaviour — including test monkeypatches on the ``cli`` package —
is identical to the pre-split single-module layout.
"""
from __future__ import annotations

import nutmeg.interfaces.cli as _cli


@_cli.app.command(name="psychology-inspect")
def psychology_inspect_cmd(
    fixture_file: _cli.Path = _cli.PSYCHOLOGY_FIXTURE_FILE_OPTION,
    rules_only: bool = _cli.PSYCHOLOGY_RULES_ONLY_OPTION,
) -> None:
    """Dump SignalReadings for a single fixture from each enabled provider."""
    from nutmeg.services.psychology.engine import (
        PsychologyEngine,
        SignalContext,
        TournamentStageSignal,
    )

    fixture = _cli.json.loads(fixture_file.read_text(encoding="utf-8"))
    fixture_id = str(fixture.get("id"))
    providers: list = [TournamentStageSignal()]
    if not rules_only:
        pass
    engine = PsychologyEngine(providers=providers)
    [verdict] = engine.evaluate(
        ctx=SignalContext(date="manual", fixtures=[fixture], snapshots={}, odds={}),
        data_picks={fixture_id: {}},
    )
    payload = {
        "fixture_id": fixture_id,
        "lean_direction": verdict.lean_direction,
        "conviction": verdict.conviction,
        "market_views": {
            market: {"outcome": view.outcome, "conviction": view.conviction}
            for market, view in verdict.market_views.items()
        },
        "readings": [
            {
                "provider": r.provider,
                "market": r.market,
                "outcome_view": r.outcome_view,
                "conviction": r.conviction,
                "evidence": r.evidence,
                "abstain_reason": r.abstain_reason,
            }
            for r in verdict.contributing_readings
        ],
    }
    _cli.typer.echo(_cli.json.dumps(payload, ensure_ascii=False, indent=2))


@_cli.app.command(name="inspiration-write")
def inspiration_write_cmd(
    date: str = _cli.INSPIRATION_DATE_OPTION,
    text: str | None = _cli.INSPIRATION_TEXT_OPTION,
) -> None:
    import os
    from datetime import datetime, timezone

    from nutmeg.services.psychology.io import InspirationStore

    base = _cli.Path(os.environ.get("NUTMEG_INSPIRATION_DIR", ".nutmeg-data/inspiration"))
    iso = _cli._normalize_date(date)
    if text is None:
        editor = os.environ.get("EDITOR", "nano")
        tmpfile = base / iso / "raw.md"
        tmpfile.parent.mkdir(parents=True, exist_ok=True)
        if not tmpfile.exists():
            tmpfile.write_text("", encoding="utf-8")
        os.system(f"{editor} {tmpfile!s}")
        text = tmpfile.read_text(encoding="utf-8")
    store = InspirationStore(base_dir=base)
    store.write_raw(date=iso, text=text)
    note = _cli._build_inspiration_parser().parse(text, date=iso)
    store.write_parsed(
        date=iso,
        tags=note.parsed_tags,
        raw_text=note.raw_text,
        parse_method=note.parse_method,
        timestamp=datetime.now(tz=timezone.utc).isoformat(),
    )
    _cli.typer.echo(f"saved {iso} via {note.parse_method}")


@_cli.app.command(name="inspiration-show")
def inspiration_show_cmd(date: str = _cli.typer.Argument(..., help="YYYYMMDD")) -> None:
    import os

    from nutmeg.services.psychology.io import InspirationStore

    base = _cli.Path(os.environ.get("NUTMEG_INSPIRATION_DIR", ".nutmeg-data/inspiration"))
    iso = _cli._normalize_date(date)
    note = InspirationStore(base_dir=base).read(date=iso)
    if note is None:
        _cli.typer.echo(f"no inspiration recorded for {iso}")
        raise _cli.typer.Exit(code=1)
    _cli.typer.echo(
        _cli.json.dumps(
            {
                "date": note.date,
                "raw_text": note.raw_text,
                "parsed_tags": {
                    "lean": note.parsed_tags.lean,
                    "conviction": note.parsed_tags.conviction,
                    "focus": note.parsed_tags.focus,
                    "force_psychology": note.parsed_tags.force_psychology,
                    "force_data": note.parsed_tags.force_data,
                },
                "parse_method": note.parse_method,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
