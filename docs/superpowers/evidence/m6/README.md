# M6 Verification Evidence

Verified at: `2026-08-25T03:03:23Z`
Product candidate: `33e5753` (`fix(reliability): verify source CAS before backup`)
Scope: M6 reliability evidence, recovery, release governance, observability, and the
complete M1-M6 operator lifecycle

## Result

M6 software implementation and isolated verification are complete. Evidence collection
is operational, but the real release is intentionally blocked. This evidence does not
authorize a production migration, scheduler change, external dispatch, betting action,
funds action, or `ReleaseApproval`.

The Spec-Kit prerequisite resolver cannot map the non-numeric branch
`feature/nutmeg-intelligence-os-m1`; `.specify/feature.json` points to the unrelated
`045-content-publisher-v0`. That feature was not modified. The approved M6 design and
plan under `docs/superpowers/` are therefore the coverage authority.

## Implementation Map

| Capability | Commit |
| --- | --- |
| Migration 14 and reliability ledger | `6a2b523` |
| Strict reliability Actions and validators | `38cf95b` |
| Release evaluator and approval guard | `02bd19d` |
| Atomic backup and restore drill | `170f0c6` |
| Reliability CLI and scheduler inspection | `a97c34d` |
| Product release API | `7177176` |
| Route metrics and release workspace | `c5e5f2f` |
| Fault, performance, and lifecycle E2E | `9593104` |

## Quality Gates

| Gate | Fresh result |
| --- | --- |
| M6 reliability/product focused suite | passed, zero failures |
| Full repository pytest | 100%, zero failures |
| Ruff | `All checks passed!` |
| Python compileall | exit 0 for `nutmeg` and `scripts` |
| Pre-commit | all configured hooks passed or correctly skipped by path |
| Whitespace | base-to-head and worktree checks passed |
| Ontology schema | schema 14, SQLite integrity `ok` |

These gates were run after the implementation fixes and are repeated after this evidence
commit so the final branch state, rather than an earlier working tree, is authoritative.

## Independent Critique Closure

No Critical finding remains. Five closure commits resolved one product evidence
visibility defect and four reliability integrity findings:

| Review area | Closure |
| --- | --- |
| Release API/UI evidence facts | `5782270` exposes only allowlisted scheduler, backup, and observed performance facts |
| Reliability record identity | `933c5ab` scopes idempotency by workflow, business date, and observation window |
| Candidate-bound selection | `8bcc26a` selects the latest evidence within the requested candidate |
| Approval snapshot integrity | `69c87df` snapshots inputs and revalidates content hashes before Action creation |
| Backup source integrity | `33e5753` rejects corrupted content-addressed blobs before publication |

Evidence age has no invented TTL: the approved design defines no age threshold. The
evaluator instead enforces exact candidate selection, rejects future evidence, binds
approval to an immutable evidence snapshot, and publishes observation timestamps.

## Recovery Drill

Recovery root: `/tmp/nutmeg-m6-recovery.RUlgFo` (isolated, non-production)

- Manifest SHA-256: `06f0c16811393741f35da653e3a8deb49b094b26c60aa1d07cae0de9cbc6fdd7`.
- Restored schema 14 and SQLite integrity `ok`.
- Action/outbox high-watermarks remained `1/1`; rebuilt projection watermark was `1`.
- Restored artifact/retrieval counts remained `1/1`.
- No `ReleaseApproval` was created.

## Decision Replay

Replay root: `/tmp/nutmeg-m6-replay.pbRg0z` (isolated, non-production)
Source business date: `2026-08-24`

- Production snapshots were copied read-only into the temporary root.
- `decision-sense` replayed 11 matches and 18 snapshots.
- `decision-backfill` created 22 market-baseline shadow Reads.
- `decision-settle` produced 22 settlements and a calibration report.
- `decision-close` consumed a valid empty ticket, produced a 46 KB PDF, and kept stake
  at CNY 0.
- No external dispatch was used.

## Browser Evidence

The app ran only on `http://127.0.0.1:63861` over
`/tmp/nutmeg-m6-production-copy.YML56o/data`; the server was stopped after capture. The
in-app Browser Node REPL was unavailable, so Chrome 151 through Selenium was used for
equivalent DOM, network, console, viewport, focus, and screenshot checks.

| Workspace/state | 1440x1000 | 390x844 |
| --- | --- | --- |
| Command center | [desktop](command-center-desktop.png) | [mobile](command-center-390.png) |
| Data operations | [desktop](operations-desktop.png) | [mobile](operations-390.png) |
| Match investigation | [desktop](match-desktop.png) | [mobile](match-390.png) |
| Ticket adjudication | [desktop](tickets-desktop.png) | [mobile](tickets-390.png) |
| Settlement review | [desktop](review-desktop.png) | [mobile](review-390.png) |
| Calibration | [desktop](calibration-desktop.png) | [mobile](calibration-390.png) |
| Ontology browser | [desktop](ontology-desktop.png) | [mobile](ontology-390.png) |
| Release blocked | [desktop](release-blocked-desktop.png) | [mobile](release-blocked-390.png) |

Additional states:

- [Mobile release gates](release-gates-390.png) shows stable `missing_evidence` block
  codes; DOM verification found all six gates blocked and no approval form.
- [DuckDB offline](calibration-duckdb-offline-390.png) shows
  `projection_unavailable`; [restored](calibration-duckdb-restored-390.png) returns to
  `AVAILABLE`, projection `fe-v1`, high-watermark 5223.
- [First-Tab focus](skip-link-focus-desktop.png) visibly focuses the `#main-content`
  skip link.

All captures used the exact stated inner viewport. Every route and product asset returned
200, severe console entries and failed responses were zero, document
`scrollWidth == clientWidth`, and one workspace root was present. Screenshots were also
visually inspected for blank panels, clipping, overlap, and incoherent layout.

## Truthful Real-State Gate

The production data was copied to `/tmp/nutmeg-m6-production-copy.YML56o/data`; only the
copy was migrated. It reached schema 14 with integrity `ok`. A read-only release-v1
evaluation for candidate `33e5753` returned:

| Fact | Actual value |
| --- | --- |
| `ready` | `false` |
| `approval_status` | `none` |
| ReleaseApproval rows | `0` |
| ReliabilityEvidence rows | `0` |
| G1-G6 | all `missing_evidence` |
| JCZQ soak | `dates=[]`, 0 distinct days, 0-day span |
| Zucai soak | `dates=[]`, 0 distinct days, 0-day span |

There is no legitimate list of future dates to synthesize. Both workflows are missing
14 real, non-dispatch business dates and a 14-day inclusive span; collection must happen
over real elapsed operation before the gate can turn green.

## Production Non-Mutation

Before and after values were identical:

| Production path | SHA-256 |
| --- | --- |
| `.nutmeg-data/scoreboard.json` | `497d6822f2ba832447bdb0daa818d6dc80736d4cce664a77cf0d121e48231db5` |
| `.nutmeg-data/ontology/ontology.db` | `da6b0793382370a0236564f40387c2f8b65deff2260284e10877f2f0dbf5f0e1` |
| `docs/sop/CONSTITUTION.md` | `4abf6bf29bb5d758e7b89c656104820dd39f57eec9a1c70176742c324e9b2e83` |
| `docs/sop/RUNBOOK.md` | `3519ad24aa4294fe32222c2c9e09a097cd992d22c4cdc3b1923ea160735e4ccc` |
| `docs/sop/RULEBOOK.md` | `a77f5e4350f308c13f5e61f8c21b309881d7970dca2e3740093cc2ce2f5e9279` |
| `AGENTS.md` | `3a714bed62e93ff7d6903a84824fd0ca52a6a4ef2405e8f0d4f1e3d3ff1e0324` |
| `CLAUDE.md` | `6548d3838fe88902308b6d31a3d83f7f77eac42e3a9199616d5ac73ddad9186d` |

## Design Coverage

- [x] Immutable reliability evidence and guarded human-only ReleaseApproval.
- [x] Candidate-bound six-gate evaluation with explicit block codes and soak calendars.
- [x] Atomic backup, content verification, restore comparison, and projection rebuild.
- [x] Fixed 10x performance budgets and bounded allowlisted route metrics.
- [x] Eight executable fault scenarios with no state corruption.
- [x] Full M1-M6 API/browser lifecycle, reconnect, focus, and degraded-state coverage.
- [x] Read-only scheduler authority inspection and secret-safe product summaries.
- [x] Production non-mutation proof and truthful real 14-day soak block.

## Second-Pass Independent Critique (2026-08-25, session nutmeg-5f)

A second independent adversarial review of `9032644..33e5753` (0 Critical, 3
Important, 8 Minor) was closed RED-GREEN on top of the recorded evidence:

| Finding | Closure |
| --- | --- |
| I-1 FAILED terminal actions permanently poisoned their idempotency key, and a replayed failure exited 0 | `676d3e8` releases the key under `#failed-<action_id>` (audit row kept) and re-executes; `a41caa8` makes every non-COMMITTED CLI outcome exit 1 |
| I-3 operator-supplied `--requested-at`/`--evaluated-at` in the future could pre-fabricate 14-day soak evidence through the release-v1 gate | `a41caa8` caps every explicit CLI instant at the server clock (+5 min skew; business_date +1 day zone slack); the API path already used the server clock |
| I-2 the seven generic check-report kinds accepted a single self-declared boolean, letting G1/G2/G4/G5/G6 turn green without named evidence | `9e7aa77` fixes per-kind `schema_version` + required check lists (scheduler_authority aligned to `to_evidence_report`), rejects unknown fields, caps canonical report size at 256 KB |

Minor findings M-1..M-8 (acknowledged trade-offs, display truncation, attribution
constants) are recorded in the session review and left as documented behavior.

Post-closure gates on this branch state: full pytest exit 0, Ruff clean,
compileall exit 0, base-to-head and worktree whitespace checks clean. An
independent re-verification earlier in the same session also reproduced the
migration rehearsal (production copy 9→14, integrity ok), the atomic
backup/restore drill (`status: "passed"`, watermark 5223), the `/verify`
decision-chain replay for 2026-08-24, the blocked release evaluation
(`ready=false`, both soak lanes 0/14), and byte-identical production hashes
before and after all operations.
