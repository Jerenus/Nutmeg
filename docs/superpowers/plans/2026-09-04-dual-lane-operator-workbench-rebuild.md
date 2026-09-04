# Dual-Lane Operator Workbench Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stale rx-driven Application with one current-data JCZQ/Zucai operator surface that carries human judgments through evidence, ticket comparison, protected Telegram confirmation, ledger, settlement, and governed review without exposing raw JSON.

**Architecture:** Keep the existing FastAPI/Jinja operator shell, but replace its v1 artifact-derived state with strict v2 DTOs backed by additive ontology revisions and typed Actions. Split persistence and services by sale, decision, result, and review domains; keep collection outside the Application, keep final placement in the sole OpenClaw Telegram owner, and activate production only behind the accepted-commit gate.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy Core with SQLite, FastAPI, Jinja2, Typer, Decimal arithmetic, vanilla JavaScript/CSS, pytest, Playwright, ruff, uv.

---

## Source of truth and execution rules

Before every package, reread:

- `AGENTS.md`
- `docs/sop/CONSTITUTION.md`
- `docs/sop/RUNBOOK.md`
- `docs/sop/RULEBOOK.md`
- `docs/superpowers/specs/2026-08-24-nutmeg-intelligence-os-design.md`
- `docs/superpowers/specs/2026-09-03-dual-lane-operator-workbench-rebuild-design.md`

The 2026-09-03 design is the requirement source. This plan supplies file and test order; it
does not weaken any invariant in that design. In particular:

- no code chooses a probability, face, match, rule interpretation, no-ticket reason, or
  deployment outcome for Jun;
- no Web route performs final placement, edits `scoreboard.json`, changes launchd, performs
  cutover, or grants `ConfirmDispatch` to an AI role;
- every production schema migration requires a verified copy of `ontology.db` under
  `.nutmeg-data/archive/` before the idempotent `nutmeg ontology init` migrator is run;
- tests always invoke pytest as `uv run pytest` and use isolated temporary data directories;
- each package follows RED -> GREEN -> REFACTOR and receives a focused commit;
- never modify, stage, or commit `docs/nutmeg-scheduler-operations.md`,
  `scripts/openclaw/nutmeg_scheduler_ops.py`, or
  `tests/test_nutmeg_scheduler_ops.py`;
- do not stage the unrelated untracked handoff/render scripts present at plan time.

Package branches are stacked only when uninterrupted implementation has not received
authority to merge the predecessor into `main`. The preferred sequence is: verify a package,
report it, integrate it by the user's selected method, then branch the next package from the
updated `main`. A stacked successor may be used to keep implementation moving, but no stack
is pushed or described as merged.

## File structure

### Runtime and product boundary

- `nutmeg/product/operator_runtime.py`: runtime modes, accepted/running commit validation,
  production-data-path checks, and the process lease.
- `nutmeg/product/operator_workers.py`: the sole Application supervisor for evidence-freeze,
  baseline, candidate-generation, deadline, settlement, review-materialization,
  review-completion, outbox, and read-model workers, including durable lease/retry state.
- `nutmeg/product/operator_contracts.py`: replace v1 DTOs with strict v2 discriminated
  response/command contracts; no persistence or arithmetic.
- `nutmeg/product/operator_state.py`: pure offer/work-item/task/focus/Today resolvers.
- `nutmeg/product/operator_lanes.py`: shared lane protocol and JCZQ/Zucai adapters.
- `nutmeg/product/operator_evidence.py`: E1-E6b/EC deterministic evaluation only.
- `nutmeg/product/operator_candidates.py`: bounded exhaustive enumeration and Decimal
  comparison metrics; never selection or recommendation.
- `nutmeg/product/operator_settlement.py`: result readiness and presentation adapters only.
- `nutmeg/product/operator_maintenance.py`: fixed-argv, bounded, read-only OpenClaw and
  launchd ownership diagnostics; no scheduler mutation.
- `nutmeg/product/operator_queries.py`: v2 orchestration over the focused domain services.
- `nutmeg/product/operator_actions.py`: strict named command delegation to typed Actions.
- `nutmeg/product/repository.py`: product-facing read queries; no domain writes.
- `nutmeg/product/wiring.py`: compose v2 services without creating a Telegram poller.

### Ontology and deterministic services

- `nutmeg/ontology/repository/schema_operator_sale.py` and `operator_sale.py`: schedule checks,
  slate/offer revisions, stable offer families, and sale snapshots.
- `nutmeg/ontology/repository/schema_operator_decision.py` and `operator_decision.py`: evidence
  freezes, baseline/envelope/judgment/prescription/candidate/no-ticket/lineage revisions.
- `nutmeg/ontology/repository/schema_operator_result.py` and `operator_result.py`: ticket notes,
  result evidence, outcomes, fixed-prize policy, grades, task settlement receipts, and cash
  links.
- `nutmeg/ontology/repository/schema_operator_review.py` and `operator_review.py`: review
  dispositions, observation links, and completion receipts.
- `nutmeg/ontology/operator/models.py`: frozen rows, closed enums, token/hash helpers.
- `nutmeg/ontology/operator/sale_actions.py`: schedule/check imports and sale snapshot Actions.
- `nutmeg/ontology/operator/evidence_actions.py`: strict evidence manifest ingest and freeze
  request execution.
- `nutmeg/ontology/operator/decision_actions.py`: baseline, envelope, judgment, prescription,
  candidate generation/selection, audit binding, override, and no-ticket Actions.
- `nutmeg/ontology/operator/confirmation.py`: effective-cutoff CAS and terminal receipts.
- `nutmeg/ontology/operator/result_actions.py`: result/fixed-policy imports and task settlement.
- `nutmeg/ontology/operator/review_actions.py`: disposition/link/completion Actions.
- `nutmeg/ontology/repository/migrations.py`, `unit_of_work.py`, and
  `nutmeg/ontology/wiring.py`: migrations 17-25 and service composition.

### Interfaces and assets

- `nutmeg/interfaces/operator_api.py`: `/api/v2/operator` GETs and named mutation allowlist.
- `nutmeg/interfaces/product_api.py`: shared security/error middleware, mode-based mounts, and
  405 guards for legacy/generic mutation paths.
- `nutmeg/interfaces/operator_ui.py`: Today, lane, task, evidence, audit-detail, and recovery
  pages selected by the v2 resolver.
- `nutmeg/interfaces/cli/workflow.py`: strict official/evidence/result manifest commands.
- `nutmeg/interfaces/cli/product.py`: lease-aware app startup and worker lifespan.
- `scripts/openclaw/nutmeg_command_router.py`: delegate `ntc:` callbacks and supported ingest
  commands to the existing services; the native plugin invokes this bridge over stdin.
- `integrations/openclaw/nutmeg-ticket-confirmation/package.json`, `openclaw.plugin.json`, and
  `index.js`: repo-owned native OpenClaw plugin that registers the `ntc` Telegram interactive
  handler and owner-heartbeat service. Installation and enablement remain a user gate.
- `integrations/openclaw/nutmeg-ticket-confirmation/index.test.mjs`: Node built-in tests for
  registration, authorization, no-AI handling, and the real stdin bridge without requiring a
  production plugin install.
- `nutmeg/interfaces/web/templates/operator/`: replace generic v1 steps with Today/lane and
  v2 phase partials using only strict DTOs.
- `nutmeg/interfaces/web/static/product/operator.css` and `operator.js`: stable responsive
  layout and form transport; no domain calculations.
- `docs/application-operator-manual.md`: actual daily execution manual and recovery table.

### Tests and fixtures

- `tests/ontology/operator/`: migration, repository, Action, CAS, settlement, and review tests.
- `tests/product/operator_v2/`: contracts, state, lane, evidence, candidate, query/action/API,
  and UI tests.
- `tests/product/fixtures/operator/`: strict checked-in manifests for both lanes and legacy
  issues 26113-26116; no production database copies.
- `tests/product/test_operator_v2_e2e.py`: isolated full lifecycle for both lanes.
- `tests/product/test_operator_v2_browser.py`: Playwright desktop/mobile workflow and visual
  assertions.
- `tests/product/operator_v2/test_maintenance_ownership.py`: fixed-command parsing,
  overlap detection, failure visibility, and no-mutation assertions.

Do not add more v2 logic to the already large `nutmeg/product/queries.py` or generic
`nutmeg/product/actions.py`. Do not pass dictionaries from repositories into v2 templates.

### Infrastructure worker contract

`nutmeg app` owns one `OperatorInfrastructureWorkers` supervisor. Packages add consumers to
this registry rather than starting background tasks in Actions, queries, routes, or Telegram.
The final active order and exact completion Actions are:

| Order | Consumer | Source | Completion |
| --- | --- | --- | --- |
| 1 | evidence freeze | `operator_evidence_freeze_requests` | `freeze_evidence_bundle` per match, then `link_operator_task_evidence_freeze` |
| 2 | market baseline | completed task evidence-freeze claim | `freeze_market_prior_baseline` |
| 3 | candidate generation | `operator_candidate_generation_requests` | `generate_ticket_candidate_set` |
| 4 | confirmation deadline | due protected artifacts/challenge heads | existing `mark_ticket_shadow` via shared artifact CAS |
| 5 | task settlement | `operator_task_settlement_requests` | `settle_task` |
| 6 | review materialization | `operator_review_eligibility_facts` | `materialize_operator_review_item` |
| 7 | review completion | `operator_scoreboard_review_completion_requests` | `complete_scoreboard_review` |
| 8 | outbox/read model | committed outbox cursor | projection-only delivery/invalidation; no domain Action |

Judge requests and eligibility facts remain immutable. Migration 19 creates the shared
operational `operator_worker_jobs` table with one unique row per
`(job_kind, source_object_type, source_object_id)`, state
`queued | leased | completed | failed`,
`lease_owner`, `lease_expires_at`, `attempt_count`, `available_at`, `last_error_code`, and
nullable result Action/receipt. Each source Action appends its job atomically; later packages
reuse the same table instead of adding private loops. Each `run_once(limit)` recovers expired
leases, claims in creation/ID order, and processes one outer UOW per item. Retry only SQLite
contention, interrupted/expired leases, and errors marked retryable, with bounded exponential
backoff; validation, permission, stale-dependency, and invariant failures become visible
terminal failures. Completion idempotency keys are derived from the source row and exact
dependency revisions. Lease/error updates are operational; every successful business result
is the named typed Action.

The migration-19 `job_kind` check is closed from the start to `evidence_freeze`,
`market_baseline`, `candidate_generation`, `task_settlement`, `review_materialization`, and
`scoreboard_review_completion`. Deadline scanning and outbox projection are bounded scans,
not synthetic jobs. A package may leave a future kind unclaimed until its consumer ships, but
must never reinterpret or drop its durable row.

The active lifespan recovers leases and starts the registry before serving HTTP. It stops new
claims in reverse order, lets each current bounded transaction finish, then releases leases.
Production `legacy_read_only` and `shadow` run only deadline, outbox, and read-model consumers;
queued decision/result/review work stays durable. Isolated active runs all installed
consumers. Package 9 wires consumers 1-4 and 8, Package 10 adds 5, Package 11 adds 6-7, and
Package 12 proves the complete registry through TestClient lifespan without direct
`run_once()` calls.

## Package 1: Single-instance lock and read-only rollout shell

**Branch:** `feat/operator-runtime-shell`

**Files:**

- Create: `nutmeg/product/operator_runtime.py`
- Create: `nutmeg/product/operator_tokens.py`
- Create: `nutmeg/interfaces/operator_api.py`
- Create: `nutmeg/interfaces/web/templates/operator/read_only_shell.html`
- Create: `tests/product/operator_v2/test_runtime.py`
- Create: `tests/product/operator_v2/test_snapshot_tokens.py`
- Create: `tests/product/operator_v2/test_guarded_migration.py`
- Modify: `nutmeg/config/settings.py`
- Modify: `nutmeg/interfaces/cli/product.py`
- Modify: `nutmeg/interfaces/cli/ontology.py`
- Modify: `nutmeg/interfaces/product_api.py`
- Modify: `nutmeg/interfaces/operator_ui.py`
- Modify: `nutmeg/ontology/repository/unit_of_work.py`
- Modify: `nutmeg/ontology/wiring.py`
- Modify: `nutmeg/product/wiring.py`
- Modify: `nutmeg/interfaces/web/templates/operator/layout.html`
- Modify: `nutmeg/interfaces/web/templates/operator/task.html`
- Modify: `nutmeg/interfaces/web/templates/operator/steps/audit_deployment.html`
- Modify: `nutmeg/interfaces/web/templates/operator/steps/await_confirmation.html`
- Modify: `nutmeg/interfaces/web/templates/operator/steps/construct_ticket.html`
- Modify: `nutmeg/interfaces/web/templates/operator/steps/judge_matches.html`
- Modify: `nutmeg/interfaces/web/templates/operator/steps/review.html`
- Modify: `nutmeg/interfaces/web/static/product/operator.css`
- Modify: `nutmeg/interfaces/web/static/product/operator.js`
- Test: `tests/product/conftest.py`
- Test: `tests/product/test_operator_api.py`
- Test: `tests/product/test_operator_ui.py`
- Test: `tests/product/test_cli.py`
- Test: `tests/product/test_m3_copilot.py`
- Test: `tests/product/test_api.py`
- Test: `tests/product/test_m1_e2e.py`
- Test: `tests/product/test_m2_api.py`
- Test: `tests/product/test_m2_e2e.py`
- Test: `tests/product/test_m3_api.py`
- Test: `tests/product/test_m3_e2e.py`
- Test: `tests/product/test_m4_api.py`
- Test: `tests/product/test_m4_e2e.py`
- Test: `tests/product/test_m5_api.py`
- Test: `tests/product/test_m6_api.py`
- Test: `tests/product/test_m6_e2e.py`
- Test: `tests/product/test_m6_performance.py`
- Test: `tests/product/test_m6_ui.py`
- Test: `tests/product/test_operator_e2e.py`
- Test: `tests/product/test_operator_browser.py`

- [ ] **Step 1: Write failing settings and runtime-mode tests**

Create `tests/product/operator_v2/test_runtime.py` with explicit coverage for defaults,
invalid enum values, production/candidate path equality, accepted-commit mismatch, dirty or
unresolved running commits, and all four legal scope/mode combinations:

```python
from pathlib import Path

import pytest

from nutmeg.config.settings import AppSettings
from nutmeg.product.operator_runtime import (
    OperatorRuntimeScope,
    OperatorSurfaceMode,
    validate_operator_runtime,
)


def test_operator_runtime_defaults_are_read_only_production(tmp_path: Path) -> None:
    settings = AppSettings(
        data_dir=tmp_path / "data",
        production_data_dir=tmp_path / "data",
        _env_file=None,
    )
    assert settings.operator_surface_mode is OperatorSurfaceMode.LEGACY_READ_ONLY
    assert settings.operator_runtime_scope is OperatorRuntimeScope.PRODUCTION


def test_production_active_requires_three_identical_clean_commits(tmp_path: Path) -> None:
    settings = AppSettings(
        data_dir=tmp_path / "prod",
        production_data_dir=tmp_path / "prod",
        operator_surface_mode="active",
        operator_runtime_scope="production",
        candidate_commit="a" * 40,
        operator_accepted_commit="b" * 40,
        _env_file=None,
    )
    with pytest.raises(ValueError, match="accepted.*candidate.*running"):
        validate_operator_runtime(settings, running_commit="a" * 40, dirty=False)


def test_isolated_active_rejects_production_path_and_side_effects(tmp_path: Path) -> None:
    settings = AppSettings(
        data_dir=tmp_path / "prod",
        production_data_dir=tmp_path / "prod",
        operator_surface_mode="active",
        operator_runtime_scope="isolated_candidate",
        telegram_bot_token="secret",
        _env_file=None,
    )
    with pytest.raises(ValueError, match="isolated candidate data directory"):
        validate_operator_runtime(settings, running_commit="a" * 40, dirty=False)
```

Every settings construction in this package passes `_env_file=None`, because the repository
has a configured production `.env` and an isolated test must never inherit its Telegram token
or runtime switches. Parameterize the exact legal matrix: production with
`legacy_read_only`, `shadow`, or `active`, and isolated candidate with `active` only. Reject
the other two isolated combinations and require a production scope data path to resolve
exactly to `production_data_dir`. In production active only, reject empty, short, non-hex,
unresolved, or dirty commit identities even when all three strings happen to match. Isolated
active is the development/acceptance scope and may run from an identifiable dirty checkout;
add an explicit passing test so the production acceptance rule cannot spread to that scope.

- [ ] **Step 2: Run the runtime test and verify RED**

Run:

```bash
uv run pytest tests/product/operator_v2/test_runtime.py -v
```

Expected: collection fails because `nutmeg.product.operator_runtime` and the settings fields
do not exist.

- [ ] **Step 3: Add closed runtime settings and validation**

Add these settings and keep secrets `repr=False`:

```python
import re


class OperatorSurfaceMode(StrEnum):
    LEGACY_READ_ONLY = "legacy_read_only"
    SHADOW = "shadow"
    ACTIVE = "active"


class OperatorRuntimeScope(StrEnum):
    PRODUCTION = "production"
    ISOLATED_CANDIDATE = "isolated_candidate"


def validate_operator_runtime(
    settings: AppSettings,
    *,
    running_commit: str,
    dirty: bool,
) -> OperatorRuntimeConfig:
    data_dir = settings.data_dir.resolve()
    production_dir = settings.production_data_dir.resolve()
    pair = (settings.operator_runtime_scope, settings.operator_surface_mode)
    legal_pairs = {
        (OperatorRuntimeScope.PRODUCTION, OperatorSurfaceMode.LEGACY_READ_ONLY),
        (OperatorRuntimeScope.PRODUCTION, OperatorSurfaceMode.SHADOW),
        (OperatorRuntimeScope.PRODUCTION, OperatorSurfaceMode.ACTIVE),
        (OperatorRuntimeScope.ISOLATED_CANDIDATE, OperatorSurfaceMode.ACTIVE),
    }
    if pair not in legal_pairs:
        raise ValueError("illegal operator runtime scope/mode")
    if (
        settings.operator_runtime_scope is OperatorRuntimeScope.PRODUCTION
        and data_dir != production_dir
    ):
        raise ValueError("production data directory must match configured production path")
    if settings.operator_runtime_scope is OperatorRuntimeScope.ISOLATED_CANDIDATE:
        if data_dir == production_dir:
            raise ValueError("isolated candidate data directory must differ from production")
        if settings.telegram_bot_token or settings.operator_scheduler_enabled:
            raise ValueError("isolated candidate side effects must be disabled")
    if (
        settings.operator_runtime_scope is OperatorRuntimeScope.PRODUCTION
        and settings.operator_surface_mode is OperatorSurfaceMode.ACTIVE
    ):
        commits = (
            settings.operator_accepted_commit,
            settings.candidate_commit,
            running_commit,
        )
        if (
            dirty
            or not all(re.fullmatch(r"[0-9a-f]{40}", value or "") for value in commits)
            or len(set(commits)) != 1
        ):
            raise ValueError("accepted, candidate, and running commits must match cleanly")
    return OperatorRuntimeConfig(
        surface_mode=settings.operator_surface_mode,
        runtime_scope=settings.operator_runtime_scope,
        data_dir=data_dir,
        production_data_dir=production_dir,
        running_commit=running_commit,
    )
```

Add `operator_surface_mode`, `operator_runtime_scope`, `production_data_dir`,
`operator_accepted_commit`, `telegram_update_owner`, and
`operator_scheduler_enabled=False` to `AppSettings` with the exact defaults from the spec.
Define both enums in `settings.py` and re-export them from `operator_runtime.py`, avoiding a
settings/runtime import cycle. Add an injectable source-identity probe that returns the full
40-character running commit and dirty state; production active startup accepts neither a
request-supplied identity nor a shortened revision.

`production_data_dir` must be configured as an absolute path. `nutmeg app` adds an explicit
`--data-dir PATH`; isolated scope requires that option to be present and absolute, even when
an environment/default data directory happens to differ from production. Carry a
`data_dir_was_explicit` boolean into validation and test omitted, relative, equal, and valid
isolated paths separately.

- [ ] **Step 4: Write failing process-lease and route-matrix tests**

Use a subprocess for lease contention so the test proves OS ownership rather than an
in-memory singleton. Assert a second writer receives `app_instance_conflict`, a dead-PID lock
is reclaimed, and isolated data has its own lease. Add a second
`<data_dir>/state/ontology-writer.lock`: the Application holds a shared writer lease for its
lifespan, callback/CLI worker transactions can acquire compatible short shared leases, and a
maintenance subprocess can acquire the exclusive lease only after every writer releases it.
Prove exclusive contention is `ontology_maintenance_conflict` and that no PID-file or mtime
guess is accepted as ownership evidence.

Add a subprocess test for the guarded migration command:

```bash
nutmeg ontology guarded-init --data-dir <production-root> --backup-file <new-db-path>
```

Hold a normal UOW or Application shared writer lease and prove
the command fails before opening the backup. Release it, then prove one process retains the
same exclusive lock continuously across source audit, SQLite online backup, backup audit,
migration, and post-migration audit. Inject a writer attempt between each stage and require
every attempt to block. A plain `ontology init` must refuse a pending migration when its
resolved data directory equals the configured production directory; it remains legal for a
fresh isolated database.

Before any route, CLI, wiring, or template implementation, update the affected legacy tests
listed in this package and write new failing tests for all behavior below. Assert GETs in
shadow do not advance the Action high water. Cover all twelve existing write
families, not only the generic Action route: five `/api/v1/operator/tasks/...` POSTs, five
`/api/v1/ticket-*` POSTs, `/api/v1/actions`, and `/api/v1/matches/{id}/copilot`. Every one,
plus guessed `/api/v2/*` mutation paths other than the exact allowlisted endpoint, returns
405 before body parsing and leaves Actions/domain rows unchanged. `/` versus
`/operator-next` matches the four-row spec matrix. The route table must include these exact
assertions:

```python
@pytest.mark.parametrize(
    ("scope", "mode", "root_status", "next_status", "legacy_status", "v2_status"),
    [
        ("production", "legacy_read_only", 200, 404, 405, 405),
        ("production", "shadow", 200, 200, 405, 405),
        ("isolated_candidate", "active", 307, 200, 405, 422),
        ("production", "active", 200, 307, 405, 422),
    ],
)
def test_operator_route_matrix(
    app_factory, scope, mode, root_status, next_status, legacy_status, v2_status
) -> None:
    client = app_factory(scope=scope, mode=mode)
    assert client.get("/", follow_redirects=False).status_code == root_status
    assert client.get("/operator-next", follow_redirects=False).status_code == next_status
    assert client.post("/api/v1/actions", json={}).status_code == legacy_status
    assert client.post("/api/v2/operator", json={}).status_code == v2_status
```

The active-mode `422` proves the exact v2 endpoint reached strict DTO parsing rather than a
generic bypass. Both disabled-mode calls must leave Action and every domain count unchanged.
Add CLI tests proving validation/lease failures happen before service construction and
uvicorn, wiring tests for real-token rejection versus explicitly token-free simulated
transport, and shell/browser tests proving `/operator-next` performs no artifact, provider,
network, or Action call. Update `tests/product/conftest.py` and every Package 1 settings
fixture to pass `_env_file=None`; prove an isolated wiring test with an inherited real token
fails before constructing Telegram, while an explicitly token-free fixture receives only the
simulated transport. Add a clean-release test that reacquires the same instance path in the
same PID and proves the stable lock inode is not replaced. Run
`uv run pytest tests/product/ -q` now and retain the expected RED failures before Step 5.

- [ ] **Step 5: Implement the lease and mode-based route guards**

`ApplicationInstanceLease.acquire()` first attempts to create
`<data_dir>/state/operator-app.lock` with `O_CREAT | O_EXCL`, then opens it and takes
`fcntl.LOCK_EX | LOCK_NB`. Only a file proven newly created by that call may begin empty. For
an already existing file, validate its stale JSON only after `os.kill(pid, 0)` reports no
process, and fail closed for an empty record, missing/invalid PID, or malformed JSON. After
lock acquisition it writes PID/start/data/bind/port with
`seek(0)`, `truncate()`, canonical JSON, `flush()`, and `fsync()`, then keeps the descriptor
open through the uvicorn lifespan. The stable file is never unlinked: its canonical record
has `lease_state = held | released`; a clean `release()` writes `released`, a server release
time, and the prior owner facts under the lock, fsyncs, then unlocks and closes. A later owner
may accept a valid `released` record without treating the old PID as live ownership. It may
accept a `held` record only after `os.kill(pid, 0)` proves that PID absent. Empty, malformed,
or unverifiable existing records fail closed. This stable-inode protocol prevents the
unlink/open ABA race while allowing clean same-process restart. Map contention to the stable
`app_instance_conflict` error.

`OntologyWriterLease` uses the separate writer-lock descriptor and `fcntl.LOCK_SH` for normal
Application/CLI/callback ownership or `fcntl.LOCK_EX | LOCK_NB` for guarded maintenance. It
keeps the descriptor open for the full protected interval, records no authority in a stale
side file, and maps exclusive contention to `ontology_maintenance_conflict`. Application
startup acquires app-exclusive plus writer-shared locks in that fixed order and releases in
reverse order; migration tooling acquires only writer-exclusive and therefore proves that no
Application, callback, or worker using the v2 boundary owns the root.

Wire the shared lease into the ontology UOW factory so every formal Action transaction,
including existing CLI and OpenClaw writes, participates without each command remembering a
separate lock call. The UOW acquires before opening its SQL transaction and releases after
commit/rollback and connection close. The guarded migrator does not open a UOW; it acquires
one exclusive descriptor and keeps it open while it uses Python's SQLite online-backup API,
compares the source and backup schema/Action-high-water/key-count facts, runs
`kernel.initialize()`, and verifies the migrated source. It refuses an existing backup,
non-absolute paths, a backup outside `.nutmeg-data/archive`, a source-path mismatch, or any
pre/post fact mismatch, and never shells out or invokes a nested CLI.

In `create_product_app`, mount v2 reads only where the matrix permits them and install a
method/path guard before all twelve legacy POSTs and every non-allowlisted v2 mutation. The
guard returns 405 before request-body parsing. Register `/` and `/operator-next` explicitly
before the existing UI mount helpers so route order cannot expose the wrong root. Package 1's
`/operator-next` is a typed, read-only shell that performs no rx/artifact/provider/network
lookup; do not alias the current v1 operator task page because its deployment query can fetch
Renjiu history. Mark the legacy root visibly read-only and remove/hide its mutation forms.
Pass a server-owned read-only flag through `task.html` and the five phase templates above so
no legacy form is present in the DOM in any runtime mode; `operator.js` must not request a
session or attach mutation handlers on a read-only page.

Package 1 also defines a strict `extra="forbid"` base `OperatorCommandV2` envelope with
`schema_version="2"`, one closed `OperatorCommandKind`, `expected_snapshot_token`, and
`idempotency_key`. An empty, unknown, or extra-field body is 422. A syntactically valid known
kind whose business DTO is added only by a later package returns the stable non-writing
`command_unavailable` response; it never falls through to a generic Action executor. Later
packages replace that case one literal kind at a time with their discriminated DTO and named
handler.

Pass `OperatorRuntimeConfig` into `product/wiring.py`. Production must not construct another
inbound Telegram poller. In isolated active, an inherited/configured real token fails startup;
only after the caller explicitly clears all real Telegram/placement/scheduler configuration
does wiring inject a simulated confirmation transport. Test those as two separate cases.

In `nutmeg interfaces/cli/product.py`, enforce this order: load settings, probe source
identity, validate runtime, acquire Application and shared writer leases, build services,
create the app, call `uvicorn.run`, and release in reverse order in `finally`. Validation or
lease failure must occur before service construction; `app_instance_conflict` has a stable
message and nonzero exit code.

Implement `probe_source_identity(repo_root, runner) -> SourceIdentity` with fixed,
non-shell argv: `git -C <repo_root> rev-parse --verify HEAD` and
`git -C <repo_root> status --porcelain=v1 --untracked-files=normal`. The default repository
root is derived from the installed source module, not the current directory or a request.
The injected runner has a five-second timeout and bounded output. A non-repository, nonzero
exit, timeout, non-ASCII/oversized output, or non-40-hex revision returns an explicit
unresolved identity; production active validation then fails before building services.

- [ ] **Step 6: Write signed snapshot-token RED tests**

In `test_snapshot_tokens.py`, construct strict payloads containing `task_snapshot_hash`,
`work_item_id`, one literal `command_kind`, and the sorted complete set of dependency revision
IDs read by the form. Test round trip, one-byte payload/signature tampering, wrong key,
cross-command replay, wrong work item/task hash, duplicate/unsorted dependency rejection, and
a newly current dependency invalidating an old token. Assert exactly one `.` frame separator,
unpadded canonical base64url on both sides, rejection of `=`, whitespace, standard-base64
characters, extra frames, alternate JSON encodings, and a non-enum command kind. Assert the
signing key, token payload, and signature never appear in logs, error bodies, or rendered text.

- [ ] **Step 7: Implement the closed token codec and dependency verification**

Create `OperatorSnapshotTokenPayloadV1` with `extra="forbid"` and this closed command enum and
public codec contract:

```python
class OperatorCommandKind(StrEnum):
    FREEZE_EVIDENCE = "freeze_evidence"
    RECORD_BASELINE_ENVELOPE = "record_baseline_envelope"
    COMMIT_MATCH_JUDGMENT = "commit_match_judgment"
    FREEZE_JUDGMENT_PRESCRIPTION = "freeze_judgment_prescription"
    REQUEST_CANDIDATE_GENERATION = "request_candidate_generation"
    SELECT_CANDIDATE = "select_candidate"
    RECORD_NO_TICKET = "record_no_ticket"
    SUPERSEDE_NO_TICKET = "supersede_no_ticket"
    CREATE_TICKET_BATCH = "create_ticket_batch"
    ADJUDICATE_AUDIT_WARN = "adjudicate_audit_warn"
    APPROVE_TICKET_BATCH = "approve_ticket_batch"
    REQUEST_CONFIRMATION = "request_confirmation"
    REQUEST_SETTLEMENT = "request_settlement"
    GRADE_PREDICTION = "grade_prediction"
    RECORD_SCOREBOARD_EFFECT_DISPOSITION = "record_scoreboard_effect_disposition"
    RECORD_SCOREBOARD_OBSERVATION = "record_scoreboard_observation"
    REQUEST_SCOREBOARD_REVIEW_COMPLETION = "request_scoreboard_review_completion"
    REBUILD_SCOREBOARD_PROJECTION = "rebuild_scoreboard_projection"


class OperatorSnapshotTokenCodec:
    def encode(self, payload: OperatorSnapshotTokenPayloadV1) -> str: ...
    def decode(self, token: str) -> OperatorSnapshotTokenPayloadV1: ...
    def verify(
        self,
        token: str,
        *,
        expected_command_kind: OperatorCommandKind,
        current_task_snapshot_hash: str,
        current_work_item_id: str,
        current_dependency_revision_ids: Sequence[str],
    ) -> OperatorSnapshotTokenPayloadV1: ...
```

Serialize with the repository canonical JSON helper to UTF-8 `payload_bytes`. The wire format
is exactly
`base64url_no_pad(payload_bytes) + "." + base64url_no_pad(HMAC_SHA256(key, b"operator-snapshot-v1\\0" + payload_bytes))`.
Decode requires the re-encoded canonical payload segment to equal the received segment and
uses `hmac.compare_digest`. Add
`operator_token_signing_key` to settings with `repr=False`; require at least 32 bytes in any
active runtime, inject a fixed non-production key in isolated tests, and never derive it from
the Telegram token. Shadow mode emits no mutating form token when the key is absent.

Every command handler calls one verifier with its expected literal command kind, current task
hash, work-item ID, and freshly resolved sorted dependency IDs before invoking a domain
Action. A valid signature with stale dependencies returns `task_snapshot_changed`; a malformed
signature/encoding/payload or cross-command token returns `invalid_request` without decoded
content. Task hash, work-item, or dependency mismatch after valid signature verification
returns `task_snapshot_changed`.

- [ ] **Step 8: Verify, refactor, and commit Package 1**

Confirm the legacy-test conversions written in Step 4 now pass. Preserve useful lifecycle
coverage at the existing typed Action/service layer; do not add a test-only HTTP bypass.
Confirm legacy browser/UI tests cover the visibly read-only shell and the settings repr test
proves `operator_token_signing_key` is redacted.

Run:

```bash
uv run pytest tests/product/ -q
uv run ruff check nutmeg/product/operator_runtime.py nutmeg/product/operator_tokens.py nutmeg/product/wiring.py nutmeg/config/settings.py nutmeg/interfaces/cli/product.py nutmeg/interfaces/cli/ontology.py nutmeg/interfaces/product_api.py nutmeg/interfaces/operator_api.py nutmeg/interfaces/operator_ui.py nutmeg/ontology/repository/unit_of_work.py nutmeg/ontology/wiring.py tests/product
```

Expected: all tests pass; route GETs leave Action high water unchanged. Then stage only the
listed files and commit:

```bash
git commit -m "feat(product): add guarded operator runtime shell"
```

## Package 2: Official sale slate and dual-lane discovery

**Branch:** `feat/operator-official-sale-discovery`

**Files:**

- Create: `nutmeg/ontology/repository/schema_operator_sale.py`
- Create: `nutmeg/ontology/repository/operator_sale.py`
- Create: `nutmeg/ontology/operator/__init__.py`
- Create: `nutmeg/ontology/operator/models.py`
- Create: `nutmeg/ontology/operator/sale_actions.py`
- Create: `nutmeg/product/operator_lanes.py`
- Create: `tests/ontology/operator/test_sale_migration.py`
- Create: `tests/ontology/operator/test_sale_actions.py`
- Create: `tests/product/operator_v2/test_discovery.py`
- Create: `tests/product/operator_v2/test_sale_cli.py`
- Modify: `nutmeg/interfaces/cli/workflow.py`
- Modify: `scripts/openclaw/nutmeg_command_router.py`
- Modify: `tests/test_openclaw_router.py`
- Modify: `nutmeg/ontology/repository/migrations.py`
- Modify: `nutmeg/ontology/repository/unit_of_work.py`
- Modify: `nutmeg/ontology/wiring.py`
- Modify: `nutmeg/product/operator_state.py`

- [ ] **Step 1: Write migration 17 and repository RED tests**

Test fresh and v16 upgrade databases. Require these tables and constraints:

```text
official_sale_slate_revisions
official_offer_families
official_offer_revisions
official_schedule_check_receipts
```

Assert `(lane, business_key, revision_no)` and `(slate_family_id, content_hash)` uniqueness,
stable offer-family identity across slate revisions, one current leaf, foreign-key restricted
source retrievals, and one schedule-check receipt per Action. Assert only
`deterministic_system` may execute `import_official_sale_slate` and
`record_official_schedule_check`.

- [ ] **Step 2: Verify migration RED**

```bash
uv run pytest tests/ontology/operator/test_sale_migration.py -v
```

Expected: imports/tables for operator sale storage are missing.

- [ ] **Step 3: Implement migration 17 and repository rows**

Define frozen rows matching the spec and use canonical decimal/time strings. The migration
must only create new tables and permissions:

```python
Migration(
    version=17,
    name="operator_official_sale",
    fingerprint=(
        "official_sale_slate_revisions+official_offer_families+"
        "official_offer_revisions+official_schedule_check_receipts+operator_sale_permissions"
    ),
    apply=_apply_operator_official_sale,
)
```

Repository methods are exactly `current_slate(lane, business_key)`,
`slate_revision(id)`, `offer_revisions_for_slate(id)`,
`current_offer_by_family(family_id)`, `latest_schedule_check(lane, shanghai_date)`, and
their insert counterparts. Reads return frozen rows, never mappings.

- [ ] **Step 4: Write strict importer and Action RED tests**

Cover valid Zucai 14-order and multi-offer JCZQ manifests; unknown/extra fields; non-aware
times; `opens >= deadline`; duplicate match numbers; unresolved match IDs; unofficial
retrievals; invalid markets; bad supersession; idempotent replay; exact row-count receipts;
`slate_imported`, `confirmed_no_sale`, failed check states; and quarantine without a partial
slate. Use this minimal manifest shape:

```python
manifest = {
    "schema_version": "official-sale-slate-v1",
    "lane": "jczq",
    "business_key": "2026-09-04",
    "published_at": "2026-09-04T08:00:00+08:00",
    "retrieved_at": "2026-09-04T08:01:00+08:00",
    "official_source_artifact_retrieval_id": retrieval_id,
    "supersedes_slate_revision_id": None,
    "offers": [{
        "canonical_match_id": match_id,
        "official_match_no": "周五001",
        "market_definition_ids": ["md-had"],
        "sale_opens_at": "2026-09-04T08:00:00+08:00",
        "sale_deadline_at": "2026-09-04T19:00:00+08:00",
        "status": "on_sale",
    }],
}
```

- [ ] **Step 5: Implement strict sale/check Actions**

Use Pydantic `extra="forbid"` manifests and one `ActionService.execute()` transaction per
import. Derive `official_offer_family_id` from canonical JSON of lane, business key, official
match number, and canonical match ID. Assign a new `official_offer_revision_id` to each slate
revision. Never synthesize a deadline. Validate referenced retrieval,
match, and markets before inserts. The committed Action returns the slate plus every offer
revision and a count receipt; any mismatch raises inside the transaction.

`record_official_schedule_check` accepts exactly `slate_imported`, `confirmed_no_sale`, or
`failed`, enforces the cross-field rules in section 5.1, and cannot be called by the browser.

- [ ] **Step 6: Write official-sale CLI and OpenClaw-router RED tests**

Invoke the public CLI against a fresh temporary ontology and a checked-in manifest. Require
the exact commands and explicit contracts:

```text
uv run nutmeg workflow ingest-official-sale --manifest <path> --contract-version official-sale-slate-v1
uv run nutmeg workflow record-official-schedule-check --manifest <path> --contract-version official-schedule-check-v1
```

Assert business key, slate/check state, committed and persisted counts, and Action ID type in
machine output; malformed, mismatched, non-official, and duplicate manifests exit nonzero
without partial rows. Add router actions `operator-sale-ingest` and
`operator-schedule-check` that accept only a resolved manifest below the configured local
intake root and an exact contract version. Path traversal, inline JSON, URL input, and an
unknown contract are rejected before subprocess execution.

- [ ] **Step 7: Implement the two public official-sale entry points**

Both CLI commands parse and validate the complete file before calling the same deterministic
sale/check services tested above. They do not scrape, infer a business key, synthesize a
`confirmed_no_sale`, or accept raw payload text. The OpenClaw router only delegates the local
manifest reference to those CLI commands. These are the required starting boundary for every
Package 12 daily replay; the browser cannot call either Action.

- [ ] **Step 8: Write pure offer/snapshot/discovery resolver RED tests**

Test opening equality, deadline equality, explicit close/cancel, a removed offer, no raw
`as_of` hash churn, transition-driven hash change, new-offer/new-wave behavior, no-ticket
family preservation, rolling JCZQ deadlines, multiple Zucai issues, tomorrow presale,
recovery-only null focus, historical review focus, and all-closed archive landing.

- [ ] **Step 9: Implement lane protocol and deterministic discovery**

Expose this protocol and keep lane-specific market/order validation in adapters:

```python
class OperatorLaneAdapter(Protocol):
    lane: OperatorLane

    def validate_slate(self, slate: SaleSlateSnapshot) -> None:
        raise NotImplementedError

    def evidence_offer_ids(self, slate: SaleSlateSnapshot) -> Sequence[str]:
        raise NotImplementedError

    def candidate_inputs(self, slate: SaleSlateSnapshot) -> CandidateLaneInputs:
        raise NotImplementedError

    def result_offer_ids(self, slate: SaleSlateSnapshot) -> Sequence[str]:
        raise NotImplementedError
```

Implement `offer_state`, `task_snapshot_hash`, `derive_sale_wave`, `task_state`,
`today_priority_key`, and `focus_business_key` as pure functions. Equality at deadline is
terminal. Odds and forecast fields must not appear in ordering inputs.

- [ ] **Step 10: Verify and commit Package 2**

```bash
uv run pytest tests/ontology/operator/test_sale_migration.py tests/ontology/operator/test_sale_actions.py tests/product/operator_v2/test_sale_cli.py tests/product/operator_v2/test_discovery.py tests/ontology/test_migrations.py tests/test_openclaw_router.py -q
uv run pytest tests/product/test_operator_state.py tests/product/test_operator_queries.py -q
uv run ruff check nutmeg/ontology/operator nutmeg/ontology/repository/schema_operator_sale.py nutmeg/ontology/repository/operator_sale.py nutmeg/product/operator_lanes.py nutmeg/product/operator_state.py nutmeg/interfaces/cli/workflow.py scripts/openclaw/nutmeg_command_router.py tests/ontology/operator tests/product/operator_v2/test_sale_cli.py tests/product/operator_v2/test_discovery.py
```

Expected: all pass and migration 17 is idempotent. Commit:

```bash
git commit -m "feat(ontology): add official dual-lane sale discovery"
```

## Package 3: Versioned legacy importer and quarantine

**Branch:** `feat/operator-legacy-import`

**Files:**

- Create: `nutmeg/product/operator_legacy_import.py`
- Create: `tests/product/operator_v2/test_legacy_import.py`
- Create: `tests/product/fixtures/operator/legacy/26113-rx.json`
- Create: `tests/product/fixtures/operator/legacy/26114-rx.json`
- Create: `tests/product/fixtures/operator/legacy/26115-rx.json`
- Create: `tests/product/fixtures/operator/legacy/26116-rx.json`
- Create: `tests/product/fixtures/operator/legacy/26113-issue.json`
- Create: `tests/product/fixtures/operator/legacy/26113-prep.json`
- Create: `tests/product/fixtures/operator/legacy/26114-issue.json`
- Create: `tests/product/fixtures/operator/legacy/26114-prep.json`
- Create: `tests/product/fixtures/operator/legacy/26115-issue.json`
- Create: `tests/product/fixtures/operator/legacy/26115-prep.json`
- Create: `tests/product/fixtures/operator/legacy/26116-issue.json`
- Create: `tests/product/fixtures/operator/legacy/26116-prep.json`
- Modify: `nutmeg/product/operator_artifacts.py`
- Modify: `nutmeg/product/operator_queries.py`
- Modify: `nutmeg/interfaces/cli/workflow.py`
- Modify: `tests/product/test_operator_queries.py`

- [ ] **Step 1: Write golden legacy-import RED tests**

Copy only sanitized fixture shapes already represented by repository artifacts. Assert the
exact table from the spec: 26113 has 5 Predictions/6 Adjudications/4 non-deployable strings;
26114 has 5/7/3; 26115 has 6/5, four faceless non-deployable summaries; 26116 has 8/7,
eight face-bearing unaudited drafts and four summaries. Assert unknown schema versions,
missing fields, ambiguous face strings, and issue mismatch produce a typed quarantine report
and no partial workflow Actions. Import each issue/prep fixture independently and assert its
business key, official order, provenance state, committed counts, and idempotent receipt. An
issue/prep source lacking an official Sporttery retrieval is labelled `legacy_replay` and
cannot become production slate authority.

Before changing `_build_all()`, add two failing query tests in
`tests/product/test_operator_queries.py`: one creates a current official slate with no rx file
and requires the task to remain discoverable; the other writes an orphan `*-rx.json` without
an official slate and requires no task. Patch `ZucaiArtifactRepository.discover()` to raise if
called by the v2 query and assert the official-slate query still succeeds. These failures must
be observed before Step 3 or Step 4 changes production code.

- [ ] **Step 2: Verify legacy RED**

```bash
uv run pytest tests/product/operator_v2/test_legacy_import.py \
  tests/product/test_operator_queries.py -k "legacy_import or rx_file_cannot_create_task or official_slate_survives_missing_rx" -v
```

Expected: `operator_legacy_import` is missing and the two authority tests fail against the
legacy rx discovery path.

- [ ] **Step 3: Implement closed v2/v3 models and deterministic mapping**

Define `LegacyZucaiRxV2`, `LegacyZucaiRxV3`, `LegacyCandidateDraft`, and
`LegacyImportReceipt` with `extra="forbid"`. The CLI requires the explicit option
`--contract-version zucai-legacy-rx-v2|zucai-legacy-rx-v3`; never inspect arbitrary keys to
select a version. Reuse `map_rx_predictions` and `map_rx_adjudications` only after the
selected strict model has validated. Candidate strings never become `TicketCandidate`
objects:

```python
def classify_legacy_candidate(raw: LegacyCandidateInput) -> LegacyCandidateDraft:
    if raw.faces is None:
        return LegacyCandidateDraft(
            label=raw.label,
            deployable=False,
            reason_code="legacy_faces_missing",
            faces=None,
        )
    return LegacyCandidateDraft(
        label=raw.label,
        deployable=False,
        reason_code="legacy_audit_required",
        faces=raw.faces,
    )
```

The CLI `workflow import-legacy-operator --manifest --contract-version <declared-version>`
records typed existing Actions and one source-artifact-backed receipt. Issue/prep import uses
its own declared contract option and receipt. Neither path discovers current tasks; only
current official slates do.

- [ ] **Step 4: Remove rx filename discovery authority to satisfy the RED tests**

Change `OperatorQueryService._build_all()` to start from official lane discovery. Keep
`ZucaiArtifactRepository` only behind the explicit legacy import/fixture adapter. A missing
`*-rx.json` cannot remove a valid official task, and an old rx file cannot create one.

- [ ] **Step 5: Verify and commit Package 3**

```bash
uv run pytest tests/product/operator_v2/test_legacy_import.py tests/product/test_operator_artifacts.py tests/decision/test_rx_ingest.py -q
uv run ruff check nutmeg/product/operator_legacy_import.py nutmeg/product/operator_artifacts.py nutmeg/product/operator_queries.py tests/product/operator_v2/test_legacy_import.py
```

Expected: all golden counts match and no legacy candidate is deployable. Commit:

```bash
git commit -m "feat(product): quarantine versioned legacy operator artifacts"
```

## Package 4: Strict evidence policy and external ingest

**Branch:** `feat/operator-evidence-gate`

**Files:**

- Create: `nutmeg/ontology/operator/evidence_manifest.py`
- Create: `nutmeg/ontology/operator/evidence_actions.py`
- Create: `nutmeg/product/operator_evidence.py`
- Create: `nutmeg/ontology/repository/schema_operator_decision.py`
- Create: `nutmeg/ontology/repository/operator_decision.py`
- Create: `tests/ontology/operator/test_evidence_migration.py`
- Create: `tests/ontology/operator/test_evidence_ingest.py`
- Create: `tests/product/operator_v2/test_evidence_policy.py`
- Create: `tests/product/operator_v2/test_evidence_cli.py`
- Create: `tests/product/fixtures/operator/evidence/jczq-valid.json`
- Create: `tests/product/fixtures/operator/evidence/zucai-valid.json`
- Modify: `nutmeg/ontology/repository/migrations.py`
- Modify: `nutmeg/ontology/repository/unit_of_work.py`
- Modify: `nutmeg/ontology/wiring.py`
- Modify: `nutmeg/interfaces/cli/workflow.py`
- Modify: `scripts/openclaw/nutmeg_command_router.py`
- Modify: `tests/test_openclaw_router.py`
- Modify: `docs/sop/RUNBOOK.md`

- [ ] **Step 1: Write manifest and migration 18 RED tests**

Test the complete `EvidenceIntakeManifestV1` discriminated unions from spec section 6.3.
Reject unknown/extra fields, object-valued free-form payloads, unknown predicates,
verification methods or requirement IDs, negative recent-form counts, duplicate sample refs,
and recent-form totals that do not equal distinct samples. Require migration 18 tables:

```text
operator_evidence_intake_receipts
operator_evidence_coverage_receipts
operator_evidence_intake_objects
```

Each receipt binds the parent Action, task/slate snapshot, source retrievals, manifest hash,
committed/rejected/skipped counts, and persisted-row count. Only
`deterministic_system` receives `ingest_operator_evidence_manifest`.

- [ ] **Step 2: Verify evidence contract RED**

```bash
uv run pytest tests/ontology/operator/test_evidence_migration.py tests/ontology/operator/test_evidence_ingest.py -v
```

Expected: the evidence manifest and migration 18 do not exist.

- [ ] **Step 3: Implement closed manifests and atomic ingest Action**

Use `Annotated[ObservationInput, Field(discriminator="kind")]` and the corresponding closed
claim union. Validate the complete manifest and all retrieval/entity/match/slate references before opening the
write handler. Execute one typed `ingest_operator_evidence_manifest` Action that inserts the
objects plus receipt in one UOW. Claims always start `provisional`; the manifest cannot
verify/dispute/retract them. Coverage rows are pointers only:

```python
class EvidenceCoverageReceiptV1(StrictManifest):
    requirement_id: Literal["E1", "E2", "E3", "E4", "E5", "E6a", "E6b", "EC"]
    subject_scope: str = Field(min_length=1)
    evidence_ref_tokens: list[str] = Field(min_length=1)


class EvidenceIntakeReceiptRow:
    action_id: str
    task_snapshot_hash: str
    manifest_sha256: str
    committed_count: int
    rejected_count: int
    skipped_count: int
    persisted_count: int
```

The handler asserts `committed_count == persisted_count`, `rejected_count == 0`, and
`skipped_count == 0` before commit. An invalid object rolls back the parent receipt and every
object. Idempotent replay returns the existing receipt.

- [ ] **Step 4: Write E1-E6b/EC evaluation RED tests**

Use table-driven tests at `cutoff - 6h`, exactly `cutoff - 6h`, and one microsecond stale;
repeat for 24h and 72h requirements. Test provisional/ambiguous/merged identities, absent
rows, one official plus one international quote, Claim validity intervals, two-source
corroboration, positive `no_known_absence`, positive
`no_material_structural_change`, conflict/retraction combinations, and whole-task counts for
14-leg Zucai and current-open-only JCZQ. Assert coverage receipts alone never pass.

```python
@pytest.mark.parametrize(
    ("observed_at", "expected"),
    [
        (CUTOFF - timedelta(hours=6), EvidenceState.COMPLETE),
        (CUTOFF - timedelta(hours=6, microseconds=1), EvidenceState.STALE),
    ],
)
def test_market_freshness_boundary(observed_at, expected, evidence_fixture) -> None:
    status = evaluate_requirement("E3", evidence_fixture(observed_at), cutoff=CUTOFF)
    assert status.state is expected
```

- [ ] **Step 5: Implement the deterministic evidence evaluator**

Expose `evaluate_match_requirements(snapshot, cutoff)` and
`evaluate_task_evidence(snapshot, cutoff)`. Return frozen `RequirementStatus` rows with
`missing_ref_tokens`, `stale_ref_tokens`, and `conflict_ref_tokens`; never a Boolean without
diagnostics. Use instant comparisons, not ISO-string ordering. Only verified Observations or
separately adjudicated Claims count. E1-E6b must all be complete and EC clear for every
required match.

- [ ] **Step 6: Write CLI, OpenClaw-router, and RUNBOOK contract RED tests**

In `test_evidence_cli.py`, invoke the exact CLI below with valid, quarantined, mismatched,
and count-reconciliation fixtures. Assert the valid run calls the same ingest Action and
prints the manifest hash plus committed/persisted counts; every invalid run exits nonzero and
adds no row. In `test_openclaw_router.py`, require a reference below the configured intake
root and the exact contract version; reject traversal, symlinks escaping the root, inline
JSON, URLs, unknown versions, and extra arguments before delegation. Add a governance-doc
test that fails until RUNBOOK names this bridge and keeps the v2 strict gate in shadow until
the CLI and gate ship together.

Run:

```bash
uv run pytest tests/product/operator_v2/test_evidence_cli.py tests/test_openclaw_router.py \
  tests/ontology/test_governance_docs.py -k "evidence or operator" -v
```

Expected: the CLI command, router allowlist, and synchronized RUNBOOK text are absent.

- [ ] **Step 7: Wire CLI/OpenClaw ingest and shadow-only RUNBOOK alignment**

Add:

```text
uv run nutmeg workflow ingest-evidence --manifest <path>
```

The command parses the strict manifest, invokes the one ingest service, prints manifest hash
and committed/persisted counts, and exits nonzero on quarantine or reconciliation failure.
The Telegram router accepts only a local manifest reference already inside the configured
intake directory; it delegates to the same service and never accepts arbitrary JSON in chat.
Update RUNBOOK A1/B evidence steps to state that v2 remains shadow until this command and
strict gate are deployed together.

- [ ] **Step 8: Verify and commit Package 4**

```bash
uv run pytest tests/ontology/operator/test_evidence_migration.py tests/ontology/operator/test_evidence_ingest.py tests/product/operator_v2/test_evidence_policy.py tests/product/operator_v2/test_evidence_cli.py tests/ontology/test_evidence_models.py tests/ontology/test_claim_adjudication.py -q
uv run pytest tests/test_openclaw_router.py -q
uv run ruff check nutmeg/ontology/operator/evidence_manifest.py nutmeg/ontology/operator/evidence_actions.py nutmeg/product/operator_evidence.py nutmeg/interfaces/cli/workflow.py tests/ontology/operator tests/product/operator_v2/test_evidence_policy.py
```

Expected: all pass and a rejected manifest leaves every tested table count unchanged. Commit:

```bash
git commit -m "feat(decision): enforce strict operator evidence intake"
```

## Package 5: Evidence freeze and version invalidation

**Branch:** `feat/operator-evidence-freeze`

**Files:**

- Modify: `nutmeg/ontology/repository/schema_operator_decision.py`
- Modify: `nutmeg/ontology/repository/operator_decision.py`
- Modify: `nutmeg/ontology/operator/evidence_actions.py`
- Create: `nutmeg/product/operator_workers.py`
- Modify: `nutmeg/product/operator_contracts.py`
- Modify: `nutmeg/product/operator_actions.py`
- Modify: `nutmeg/product/operator_queries.py`
- Modify: `nutmeg/interfaces/operator_api.py`
- Modify: `nutmeg/interfaces/operator_ui.py`
- Create: `nutmeg/interfaces/web/templates/operator/steps/prepare_evidence_v2.html`
- Create: `tests/ontology/operator/test_evidence_freeze_migration.py`
- Create: `tests/ontology/operator/test_evidence_freeze_actions.py`
- Create: `tests/product/operator_v2/test_evidence_invalidation.py`
- Create: `tests/product/operator_v2/test_evidence_freeze_api.py`
- Create: `tests/product/operator_v2/test_evidence_freeze_ui.py`
- Modify: `nutmeg/ontology/repository/migrations.py`

- [ ] **Step 1: Write migration 19 and freeze-request RED tests**

Require append-only `operator_evidence_freeze_requests`,
`operator_task_evidence_bundle_revisions`, and
`operator_task_evidence_bundle_items`, plus the operational `operator_worker_jobs` table
defined by the shared worker contract. Test one current leaf per task family, immutable
supersession, exact policy/slate/task/cutoff binding, per-match existing EvidenceBundle IDs,
requirement refs/states, market prior refs, conflicts cleared, content hash, request Action,
and deterministic task-link Action. Grant `request_evidence_freeze` only to
`judge_operator`; keep the existing `freeze_evidence_bundle` permission unchanged at
`deterministic_system`, and grant `link_operator_task_evidence_freeze` only to
`deterministic_system`. There is no second Action type that purports to freeze a match bundle.
Assert request creation atomically adds exactly one evidence-freeze job, replay adds none,
expired leases recover, and a terminal job retains its immutable source and result Action.
The successful `link_operator_task_evidence_freeze` Action atomically adds exactly one
`market_baseline` job sourced from the task-freeze revision.

- [ ] **Step 2: Verify freeze RED**

```bash
uv run pytest tests/ontology/operator/test_evidence_freeze_migration.py tests/ontology/operator/test_evidence_freeze_actions.py -v
```

Expected: migration 19 and request/task-link Actions are missing.

- [ ] **Step 3: Implement request plus deterministic worker completion**

The browser Action contains only current signed task/requirement tokens. The request handler
re-evaluates the entire gate and appends a queued request. `OperatorInfrastructureWorker`
claims it idempotently. For each required match it invokes the existing public
`freeze_evidence_bundle` Action as `deterministic_system`, preserving that exact Action type,
permission, bundle schema, and ledger evidence. Each call uses a deterministic idempotency key
bound to request/match/current dependency hashes.

After all required match bundles are committed, one
`link_operator_task_evidence_freeze` deterministic Action re-resolves them, verifies their
exact `freeze_evidence_bundle` Action IDs and request dependencies, reconciles
required/built/item counts, and persists the task-bundle revision. A failure may leave
individually valid match bundles, but never a falsely completed task link; retry reuses those
bundles and atomically appends the link. Do not call the existing bundle handler inside a
differently named parent Action.

```python
def process_evidence_freeze_request(request_id: str, *, as_of: datetime) -> ActionOutcome:
    request = repository.current_freeze_request(request_id)
    snapshot = sale_service.snapshot(request.task_id, as_of=as_of)
    gate = evidence_service.evaluate_task(snapshot, cutoff=request.cutoff_at)
    if not gate.complete:
        raise OptimisticConcurrencyError("evidence gate changed before freeze")
    bundles = tuple(
        bundle_actions.freeze_evidence_bundle(
            build_match_bundle_request(request, match_status)
        )
        for match_status in gate.matches
    )
    return evidence_actions.link_task_freeze(request, snapshot=snapshot, bundles=bundles)
```

Do not let the Web command submit `deterministic_system` or direct bundle IDs.

- [ ] **Step 4: Write invalidation RED tests**

Assert new evidence does not rewrite a frozen bundle; the query returns
`new_evidence_available`; explicit refreeze supersedes the current task bundle; a new slate,
offer-state boundary, evidence bundle, Forecast, prescription, candidate set, selection, or
audit revision makes every dependent token stale; and stale required market evidence blocks
artifact approval even when the old bundle remains readable.

- [ ] **Step 5: Implement dependency fingerprints and stale-token checks**

Store a canonical dependency fingerprint on each descendant. Add repository methods that
return the full current leaf set consumed by the Package 1 token verifier. Never
delete or mutate descendants; return `task_snapshot_changed` with a stable recovery link.
The operator task page may display the frozen revision and new-evidence flag but must not
render IDs/hashes outside audit drill-down.

- [ ] **Step 6: Write freeze command/API/UI RED tests**

Submit `freeze_evidence` through `/api/v2/operator` with a token signed for that command and
assert one judge request, no browser-supplied role/IDs, and a queued response. Test unknown
fields, a token signed for another command, stale requirements, and shadow/read-only 405s.
First advance the global Action high water beyond the scoreboard
projection and prove `freeze_evidence` still queues normally: evidence freeze has no scoreboard
dependency. Render complete, missing, stale, conflict, queued, and linked states
without raw refs or JSON; the only primary control appears when the gate is currently
complete. Test the named `rebuild_scoreboard_projection` maintenance command separately:
it rebuilds only the projection, changes neither Action high water nor `scoreboard.json`
checksum, and returns the source/projection high waters; all generic Action POSTs remain 405.

- [ ] **Step 7: Implement the strict freeze command and focused view**

Add the discriminated `FreezeEvidenceCommandV2` and delegate only to
`request_evidence_freeze`; worker progress is read from committed request/link receipts.
Evidence freeze has no scoreboard dependency and remains available when that projection is
stale. Expose the existing governed build-only `ScoreboardProjector.build` operation
separately as the strict `rebuild_scoreboard_projection` maintenance command; it never shells
out. Neither GET nor rebuild writes `scoreboard.json` or advances the Action ledger.

- [ ] **Step 8: Verify and commit Package 5**

```bash
uv run pytest tests/ontology/operator/test_evidence_freeze_migration.py tests/ontology/operator/test_evidence_freeze_actions.py tests/product/operator_v2/test_evidence_invalidation.py tests/product/operator_v2/test_evidence_freeze_api.py tests/product/operator_v2/test_evidence_freeze_ui.py tests/ontology/test_freeze_bundle.py -q
uv run ruff check nutmeg/ontology/operator/evidence_actions.py nutmeg/ontology/repository/operator_decision.py nutmeg/product/operator_workers.py nutmeg/product/operator_contracts.py nutmeg/product/operator_actions.py nutmeg/product/operator_queries.py nutmeg/interfaces/operator_api.py tests/ontology/operator tests/product/operator_v2
```

Expected: all pass and superseded rows remain queryable. Commit:

```bash
git commit -m "feat(decision): freeze versioned operator evidence"
```

## Package 6: Structured judgment and market baseline

**Branch:** `feat/operator-judgment-baseline`

**Files:**

- Modify: `nutmeg/ontology/repository/schema_operator_decision.py`
- Modify: `nutmeg/ontology/repository/operator_decision.py`
- Create: `nutmeg/ontology/operator/decision_actions.py`
- Modify: `nutmeg/product/operator_contracts.py`
- Modify: `nutmeg/product/operator_queries.py`
- Modify: `nutmeg/product/operator_actions.py`
- Modify: `nutmeg/product/operator_workers.py`
- Modify: `nutmeg/interfaces/operator_api.py`
- Modify: `nutmeg/interfaces/operator_ui.py`
- Create: `nutmeg/interfaces/web/templates/operator/steps/judge_matches.html`
- Create: `nutmeg/interfaces/web/templates/operator/steps/baseline_envelope.html`
- Create: `tests/ontology/operator/test_judgment_migration.py`
- Create: `tests/ontology/operator/test_judgment_actions.py`
- Create: `tests/product/operator_v2/test_judgment_api.py`
- Create: `tests/product/operator_v2/test_judgment_ui.py`
- Modify: `nutmeg/ontology/repository/migrations.py`

- [ ] **Step 1: Write migration 20 RED tests**

Require revision tables and normalized children for
`MarketPriorBaselineRevision`, `BaselineEnvelopeRevision`,
`OperatorMatchJudgmentRevision`, and `JudgmentPrescriptionRevision`. Every parent has family,
revision, supersedes, task/work-item/slate/bundle refs, content hash, Action ID, and timestamps.
Store probabilities and offsets as canonical decimal strings, not floats or opaque JSON.
Grant baseline freeze only to `deterministic_system`; envelope, judgment, and prescription
Actions only to `judge_operator`.

- [ ] **Step 2: Verify judgment migration RED**

```bash
uv run pytest tests/ontology/operator/test_judgment_migration.py -v
```

Expected: migration 20 tables are missing.

- [ ] **Step 3: Write baseline/envelope Action and worker RED tests**

In `test_judgment_actions.py`, require a market-prior baseline only after the exact governed
task freeze link; exact Snapshot/Quote/cutoff/policy/precision bindings; comparison-only
status; missing/conflicting market blocking; idempotency and supersession; and rollback on a
forced child failure. Require the envelope to preserve only the judge-submitted cap,
currency, offer/market/face/omission options, structure templates, and enumeration bound.
Assert the worker does not freeze a baseline before all existing match-bundle Actions and the
task link are committed.

- [ ] **Step 4: Implement baseline and envelope Actions**

`freeze_market_prior_baseline` copies exact market probabilities from bound Snapshots after
the task evidence freeze. It marks the object `comparison_only` and records precision,
arithmetic, cutoff, policy, and source refs. `record_baseline_envelope` accepts only the
strict `OfferConstraintInputV2` and `StructureTemplateInputV2` DTOs. Validate unique offer/
market/bundle/template codes, cap in integer minor units, positive explicit enumeration
limits, and lane-specific SFC/Renjiu/JCZQ structural rules. Do not infer any option.

The infrastructure worker consumes each `market_baseline` job idempotently and runs
`freeze_market_prior_baseline` before the work item can enter `judge_matches`. It marks the
job complete in the same outer UOW as that Action receipt. The
browser never supplies a `deterministic_system` role or baseline probabilities. A missing or
conflicting exact market Snapshot leaves a typed block and no partial baseline.

- [ ] **Step 5: Write exact judgment-invariant RED tests**

Test prior equality, zero delta with no Factor, nonzero delta with no Factor rejection,
multi-Factor exact reconstruction, offset zero sum, normalized belief sum exactly one at
stored precision, missing evidence anchors, unknown Rule/Factor/face/market, stale bundle,
AI role denial, and progress counted only from committed current judgments. Use Decimal:

```python
def test_nonzero_belief_requires_exact_factor_reconstruction(judgment_service) -> None:
    request = judgment_request(
        prior={"3": "0.400000000000", "1": "0.300000000000", "0": "0.300000000000"},
        belief={"3": "0.450000000000", "1": "0.280000000000", "0": "0.270000000000"},
        factors=[],
    )
    with pytest.raises(ValueError, match="non-zero.*Factor"):
        judgment_service.commit(request)
```

- [ ] **Step 6: Implement judgment and prescription Actions**

Extract the existing Forecast/Read handler so it can execute against a caller-supplied UOW;
the public legacy Action keeps its current wrapper, while `commit_operator_match_judgment`
opens one `ActionService.execute()` transaction and calls that handler before appending the
operator judgment link. Neither service may call the other's public commit method, because
that would commit one half before the other. Force a failure after each insert in tests and
assert that the Forecast/Read row, judgment link, and parent Action all roll back together.
Quantize to 12 places with `ROUND_HALF_EVEN`; reconstruct
`belief = prior + sum(offsets)` per face and require the exact stored strings to match.
Expression bundles, Factor IDs, Rule IDs, evidence refs, falsifier, and rationale are explicit
judge fields. `freeze_judgment_prescription` succeeds only when every required match has a
current judgment bound to the same task bundle.

- [ ] **Step 7: Write strict judgment DTO/API/UI RED tests**

Post every judgment and envelope command through the v2 route. Reject extra fields, floats,
anonymous mappings, actor/role/policy fields, a token for another command, stale dependencies,
and AI authority. Test atomic Forecast/Read plus judgment linkage through the public boundary.
Render every evidence/baseline/envelope/judgment state and assert the form contains named
typed controls, no raw JSON/IDs, and advances only after a committed response.

- [ ] **Step 8: Replace v1 dynamic judgment DTO/API/UI with strict v2**

Add the spec's `FaceProbabilityInputV2`, `FaceOffsetInputV2`, `FactorAdjustmentInputV2`, and
`FaceBundleInputV2`. Each `/api/v2/operator` POST body has
`schema_version="2"`, a literal `kind`, opaque snapshot token, and idempotency key; actor,
role, policy, and IDs are server-owned. The Jinja editor shows evidence status, prior,
movement, belief, delta, Factors, Rules, faces, falsifier, and reason. It posts no arbitrary
mapping and advances to the next unresolved match after a committed response.

- [ ] **Step 9: Verify and commit Package 6**

```bash
uv run pytest tests/ontology/operator/test_judgment_migration.py tests/ontology/operator/test_judgment_actions.py tests/product/operator_v2/test_judgment_api.py tests/product/operator_v2/test_judgment_ui.py tests/ontology/test_commit_forecast.py -q
uv run ruff check nutmeg/ontology/operator/decision_actions.py nutmeg/product/operator_contracts.py nutmeg/product/operator_queries.py nutmeg/product/operator_actions.py nutmeg/interfaces/operator_api.py tests/ontology/operator tests/product/operator_v2
```

Expected: all pass, rejected Actions do not advance progress, and normal responses contain no
raw IDs or payload JSON. Commit:

```bash
git commit -m "feat(decision): add structured operator judgments"
```

## Package 7: Exhaustive candidate comparison

**Branch:** `feat/operator-candidate-comparison`

**Files:**

- Modify: `nutmeg/ontology/repository/schema_operator_decision.py`
- Modify: `nutmeg/ontology/repository/operator_decision.py`
- Create: `nutmeg/ontology/repository/schema_operator_result.py`
- Create: `nutmeg/ontology/repository/operator_result.py`
- Modify: `nutmeg/ontology/operator/decision_actions.py`
- Create: `nutmeg/ontology/operator/result_actions.py`
- Create: `nutmeg/product/operator_candidates.py`
- Modify: `nutmeg/product/operator_contracts.py`
- Modify: `nutmeg/product/operator_queries.py`
- Modify: `nutmeg/product/operator_actions.py`
- Modify: `nutmeg/product/operator_workers.py`
- Create: `nutmeg/interfaces/web/templates/operator/steps/compare_tickets.html`
- Create: `tests/ontology/operator/test_candidate_migration.py`
- Create: `tests/ontology/operator/test_candidate_actions.py`
- Create: `tests/product/operator_v2/test_candidates.py`
- Create: `tests/product/operator_v2/test_candidate_ui.py`
- Modify: `docs/sop/RUNBOOK.md`
- Modify: `docs/sop/RULEBOOK.md`
- Modify: `nutmeg/ontology/repository/migrations.py`
- Modify: `nutmeg/ontology/repository/unit_of_work.py`
- Modify: `nutmeg/ontology/wiring.py`

- [ ] **Step 1: Write migration 21 and bounded-enumeration RED tests**

Require these normalized candidate-generation request, candidate-set, candidate,
ticket/note/leg-composition, metric, audit finding, selection, and fixed-prize policy tables:

```text
operator_candidate_generation_requests
operator_candidate_set_revisions
operator_candidates
operator_candidate_tickets
operator_candidate_ticket_legs
operator_candidate_metrics
operator_candidate_audit_findings
operator_candidate_selections
zucai_fixed_prize_policy_revisions
zucai_fixed_prize_policy_tiers
```

The candidate composition is already the complete future settlement input, not a face-summary
JSON blob:

```text
operator_candidate_tickets
  candidate_ticket_id, candidate_revision_id, ticket_index
  ticket_kind, structure_code, group_code, currency
  unit_stake_minor, unit_count, stake_minor, composition_hash
  fixed_prize_policy_revision_id
operator_candidate_ticket_legs
  candidate_ticket_id, leg_index, official_offer_revision_id, match_id
  market_definition_id, selection_code, quote_id
  booked_decimal_odds, settlement_parameter_decimal
zucai_fixed_prize_policy_revisions
zucai_fixed_prize_policy_tiers
```

JCZQ legs require the exact Quote, positive canonical Decimal booked odds, and the signed HHAD
line where applicable. Zucai legs require null quote/odds/line fields and bind the same policy
revision as their candidate ticket. `unit_count`, integer-minor stake, currency, complete
composition, and Zucai policy are therefore fixed before comparison and cannot be invented by
Package 9 placement.

Migration 21 also appends the three official CRS aggregate selections `win_other`,
`draw_other`, and `loss_other` under `md-crs`. It preserves the legacy `other` row for audit
history but marks it non-deployable; candidate validation must reject any current leg that
still uses generic `other`. The later grader returns a bound exact score selection when one
exists, otherwise the direction-specific aggregate bucket. Test all three aggregates and a
legacy-generic rejection here so no incomplete candidate can reach an artifact.

Store the set kind as `judgment_bound` or `conditional_market_counterfactual`. Grant the
request only to `judge_operator`, generation and fixed-policy registration only to
`deterministic_system`, and selection only to `judge_operator`. Register immutable initial
`sfc` and `renjiu` CNY policies with `standard_unit_stake_minor=200`, the closed tier sets,
and `official_void_rule="all_faces_match"` before generating any Zucai candidate. A content
change appends a policy revision; no browser mutation exists. Test exact replay and revision
supersession. Test that the generator enumerates exactly the operator-declared finite space,
rejects a calculated count above `maximum_exhaustive_candidate_count` before enumeration,
and never truncates, beams, or prunes. Cover Zucai SFC 14, Renjiu exact 9 groups/multiple
tickets, and JCZQ declared markets/passes.

- [ ] **Step 2: Verify candidate RED**

```bash
uv run pytest tests/ontology/operator/test_candidate_migration.py tests/product/operator_v2/test_candidates.py -v
```

Expected: candidate tables and `operator_candidates` are missing.

- [ ] **Step 3: Implement migration 21, fixed policies, deterministic composition, and Decimal metrics**

Create the normalized tables and CRS selection upgrade proven by Step 1, register the initial
fixed-prize policies through the deterministic Action, and wire their repositories through
the UOW/kernel. Reuse existing Zucai composition/audit helpers where their contracts match;
wrap rather than copy them. For a ticket event, multiply each required offer's summed selected-face
probability. For a multi-ticket union, use exact inclusion-exclusion over ticket events;
incompatible intersections contribute zero. Quantize only the stored result:

```python
def union_probability(
    tickets: Sequence[TicketEvent],
    probabilities: ProbabilityMatrix,
) -> Decimal:
    total = Decimal("0")
    for size in range(1, len(tickets) + 1):
        sign = Decimal("1") if size % 2 else Decimal("-1")
        for subset in combinations(tickets, size):
            total += sign * intersection_probability(subset, probabilities)
    return total.quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN)
```

Calculate cost, cap utilization, expected broken legs, common dead faces, break-even bonus,
and official-median multiple deterministically. Persist unrounded canonical inputs in the
content hash. Do not calculate in JavaScript.

- [ ] **Step 4: Write generation-request, all-candidate audit, and worker RED tests**

Require the judge request to bind the exact task/baseline/envelope/prescription token set and
atomically append exactly one `candidate_generation` worker job; replay adds none and a stale
or cross-command token starts no work. Inject failures between the judgment-bound
and counterfactual sets and require neither set to commit. For every generated row assert the
leg audit, prescription-difference audit, budget check, and deployment report are persisted;
over-cap and ERROR rows remain visible but ineligible. Test the exact deterministic ordering,
no default selection, no recommendation field, and a conditional set that is permanently
non-deployable even when its composition equals a judgment-bound row.

- [ ] **Step 5: Implement generation worker and run every candidate through all audits before ordering**

Apply the current leg audit, prescription-difference audit, budget check, and lane deployment
report to every row. Persist `eligible`, `audit_blocked`, and `over_cap` partitions without
hiding any candidate. Require a named Rule ID for every prescription deviation. Eligible
sort is `objective_probability DESC, stake_minor ASC, content_hash ASC`; no field or label may
say `recommended`, and no candidate is selected by generation or GET.

`request_candidate_generation` stores exact baseline, envelope, prescription, current Quote,
settlement-parameter, currency/stake, and fixed-policy tokens.
The worker generates both the judgment-bound set and, when the same declared envelope is
valid against the market prior, the conditional market counterfactual set. The latter is
always `comparison_only`, cannot receive a selection token, and remains non-deployable even
when its composition equals a judgment-bound candidate. A worker failure commits neither
half; retry consumes the same request idempotently.

- [ ] **Step 6: Write selection and comparison API/UI RED tests**

Test a valid human selection, empty reason, conditional/baseline/over-cap candidate,
superseded set, wrong command token, and replay through `/api/v2/operator`. Render eligible,
audit-blocked, and over-cap rows in one comparison table with exact metrics and no hidden row,
prechecked control, `recommended` text/field, raw JSON, or internal ID. A rejected Action must
leave the work item in comparison.

- [ ] **Step 7: Add selection Action and comparison DTO/UI**

`select_ticket_candidate` is judge-only, accepts one opaque judgment-bound candidate token
and a non-empty reason, and rejects market-prior or conditional-counterfactual object kinds.
The comparison table displays all partitions, exact P label, stake/cap, expected broken legs,
dead faces, deviations, audits, and market difference. It starts with no radio row selected.

- [ ] **Step 8: Synchronize RUNBOOK/RULEBOOK objective text**

Replace lower-document break-even ranking instructions with the constitutional ordering
implemented above. Preserve break-even/median values as report-only data and preserve the
existing deployment-door language that leaves reduction/no-ticket judgment to Jun. Do not
modify `CONSTITUTION.md`.

- [ ] **Step 9: Verify 26111 and both lanes, then commit Package 7**

```bash
uv run pytest tests/ontology/operator/test_candidate_migration.py tests/ontology/operator/test_candidate_actions.py tests/product/operator_v2/test_candidates.py tests/product/operator_v2/test_candidate_ui.py tests/decision/test_zucai_optimizer.py tests/decision/test_zucai_optimizer_cli.py tests/decision/test_legs_audit.py -q
uv run pytest tests/ontology/test_governance_docs.py -q
uv run ruff check nutmeg/product/operator_candidates.py nutmeg/ontology/operator/decision_actions.py nutmeg/ontology/operator/result_actions.py nutmeg/ontology/repository/schema_operator_result.py nutmeg/ontology/repository/operator_result.py nutmeg/product/operator_contracts.py tests/ontology/operator tests/product/operator_v2
```

Replay the checked-in 26111 U864 family and assert objective P values
`0.279600000000`, `0.244900000000`, and `0.336500000000` for the matching recorded versions.
Expected: all tests pass, no row is auto-selected, and no normal DTO contains
`recommended=True`. Commit:

```bash
git commit -m "feat(decision): compare exhaustive operator candidates"
```

## Package 8: Override, no-ticket, protected artifact, and complete lineage

**Branch:** `feat/operator-deployment-adjudication`

**Files:**

- Modify: `nutmeg/ontology/repository/schema_operator_decision.py`
- Modify: `nutmeg/ontology/repository/operator_decision.py`
- Modify: `nutmeg/ontology/repository/schema_tickets.py`
- Modify: `nutmeg/ontology/repository/tickets.py`
- Modify: `nutmeg/ontology/repository/schema_operator_result.py`
- Modify: `nutmeg/ontology/repository/operator_result.py`
- Modify: `nutmeg/ontology/operator/models.py`
- Modify: `nutmeg/ontology/operator/decision_actions.py`
- Create: `nutmeg/ontology/operator/confirmation.py`
- Modify: `nutmeg/ontology/operator/result_actions.py`
- Modify: `nutmeg/ontology/actions/protected_ticket_actions.py`
- Modify: `nutmeg/ontology/actions/workflow_actions.py`
- Modify: `nutmeg/decision/audit_override.py`
- Modify: `nutmeg/interfaces/cli/decision.py`
- Modify: `nutmeg/product/operator_contracts.py`
- Modify: `nutmeg/product/operator_state.py`
- Modify: `nutmeg/product/operator_queries.py`
- Modify: `nutmeg/product/operator_actions.py`
- Modify: `nutmeg/interfaces/operator_api.py`
- Create: `nutmeg/interfaces/web/templates/operator/steps/audit_deployment_v2.html`
- Create: `tests/ontology/operator/test_deployment_migration.py`
- Create: `tests/ontology/operator/test_lineage_actions.py`
- Create: `tests/ontology/operator/test_no_ticket_actions.py`
- Create: `tests/product/operator_v2/test_deployment_api.py`
- Create: `tests/product/operator_v2/test_deployment_replay.py`
- Create: `tests/product/operator_v2/test_no_ticket_ui.py`
- Modify: `tests/decision/test_audit_override.py`
- Modify: `tests/ontology/test_protected_ticket_actions.py`
- Modify: `nutmeg/ontology/repository/migrations.py`
- Modify: `nutmeg/ontology/repository/unit_of_work.py`
- Modify: `nutmeg/ontology/wiring.py`

- [ ] **Step 1: Write migration 22 and authority RED tests**

Require append-only revisions and normalized children for:

```text
operator_ticket_decision_lineage_revisions
operator_ticket_decision_lineage_items
operator_ticket_audit_override_receipts
operator_candidate_generation_override_links
operator_no_ticket_revisions
operator_no_ticket_offer_scopes
operator_no_ticket_artifact_scopes
operator_no_ticket_command_receipts
operator_artifact_work_item_links
operator_protected_artifact_bindings
operator_protected_artifact_offer_revision_links
operator_confirmation_challenge_revisions
operator_confirmation_challenge_heads
operator_artifact_terminal_receipts
operator_review_eligibility_facts
```

Assert one current leaf per lineage/no-ticket family, immutable supersession, unique finding
bindings, one terminal receipt per artifact and per non-null challenge, restricted foreign
keys, and server-time fields. `operator_protected_artifact_bindings` has relational,
non-null `ticket_artifact_id`, `lineage_revision_id`, `candidate_revision_id`,
`candidate_ticket_id`, `ticket_index`, `ticket_kind`, `stake_minor`, `currency`,
`composition_hash`, and `frozen_deadline_at`; its nullable
`fixed_prize_policy_revision_id` is required for Zucai and forbidden for JCZQ. The child link
table preserves every ordered official offer revision. Require a restricted foreign key from
`candidate_ticket_id` to migration 21 and uniqueness on both `ticket_artifact_id` and the
bound `(candidate_revision_id, ticket_index)` so one artifact always identifies one concrete
ticket inside a multi-ticket candidate. The artifact payload may duplicate these values for
a signed receipt, but JSON is never their query or integrity authority.

`operator_artifact_terminal_receipts` stores a closed `terminal_kind = placed | shadow` and
an independent `terminal_reason`. Enforce `actual_placement_confirmed` only with `placed` and
all no-ticket/deadline/correction reasons only with `shadow`; no row overloads reason as state.
Create the empty challenge revision/head tables before this receipt table in the same
migration. Their exact keys are `challenge_revision_id` and `challenge_family_id`; the
receipt's nullable unique `challenge_revision_id` has a real restricted foreign key from its
first write. Package 8 creates no challenge and grants no confirmation authority.
`operator_review_eligibility_facts` records terminal trigger, task/work-item snapshot,
optional baseline, `operational_data_availability | forecast_truth`, and
`immediate | outcomes_required`. It is not a review row and has no disposition.

Require
`record_ticket_audit_override`, `record_no_ticket`, and `supersede_no_ticket` only for
`judge_operator`. No Web permission or command may expose
`record_ticket_audit_override`.

- [ ] **Step 2: Run the deployment migration tests and verify RED**

```bash
uv run pytest tests/ontology/operator/test_deployment_migration.py -v
```

Expected: migration 22 tables and permissions are absent.

- [ ] **Step 3: Write normalized lineage, override, and regeneration-request RED tests**

Test exact normalized baseline, bundle, Forecast/Read, judgment, prescription, candidate
set/candidate/**candidate ticket**, selection, audit-policy, finding, adjudication, and override refs; reject a
missing, superseded, or cross-batch dependency. Test an exact non-empty ERROR set,
prevalidation of all findings before the first write, the same committed deviation records,
current candidate hash and audit-policy version, idempotency, AI denial, and rollback after
each Adjudication/receipt insert. Assert no Web override command exists.

When eligibility changes, require the override Action to append one Package 7 candidate-
generation request plus normalized links to all override receipts. Assert that no candidate
set or candidate row is written by the override transaction; the deterministic Package 7
worker alone consumes the request and creates a new judgment-bound set.

- [ ] **Step 4: Implement normalized lineage and one override Action**

Migration 22 appends only the tables above. Store the exact lineage refs in normalized items.
The write API accepts domain tokens, resolves IDs server-side, and rejects any missing or
superseded dependency.

Refactor the existing CLI override through this request without changing its human-only
surface:

```python
@dataclass(frozen=True, slots=True)
class TicketAuditOverrideInput:
    finding_token: str
    reason: str
    rule_ids: Sequence[str]


@dataclass(frozen=True, slots=True)
class RecordTicketAuditOverrideRequest:
    ticket_batch_token: str
    expected_snapshot_token: str
    overrides: Sequence[TicketAuditOverrideInput]
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime
```

`TicketAuditOverrideInput` contains one signed finding token, non-empty human reason, and
named Rule IDs. Require a non-empty exact ERROR set and the same deviation records committed
on the batch. Extract a UOW-level Adjudication insert helper so one transaction writes the
existing `evidence_rejected` Adjudication, its override receipt, and Action refs without
calling a second public Action. A forced failure after either insert must leave neither row.
Re-evaluation appends a new candidate-generation request linked to the receipts; it never
creates, edits, or reorders a candidate set in the judge Action. The external CLI requires
`--ticket-batch-token` whenever `--user-override` is present; historical file-only overrides
remain non-deployable records.

- [ ] **Step 5: Write cutoff-first no-ticket and supersession RED tests**

Cover all five closed reason codes, non-empty reason text, human-submitted
`reason_basis = rule_derived | operator_judgment`, Rule IDs, judge-only
permission, server-derived scope, pre-evidence missing/stale/conflict capture, baseline and
candidate counterfactual capture, the envelope-present/candidate-not-yet-generated phase,
zero-placement and partially placed outcomes, per-family
scope preservation, newly added offer isolation, challenge invalidation, and idempotent
replay. At the exact cutoff, with the periodic scanner deliberately not run, assert expiry
wins and the no-ticket request returns `task_snapshot_changed` without relabelling the
terminal scope. Race no-ticket against a consumed challenge and assert exactly one terminal
receipt. Separately test `supersede_no_ticket` at cutoff minus one microsecond, equality, and
plus one microsecond; only the first may create a new sale-wave snapshot.

Software never maps a reason code to a basis. The operator explicitly supplies the basis;
`rule_derived` requires one or more current Rule IDs, while `operator_judgment` does not
require fabricated Rule references. The code validates this cross-field contract only and
does not interpret which reason is football-derived.

Use the legal transition table directly:

```python
@pytest.mark.parametrize(
    ("receipt_delta", "expected"),
    [
        (timedelta(microseconds=-1), "human_no_ticket"),
        (timedelta(0), "expired"),
        (timedelta(microseconds=1), "expired"),
    ],
)
def test_no_ticket_respects_effective_cutoff(
    deployment_fixture, receipt_delta, expected
) -> None:
    result = deployment_fixture.record_no_ticket_at(
        deployment_fixture.cutoff + receipt_delta
    )
    assert result.terminal_outcome == expected
```

Here `terminal_outcome` is the derived work-item outcome. Artifact rows assert separately
that expiry is `terminal_kind="shadow"` with
`terminal_reason="deadline_unconfirmed"` or `confirmation_not_requested`; `expired` is never
stored as an artifact terminal kind.

- [ ] **Step 6: Implement dedicated no-ticket, eligibility, and explicit reopen Actions**

`record_no_ticket` receives only a signed work-item token, the human-entered reason/code,
reason basis, Rule tokens, and an optional comparison-candidate token. Inside one transaction, resolve the
current slate and every remaining offer/artifact; recompute offer state and
`effective_cutoff`; first terminalize already-due rows through the shared CAS; then compare
the derived scope to the submitted token. Persist a `NoTicketCommandReceipt` with result
`recorded`, `task_snapshot_changed`, or `already_current`, so cutoff terminalization commits
even when the product maps `task_snapshot_changed` to HTTP 409. Only an unchanged,
still-open scope receives the immutable no-ticket revision and `human_no_ticket` terminals;
never raise after due terminal rows have been written merely to signal staleness.

```python
class NoTicketCommandResult(StrEnum):
    RECORDED = "recorded"
    TASK_SNAPSHOT_CHANGED = "task_snapshot_changed"
    ALREADY_CURRENT = "already_current"


class ArtifactTerminalKind(StrEnum):
    PLACED = "placed"
    SHADOW = "shadow"


class ArtifactTerminalReason(StrEnum):
    ACTUAL_PLACEMENT_CONFIRMED = "actual_placement_confirmed"
    CONFIRMATION_NOT_REQUESTED = "confirmation_not_requested"
    DEADLINE_UNCONFIRMED = "deadline_unconfirmed"
    HUMAN_NO_TICKET = "human_no_ticket"
    OFFICIAL_DEADLINE_SHORTENED = "official_deadline_shortened"
    OFFICIAL_OFFER_CANCELLED = "official_offer_cancelled"
```

Implement the first shared artifact-terminal primitive in this package. Its required lookup
key is the protected artifact, not a challenge; `challenge_revision_id` is nullable for
approval-without-challenge and unique when present. Migration 22 creates the challenge table
first and then this exact restricted foreign key; there is no forward reference or later
receipt-column rename. The primitive accepts the terminal kind,
compatible reason, server-derived effective cutoff, and server receipt time, takes the SQLite
write lock before re-reading state, and returns an existing receipt on an
idempotent/competing transition. Package 9 extends this same helper for placement callbacks
and deadline scanning; it does not introduce a second terminal model. Test an approved
artifact with no challenge becoming `shadow/confirmation_not_requested` at equality with no
Ticket, placement, or money row.

```python
def effective_artifact_cutoff(
    artifact: ProtectedArtifactRow,
    current_offers: Sequence[OfficialOfferRevisionRow],
) -> datetime:
    deadlines = [parse_aware(artifact.frozen_deadline_at)]
    deadlines.extend(parse_aware(row.sale_deadline_at) for row in current_offers)
    return min(deadlines)
```

`supersede_no_ticket` names the current adjudication revision and a human reason. It may
reopen only offer families that are still upcoming/open strictly before cutoff, creates a
new sale-wave snapshot, and never restores an invalidated artifact, closed offer, or old
confirmation window. No evidence/slate/result change invokes it implicitly. Zero-placement
scopes resolve settlement to `not_applicable` and persist only the review-eligibility fact.
Package 11 deterministically derives the actual review item after checking the recorded
readiness condition; Package 8 must not insert into future review tables.

- [ ] **Step 7: Write protected-artifact and current-audit RED tests**

Assert `create_ticket_batch` atomically stores complete lineage; current audit ERROR blocks
Web approval; external overrides permit approval only while the finding IDs, candidate hash,
and audit-policy version still match; WARN adjudications remain required; every deviation
has a registered Rule ID; over-cap candidates cannot materialize; and conditional/baseline
objects cannot deploy. Assert the server, not the request, freezes the minimum current
deadline and rejects equality, a superseded slate, removed/cancelled offer, or a deadline
shortening race. Force lineage/audit/artifact failures at each insert and assert total
rollback. Query the normalized artifact binding and ordered offer links to prove ticket kind,
stake minor, currency, policy, composition hash, and offer revisions remain available after
removing or ignoring payload JSON. Include RED API/UI assertions for every strict command,
cross-command/stale token rejection, Web ERROR override 405, no preselected no-ticket reason,
and no raw IDs or JSON.

- [ ] **Step 8: Extend protected Actions without nesting commits**

Extract batch composition, audit, lineage, and artifact insertion into UOW-level handlers.
The existing public methods keep compatibility wrappers, while the operator Action opens one
outer transaction for each command. Replace `CreateTicketBatchRequest.deadline_at` as an
operator input with a server-resolved deadline in the v2 path. In the same transaction insert
the relational artifact binding and ordered offer links, then include this immutable artifact
document as a signed duplicate rather than the integrity source:

```python
artifact_document = {
    "schema_version": "2",
    "lineage_revision_id": lineage.lineage_revision_id,
    "candidate_ticket_id": candidate_ticket.candidate_ticket_id,
    "ticket_index": candidate_ticket.ticket_index,
    "candidate_content_hash": candidate.content_hash,
    "audit_policy_version": audit.policy_version,
    "audit_finding_ids": [item.finding_id for item in audit.findings],
    "override_receipt_ids": list(override_receipt_ids),
    "fixed_prize_policy_revision_id": candidate.fixed_prize_policy_revision_id,
    "frozen_deadline_at": minimum_deadline.isoformat(),
    "offer_revision_ids": list(candidate.official_offer_revision_ids),
    "ticket": candidate.canonical_ticket,
}
```

Hash canonical bytes and reconcile lineage, audit, candidate note count, stake, binding, and
offer-link rows before commit. The Application may create, adjudicate WARN, approve, and request stage
one; it may never confirm final placement or override an ERROR.

- [ ] **Step 9: Add strict deployment/no-ticket API and focused UI**

Implement the RED interface behavior from Step 7. Add only the named v2 commands
`record_no_ticket` (including the operator-selected `reason_basis`), `supersede_no_ticket`,
`create_ticket_batch`, `adjudicate_audit_warn`, `approve_ticket_batch`, and
`request_confirmation`. Reject extras, actor/role fields, raw IDs, browser deadlines, generic
Adjudications, and audit override fields. Render no-ticket as a secondary action with no
preselected reason. Render ERROR with its external CLI recovery command and no override
button. A successful save uses the returned recovery link and never exposes token contents.

- [ ] **Step 10: Verify and commit Package 8**

```bash
uv run pytest tests/ontology/operator/test_deployment_migration.py tests/ontology/operator/test_lineage_actions.py tests/ontology/operator/test_no_ticket_actions.py tests/product/operator_v2/test_deployment_api.py tests/product/operator_v2/test_no_ticket_ui.py tests/decision/test_audit_override.py tests/ontology/test_protected_ticket_actions.py -q
uv run ruff check nutmeg/ontology/operator/decision_actions.py nutmeg/ontology/operator/confirmation.py nutmeg/ontology/operator/result_actions.py nutmeg/ontology/repository/schema_operator_result.py nutmeg/ontology/repository/operator_result.py nutmeg/ontology/actions/protected_ticket_actions.py nutmeg/ontology/actions/workflow_actions.py nutmeg/decision/audit_override.py nutmeg/interfaces/cli/decision.py nutmeg/product/operator_contracts.py nutmeg/product/operator_state.py nutmeg/product/operator_queries.py nutmeg/product/operator_actions.py tests/ontology/operator tests/product/operator_v2
```

The three named tests below accept `NUTMEG_P8_REPLAY_ROOT`, retain
`<root>/data/ontology/ontology.db`, and must drive the public boundary named in the test. The
artifact and no-ticket tests use the strict ASGI API; the override test invokes the real Typer
CLI, then drains candidate regeneration through the Application worker boundary. A direct
call to an Action/service method does not satisfy these replay tests.

```bash
NUTMEG_P8_ARTIFACT_ROOT="$(mktemp -d /tmp/nutmeg-p8-artifact.XXXXXX)"
env NUTMEG_P8_REPLAY_ROOT="$NUTMEG_P8_ARTIFACT_ROOT" NUTMEG_DATA_DIR="$NUTMEG_P8_ARTIFACT_ROOT/data" NUTMEG_PRODUCTION_DATA_DIR="/Users/jz71/Projects/Nutmeg/.nutmeg-data" NUTMEG_OPERATOR_RUNTIME_SCOPE=isolated_candidate NUTMEG_OPERATOR_SURFACE_MODE=active NUTMEG_OPERATOR_TOKEN_SIGNING_KEY=isolated-p8-signing-key-32-bytes-min uv run pytest tests/product/operator_v2/test_deployment_replay.py::test_isolated_artifact_approval_public_api_replay -vv -s
sqlite3 "$NUTMEG_P8_ARTIFACT_ROOT/data/ontology/ontology.db" "SELECT action_type,status,count(*) FROM actions GROUP BY 1,2 ORDER BY 1,2; SELECT count(*) FROM operator_ticket_decision_lineage_revisions; SELECT count(*) FROM operator_protected_artifact_bindings; SELECT count(*) FROM operator_protected_artifact_offer_revision_links; SELECT count(*) FROM operator_artifact_terminal_receipts; SELECT count(*) FROM tickets; SELECT count(*) FROM cash_transactions;"

NUTMEG_P8_OVERRIDE_ROOT="$(mktemp -d /tmp/nutmeg-p8-override.XXXXXX)"
env NUTMEG_P8_REPLAY_ROOT="$NUTMEG_P8_OVERRIDE_ROOT" NUTMEG_DATA_DIR="$NUTMEG_P8_OVERRIDE_ROOT/data" NUTMEG_PRODUCTION_DATA_DIR="/Users/jz71/Projects/Nutmeg/.nutmeg-data" NUTMEG_OPERATOR_RUNTIME_SCOPE=isolated_candidate NUTMEG_OPERATOR_SURFACE_MODE=active NUTMEG_OPERATOR_TOKEN_SIGNING_KEY=isolated-p8-signing-key-32-bytes-min uv run pytest tests/product/operator_v2/test_deployment_replay.py::test_isolated_override_cli_regeneration_replay -vv -s
sqlite3 "$NUTMEG_P8_OVERRIDE_ROOT/data/ontology/ontology.db" "SELECT action_type,status,count(*) FROM actions WHERE action_type IN ('record_ticket_audit_override','generate_ticket_candidate_set') GROUP BY 1,2 ORDER BY 1,2; SELECT count(*) FROM adjudications; SELECT count(*) FROM operator_ticket_audit_override_receipts; SELECT count(*) FROM operator_candidate_generation_override_links; SELECT count(*) FROM operator_candidate_set_revisions; SELECT count(*) FROM operator_artifact_terminal_receipts; SELECT count(*) FROM tickets; SELECT count(*) FROM cash_transactions;"

NUTMEG_P8_NO_TICKET_ROOT="$(mktemp -d /tmp/nutmeg-p8-no-ticket.XXXXXX)"
env NUTMEG_P8_REPLAY_ROOT="$NUTMEG_P8_NO_TICKET_ROOT" NUTMEG_DATA_DIR="$NUTMEG_P8_NO_TICKET_ROOT/data" NUTMEG_PRODUCTION_DATA_DIR="/Users/jz71/Projects/Nutmeg/.nutmeg-data" NUTMEG_OPERATOR_RUNTIME_SCOPE=isolated_candidate NUTMEG_OPERATOR_SURFACE_MODE=active NUTMEG_OPERATOR_TOKEN_SIGNING_KEY=isolated-p8-signing-key-32-bytes-min uv run pytest tests/product/operator_v2/test_deployment_replay.py::test_isolated_no_ticket_exact_cutoff_public_api_replay -vv -s
sqlite3 "$NUTMEG_P8_NO_TICKET_ROOT/data/ontology/ontology.db" "SELECT action_type,status,count(*) FROM actions GROUP BY 1,2 ORDER BY 1,2; SELECT count(*) FROM operator_no_ticket_revisions; SELECT result,count(*) FROM operator_no_ticket_command_receipts GROUP BY 1; SELECT terminal_kind,terminal_reason,count(*) FROM operator_artifact_terminal_receipts GROUP BY 1,2; SELECT count(*) FROM operator_review_eligibility_facts; SELECT count(*) FROM tickets; SELECT count(*) FROM cash_transactions;"
```

Expected business output: the artifact replay reports one approved immutable artifact and
zero placement rows; the override replay reports the original ERROR, its human
`evidence_rejected` receipt, and one new deterministic candidate-set revision; the cutoff
replay reports `task_snapshot_changed` plus a single shadow terminal and zero Ticket/ledger
rows. Every printed service count must equal the SQL counts.

Expected: all pass; exact-cutoff tests produce expiry, Web ERROR override attempts return
405/422, and every approved artifact has complete immutable lineage. Commit:

```bash
git commit -m "feat(decision): govern operator deployment adjudication"
```

## Package 9: Telegram ownership, confirmation CAS, ticket notes, ledger, and shadow

**Branch:** `feat/operator-confirmation-ledger`

**Files:**

- Modify: `nutmeg/ontology/repository/schema_operator_result.py`
- Modify: `nutmeg/ontology/repository/operator_result.py`
- Modify: `nutmeg/ontology/operator/confirmation.py`
- Modify: `nutmeg/ontology/repository/schema_tickets.py`
- Modify: `nutmeg/ontology/repository/tickets.py`
- Modify: `nutmeg/ontology/repository/schema_finance.py`
- Modify: `nutmeg/ontology/repository/finance.py`
- Modify: `nutmeg/ontology/actions/protected_ticket_actions.py`
- Modify: `nutmeg/ontology/operator/sale_actions.py`
- Modify: `nutmeg/ontology/repository/migrations.py`
- Modify: `nutmeg/ontology/repository/unit_of_work.py`
- Modify: `nutmeg/ontology/wiring.py`
- Modify: `nutmeg/services/telegram_ticket_confirmation.py`
- Modify: `nutmeg/interfaces/bot/telegram.py`
- Modify: `scripts/openclaw/nutmeg_command_router.py`
- Create: `scripts/openclaw/nutmeg_ticket_confirmation_bridge.py`
- Create: `integrations/openclaw/nutmeg-ticket-confirmation/package.json`
- Create: `integrations/openclaw/nutmeg-ticket-confirmation/openclaw.plugin.json`
- Create: `integrations/openclaw/nutmeg-ticket-confirmation/index.js`
- Create: `integrations/openclaw/nutmeg-ticket-confirmation/index.test.mjs`
- Modify: `nutmeg/product/operator_workers.py`
- Modify: `nutmeg/product/operator_contracts.py`
- Modify: `nutmeg/product/operator_queries.py`
- Modify: `nutmeg/interfaces/product_api.py`
- Modify: `nutmeg/interfaces/cli/product.py`
- Create: `tests/ontology/operator/test_confirmation_migration.py`
- Create: `tests/ontology/operator/test_confirmation_cas.py`
- Create: `tests/ontology/operator/test_ticket_notes.py`
- Create: `tests/product/operator_v2/test_confirmation_owner.py`
- Create: `tests/product/operator_v2/test_confirmation_lifecycle.py`
- Create: `tests/product/fixtures/operator/confirmation/jczq-callback.json`
- Create: `tests/product/fixtures/operator/confirmation/jczq-timeout.json`
- Create: `tests/product/fixtures/operator/confirmation/openclaw-update.json`
- Modify: `tests/test_openclaw_router.py`
- Create: `tests/test_nutmeg_ticket_confirmation_bridge.py`
- Modify: `tests/test_telegram_ticket_confirmation.py`

- [ ] **Step 1: Write migration 23 upgrade and ticket-composition RED tests**

Require migration 22's empty challenge revision/head schema to remain unchanged. Migration 23
adds append-only note, leg, placement-cash-link, and callback-attestation tables plus one
explicitly operational heartbeat lease table:

```text
operator_ticket_notes
operator_ticket_note_legs
operator_placement_cash_links
operator_telegram_owner_heartbeats
operator_telegram_callback_attestations
```

`operator_telegram_owner_heartbeats` is keyed by account/owner instance and renews its
observed/expiry fields in place. It has no `created_by_action_id` and renewal never inserts an
Action; it is health/lease state, not business evidence. All other listed tables remain
append-only, and an actual callback attestation/placement is still one typed Action.

Regression-test migration 22's challenge/head schema and unique terminal receipt per non-null
`challenge_revision_id` and per protected artifact. The precreated challenge revision stores
`challenge_revision_id`, `challenge_family_id`, nullable unique `legacy_confirmation_id`,
`revision_no`, nullable unique predecessor, `ticket_artifact_id`, artifact composition hash,
lineage revision, nonce hash, `issued_at`, `effective_cutoff_at`, and issuing Action. The head
table has one row per artifact and one unique challenge revision, which is the sole current-
leaf model; an artifact with a terminal receipt has no open head. Test unique note index per
Ticket and leg index per note; positive integer unit counts; integer minor-unit identities;
JCZQ quote/odds/line requirements; Zucai null quote/odds/line fields; one policy revision
copied across artifact, Ticket, notes, and legs; and ticket-kind/currency/stake/tier
constraints against the migration 21 policy rows.
Preserve legacy float columns for old readers, but require exact integer `stake_minor` and
currency on every v2 Ticket and cash row.

Test the v22 -> v23 upgrade explicitly. Group legacy challenges per artifact, order them by
`(issued_at, confirmation_id)`, assign one family with consecutive revisions/predecessors,
derive a stable `challenge_revision_id` from each legacy row, retain its old identifier only
as `legacy_confirmation_id`, and preserve the old `expires_at` only as
`legacy_expires_at` audit data. New compatibility responses may label the current
`challenge_revision_id` as `confirmation_id`, but persistence and terminal CAS never do. For a non-terminal
artifact the newest unconsumed row becomes the sole head and its new
`effective_cutoff_at` is resolved from the protected artifact/current offer links, never the
legacy five-minute value. A terminal artifact gets no head. More than one consumed legacy
challenge, contradictory placement/shadow rows, or an unresolvable artifact binding aborts
the migration with `legacy_confirmation_conflict`; no row is silently discarded. Test fresh
initialization, zero/one/multiple historical rows, deterministic replay, upgraded defaults,
and idempotency.

Owner heartbeat rows are mutable operational lease heads, one per registered owner instance,
not append-only pulse history. They contain owner instance ID, fixed account/transport label,
owner mode, router version, monotonic heartbeat sequence, observed/lease-expiry instants, and
the immutable `register_telegram_update_owner` Action ID; callback attestations contain unique
Telegram update/callback identifiers, owner heartbeat ref, server ingress time, allowed chat
identity, message identity, and source artifact/retrieval refs. Neither table stores a bot
token, plaintext nonce, or normal-view payload. Grant the registration Action only to
`deterministic_system`; its idempotency key is canonical over account, owner instance,
transport, and router version. A pulse updates only the lease head under compare-and-swap,
creates no Action/outbox event, and accumulates no row requiring retention cleanup.

- [ ] **Step 2: Verify confirmation storage RED**

```bash
uv run pytest tests/ontology/operator/test_confirmation_migration.py tests/ontology/operator/test_ticket_notes.py -v
```

Expected: migration 23 note/heartbeat/attestation rows and legacy challenge upgrades are
missing, while migration 21 policy and migration 22 empty challenge/terminal tables already
exist.

- [ ] **Step 3: Implement migration 23 legacy challenge upgrade and canonical notes**

Add frozen row models and repository methods returning typed rows. Perform the tested legacy
challenge reconciliation before enabling v2 writes, and use the head table for every current
lookup. Resolve and revalidate the
policy revision already bound at artifact approval. Expand a protected artifact into one row
per unique canonical note and combine duplicates through `unit_count`:

```python
@dataclass(frozen=True, slots=True)
class TicketNoteDraft:
    ticket_kind: Literal["jczq", "sfc", "renjiu"]
    structure_code: str
    group_code: str | None
    currency: str
    unit_stake_minor: int
    unit_count: int
    legs: Sequence[TicketNoteLegDraft]

    @property
    def stake_minor(self) -> int:
        return self.unit_stake_minor * self.unit_count
```

Canonical composition hash covers sorted note/leg content, multiplicity, booked quote/odds
or fixed-prize policy, and stake. Reconcile the note stake sum to artifact and Ticket stake in
the same transaction. `operator_placement_cash_links` binds the stake transaction to integer
`stake_minor` and currency; legacy `cash_transactions.amount` is compatibility output, never
the source for later minor-unit arithmetic. Do not add fake odds to Zucai rows.

- [ ] **Step 4: Write the four-way terminal CAS RED tests**

Race owner callback, deadline scanner, official deadline correction/cancellation, and human
no-ticket against the same artifact, both with and without a challenge. Assert the first
committed transition alone writes `terminal_kind="placed"` or `"shadow"` plus exactly one
compatible `terminal_reason`; replay returns the existing receipt and a competing transition
reports it without Ticket, duplicate shadow, or cash. Cover every reason, including
`confirmation_not_requested` for an approved artifact with no challenge. Test ingress one microsecond
before cutoff, exactly at cutoff, and after cutoff. Assert `effective_cutoff` can shorten but
never extend after a slate revision.

Assert an issued challenge expires at the artifact's current effective cutoff rather than
the legacy five-minute TTL. Re-request before terminality returns the same open challenge;
after terminality it returns the terminal receipt and never creates another challenge.

```python
def consume_artifact_terminal(
    uow: OntologyUnitOfWork,
    *,
    ticket_artifact_id: str,
    challenge_revision_id: str | None,
    expected_challenge_revision: int | None,
    terminal_kind: ArtifactTerminalKind,
    reason: ArtifactTerminalReason,
    ingress_at: datetime,
) -> ArtifactTerminalReceiptRow:
    uow.acquire_write_lock()
    artifact = uow.operator_result.required_artifact_binding(ticket_artifact_id)
    challenge = uow.operator_result.current_challenge(ticket_artifact_id)
    validate_optional_challenge(
        challenge,
        challenge_revision_id=challenge_revision_id,
        expected_revision=expected_challenge_revision,
    )
    cutoff = resolve_current_effective_cutoff(uow, artifact.ticket_artifact_id)
    validate_transition_time(terminal_kind, reason, ingress_at=ingress_at, cutoff=cutoff)
    return uow.operator_result.insert_terminal_receipt(
        challenge_revision_id=challenge_revision_id,
        ticket_artifact_id=artifact.ticket_artifact_id,
        terminal_kind=terminal_kind,
        terminal_reason=reason,
        effective_cutoff=cutoff,
        terminal_at=ingress_at,
    )
```

SQLite obtains the write lock before reading/rechecking artifact, optional challenge head,
and terminal receipt; the final insert uses the unique artifact constraint as a second guard.
Never decide the race using a pre-transaction GET or require a challenge for timeout.

- [ ] **Step 5: Implement shared CAS and official-correction terminalization**

Move placement and shadow terminal choice into `nutmeg/ontology/operator/confirmation.py`.
The placement handler calls it inside the same outer Action transaction that writes Ticket,
notes, legs, placement, receipt retrieval, and stake cash row. Extend official slate import
to resolve affected open challenges and record shortened/cancelled terminals in its import
transaction. The infrastructure scanner handles due artifacts with and without a challenge;
use `confirmation_not_requested` for the latter and `deadline_unconfirmed` for the former.
No ledger row is written for any non-placement terminal. Each zero-placement shadow/cancel
transition appends the Package 8 review-eligibility fact in the same Action: immediate
operational/data-availability when no baseline exists, or forecast-truth with
`outcomes_required` when one does. It does not create a Package 11 review row.

- [ ] **Step 6: Write owner/heartbeat and rollback RED tests**

Assert production defaults to OpenClaw ownership; `nutmeg app` never starts `getUpdates` or
another inbound poller for the production token (outbound `sendMessage` for a requested
challenge remains allowed). Load the checked-in plugin with a fake OpenClaw API and assert it
registers exactly one `registerInteractiveHandler({channel: "telegram", namespace: "ntc"})`
plus one heartbeat `registerService`. The handler accepts only the configured `accountId`, an
authorized sender, configured chat and sender allowlists, and
`ctx.callback.data.startswith("ntc:")`. Its first operation captures `ingressAt` from the
injected plugin-process clock before validation or subprocess startup. For every callback in
the `ntc` namespace, success, authorization denial, validation failure, timeout, and bridge
failure all send a bounded safe response and return `{handled: true}` without `submitText`, so
none can enter the AI path. The handler leaves the button retryable on a recoverable failure.
Run multiple heartbeat intervals without a callback and assert Action and scoreboard-source
high water remain unchanged; then process one valid callback and assert exactly one committed
Action advances both business state and the source high water.

The plugin sends one strict `openclaw-telegram-interactive-v1` document to
`scripts/openclaw/nutmeg_ticket_confirmation_bridge.py callback` over stdin. It contains the
trusted plugin/account/owner instance, OpenClaw callback ID, sender/chat/message identities,
authorization result, namespace, opaque callback data, and the plugin-recorded
`server_ingress_at`; it contains no token, nonce expansion, artifact, client-controlled
timestamp, shell command, or arbitrary payload mapping. The Python bridge uses that trusted
server ingress for cutoff comparison and calls `ingest_openclaw_telegram_update(...)`;
argv/URL/inline JSON, trailing documents, unknown fields, and a spoofed owner/account are
rejected without echoing input. Unit tests delay subprocess completion across the cutoff and
prove the entry timestamp, rather than completion time, wins the callback/scanner race.

Require the Python boundary to record the owner heartbeat and callback attestation, and
delegate only the `ntc:` callback exactly once to the existing
`TelegramTicketConfirmationService`. A duplicate callback ID with byte-identical normalized
content replays the same result; the same ID with different account/sender/chat/message/data
or ingress content is an idempotency conflict and never reuses the old placement. Unknown
prefixes, unauthorized chats, client timestamps, inline artifact fields, and malformed
envelopes fail before placement. Assert the Application and the new plugin never open
`/getUpdates`: the plugin attaches to the one Telegram consumer already owned by OpenClaw.

Treat `accountId` and `ownerInstanceId` inside stdin as claims, not authority. The plugin
passes its configured values separately in the bounded child environment as
`NUTMEG_TELEGRAM_ACCOUNT_ID` and `NUTMEG_TELEGRAM_OWNER_INSTANCE_ID`; the bridge requires the
first to equal literal `nutmeg`, requires both variables to be present, and rejects any stdin
value that differs before opening the ontology. Capture a bridge-process `received_at` before
reading stdin and reject a plugin ingress timestamp more than ten seconds old or more than
two seconds in the future. Tests cover missing/mismatched environment authority and timestamp
skew. The single-user/local-process threat model does not claim protection from another
process already running as Jun with arbitrary environment and database access.

A native poller requires a distinct token; duplicate owners return
`telegram_update_owner_conflict`. Freshness comes only from the formal heartbeat rows, never
from `telegram-bot.offset` existence or mtime. Test missing, fresh, expired, future-skewed,
wrong-owner, and conflicting heartbeat attestations. Stale/missing heartbeat blocks new
confirmation requests only; it does not block read/judgment work or prevent the sole owner
from finishing an already-issued challenge. Isolated candidate mode rejects all real
Telegram configuration. Assert
rollback to `legacy_read_only` blocks new requests but the same OpenClaw route and scanner
finish already-issued challenges.

- [ ] **Step 7: Implement the repository OpenClaw plugin, bridge, and workers**

Keep `TelegramTicketConfirmationService` transport-agnostic after callback parsing and make
the persisted owner/callback attestations the only final-placement entry point. The Python
bridge owns strict stdin parsing; the plugin owns the server ingress timestamp and translates
the documented OpenClaw `TelegramInteractiveHandlerContext` into that envelope:

```python
def ingest_openclaw_telegram_update(
    interactive_envelope: Mapping[str, object],
    *,
    trusted_account_id: str,
    owner_instance_id: str,
    bridge_received_at: datetime,
    heartbeat_service: TelegramOwnerHeartbeatService,
    confirmation_service: TelegramTicketConfirmationService,
) -> OpenClawTelegramUpdateResult:
    update = OpenClawTelegramInteractiveV1.model_validate(interactive_envelope)
    require_trusted_owner(
        update,
        trusted_account_id=trusted_account_id,
        owner_instance_id=owner_instance_id,
        bridge_received_at=bridge_received_at,
    )
    ingress_at = update.server_ingress_at
    heartbeat = heartbeat_service.attest(
        owner_instance_id=owner_instance_id,
        observed_at=bridge_received_at,
    )
    callback = require_ntc_callback(update, ingress_at=ingress_at)
    return confirmation_service.handle_attested_callback(callback, heartbeat)
```

The plugin `registerService` first replays or commits the one
`register_telegram_update_owner` Action for its configured registration, then calls
`nutmeg_ticket_confirmation_bridge.py heartbeat` on startup and every 30 seconds, with a
90-second lease; every interactive callback also refreshes the same owner lease before
dispatch. Stopping the service clears its timer but does not forge a terminal heartbeat. Add
no Application poller and no browser command. Both bridge invocations are deterministic and
keep callback data off argv and stdout:

```bash
env NUTMEG_TELEGRAM_ACCOUNT_ID=nutmeg \
  NUTMEG_TELEGRAM_OWNER_INSTANCE_ID=openclaw-primary \
  uv run python scripts/openclaw/nutmeg_ticket_confirmation_bridge.py callback \
  --contract-version openclaw-telegram-interactive-v1 \
  < tests/product/fixtures/operator/confirmation/openclaw-update.json
```

The heartbeat subcommand captures its own observed time, increments the registration's
heartbeat sequence with compare-and-swap, and upserts only the operational lease row under
the writer lock. It verifies that Action/outbox high water is unchanged before commit. The
callback subcommand uses the same lease refresh inside its outer typed Action transaction;
it does not append a separate heartbeat Action. One row is retained per configured owner
registration, including expired rows; because pulses update rather than append, v1 needs no
time-based purge and health queries consider only the current configured registration.

`package.json` points `openclaw.extensions` to `./index.js`; `openclaw.plugin.json` declares
the matching `nutmeg-ticket-confirmation` ID and a strict schema for `projectRoot`, `accountId`,
`ownerInstanceId`, `allowedChatIds`, `allowedSenderIds`, `heartbeatIntervalSeconds`, and
`leaseSeconds`, with no token field. In non-`full` registration modes it performs no
subprocess, timer, database, or network work. Spawn uses fixed argv, `shell: false`, a bounded
environment, timeout, and stdout/stderr byte limits. The plugin is validated from this
checkout without installation; installing/enabling it in the live OpenClaw configuration and
restarting the production gateway are explicit Jun deployment steps, not Application actions.

Its public result is a business message, not IDs or canonical JSON. At Package 9,
`nutmeg app` registers every consumer implemented so far; later packages append their slots to
the same supervisor:

```python
workers = OperatorInfrastructureWorkers(
    evidence_freeze=EvidenceFreezeRequestWorker(kernel),
    market_baseline=MarketBaselineWorker(kernel),
    candidate_generation=CandidateGenerationWorker(kernel),
    confirmation_deadlines=ConfirmationDeadlineWorker(kernel),
    outbox=ProductOutboxWorker(kernel),
    read_model=OperatorReadModelInvalidator(kernel),
)
```

The active lifespan calls `recover_expired_leases()` and `start()` before accepting requests,
then `stop_accepting()`, `drain_current_transactions()`, and `close()` in reverse consumer
order. Package 10 registers `TaskSettlementWorker`; Package 11 registers
`ReviewMaterializationWorker` and `ScoreboardReviewCompletionWorker`. Tests fail if a queued
request is visible after a bounded lifespan drain when all prerequisites are present.

Every OpenClaw callback/heartbeat write and every infrastructure `run_once(limit)` holds the
Package 1 shared `OntologyWriterLease` around its outer UOW. This lets a guarded migration take
the exclusive lease and fail closed while a callback or worker is active, without turning the
Application instance lock into a global SQLite lock.

Derive OpenClaw heartbeat state only from the latest valid formal owner attestation. The old
`state/telegram-bot.offset` remains offset storage and has no health semantics. The v2 status DTO exposes
configured/available/blocking state and a recovery label, not secrets. Do not add official
collection, research, candidate selection, placement, or scoreboard work to these workers.

- [ ] **Step 8: Write Web-denial and atomic ledger materialization RED tests**

Browser POSTs to
the old and guessed v2 placement paths return 405 before parsing. On a valid callback, assert
one Action atomically creates every expected object and reconciles counts:

```text
1 confirmation terminal receipt
1 Ticket + N TicketNotes + M TicketNoteLegs
1 placement + 1 attestation artifact/retrieval
1 negative stake CashTransaction
```

Inject failure after notes, placement, and cash inserts; each leaves the challenge open and
all those counts unchanged. Test two artifacts in one batch resolving to `partially_placed`
when one callback wins and the other shadows.

- [ ] **Step 9: Remove Web placement and implement atomic materialization**

Remove the active Web/API route that accepts nonce, receipt, external reference, or
`ConfirmPlacementCommand`; retain domain access only for the attested OpenClaw boundary and
tests. Make the one outer placement Action insert the attestation retrieval, terminal receipt,
Ticket, notes, legs, placement, and stake debit, then reconcile every Step 8 count before
commit. No nested public Action or post-commit ledger write is allowed.

- [ ] **Step 10: Verify exact isolated dry-run paths and commit Package 9**

```bash
uv run pytest tests/ontology/operator/test_confirmation_migration.py tests/ontology/operator/test_confirmation_cas.py tests/ontology/operator/test_ticket_notes.py tests/product/operator_v2/test_confirmation_owner.py tests/product/operator_v2/test_confirmation_lifecycle.py tests/test_openclaw_router.py tests/test_nutmeg_ticket_confirmation_bridge.py tests/test_telegram_ticket_confirmation.py tests/ontology/test_telegram_confirmation_e2e.py -q
node --test integrations/openclaw/nutmeg-ticket-confirmation/index.test.mjs
openclaw plugins validate --root integrations/openclaw/nutmeg-ticket-confirmation --entry index.js
uv run ruff check nutmeg/ontology/operator/confirmation.py nutmeg/ontology/repository/schema_operator_result.py nutmeg/ontology/repository/operator_result.py nutmeg/services/telegram_ticket_confirmation.py nutmeg/product/operator_workers.py scripts/openclaw/nutmeg_command_router.py scripts/openclaw/nutmeg_ticket_confirmation_bridge.py tests/ontology/operator tests/product/operator_v2 tests/test_nutmeg_ticket_confirmation_bridge.py
```

The two named lifecycle tests accept `NUTMEG_P9_REPLAY_ROOT` and leave their isolated database
at `<root>/data/ontology/ontology.db`. The callback replay must load the JavaScript plugin,
invoke the registered OpenClaw handler context, and cross the real stdin Python bridge; it
fails if it imports or calls the confirmation service directly. The timeout replay requests
confirmation through `/api/v2/operator` and lets the TestClient lifespan's bounded
infrastructure worker terminalize it; it fails if the test calls `run_once` or a repository
insert itself. Run both exact public-boundary replays; no production token or directory is
used:

```bash
NUTMEG_P9_CALLBACK_ROOT="$(mktemp -d /tmp/nutmeg-p9-callback.XXXXXX)"
env NUTMEG_P9_REPLAY_ROOT="$NUTMEG_P9_CALLBACK_ROOT" NUTMEG_DATA_DIR="$NUTMEG_P9_CALLBACK_ROOT/data" NUTMEG_PRODUCTION_DATA_DIR="/Users/jz71/Projects/Nutmeg/.nutmeg-data" NUTMEG_OPERATOR_RUNTIME_SCOPE=isolated_candidate NUTMEG_OPERATOR_SURFACE_MODE=active NUTMEG_OPERATOR_TOKEN_SIGNING_KEY=isolated-p9-signing-key-32-bytes-min uv run pytest tests/product/operator_v2/test_confirmation_lifecycle.py::test_isolated_callback_replay -vv -s
sqlite3 "$NUTMEG_P9_CALLBACK_ROOT/data/ontology/ontology.db" "SELECT action_type,status,count(*) FROM actions GROUP BY 1,2 ORDER BY 1,2; SELECT terminal_kind,terminal_reason,count(*) FROM operator_artifact_terminal_receipts GROUP BY 1,2; SELECT count(*) FROM operator_telegram_callback_attestations; SELECT count(*) FROM tickets; SELECT count(*) FROM operator_ticket_notes; SELECT count(*) FROM operator_ticket_note_legs; SELECT count(*) FROM ticket_placements; SELECT count(*),sum(stake_minor) FROM operator_placement_cash_links;"

NUTMEG_P9_TIMEOUT_ROOT="$(mktemp -d /tmp/nutmeg-p9-timeout.XXXXXX)"
env NUTMEG_P9_REPLAY_ROOT="$NUTMEG_P9_TIMEOUT_ROOT" NUTMEG_DATA_DIR="$NUTMEG_P9_TIMEOUT_ROOT/data" NUTMEG_PRODUCTION_DATA_DIR="/Users/jz71/Projects/Nutmeg/.nutmeg-data" NUTMEG_OPERATOR_RUNTIME_SCOPE=isolated_candidate NUTMEG_OPERATOR_SURFACE_MODE=active NUTMEG_OPERATOR_TOKEN_SIGNING_KEY=isolated-p9-signing-key-32-bytes-min uv run pytest tests/product/operator_v2/test_confirmation_lifecycle.py::test_isolated_timeout_replay -vv -s
sqlite3 "$NUTMEG_P9_TIMEOUT_ROOT/data/ontology/ontology.db" "SELECT action_type,status,count(*) FROM actions GROUP BY 1,2 ORDER BY 1,2; SELECT terminal_kind,terminal_reason,count(*) FROM operator_artifact_terminal_receipts GROUP BY 1,2; SELECT count(*) FROM operator_review_eligibility_facts; SELECT count(*) FROM tickets; SELECT count(*) FROM ticket_placements; SELECT count(*) FROM operator_placement_cash_links;"
```

Expected callback evidence is `placed|actual_placement_confirmed|1`, one Ticket, the exact
fixture note count, one placement, and one negative stake row. Expected timeout evidence is
`shadow|confirmation_not_requested|1` or `shadow|deadline_unconfirmed|1` according to the
fixture, with zero Tickets, placements, and money rows.
Commit:

```bash
git commit -m "feat(tickets): close operator confirmation and ledger loop"
```

## Package 10: Three-source results and full JCZQ/Zucai settlement

**Branch:** `feat/operator-results-settlement`

**Files:**

- Modify: `nutmeg/ontology/repository/schema_operator_result.py`
- Modify: `nutmeg/ontology/repository/operator_result.py`
- Create: `nutmeg/ontology/operator/result_manifest.py`
- Modify: `nutmeg/ontology/operator/result_actions.py`
- Create: `nutmeg/product/operator_settlement.py`
- Modify: `nutmeg/ontology/repository/migrations.py`
- Modify: `nutmeg/ontology/repository/unit_of_work.py`
- Modify: `nutmeg/ontology/wiring.py`
- Modify: `nutmeg/ontology/finance/settlement.py`
- Modify: `nutmeg/product/operator_contracts.py`
- Modify: `nutmeg/product/operator_queries.py`
- Modify: `nutmeg/product/operator_actions.py`
- Modify: `nutmeg/interfaces/operator_api.py`
- Modify: `nutmeg/interfaces/cli/workflow.py`
- Create: `nutmeg/interfaces/web/templates/operator/steps/await_result_v2.html`
- Create: `tests/ontology/operator/test_result_migration.py`
- Create: `tests/ontology/operator/test_result_ingest.py`
- Create: `tests/ontology/operator/test_task_settlement.py`
- Create: `tests/ontology/operator/test_settlement_corrections.py`
- Create: `tests/product/operator_v2/test_result_contracts.py`
- Create: `tests/product/operator_v2/test_result_ui.py`
- Create: `tests/product/fixtures/operator/results/jczq-complete.json`
- Create: `tests/product/fixtures/operator/results/zucai-complete.json`

- [ ] **Step 1: Write migration 24 and strict manifest RED tests**

Require normalized append-only storage in these exact tables:

```text
operator_result_set_families
operator_result_set_revisions
operator_result_match_revisions
operator_result_source_receipts
operator_outcome_revisions
zucai_prize_table_revisions
zucai_prize_table_tiers
operator_settlement_requests
operator_task_settlement_runs
operator_task_settlement_skips
operator_ticket_settlement_revisions
operator_ticket_note_settlements
operator_ticket_note_leg_settlements
operator_settlement_cash_links
```

Test v23 upgrade and fresh initialization, current-leaf uniqueness, restricted supersession,
Action refs, exact count checks, and direct-predecessor correction links.

Build `ResultEvidenceManifestV1` with Pydantic `extra="forbid"`. For every required official
match, require exactly one row for each source kind:
`api_football`, `sporttery_game90`, and `okooo_manual`. Cover every valid
`missing | invalid | available` field combination; `played_90 | postponed | official_void`
score rules; aware timestamps; unknown/duplicate rows; issue/task/slate mismatch; unofficial
retrievals; Zucai-only prize tables; exact SFC/Renjiu tiers; negative/non-integer prize
values; and no partial inserts after rejection.

- [ ] **Step 2: Verify result storage and contract RED**

```bash
uv run pytest tests/ontology/operator/test_result_migration.py tests/ontology/operator/test_result_ingest.py -v
```

Expected: migration 24 and result manifest types are absent.

- [ ] **Step 3: Implement atomic result/prize ingest and correction**

Validate the whole manifest and every retrieval before invoking one
`import_result_evidence_set` deterministic Action. Normalize only when all three sources are
available and agree. The official source is mandatory; missing rows yield `missing`, score or
disposition disagreement yields `conflict`, agreed postponed yields no Outcome, and agreed
played/official-void appends an Outcome revision. Corrections name and directly supersede the
current result-set token and append dependent Outcomes; never rewrite a predecessor.

```python
def normalize_match_result(
    receipts: Sequence[ResultSourceReceiptInput],
) -> NormalizedResult:
    by_kind = {row.source_kind: row for row in receipts}
    if set(by_kind) != RESULT_SOURCE_KINDS:
        raise ValueError("exactly three configured result sources are required")
    if any(row.receipt_state == "missing" for row in receipts):
        return NormalizedResult(agreement_state="missing")
    available = tuple(row for row in receipts if row.receipt_state == "available")
    if len(available) != 3 or not all_same_result(available):
        return NormalizedResult(agreement_state="conflict")
    return NormalizedResult.from_agreed(available[0])
```

Prize tables require the official retrieval, exact issue/currency, and exactly the closed
tier set. Persist integer amounts and counts only. Register no historical or estimated prize
value.

- [ ] **Step 4: Write pure grader RED tests for every enabled market and ticket kind**

Test HAD, HHAD with persisted signed line, TTG, and every CRS exact/aggregate result code; one Outcome per JCZQ
leg's own match; positive Decimal booked odds; lost, won, mixed-void, and all-void notes;
half-up rounding once per note; multipliers; and unsupported market rejection during
candidate audit. For SFC test exactly 14 and exactly 13 as mutually exclusive tiers, all
other counts losing, and all 14 bound legs. For Renjiu test only its bound nine legs and only
exactly nine correct. Official-void fixed-prize legs count as correct through the bound
policy and never turn a Zucai note into JCZQ-style `void`.

For CRS, include one exact bound selection and all three official aggregates:
`win_other` when home is greater, `draw_other` when equal, and `loss_other` when home is
less, whenever the exact score is not a registered selectable code. A persisted or generated
generic `other` is an unsupported market input and blocks the whole settlement transaction;
it is never guessed into one of the three buckets.

```python
@pytest.mark.parametrize(
    ("grades", "expected"),
    [
        (("lost", "void"), "lost"),
        (("won", "void"), "won"),
        (("void", "void"), "void"),
    ],
)
def test_jczq_note_state_is_closed(grades, expected) -> None:
    assert jczq_note_grade(grades).value == expected
```

- [ ] **Step 5: Implement versioned graders and exact arithmetic**

Split graders by market definition and dispatch only through a closed registry. Parse odds
and HHAD parameters with Decimal context precision 50. Under
`cn_sporttery_jczq_v1`, use multiplier one for void legs, multiply stake by every winning
non-void booked odd, round half-up once to integer minor units for each note, then sum notes.
For Zucai, map correct count to exactly one allowed tier and calculate
`unit_count * payout_minor_per_winning_note` in integers. Return frozen grade objects; no
grader writes storage.

```python
def crs_result_code(home_90: int, away_90: int, exact_codes: frozenset[str]) -> str:
    exact = f"{home_90}:{away_90}"
    if exact in exact_codes:
        return exact
    if home_90 > away_90:
        return "win_other"
    if home_90 < away_90:
        return "loss_other"
    return "draw_other"
```

- [ ] **Step 6: Write request, task-run, reconciliation, and correction RED tests**

Require `request_settlement` from `judge_operator` with exact task/result tokens and worker
execution by `deterministic_system`. The request Action atomically appends one
`task_settlement` worker job and replay adds none. Test zero-placement `not_applicable`; result/prize
waiting; placement integrity block; exact replay; multiple Tickets/notes; requested,
eligible, skipped, settled, note, leg, and cash counts; `paid_note_unit_count`,
`winning_note_unit_count`, and JCZQ-only `void_note_unit_count`; currency/policy/stake/tier
mismatches; rollback after each child class; and ledger conservation.
Require the terminal settlement transaction to append exactly one review-eligibility fact
per settled task/work item, bound to its settlement receipt and Outcomes. It must not create
an `operator_review_item`, which does not exist until Package 11.

Cover all direct correction transitions:

| Prior payout | New payout | New cash rows |
| --- | --- | --- |
| positive | zero | one exact negative `payout_reversal` |
| zero | positive | one positive `payout` |
| positive | positive | direct-predecessor reversal plus replacement payout |
| zero | zero | none |

Add a third correction proving it reverses only the second revision's positive replacement.
Assert unique `reverses_transaction_id`, no repeated stake, and no mutation/deletion of prior
settlement or cash rows.

- [ ] **Step 7: Implement queued settlement and one atomic task run**

The request handler validates readiness and queues an immutable request. The worker claims it
idempotently and executes exactly one `settle_task` Action. Scope all placed Tickets for the
work item, validate note/placement totals, grade against the exact result revision, and write
the run receipt plus every settlement/grade/cash row in one UOW. Enforce:

```python
assert requested_ticket_count == eligible_ticket_count + skipped_ticket_count
assert eligible_ticket_count == settled_ticket_count
assert persisted_settlement_count == len(ticket_settlement_revision_ids)
assert persisted_note_grade_count == repository.count_run_note_grades(run_id)
assert persisted_leg_grade_count == repository.count_run_leg_grades(run_id)
assert persisted_cash_count == repository.count_run_cash_links(run_id)
```

Use only the closed skip codes `already_current`, `result_not_ready`, `prize_not_ready`, and
`placement_integrity_blocked`. A persisted unsupported market or invariant mismatch aborts
the run rather than becoming a skip.

After count reconciliation, append the settlement-backed forecast/money review-eligibility
fact in the same transaction. Package 11 alone projects this fact into an actionable review
row.

- [ ] **Step 8: Write strict CLI, DTO/API, worker, and result-view RED tests**

Invoke `workflow ingest-results --manifest <path>` against valid, missing, conflict,
postponed, correction, and malformed fixtures; assert output counts reconcile to persisted
rows and no partial Action survives rejection. Through `/api/v2/operator`, test
`request_settlement`, wrong-command/stale tokens, unknown fields, browser-supplied actor or
result IDs, and worker queue/replay. Advance the global Action high water beyond the
scoreboard projection and prove `request_settlement` is unaffected; settlement has no
scoreboard dependency. Render source readiness,
conflict, result facts, prize readiness, every note/leg grade, payout/correction, and
`not_applicable` without raw payloads or ontology IDs.

- [ ] **Step 9: Wire strict CLI, DTO/API, worker, and result view**

Add `uv run nutmeg workflow ingest-results --manifest <path>` and print only business key,
manifest hash, agreement counts, Outcome count, prize-table state, and Action status. It
never researches or synthesizes a source. The Application offers only judge-owned
`request_settlement`; GET renders source availability/conflict, normalized 90-minute facts,
prize readiness, Ticket/note/leg grades, payout and correction labels. Technical IDs and
payload locations stay in audit drill-down. `not_applicable` always has zero totals, null
currency, and no Ticket rows.

- [ ] **Step 10: Verify both lane settlements and commit Package 10**

```bash
uv run pytest tests/ontology/operator/test_result_migration.py tests/ontology/operator/test_result_ingest.py tests/ontology/operator/test_task_settlement.py tests/ontology/operator/test_settlement_corrections.py tests/product/operator_v2/test_result_contracts.py tests/product/operator_v2/test_result_ui.py tests/ontology/test_odds_faithful_settlement.py tests/ontology/test_settlement_grading.py tests/decision/test_results_source.py -q
uv run ruff check nutmeg/ontology/operator/result_manifest.py nutmeg/ontology/operator/result_actions.py nutmeg/ontology/repository/schema_operator_result.py nutmeg/ontology/repository/operator_result.py nutmeg/ontology/finance/settlement.py nutmeg/product/operator_settlement.py tests/ontology/operator tests/product/operator_v2
```

The named tests accept `NUTMEG_P10_REPLAY_ROOT`, drive the public result CLI plus request and
worker boundaries, and retain `<root>/data/ontology/ontology.db`. Each test invokes the real
`workflow ingest-results` Typer command, submits settlement through `/api/v2/operator`, and
lets the TestClient lifespan worker claim it. Boundary guards fail the test if it directly
imports a result Action, settlement service, worker `run_once`, or repository insert. Run
these exact isolated commands:

```bash
NUTMEG_P10_JCZQ_ROOT="$(mktemp -d /tmp/nutmeg-p10-jczq.XXXXXX)"
env NUTMEG_P10_REPLAY_ROOT="$NUTMEG_P10_JCZQ_ROOT" NUTMEG_DATA_DIR="$NUTMEG_P10_JCZQ_ROOT/data" NUTMEG_PRODUCTION_DATA_DIR="/Users/jz71/Projects/Nutmeg/.nutmeg-data" NUTMEG_OPERATOR_RUNTIME_SCOPE=isolated_candidate NUTMEG_OPERATOR_SURFACE_MODE=active NUTMEG_OPERATOR_TOKEN_SIGNING_KEY=isolated-p10-signing-key-32-bytes-min uv run pytest tests/ontology/operator/test_task_settlement.py::test_isolated_jczq_public_replay -vv -s
sqlite3 "$NUTMEG_P10_JCZQ_ROOT/data/ontology/ontology.db" "SELECT action_type,status,count(*) FROM actions GROUP BY 1,2 ORDER BY 1,2; SELECT count(*) FROM operator_result_source_receipts; SELECT count(*) FROM operator_outcome_revisions; SELECT settlement_state,count(*) FROM operator_ticket_settlement_revisions GROUP BY 1; SELECT count(*) FROM operator_ticket_note_settlements; SELECT count(*) FROM operator_ticket_note_leg_settlements; SELECT count(*),sum(amount_minor) FROM operator_settlement_cash_links; SELECT terminal_kind,count(*) FROM operator_artifact_terminal_receipts GROUP BY 1; SELECT count(*) FROM tickets;"

NUTMEG_P10_ZUCAI_ROOT="$(mktemp -d /tmp/nutmeg-p10-zucai.XXXXXX)"
env NUTMEG_P10_REPLAY_ROOT="$NUTMEG_P10_ZUCAI_ROOT" NUTMEG_DATA_DIR="$NUTMEG_P10_ZUCAI_ROOT/data" NUTMEG_PRODUCTION_DATA_DIR="/Users/jz71/Projects/Nutmeg/.nutmeg-data" NUTMEG_OPERATOR_RUNTIME_SCOPE=isolated_candidate NUTMEG_OPERATOR_SURFACE_MODE=active NUTMEG_OPERATOR_TOKEN_SIGNING_KEY=isolated-p10-signing-key-32-bytes-min uv run pytest tests/ontology/operator/test_task_settlement.py::test_isolated_zucai_public_replay -vv -s
sqlite3 "$NUTMEG_P10_ZUCAI_ROOT/data/ontology/ontology.db" "SELECT action_type,status,count(*) FROM actions GROUP BY 1,2 ORDER BY 1,2; SELECT count(*) FROM operator_result_source_receipts; SELECT count(*) FROM operator_outcome_revisions; SELECT count(*) FROM zucai_prize_table_revisions; SELECT prize_tier_code,sum(winning_unit_count),sum(payout_minor) FROM operator_ticket_note_settlements GROUP BY 1 ORDER BY 1; SELECT count(*),sum(amount_minor) FROM operator_settlement_cash_links; SELECT terminal_kind,count(*) FROM operator_artifact_terminal_receipts GROUP BY 1; SELECT count(*) FROM tickets;"

NUTMEG_P10_CORRECTION_ROOT="$(mktemp -d /tmp/nutmeg-p10-correction.XXXXXX)"
env NUTMEG_P10_REPLAY_ROOT="$NUTMEG_P10_CORRECTION_ROOT" NUTMEG_DATA_DIR="$NUTMEG_P10_CORRECTION_ROOT/data" NUTMEG_PRODUCTION_DATA_DIR="/Users/jz71/Projects/Nutmeg/.nutmeg-data" NUTMEG_OPERATOR_RUNTIME_SCOPE=isolated_candidate NUTMEG_OPERATOR_SURFACE_MODE=active NUTMEG_OPERATOR_TOKEN_SIGNING_KEY=isolated-p10-signing-key-32-bytes-min uv run pytest tests/ontology/operator/test_settlement_corrections.py::test_isolated_direct_predecessor_correction_replay -vv -s
sqlite3 "$NUTMEG_P10_CORRECTION_ROOT/data/ontology/ontology.db" "SELECT action_type,status,count(*) FROM actions GROUP BY 1,2 ORDER BY 1,2; SELECT settlement_state,count(*) FROM operator_ticket_settlement_revisions GROUP BY 1; SELECT transaction_kind,amount_minor,reverses_transaction_id IS NOT NULL FROM operator_settlement_cash_links ORDER BY rowid; SELECT count(*) FROM tickets; SELECT count(*) FROM operator_placement_cash_links;"
```

Expected: the two-match/multi-market JCZQ Ticket and SFC plus multi-group Renjiu Tickets have
exact note counts and payouts reconciled to the signed ledger; the correction replay produces
only the specified direct-predecessor reversal/replacement rows. Commit:

```bash
git commit -m "feat(settlement): settle complete dual-lane ticket tasks"
```

## Package 11: Review lifecycle and scoreboard completion receipts

**Branch:** `feat/operator-review-scoreboard`

**Files:**

- Create: `nutmeg/ontology/repository/schema_operator_review.py`
- Create: `nutmeg/ontology/repository/operator_review.py`
- Create: `nutmeg/ontology/operator/review_actions.py`
- Modify: `nutmeg/ontology/repository/migrations.py`
- Modify: `nutmeg/ontology/repository/unit_of_work.py`
- Modify: `nutmeg/ontology/wiring.py`
- Modify: `nutmeg/ontology/actions/scoreboard_actions.py`
- Modify: `nutmeg/product/operator_workers.py`
- Modify: `nutmeg/product/operator_contracts.py`
- Modify: `nutmeg/product/operator_state.py`
- Modify: `nutmeg/product/operator_queries.py`
- Modify: `nutmeg/product/operator_actions.py`
- Modify: `nutmeg/interfaces/operator_api.py`
- Modify: `nutmeg/interfaces/cli/scoreboard.py`
- Create: `nutmeg/interfaces/web/templates/operator/steps/review_v2.html`
- Create: `tests/ontology/operator/test_review_migration.py`
- Create: `tests/ontology/operator/test_review_actions.py`
- Create: `tests/ontology/operator/test_review_completion.py`
- Create: `tests/product/operator_v2/test_review_contracts.py`
- Create: `tests/product/operator_v2/test_review_ui.py`
- Modify: `tests/analytics/test_scoreboard_projection.py`
- Modify: `tests/product/test_scoreboard_projection_cli.py`

- [ ] **Step 1: Write migration 25 and review-creation RED tests**

Require append-only `operator_review_items`,
`operator_scoreboard_effect_disposition_revisions`,
`operator_scoreboard_review_observation_links`,
`operator_scoreboard_review_completion_requests`, and
`operator_scoreboard_review_completion_receipts`. Test unique/current disposition rules,
one completion receipt per review, immutable supersession before completion, terminality
after completion, Action foreign keys, and nullable fields constrained by disposition. Grant
`materialize_operator_review_item` and `complete_scoreboard_review` only to
`deterministic_system`; disposition and observation-link requests remain judge-owned.

Derive review items only through the exact `materialize_operator_review_item` Action from the
Package 8-10 `operator_review_eligibility_facts`; no earlier
package writes a review row. Cover placed settlement, zero-placement no-ticket, natural
expiry, and official cancellation. A zero-placement eligibility with no baseline becomes an
operational/data-availability review immediately after deployment terminality. One with a
baseline remains ineligible until the bound Outcomes exist, then becomes forecast-truth
review. Passive result waiting does not occupy Today, but an actionable review returns as
`scope_kind=review` without making an archived task current. Repeated worker projection is
idempotent and one eligibility fact can create at most one review item.
Each Action that creates an eligibility fact also atomically appends its unique
`review_materialization` job, even before the Package 11 consumer exists.

- [ ] **Step 2: Verify review migration RED**

```bash
uv run pytest tests/ontology/operator/test_review_migration.py tests/ontology/operator/test_review_actions.py -v
```

Expected: migration 25 and the review actions are missing.

- [ ] **Step 3: Write review derivation and disposition RED tests**

Start with eligibility facts from no-ticket, unrequested timeout, cancellation, placed
settlement, and baseline-waits-for-Outcomes fixtures. Run the deterministic review worker and
assert exactly the eligible rows appear, exact replay adds none, and no GET creates a review.
Assert each row names its `materialize_operator_review_item` Action, actor role
`deterministic_system`, and idempotency key derived from the eligibility fact plus exact
satisfied Outcome revisions.
Test `effect_required`/`no_effect`, non-empty reason, metric-key cross-fields, current-revision
CAS, supersession only before completion, wrong role/token, and rollback after disposition or
completion-receipt insertion.

- [ ] **Step 4: Implement closed review projection and judge actions**

Present forecast truth, money ledger, and intervention quality as separate sections. Link
current Prediction grade work, Adjudications, Factor verdicts, night-calibration reports,
and scoreboard observations without inventing a combined score. Browser grading remains the
one named `grade_prediction` Action; there is no generic review-grade payload.

Implement this closed disposition request:

```python
@dataclass(frozen=True, slots=True)
class RecordScoreboardEffectDispositionRequest:
    review_id: str
    expected_disposition_revision_id: str | None
    disposition: Literal["effect_required", "no_effect"]
    required_metric_keys: Sequence[str]
    reason: str
    pre_update_legacy_sha256: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime
```

Both variants require a non-empty human reason. `effect_required` requires unique,
registered, non-empty metric keys; `no_effect` requires none. For `no_effect`, the same
judge Action atomically writes the disposition and its completion receipt with all
post-update/observation/shadow fields null. For `effect_required`, it writes no completion
receipt and keeps the review pending.

- [ ] **Step 5: Write observation-link and exact shadow-token RED tests**

Test one linked observation per required metric key, same review/disposition, same explicit
post-update hash, no duplicate/superseded/wrong-key/wrong-review Action, and observation
high-water inclusion. Build two qualifying global shadow reviews and prove completion uses
the exact signed token submitted by Jun rather than the newest row. Reject a token with the
wrong ID, legacy hash, metric set, source high-water, unexplained relevant difference, or a
high-water below any linked Action. Assert GETs, projection rebuilds, and unrelated shadow
runs never write a completion request or receipt.

```python
class ShadowReviewTokenPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    shadow_review_id: str
    source_high_watermark: int
    compared_legacy_sha256: str
    metric_keys: Sequence[str]
```

- [ ] **Step 6: Implement explicit completion request plus deterministic worker**

`record_scoreboard_observation` receives a signed review token and exactly one required
metric key, then delegates to the existing scoreboard observation Action and appends the
review link in the same failure boundary. `request_scoreboard_review_completion` records the
current review/disposition and the exact opaque shadow token and atomically appends one
`scoreboard_review_completion` job. Replay adds neither a request nor a job. It does not search storage.
The worker verifies that token, every link, current `scoreboard.json` hash supplied by the
governed external step, the explicit shadow review, high water, and zero unexplained
differences for the review's keys, then atomically writes
`ScoreboardReviewCompletionReceipt` through `deterministic_system`.

Do not reuse `approve_scoreboard_cutover`; completion neither changes authority nor writes
the JSON file. Projection rebuild remains build-only and Action-free.

- [ ] **Step 7: Write strict review API/UI and projection-staleness RED tests**

Cover the allowlisted `grade_prediction`, `record_scoreboard_effect_disposition`,
`record_scoreboard_observation`, and `request_scoreboard_review_completion` DTOs. Reject
generic grade targets, Factor lifecycle commands, raw Action IDs, actor roles, arbitrary
observation mappings, missing reasons, and unknown fields. Render the external gates in
order: legacy scoreboard update observed, linked observations committed, selected shadow
reconciliation valid. Keep completion visibly pending until its receipt exists and provide
the external CLI recovery step without a button that edits `scoreboard.json` or performs
cutover.

Advance the Action high water beyond the projection and assert each scoreboard-dependent
control independently returns `projection_stale`: effect disposition, observation, and
review completion. The `rebuild_scoreboard_projection` control remains enabled, invokes only
the build-only projector, leaves both Action high water and `scoreboard.json` hash unchanged,
and makes a fresh GET ready. Tokens minted before the rebuild remain stale; freshly minted
tokens can proceed. `grade_prediction` and unrelated lane controls must not gain a false
scoreboard dependency.

- [ ] **Step 8: Implement the strict review API and focused view**

Add only the four domain command DTOs plus the build-only
`rebuild_scoreboard_projection` maintenance DTO and delegate to their named boundaries.
Verify the Package 1 command-bound snapshot token and each command's declared projection high
water immediately before mutation. Render the three
external completion gates from typed receipts, keep pending/complete states stable, and expose
only a maintenance link for the external scoreboard update/shadow commands. No page or API
writes `scoreboard.json`, chooses a metric key, or performs cutover.

- [ ] **Step 9: Verify review completion and commit Package 11**

```bash
uv run pytest tests/ontology/operator/test_review_migration.py tests/ontology/operator/test_review_actions.py tests/ontology/operator/test_review_completion.py tests/product/operator_v2/test_review_contracts.py tests/product/operator_v2/test_review_ui.py tests/ontology/test_scoreboard_actions.py tests/analytics/test_scoreboard_projection.py tests/product/test_scoreboard_projection_cli.py tests/scoreboard/ -q
uv run ruff check nutmeg/ontology/operator/review_actions.py nutmeg/ontology/repository/schema_operator_review.py nutmeg/ontology/repository/operator_review.py nutmeg/product/operator_workers.py nutmeg/product/operator_contracts.py nutmeg/product/operator_state.py nutmeg/product/operator_queries.py nutmeg/product/operator_actions.py tests/ontology/operator tests/product/operator_v2
```

Expected: `no_effect` completes atomically; `effect_required` completes only from the
explicit selected shadow token; a checksum of the fixture `scoreboard.json` is unchanged by
every Application test. Commit:

```bash
git commit -m "feat(review): bind operator completion to scoreboard shadow"
```

## Package 12: Operator UX, manual, full replay, and activation gate

**Branch:** `feat/operator-workbench-completion`

**Files:**

- Modify: `nutmeg/product/operator_contracts.py`
- Modify: `nutmeg/product/operator_state.py`
- Modify: `nutmeg/product/operator_lanes.py`
- Modify: `nutmeg/product/operator_queries.py`
- Modify: `nutmeg/product/operator_actions.py`
- Create: `nutmeg/product/operator_maintenance.py`
- Modify: `nutmeg/product/wiring.py`
- Modify: `nutmeg/interfaces/operator_api.py`
- Modify: `nutmeg/interfaces/operator_ui.py`
- Modify: `nutmeg/interfaces/product_api.py`
- Modify: `nutmeg/interfaces/cli/product.py`
- Replace: `nutmeg/interfaces/web/templates/operator/worklist.html`
- Replace: `nutmeg/interfaces/web/templates/operator/task.html`
- Create: `nutmeg/interfaces/web/templates/operator/today.html`
- Create: `nutmeg/interfaces/web/templates/operator/lane.html`
- Create: `nutmeg/interfaces/web/templates/operator/_queue_entry.html`
- Create: `nutmeg/interfaces/web/templates/operator/_task_summary.html`
- Create: `nutmeg/interfaces/web/templates/operator/_status.html`
- Create: `nutmeg/interfaces/web/templates/operator/_audit_details.html`
- Create: `nutmeg/interfaces/web/templates/operator/maintenance.html`
- Modify: `nutmeg/interfaces/web/static/product/operator.css`
- Modify: `nutmeg/interfaces/web/static/product/operator.js`
- Create: `docs/application-operator-manual.md`
- Create: `tests/product/fixtures/operator/current/jczq-sale.json`
- Create: `tests/product/fixtures/operator/current/zucai-issue.json`
- Create: `tests/product/fixtures/operator/current/scoreboard.json`
- Create: `tests/product/operator_v2/test_contract_completeness.py`
- Create: `tests/product/operator_v2/test_today_lane_queries.py`
- Create: `tests/product/operator_v2/test_operator_security.py`
- Create: `tests/product/operator_v2/test_maintenance_ownership.py`
- Create: `tests/product/test_operator_v2_e2e.py`
- Create: `tests/product/test_operator_v2_browser.py`
- Modify: `tests/product/test_operator_api.py`
- Modify: `tests/product/test_operator_ui.py`

- [ ] **Step 1: Write complete DTO, resolver, and route RED tests**

Instantiate every normal response and every command with unknown fields to prove
`extra="forbid"`. Reject naive datetimes, floats for money/probability, arbitrary mappings,
actor/role/policy/internal-ID fields, illegal scope/phase/outcome combinations, and a
schedule recovery row with a fake business key or task token. Assert passive/archive work
items have nullable actions, while every Today row has one action or external recovery.

Create mixed JCZQ/Zucai fixtures proving the exact Today priority order, stable tie breaks,
successive JCZQ waves, multiple current business keys, tomorrow presale, historical review
re-entry, recovery-only null focus, and all-closed archive landing. Odds, probability,
confidence, EV, and narrative changes must leave ordering unchanged. Test all four root mode
rows again after the full v2 router is mounted.

Add maintenance RED tests with an injected subprocess runner. Permit only these bounded,
read-only argv shapes: `openclaw cron list --all --json`,
`openclaw channels status --channel telegram --json`, and
`launchctl print gui/<os.getuid()>/<closed Nutmeg label>`. Parse only job label, normalized
stage, enabled/loaded state, last run/status, and the `telegram:nutmeg` configured/running/
connected timestamps into strict DTOs. Detect two enabled owners of the same normalized
Nutmeg stage, but do not call enable/disable/run/edit commands. Timeout, malformed JSON, an
unknown label, or a nonzero result yields `diagnostic_unavailable`, never an inferred absent
owner. Assert the probe neither changes Action/outbox/Ticket/cash counts nor writes files.

Table-drive the closed registry exactly as follows:

| `OperatorStage` | OpenClaw exact name / normalized argv marker | launchd label |
| --- | --- | --- |
| `JCZQ_AM` | `Nutmeg-AM数据入库`; `Nutmeg-临场数据刷新`; `run-strict --stage am` | `com.nutmeg.decision.am` |
| `JCZQ_DECISION` | `Nutmeg-每日最终决策` | - |
| `JCZQ_DECISION_RECOVERY` | `Nutmeg-最终决策受限补跑` | - |
| `JCZQ_PRECLOSE_CHECK` | `Nutmeg-收盘前闸门`; `validate-preclose` | - |
| `JCZQ_CLOSE` | `Nutmeg-收盘`; `run-strict --stage close` | `com.nutmeg.decision.close` |
| `JCZQ_CLOSE_VERIFY` | `Nutmeg-收盘交付确认`; `verify-close` | - |
| `JCZQ_SETTLE` | `Nutmeg-昨日结算`; `decision-settle`; `run-strict --stage settle` | `com.nutmeg.decision.settle` |
| `JCZQ_SETTLEMENT_RETRY` | `Nutmeg-D1D2补结算`; `retry-settlement` | - |
| `ZUCAI_PREP` | - | `com.nutmeg.zucai.prep` |
| `ZUCAI_PREP_REVISION` | - | `com.nutmeg.zucai.prep-revision` |
| `ZUCAI_AFTERNOON` | - | `com.nutmeg.zucai.afternoon` |
| `ZUCAI_REVISION` | - | `com.nutmeg.zucai.revision` |

Count each enabled OpenClaw job and each loaded launchd label as one claim. Assert that any
two claims for the same enum are a conflict, including two OpenClaw jobs with the same owner;
the explicitly separate recovery/check/retry enums do not collide with their primary stage.
An exact name whose normalized argv maps elsewhere, an unknown Nutmeg name/label, or an
accepted command with unrecognized arguments makes the diagnostic unavailable rather than
using substring inference.

- [ ] **Step 2: Verify product-contract RED**

```bash
uv run pytest tests/product/operator_v2/test_contract_completeness.py tests/product/operator_v2/test_today_lane_queries.py tests/product/operator_v2/test_operator_security.py tests/product/operator_v2/test_maintenance_ownership.py -v
```

Expected: incomplete v2 DTOs/routes and old v1 template assumptions fail.

- [ ] **Step 3: Finish strict query/action boundaries and routes**

Return only `OperatorTodayResponseV1`, `OperatorLaneResponseV1`, task/work-item StepView
unions, and the deliberate audit envelope. Repositories return typed frozen rows; query
services translate them to business labels. Define routes explicitly:

```text
GET  /operator-next
GET  /operator-next/{lane}
GET  /operator-next/{lane}/{business_key}
GET  /operator-next/{lane}/{business_key}/{work_item_key}
GET  /operator-next/audit/{audit_token}
GET  /operator-next/maintenance
POST /api/v2/operator
GET  /api/v2/operator/today
GET  /api/v2/operator/lanes/{lane}
GET  /api/v2/operator/tasks/{lane}/{business_key}
GET  /api/v2/operator/maintenance
```

The single POST endpoint parses its `kind` into the closed allowlist and delegates one named
method. Origin/CSRF, server identity, idempotency, permission, and snapshot validation happen
before domain mutation. There is no generic object-write route, shell invocation, final
placement route, scoreboard JSON write, cutover, release, or scheduler mutation.

Implement `operator_maintenance.py` as a read-only adapter over an injected fixed-argv
runner with timeout and output-size limits. Normalize only the closed Nutmeg stages and
launchd labels; requests cannot supply a command, label, UID, path, URL, or environment.
Strip cron payload messages, diagnostic text, tokens, chat IDs, and raw JSON before building
the DTO. The maintenance query combines the native confirmation-plugin heartbeat with the
selected `nutmeg` account from channel status, keeping `handler loaded` and
`transport connected` as distinct facts. It reports ownership conflicts and recovery commands as text,
but exposes no mutation route.

- [ ] **Step 4: Write phase-complete template and usability RED tests**

Render every phase and recovery code for both lanes. Assert normal pages contain no `pre`,
raw JSON braces, schema version, traceback, Action ID, source payload path, hash, token,
high-water number, secret, or transport config. Assert one primary command per phase;
no-ticket remains secondary; candidate rows form one comparison table; statuses include
text/icon labels; and technical lineage is reachable only from audit drill-down.

Test the user's actual questions directly: Today names what needs attention, each row says
why it matters and what action is possible, and empty/blocked states identify the repair
owner and reevaluation path. Do not add instructional marketing copy inside the workbench.

- [ ] **Step 5: Implement the Today, lane, task, and audit views**

Use a restrained workbench layout: stable top navigation for Today/Zucai/JCZQ, one emphasized
next action, compact later-action rows, a match rail on desktop, and one reading column on
mobile. Use existing icon assets/library where available, labels plus icons for unfamiliar
states, 8px-or-less radii, and fixed control dimensions. Render evidence -> judgment ->
ticket impact -> action in mobile DOM order. All text is escaped; Jinja receives DTOs only.

`operator.js` transports strict forms, preserves focus, handles stale-token recovery, and
navigates to the server-returned link. It performs no money, probability, audit, deadline,
grade, or selection calculation. `operator.css` uses bounded grid tracks and breakpoints,
never viewport-scaled font sizes or negative letter spacing.

- [ ] **Step 6: Write both-lane isolated lifecycle RED tests**

Use fresh temporary data/artifact/projection roots. Drive both chains through public CLI/API
boundaries:

```text
official slate -> evidence intake -> freeze -> market prior -> envelope
-> all match judgments -> prescription -> exhaustive candidates -> selection
-> lineage/audit -> artifact -> simulated human callback or cutoff shadow
-> ledger/not_applicable -> result/prize ingest -> settlement -> review
-> external scoreboard fixture update -> observation -> selected shadow -> completion
```

After every transition, compare expected counts across Actions, domain tables, response DTO,
and rendered page. Inject a rejected Action into evidence, judgment, candidate, approval,
placement, result, settlement, and review and prove progress does not move. Cover active to
read-only rollback with in-flight confirmation completion, and assert the fixture scoreboard
hash changes only in the explicit external-update test helper.

- [ ] **Step 7: Implement only the missing orchestration needed by the replay**

Complete wiring, worker drains, outbox invalidation, and recovery mapping exposed by the RED
test. Do not add new domain policy in the query/UI layer. Each worker takes a bounded
`run_once(limit)` call so tests and operations can reconcile queued/committed counts without
an unbounded loop. The e2e fixture records exact Action types and roles, proving every
football judgment is `judge_operator`, infrastructure work is `deterministic_system`, and
no Action grants AI a protected authority.

- [ ] **Step 8: Write Playwright desktop/mobile RED tests**

Run at 1440x900 and 390x844. Cover Today ordering, both lane tabs, evidence block/recovery,
all-match judgment save/advance, candidate comparison with no default selection, audit
return-to-edit, explicit no-ticket, confirmation waiting, simulated placement and timeout,
ledger, result conflict, settlement, review pending/completed, and archive links. Assert:

```python
assert page.locator("pre").count() == 0
assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
assert page.locator("[data-primary-command='true']:visible").count() <= 1
assert not INTERNAL_TEXT.search(page.locator("body").inner_text())
assert_no_overlaps(page, selectors=CRITICAL_OPERATOR_SELECTORS)
```

Capture full-page desktop/mobile screenshots for Today, judgment, candidates, confirmation,
settlement, and review. Require nonblank files and inspect them before GREEN.

- [ ] **Step 9: Implement browser refinements and verify screenshots**

Fix only behavior/layout represented by the failing Playwright tests. Use semantic controls:
checkboxes for faces/evidence refs, radio/segmented options where one choice is required,
number inputs for Decimal strings, and icon buttons with tooltips for compact utilities.
Ensure the longest competition/team/recovery labels wrap without covering adjacent content;
buttons remain at least 44px high on mobile; dynamic status content does not shift the action
area. Inspect every captured image with the browser/image tooling and record dimensions and
nonblank pixel checks.

- [ ] **Step 10: Write and verify the operator manual**

Create `docs/application-operator-manual.md` in operator language, with these exact sections:

1. startup and address;
2. Today, Zucai, and JCZQ navigation;
3. official schedule/evidence external collection;
4. evidence freeze and structured per-match judgment;
5. candidate comparison, audit, override boundary, and no-ticket;
6. Telegram actual-placement confirmation and timeout shadow;
7. ledger, three-source results, settlement, and corrections;
8. review, external `scoreboard.json` update, observe, shadow, and completion;
9. stable recovery-code table;
10. read-only rollback and authority boundaries.

Include exact supported commands and expected business output, but no secret values, raw
payload dumps, or suggestion that the Application chooses a bet. State plainly that
Application confirmation stage one is a request, Telegram owner confirmation attests actual
placement, and lack of a ledger row means not placed.

- [ ] **Step 11: Verify Package 12 and commit**

```bash
uv run pytest tests/product/operator_v2 tests/product/test_operator_v2_e2e.py tests/product/test_operator_v2_browser.py tests/product/test_operator_api.py tests/product/test_operator_ui.py -q
uv run ruff check nutmeg/product nutmeg/interfaces/operator_api.py nutmeg/interfaces/operator_ui.py nutmeg/interfaces/product_api.py nutmeg/interfaces/cli/product.py tests/product/operator_v2 tests/product/test_operator_v2_e2e.py tests/product/test_operator_v2_browser.py
```

Expected: both complete chains pass; all screenshots are nonblank and overlap-free; normal
pages expose no JSON/internal identifiers; active mode remains available only under the
runtime gate. Commit:

```bash
git commit -m "feat(product): complete dual-lane operator workbench"
```

## Full verification and production-safe handoff

### 1. Run the complete automated gate

```bash
uv run ruff check .
uv run python -m compileall -q nutmeg tests
uv run pytest tests/decision/ tests/ontology/ tests/product/ tests/analytics/ tests/migration/ tests/scoreboard/ -q
uv run pytest tests/test_openclaw_router.py tests/test_nutmeg_ticket_confirmation_bridge.py tests/test_telegram_bot.py tests/test_telegram_ticket_confirmation.py -q
node --test integrations/openclaw/nutmeg-ticket-confirmation/index.test.mjs
openclaw plugins validate --root integrations/openclaw/nutmeg-ticket-confirmation --entry index.js
```

Expected: every command exits 0. Record collected/passed counts from fresh output; do not
reuse counts from an earlier package.

### 2. Run the Nutmeg decision real-chain recipe

Use the repository `verify` skill. Drive an isolated `decision-am` snapshot replay,
`decision-settle`, and `decision-close` path plus the two new full operator chains. Reconcile
service-returned counts against persisted Actions/domain rows. Final placement remains a
simulated human callback in isolated data; no real bet or public dispatch is permitted.

### 3. Back up and migrate production ontology only after all isolated gates pass

Resolve and print the configured production path first; it must equal
`/Users/jz71/Projects/Nutmeg/.nutmeg-data/ontology/ontology.db`. Stop if it resolves
elsewhere. Stop the acceptance server and choose a quiet scheduler window. The guarded
command below must acquire the Package 1 exclusive writer lease before its first source
audit and retain the same open descriptor until backup, migration, and post-migration audit
all finish. The SQLite online-backup API is mandatory because production uses WAL; copying
only the main file can omit committed rows. Then:

```bash
NUTMEG_PROD_ROOT=/Users/jz71/Projects/Nutmeg/.nutmeg-data
NUTMEG_PROD_DB="$NUTMEG_PROD_ROOT/ontology/ontology.db"
NUTMEG_BACKUP_DB=/Users/jz71/Projects/Nutmeg/.nutmeg-data/archive/ontology-pre-v17-20260904.db
mkdir -p /Users/jz71/Projects/Nutmeg/.nutmeg-data/archive
test ! -e "$NUTMEG_BACKUP_DB"
env NUTMEG_PRODUCTION_DATA_DIR="$NUTMEG_PROD_ROOT" \
  uv run nutmeg ontology guarded-init \
  --data-dir "$NUTMEG_PROD_ROOT" \
  --backup-file "$NUTMEG_BACKUP_DB" \
  --format json
sqlite3 "$NUTMEG_PROD_DB" "PRAGMA integrity_check; PRAGMA user_version; SELECT coalesce(max(rowid),0) FROM actions;"
sqlite3 "$NUTMEG_BACKUP_DB" "PRAGMA integrity_check; PRAGMA user_version; SELECT coalesce(max(rowid),0) FROM actions;"
shasum -a 256 "$NUTMEG_BACKUP_DB"
```

The command's JSON receipt must include the one lease identity, pre-source facts, backup
facts, applied migration versions, post-source facts, and backup SHA-256. It exits before
migration if the lease is contended or if backup schema/high-water/key counts differ from the
source snapshot captured under that lease. Expected: both integrity checks print `ok`;
production reaches schema 25; the backup remains at schema 16 with exactly the stable
pre-migration counts. Record only the backup's SHA-256 because a WAL-safe logical snapshot
need not be byte-identical to the source file. Do not restore, overwrite, or delete any
database. If the archive path already exists, stop and choose a new explicit name.

### 4. Perform read-only production audit

With `operator_surface_mode=shadow` and production scope, run only GETs/read-only audit
commands. Record current official business keys, schedule-check states, evidence counts,
Action high water, projection ready/stale state, Telegram owner/heartbeat state, and the
instance lease. Hash `scoreboard.json` before and after and require equality. Shadow GETs
must not change Action, outbox, shadow, placement, or cash counts.

### 5. Start the acceptance Application without crossing user gates

Keep production default/root `legacy_read_only`; do not set
`operator_accepted_commit`, activate production root, change launchd, cut over scoreboard,
record soak, or issue ReleaseApproval. Start a verified isolated candidate in `active` mode
on loopback with its own data directory and simulated confirmation transport, or expose the
new production projection at `/operator-next` in read-only `shadow` mode. Acquire the lease
and verify both the health endpoint and browser page before reporting the URL. Leave exactly
one intended server running for Jun's actual test.

## Explicit exclusions

- No autonomous research, probability judgment, match/market/face choice, rule
  interpretation, no-ticket reason, adjudication, candidate selection, or deployment choice.
- No Web/AI final placement, automatic betting, unattended placement trigger, or AI
  `ConfirmDispatch` authority.
- No `scoreboard cutover`, launchd enable/disable/edit, soak entry, ReleaseApproval, or
  production root activation.
- No `CONSTITUTION.md` modification and no C7 policy resolution.
- No WAF bypass, okooo/500.com scraping workaround, support-rate collector, generic multi-user
  cloud product, or mass narrative-history migration.
- No Application write to `.nutmeg-data/scoreboard.json`; only the external governed step may
  change it.
- No modification, staging, or commit of the three protected user files or unrelated handoff
  and rendering scripts named at the start of this plan.

## Plan self-review

### Spec coverage matrix

| Approved design requirement | Executable package(s) | Verification evidence required |
| --- | --- | --- |
| Purpose/current-chain replacement | 1, 2, 3, 12 | rx cannot discover tasks; both current lanes replay |
| Today/Zucai/JCZQ product shape and ordering | 2, 11, 12 | mixed deadline/archive/recovery resolver and browser tests |
| Official schedule checks, slates, offers, waves, focus | 2 | migration/importer, boundary-time and multi-key tests |
| Closed phase/outcome/deadline/archive lifecycle | 2, 8, 9, 11, 12 | state matrix, exact cutoff, Today re-entry tests |
| Strict E1-E6b/EC evidence and external ingest | 4 | strict manifest, freshness/conflict, count reconciliation |
| Immutable evidence freeze and invalidation | 5 | request/worker, supersession, stale descendant tests |
| Non-deployable market prior and human envelope | 6 | baseline worker, comparison-only and exact-input tests |
| Structured human judgment and decision lineage | 6, 8 | Decimal/Factor invariants, atomic Forecast link, lineage tests |
| Exhaustive dual-lane candidates and objective order | 7 | enumeration bound, union probability, 26111 replay |
| Current audit, external override, dedicated no-ticket | 8 | exact finding bindings, command receipt, cutoff-first CAS |
| Protected artifact, server deadline, fixed policy | 8 | current audit rerun, policy binding, approval race tests |
| Telegram owner, callback, notes, ledger, shadow | 9 | ownership, terminal permutation, rollback, dry-run tests |
| Three-source results and immutable Outcomes | 10 | strict result manifest, conflict/postpone/void/correction tests |
| JCZQ/Zucai settlement and cash corrections | 10 | all graders, counters, four correction transitions |
| Review queues and scoreboard external authority | 11 | no-effect/effect-required, exact shadow token, hash tests |
| Strict DTO/API/security/recovery behavior | 1, 4, 6-12 | extra-field/role/CSRF/405/recovery-code tests |
| Single instance, scheduler ownership, rollout/rollback | 1, 9, 12 | lease subprocess, route matrix, in-flight rollback tests |
| Desktop/mobile usability and no raw JSON | 12 | Playwright DOM, pixel, overlap, screenshot inspection |
| Full completion and acceptance gate | 12 and final gate | suites, verify recipe, backup/migration, read-only audit/server |
| Explicit exclusions and authority gates | every package | forbidden-route/role tests plus final diff/config audit |

No approved requirement is left without an implementation package and fresh evidence. The
review places the Zucai fixed-prize policy in migration 21 because candidate generation
already requires it. Migration 22 adds challenge revision/head storage plus the unified
artifact-terminal receipt/CAS and binds an approved artifact to that existing policy;
migration 23 migrates legacy challenges and extends the foundation with notes and placement
rather than creating a competing model.

### Mechanical and type review

- Migration order is fixed at 17 sale, 18 evidence intake, 19 evidence freeze, 20
  baseline/judgment, 21 candidates/fixed-prize policy, 22 deployment/no-ticket/terminal,
  challenge schema, 23 legacy challenge upgrade/notes/confirmation, 24 results/settlement,
  and 25 review completion.
- Shared identifiers are consistently named `task_snapshot_hash`,
  `expected_snapshot_token`, `ArtifactTerminalReason`, `ArtifactTerminalReceiptRow`,
  `official_offer_family_id`, `official_offer_revision_id`, `challenge_family_id`,
  `challenge_revision_id`, `fixed_prize_policy_revision_id`, `result_set_revision_id`, and
  `ScoreboardReviewCompletionReceipt`.
- All normal mutations use `OperatorCommandV2`; all deterministic completions are queued from
  a judge-owned request or an objective system event and execute through one outer UOW.
- Placeholder scan covers every prohibited marker and deferral phrase named by the
  `writing-plans` skill; it must return no matches before commit. Markdown fence count must
  be even, every inline code span must
  close on its own line, and `git diff --check` must pass.
- Package implementation may refine private helper names to fit existing local conventions,
  but changing a public DTO, Action name, authority, invariant, or persistence identity first
  requires updating the failing contract test and this approved plan/spec relationship.

## Execution handoff

The plan is complete at
`docs/superpowers/plans/2026-09-04-dual-lane-operator-workbench-rebuild.md`. Jun already chose
execution option 1, subagent-driven implementation, and authorized completion of all work.
Use a fresh worker for each package, require RED evidence before production edits, and perform
two reviews after every package: first against this plan/spec, then for code quality. The
named `superpowers:subagent-driven-development` package is not installed in this workspace,
so execution uses the native collaboration agents with the same fresh-agent and two-review
discipline. Never merge or push a package silently; stacked local branches/commits may keep
the work moving, with final integration reported for Jun's disposition.
