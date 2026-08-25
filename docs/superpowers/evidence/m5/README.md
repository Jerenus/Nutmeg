# M5 Verification Evidence

Verified at: 2026-08-24T11:30:07Z
Tested commit: `694ba63` (`fix(product): close M5 authority review findings`)
Scope: M5 settlement learning, calibration, ontology browser, and isolated scoreboard authority lifecycle

## Result

M5 implementation and isolated verification are complete. This evidence does not
authorize a production scoreboard cutover, scheduler change, external dispatch,
betting action, or M6 `ReleaseApproval`.

The mandatory Spec-Kit prerequisite resolver was also invoked. It rejected the
non-numeric branch name `feature/nutmeg-intelligence-os-m1`; the repository's active
`.specify/feature.json` points to the unrelated `045-content-publisher-v0`. No unrelated
feature status was changed. Verification therefore used the approved M5 design and plan
under `docs/superpowers/` as the coverage authority.

## Quality Gates

| Gate | Fresh result |
| --- | --- |
| Focused M5 regression | 52 passed, 0 failed |
| Full repository pytest | 1290 collected and passed, exit 0 |
| Ruff | `All checks passed!` |
| Python compileall | exit 0 for `nutmeg` and `scripts` |
| Pre-commit | all five configured hooks passed or correctly skipped by path |
| Whitespace | `git diff --check main...HEAD` and worktree check passed |
| Ontology schema | initialized, schema version 13, integrity `ok` |

## Independent Critique Closure

All Critical and Important M5 findings were reproduced RED before implementation and
closed by `694ba63`:

1. Shadow now rejects a projection older than the operational Action watermark;
   cutover accepts only the exact bound artifact-ingest and shadow-review Actions.
2. Shadow idempotency includes projection version and watermark, so a rebuilt projection
   creates a distinct review.
3. Export may replace only the exact legacy bytes on first publication, blocks stale
   business state, refreshes a newer current projection, and records that identity.
4. Manual observation history respects both effective and recorded time; revisions must
   supersede the single current leaf.
5. Counterfactual candidates require exactly three declared fields and finite numeric,
   non-boolean probabilities without string coercion.
6. Factor application requires an `apply` Adjudication bound to the exact lifecycle
   proposal, with defense in depth in the ontology Action.
7. Ontology `as_of` detail excludes future Action lineage; missing coverage remains
   visibly missing rather than becoming zero.
8. Mutating CLI results return canonical resolved target paths.

## Safe Replay

Replay root: `/tmp/nutmeg-m5-replay.cHJZfv` (temporary, non-production)
Business date: `2026-08-23`

The historical snapshot-safe two-stage replay was used instead of `decision-am` so no
provider fetch could replace the copied snapshot:

- `decision-sense`: 27 Match plus Sporttery/international snapshots ingested.
- `decision-backfill`: 0 new market-baseline shadows, an idempotent result against the
  copied historical decision ledger.
- `decision-settle --dry-run`: 54 Read/Ticket settlements, 21 factor verdicts, calibration
  panel generated with the participation-accuracy section.
- `decision-close --dry-run`: 0 tickets, total stake CNY 0, report generated without
  Telegram dispatch.
- Result PDF: 210,431 bytes; decision files contained 618 match, 1,040 settlement, and
  7 factor rows with explicit scopes.

## Browser Evidence

The app ran only on `http://127.0.0.1:63860` over
`/tmp/nutmeg-m5-browser.aDQgqF/data`; the server was stopped after capture. The in-app
browser Node REPL was unavailable in this session, so local Chrome 151 through Selenium
was used for equivalent DOM, network, console, viewport, and screenshot checks.

| State | Viewport | Evidence | Result |
| --- | --- | --- | --- |
| Review | 1440x1000 | [review-desktop.png](review-desktop.png) | HTTP/assets OK; 1440px document width |
| Calibration | 1440x1000 | [calibration-desktop.png](calibration-desktop.png) | Nonblank; no overflow |
| Ontology | 1440x1000 | [ontology-desktop.png](ontology-desktop.png) | Typed detail visible; no overflow |
| Review | 390x844 | [review-390.png](review-390.png) | Single-column order; no overflow |
| Calibration | 390x844 | [calibration-390.png](calibration-390.png) | Controls and empty states fit |
| Ontology | 390x844 | [ontology-390.png](ontology-390.png) | Search and long values fit |
| DuckDB unavailable | 390x844 | [review-degraded-390.png](review-degraded-390.png) | `projection_unavailable` visible |
| DuckDB restored | 390x844 | [review-restored-390.png](review-restored-390.png) | Three score planes recovered |

Every capture used the exact stated inner viewport size. All had document
`scrollWidth == clientWidth`, zero failed resources, zero severe console entries, one
visible workspace root, and no controls/code blocks escaping the viewport. Screenshots
were visually inspected for overlap, clipping, blank panels, and incoherent layout.

## Production Non-Mutation

Before and after values were identical:

| Production path | SHA-256 |
| --- | --- |
| `.nutmeg-data/scoreboard.json` | `497d6822f2ba832447bdb0daa818d6dc80736d4cce664a77cf0d121e48231db5` |
| `.nutmeg-data/ontology/ontology.db` | `4cfbfafca660dae9d1070607f62e02cdc97388a5511cbbe3a751dd9d6d011867` |
| `docs/sop/CONSTITUTION.md` | `4abf6bf29bb5d758e7b89c656104820dd39f57eec9a1c70176742c324e9b2e83` |
| `docs/sop/RUNBOOK.md` | `3519ad24aa4294fe32222c2c9e09a097cd992d22c4cdc3b1923ea160735e4ccc` |
| `docs/sop/RULEBOOK.md` | `a77f5e4350f308c13f5e61f8c21b309881d7970dca2e3740093cc2ce2f5e9279` |
| `AGENTS.md` | `3a714bed62e93ff7d6903a84824fd0ca52a6a4ef2405e8f0d4f1e3d3ff1e0324` |
| `CLAUDE.md` | `6548d3838fe88902308b6d31a3d83f7f77eac42e3a9199616d5ac73ddad9186d` |

## Design Coverage

- [x] Three independent score planes and explicit coverage: projection, contract,
  query, SSR, and E2E tests.
- [x] Existing Brier/settlement/ledger arithmetic only: analytics and finance tests;
  static JavaScript assertions.
- [x] Preregistered-only counterfactual replay: intervention projection tests.
- [x] Human-only, proposal-bound lifecycle application: API, Action, and E2E tests.
- [x] Typed manual observation evidence and linear supersession: Action/repository tests.
- [x] Exact legacy hash, complete classification, zero-unexplained gate: authority tests.
- [x] Current projection and optimistic human cutover: authority and CLI lifecycle tests.
- [x] Canonical atomic compatibility export and drift detection: authority/E2E tests.
- [x] Review, calibration, ontology, and scoreboard APIs: M5 query/API tests.
- [x] Dense SSR workspaces without client arithmetic: UI tests and browser evidence.
- [x] DuckDB degradation preserves SQLite truth: repository/query/UI/browser tests.
- [x] SOP checker is read-only and production paths are untouched: fixture tests and
  before/after hashes.
- [x] Full isolated lifecycle and project replay: M5 E2E, CLI tests, and replay above.

## M6 Boundary

M6 may build reliability controls, backup/restore drills, performance/fault evidence,
soak collection, scheduler review, and guarded release approval. No synthetic run in
this evidence represents 14 calendar days of soak; release approval must remain blocked
until real elapsed evidence satisfies the M6 policy.
