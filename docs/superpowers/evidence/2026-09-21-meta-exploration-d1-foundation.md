# Meta-Exploration D1 Ontology Foundation As-Built

Date: 2026-09-21 (UTC verification at 10:15:59Z)
Spec: `docs/superpowers/specs/2026-09-21-dream-rsi-meta-exploration-v1-design.md`
Plan: `docs/superpowers/plans/2026-09-21-dream-rsi-meta-exploration-d1.md`

## Scope Accepted For Review

D1 adds append-only discovery storage, guarded Actions, projections, and a read-only
`discovery status/show` CLI. It records fully formed facts in temporary tests; it does
not run an online harness, execute a policy, rank a tournament, or deploy a policy.
The production candidate, ticket, RSI, funds, and public-dispatch pathways are unchanged.

## Migration And Authority

- Migration 40 creates 19 append-only tables: `discovery_worlds`,
  `discovery_world_events`, `discovery_runs`, `discovery_nodes`,
  `discovery_node_evaluations`, `exploration_policy_revisions`,
  `exploration_policy_parent_links`, `policy_replay_runs`, `policy_replay_rounds`,
  `policy_replay_completions`, `policy_tournaments`,
  `policy_tournament_candidates`, `policy_tournament_worlds`,
  `policy_tournament_results`, `policy_tournament_completions`,
  `policy_archive_decisions`, `policy_holdout_exposures`,
  `policy_deployments`, and `policy_brake_events`.
- `create_discovery_world`: judge operator or deterministic system.
  `start_discovery_run`, `record_discovery_node`, `record_discovery_failure`,
  `seal_discovery_world`, `start_policy_replay`, `finish_policy_replay`,
  `finish_policy_tournament`, and `trip_policy_brake`: deterministic system only.
  `register_policy_revision`, `create_policy_tournament`, and
  `approve_policy_deployment`: judge operator only. Other roles are denied by default.
- Every Action goes through `ActionService` for permission, idempotency, atomic
  business/audit commit, and outbox. SQLite triggers reject UPDATE and DELETE on
  all 19 discovery tables. World state is projected from ordered events, not edited.
- Policy replay persists a root-only, prefix-checked trace; it never synthesizes
  children. Tournament completion persists a complete policy/world matrix and a
  `reproduction_hash` over frozen manifests, result cells, and declared winner.
  D4 must independently compute and check rankings before operational completion.
- Human deployment and reduce-only brake remain separate Actions. Canary/deploy
  require fresh sealed prospective shadow evidence and a distinct previously
  human-approved fallback. The CLI opens existing SQLite stores in `mode=ro`, does
  not initialize a fresh store, and refuses older schemas without migration.

## Frozen Inputs

Canonical SHA-256 from `nutmeg.discovery.contracts.canonical_hash`, rechecked on
2026-09-21:

- Pilot `experiments/discovery/structural-candidate-v1.contract.json`:
  `842c96bce8745ff2ae6b2249ab7d8c5e1771fc7d693581952db01863d029f08f`
- Incumbent `experiments/discovery/structural-baseline-v1.policy.json`:
  `a9dad2f5f7db577edabc379edfe60a61322e978ef9b1c2e42282040dd142e55a`

## Verification

Final commands run 2026-09-21 UTC before 10:15:59Z, after the D1 boundary
correction commit `dd7d0c5`:

| Check | Exit | Result |
| --- | --- | --- |
| D1 discovery contract, models, migration, repository, Actions, projections, CLI test files | 0 | 70 passed |
| Shared Ontology migration, Action, outbox, permission, replay, kernel tests | 0 | 47 passed |
| Candidate, candidate replay, protected ticket, and RSI tests | 0 | 54 passed |
| `uv run pytest -q` | 0 | Full suite reached 100%, no failures; two third-party websockets deprecation warnings |
| D1-targeted `uv run ruff check` (plan Task 9 paths) | 0 | All checks passed |
| `git diff --check` | 0 | No whitespace errors |
| `git status --short .nutmeg-data experiments/attempts.log experiments/corpus-v2.json` | 0 | No `.nutmeg-data` changes; two experiment files were modified before D1 and were not touched |
| `uv run ruff check .` | 1 | Three existing warnings in untracked `experiments/exp-price-bands.py` and `experiments/exp-strict-space.py`, unrelated to D1; files left untouched |

No operational harness, historical replay, tournament computation, policy generation,
RSI verdict, production migration, candidate selection, ticket, dispatch, funds,
or public-output action was executed. All D1 database writes in tests target
temporary stores.

## Remaining Boundaries

- D2: online shadow recorder, world sealing, effective-information readiness.
- D3: policy-visible environment and prefix-only replay runtime.
- D4: deterministic evaluator/aggregation, holdout tournaments, ranking proof.
- D5: metered constrained generators behind optimizer readiness; no model/system changes.
- D6: prospective shadow promotion and separate human canary/deploy/rollback approval.
- D7: recursive trigger, holdout rotation, archive maintenance, and drift operation.

The D1 exit gate requires Jun to review this evidence before D2 planning or
implementation. D1 does not grant policy execution or production deployment authority.
