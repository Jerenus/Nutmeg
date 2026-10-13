"""Baseline migration + legacy-chain rebase (2026-10-13 基线重排)."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from nutmeg.ontology.errors import MigrationDriftError
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import (
    BASELINE,
    BASELINE_TRIGGERS,
    LEGACY_CHAIN_LENGTH,
    MIGRATIONS,
    RETIRED_TABLES,
    Migration,
    migration_status,
    run_migrations,
)
from nutmeg.ontology.repository.schema import action_permissions, metadata, policy_versions

LEGACY_FIXTURE = Path(__file__).parent / "golden" / "legacy_schema_47.sql"
EXPECTED_TABLES = frozenset(metadata.tables)  # 55 + schema_migrations


def structure(database: Path) -> dict[str, object]:
    """Pragma-level shape: columns, foreign keys, indexes, triggers — independent of how
    the CREATE text was reached (ALTER-appended columns in a legacy store, one CREATE in
    a fresh one)."""
    connection = sqlite3.connect(database)
    try:
        tables = sorted(
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        )
        shape: dict[str, object] = {}
        for table in tables:
            columns = sorted(
                (r[1], r[2].upper(), r[3], r[4], r[5])
                for r in connection.execute(f'PRAGMA table_info("{table}")')
            )
            foreign = sorted(
                (r[2], r[3], r[4])
                for r in connection.execute(f'PRAGMA foreign_key_list("{table}")')
            )
            indexes = sorted(
                (
                    r[1], r[2],
                    tuple(c[2] for c in connection.execute(f'PRAGMA index_info("{r[1]}")')),
                )
                for r in connection.execute(f'PRAGMA index_list("{table}")')
                if not r[1].startswith("sqlite_autoindex")
            )
            shape[table] = (columns, foreign, indexes)
        shape["__triggers__"] = sorted(
            (name, table, re.sub(r"\s+", " ", sql).strip())
            for name, table, sql in connection.execute(
                "SELECT name, tbl_name, sql FROM sqlite_master WHERE type='trigger'"
            )
        )
        return shape
    finally:
        connection.close()


def build_legacy_store(database: Path) -> None:
    """Recreate a sealed pre-baseline store (schema 47) from the archived golden dump:
    every table / index / trigger DDL, the 47-row ledger and the seeded permissions."""
    text = LEGACY_FIXTURE.read_text(encoding="utf-8")
    # the dump is ordered by (type, name): collect per kind, then run tables → indexes → triggers
    statements: dict[str, list[str]] = {"table": [], "index": [], "trigger": [], "view": []}
    kind: str | None = None
    block: list[str] = []
    for line in text.splitlines():
        header = re.match(r"^-- (table|index|trigger|view) ", line)
        if header:
            kind, block = header.group(1), []
            continue
        if line.startswith("-- schema_migrations"):
            break
        if line == "":
            statement = "\n".join(block).rstrip().rstrip(";")
            if kind and statement and not statement.startswith("-- (implicit)"):
                statements[kind].append(statement)
            block = []
            continue
        block.append(line)
    ledger = re.findall(r"^-- (\d+) (\S+) ([0-9a-f]{64})$", text, flags=re.M)
    permissions = re.findall(r"^-- (governance-v1) (\S+) (\S+)$", text, flags=re.M)
    assert len(ledger) == LEGACY_CHAIN_LENGTH and permissions
    connection = sqlite3.connect(database)
    try:
        for kind in ("table", "index", "trigger", "view"):
            for statement in statements[kind]:
                connection.execute(statement)
        connection.executemany(
            "INSERT INTO schema_migrations(version, name, checksum, applied_at) "
            "VALUES (?, ?, ?, '2026-10-01T00:00:00+00:00')",
            [(int(v), n, c) for v, n, c in ledger],
        )
        connection.execute(
            "INSERT INTO policy_versions(policy_version_id, policy_kind, version, payload_json, "
            "status, effective_at, created_at) VALUES ('governance-v1','governance',1,'{}',"
            "'active','2026-07-22T00:00:00+00:00','2026-07-22T00:00:00+00:00')"
        )
        connection.executemany(
            "INSERT INTO action_permissions(policy_version_id, action_type, actor_role) "
            "VALUES (?, ?, ?)",
            permissions,
        )
        connection.commit()
    finally:
        connection.close()


def test_baseline_applies_once_and_seeds_the_store(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    first = run_migrations(engine)
    second = run_migrations(engine)
    assert first.applied_versions == (1,)
    assert second.applied_versions == ()
    assert migration_status(engine).current_version == 1
    assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES
    assert not RETIRED_TABLES & EXPECTED_TABLES
    with engine.connect() as connection:
        assert connection.execute(select(policy_versions.c.policy_version_id)).scalar_one() == (
            "governance-v1"
        )
        rows = connection.execute(select(action_permissions)).mappings().all()
        assert ("ingest_artifact", "connector") in {
            (row["action_type"], row["actor_role"]) for row in rows
        }
        assert len(rows) == 145
        markets = connection.exec_driver_sql("SELECT COUNT(*) FROM market_definitions").scalar()
        selections = connection.exec_driver_sql(
            "SELECT COUNT(*), SUM(deployable) FROM selection_definitions"
        ).one()
        assert (markets, tuple(selections)) == (4, (34, 33))
        triggers = {
            row[0] for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            )
        }
        assert triggers == set(BASELINE_TRIGGERS)
        with pytest.raises(IntegrityError):  # guard trigger is live
            connection.exec_driver_sql(
                "INSERT INTO historical_replay_runs(replay_run_id, business_date, "
                "source_root_fingerprint, source_manifest_hash, isolated_database_identity, "
                "schema_version, status, started_at, production_before_json) VALUES "
                "('r','2026-10-13','f','m','i',1,'running','t','{}')"
            )
            connection.exec_driver_sql("DELETE FROM historical_replay_runs")


def test_changed_fingerprint_is_rejected_as_migration_drift(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    changed = Migration(
        version=BASELINE.version,
        name=BASELINE.name,
        fingerprint="changed-after-apply",
        apply=BASELINE.apply,
    )
    with pytest.raises(MigrationDriftError, match="migration 1 checksum drift"):
        run_migrations(engine, migrations=(changed, *MIGRATIONS[1:]))


def test_sealed_legacy_store_is_rebased_in_place_to_the_baseline_shape(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.db"
    build_legacy_store(legacy)
    with sqlite3.connect(legacy) as before:
        table_count = "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        assert before.execute(table_count).fetchone()[0] > 180

    engine = build_ontology_engine(legacy)
    assert run_migrations(engine).applied_versions == ()  # rebase, not a replay
    assert run_migrations(engine).applied_versions == ()
    assert migration_status(engine).applied_versions == (1,)
    assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES

    fresh = tmp_path / "fresh.db"
    run_migrations(build_ontology_engine(fresh))
    assert structure(legacy) == structure(fresh)
    with sqlite3.connect(legacy) as rebased, sqlite3.connect(fresh) as built:
        ledger = "SELECT version, name, checksum FROM schema_migrations"
        assert rebased.execute(ledger).fetchall() == built.execute(ledger).fetchall()
        permissions = "SELECT action_type, actor_role FROM action_permissions ORDER BY 1, 2"
        assert rebased.execute(permissions).fetchall() == built.execute(permissions).fetchall()
        assert rebased.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_rebase_refuses_a_retired_table_that_holds_rows(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.db"
    build_legacy_store(legacy)
    with sqlite3.connect(legacy) as connection:
        assert "persons" in RETIRED_TABLES
        connection.execute(
            "INSERT INTO persons(person_id, canonical_name, resolution_status, created_at) "
            "VALUES ('p', 'x', 'provisional', 't')"
        )
    with pytest.raises(MigrationDriftError, match="persons holds 1 rows"):
        run_migrations(build_ontology_engine(legacy))


def test_unknown_ledger_shape_is_drift(tmp_path: Path) -> None:
    database = tmp_path / "odd.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, name TEXT NOT NULL, "
            "checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_migrations VALUES (1, 'governance_kernel', 'deadbeef', 't')"
        )
    with pytest.raises(MigrationDriftError, match="neither the baseline nor the sealed legacy"):
        run_migrations(build_ontology_engine(database))
