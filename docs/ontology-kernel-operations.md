# Ontology Kernel v2 — Package 1 Operations Contract

> Status: **Package 1 foundation only — not the v2 cutover.** The kernel here is
> the transactional write boundary (SQLite operational database, content-
> addressed artifact store, typed Actions, permissions, migrations). It creates
> **no** football-domain objects (Match/Team/Person/Forecast/Ticket) — those
> arrive in Packages 2–5. The existing five-verb `decision` commands remain the
> current production interface until the Package 5 cutover; the decision
> schedules are intentionally paused during the approved rebuild and must not be
> re-enabled until the cutover gates pass.

Design: `docs/superpowers/specs/2026-07-20-ontology-kernel-v2-design.md`
· Plan: `docs/superpowers/plans/2026-07-21-ontology-kernel-v2-package-1.md`

## 1. Scope

Package 1 gives you a correct, auditable **write path** and nothing more. If a
command or object is about football facts, forecasts, tickets or scoring, it is
not part of Package 1.

## 2. Filesystem paths and ownership

The kernel owns exactly one tree under the application `data_dir`
(`NUTMEG_DATA_DIR`, default `.nutmeg-data`):

```text
.nutmeg-data/ontology/ontology.db                         # operational SQLite (WAL)
.nutmeg-data/ontology/artifacts/sha256/<first-2>/<digest> # immutable evidence blobs
```

It is deliberately separate from `state/state.db` (notification/client state) and
`analytics/analytics.duckdb`. `ensure_directories` creates only `ontology/` and
`ontology/artifacts/`; it never creates the database file.

## 3. `ontology init` and idempotency

```bash
uv run nutmeg ontology init --format json
```

`init` creates the owned directories and applies pending numbered migrations. It
is idempotent: a second run applies nothing (`applied_versions == []`) and leaves
the schema at its current version. `init` exits `2` on an invalid `--format`.

## 4. `ontology status` — read-only health / exit-code contract

```bash
uv run nutmeg ontology status --format json
```

Contract: **status never initializes or migrates the database.** When the
database file is absent it reports `initialized=false`, `schema_version=0`, and
does not create the file. When present it runs `PRAGMA integrity_check`, reads
the migration high-water mark, and counts Actions/artifacts/retrievals. Exit code
is `1` when the kernel is uninitialized or integrity is not `ok`, otherwise `0`;
an invalid `--format` exits `2`. The same read-only status is surfaced in
`nutmeg doctor` (JSON `ontology` block plus a text line) without initializing it.

## 5. Action roles and deny-by-default permissions

Every formal write is an Action carrying an actor role. Permissions are stored as
versioned policy rows and enforced **deny-by-default**: a role may execute an
action type only when an explicit permission row exists under an *active* policy
version — there is no fallback to another policy or role.

Package 1 seeds `governance-v1` with:

| Action | Allowed roles |
|---|---|
| `ingest_artifact` | `connector`, `judge_operator` |
| `change_policy` | `judge_operator` |

`ai_extractor`/`ai_analyst`/`deterministic_system` are **not** granted
`ingest_artifact`; any future need must arrive through an explicit policy Action,
not a pre-granted role. AI roles cannot write verified facts — Claim state and its
verification arrive in Package 2.

## 6. Artifact CAS immutability and orphan-blob safety

Raw evidence is content-addressed by SHA-256 and written once. Publication is
atomic (fsynced temp file, then `os.link` — never a clobbering `rename`); a
re-fetch of identical bytes adds an `ArtifactRetrieval` row, never a second blob.
A database failure *after* a blob is published may leave an unreferenced hash
blob on disk; this is safe and reusable, and no cleanup is attempted inside the
failed transaction. Blobs are never edited in place.

## 7. Backup sequence

1. stop the writers (decision schedules and any zucai/jczq writer);
2. copy `.nutmeg-data/ontology/ontology.db` and the `artifacts/` tree;
3. hash the copy (`shasum -a 256`) into a manifest;
4. resume writers only when explicitly authorized.

## 8. Prohibited operations

Do not edit `ontology.db` with ad-hoc SQL and do not edit or delete artifact
blobs by hand. All writes go through typed Actions on the repository/unit-of-work
layer so that business rows and the Action audit log commit atomically.

## 9. Later packages and current non-goals

Packages 2–5 add the football world & evidence, the decision & finance loop,
learning & regime analytics, and the evidence migration & cutover. Until then:
no identity resolution, no Claim/Observation/Forecast/Ticket, no DuckDB scoring,
and no legacy data migration live behind this kernel.
