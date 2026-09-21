# Meta-Exploration D5 Constrained Generation As-Built

Date: 2026-09-22
Spec: `docs/superpowers/specs/2026-09-21-dream-rsi-meta-exploration-v1-design.md`
Plan: `docs/superpowers/plans/2026-09-21-dream-rsi-meta-exploration-d5.md`

## Result and Authority

D5 is implemented at the isolated-code and fixture level. Generators emit proposals,
not registered policies or tournament winners. Only the existing operator-only
`register_policy_revision` Action admits an exact proposal from a persisted round;
D4 still inserts the original incumbent independently. No D6 prospective authority
is inferred. The task agent, evaluator, football rules, Action permissions and model
weights remain frozen. `workflow_search` and `tree_search` remain unsupported.

Migration 41 adds only append-only `policy_generation_rounds` and a
`deterministic_system` recorder permission; migration 40's table mapping and
historical rows remain unchanged. Blocked and empty rounds retain a manifest,
failed readiness metrics, attempt/candidate trace, separate generation cost and
Action/outbox audit. The Action verifies registered parents, a development cutoff,
sealed source trees, generator revision/hash, proposal hashes and charged attempts.
No source world, policy, tournament or protected business state is written by
generation other than the round receipt.

The versioned program accepts only closed template priority, batching, budget
allocation and STOP threshold fields. Pydantic rejects unknown/frozen fields,
oversized state and malformed lineage. D3 interprets it from the passed observation;
no arbitrary code, import, resource, filesystem/network read or Action call is
executed. Baselines reuse the D4 variant artifact. Evolution mutates or
recombines at most two eligible parents with complete ordered lineage. Both
generators enforce
candidate, compute-attempt and monotonic wall-time caps and record actual attempts;
this cost is not folded into D3 replay execution cost.

The service checks persisted readiness before building development context or
calling a generator. Baseline generation requires baseline-comparison readiness;
bounded evolution requires every optimizer metric to pass. Its read projection
derives replay integrity, overlap and unavailable-branch metrics only from
completed D3 baseline traces on sealed prospective worlds. The context excludes
open worlds and worlds after its development cutoff; generated archive parents
are read back from their validated source artifacts. Read-only `discovery show`
exposes rounds and policy lineage; schema-40 generation queries explicitly require
migration 41 without auto-migrating.

## Verification

- Strict RED-GREEN runs were observed for contracts, round Action/migration,
  baseline and evolution gates/timeouts, admission, interpreter and read-only CLI.
- Protected discovery/ontology/permission/migration/CLI suite: 247 tests
  collected, exited 0 after the final runtime edit.
- Seeded temporary-store round reproduction matched ordered candidate hashes,
  parent links, seed, manifest hash, trace hash and attempt cost twice. An
  unregistered proposal was rejected before D3 replay; the admitted proposal
  replayed a sealed fixture with a reproducible trace.
- Targeted Ruff across D5 modules and tests: `All checks passed!`.
- `git diff --check`: exited 0 before the implementation commit.
- `uv run pytest -q`: 3,916 tests collected, exited 0 after the final runtime
  edit, with two third-party websocket deprecation warnings.
- Repository-wide `uv run ruff check .` found three pre-existing issues only in
  unrelated untracked `experiments/exp-price-bands.py` and
  `experiments/exp-strict-space.py`. Those files were not edited or staged.
- The implementation commit is `8b7508f`; its hook passed staged Ruff and
  `tests/ontology/` and restored the unrelated unstaged worktree changes.

The read-only `uv run nutmeg discovery readiness` reports `record_only`:
sealed worlds 0/30 for baseline and 0/60 for optimizer, independent dates 0/20
and 0/40, effective samples 0/24 and 0/48, replay integrity and unavailable
branch rate unknown. The synthetic passing optimizer fixture is **not** real
optimizer readiness, SC-001 evidence, or promotion evidence. No live generation,
real shadow/canary/deploy, betting, funds or public action was run.

## Remaining Gates

Jun reviews this D5 evidence before D6 implementation. Real sealed prospective
worlds, validated D3 coverage/overlap and failed/degraded strata must satisfy
the frozen gate before optimizer operation; any real generation round, tournament,
shadow, canary or deployment needs its own authorization and evidence path.
