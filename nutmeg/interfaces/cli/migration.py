"""``nutmeg migrate-decision-store`` — replay the old JSONL store into a fresh kernel.

Reads the old ``<source>/decision/*.jsonl`` (read-only) and imports it through the
kernel Actions into ``--target`` (a caller-chosen directory — **never** the production
kernel path), then reconciles the rebuilt Brier against the old settlements and prints
a JSON summary. This is Package 5A: it does not touch production, dispatch anything, or
restore any schedule — go-live is Package 5B and user-gated.
"""
from __future__ import annotations

import json
from pathlib import Path

import nutmeg.interfaces.cli as _cli
from nutmeg.config.settings import AppSettings
from nutmeg.migration.importer import HistoricalImporter
from nutmeg.migration.old_store import read_objects
from nutmeg.migration.reconcile import Reconciler

_SOURCE_OPTION = _cli.typer.Option(
    ..., "--source", help="Old decision store root (e.g. .nutmeg-data/jczq); read-only")
_TARGET_OPTION = _cli.typer.Option(
    ..., "--target", help="Fresh target data dir for the rebuilt kernel (never production)")
_AS_OF_OPTION = _cli.typer.Option("2026-07-21T00:00:00+00:00", "--as-of")
_BUILT_AT_OPTION = _cli.typer.Option("2026-07-21T00:00:00+00:00", "--built-at")


@_cli.app.command("migrate-decision-store")
def migrate_decision_store(
    source: Path = _SOURCE_OPTION,
    target: Path = _TARGET_OPTION,
    as_of: str = _AS_OF_OPTION,
    built_at: str = _BUILT_AT_OPTION,
) -> None:
    decision_dir = Path(source) / "decision"
    kernel = _cli.build_ontology_kernel(AppSettings(data_dir=Path(target)))
    kernel.initialize()

    importer = HistoricalImporter(kernel)
    importer.import_matches(read_objects(decision_dir, "matches"))
    importer.import_snapshots(read_objects(decision_dir, "snapshots"))
    importer.import_reads(read_objects(decision_dir, "reads"))
    settlements = read_objects(decision_dir, "settlements")
    importer.import_outcomes(settlements)

    reconciliation = Reconciler(kernel).reconcile(
        importer.report, read_objects(decision_dir, "reads"), settlements,
        as_of=as_of, built_at=built_at)

    summary = {
        "source": str(source),
        "target": str(target),
        "counts": importer.report.counts,
        "skipped": len(importer.report.skipped),
        "reconciliation": {
            "matched": reconciliation.matched,
            "mismatched": reconciliation.mismatched,
            "no_baseline": reconciliation.no_baseline,
            "coverage": reconciliation.coverage,
            "tolerance": reconciliation.tolerance,
        },
    }
    _cli.typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))
