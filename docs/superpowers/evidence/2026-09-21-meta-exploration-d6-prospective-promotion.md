# D6 Prospective Promotion As-Built (Inactive Control)

Date: 2026-09-22
Basis: total design, D5 as-built, D6 plan; follow-up to `887fe41`.

## Code Result Versus Operational Authority

D6's isolated code, Action guards, append-only evidence and temporary-store tests are
implemented. **No prospective control scope has been reviewed or approved.** No
production `PilotScopeContract` artifact or `policy_scope_reviews` row was created.
D0 remains `shadow_only`; a matching hash invented by a caller is insufficient to
grant runtime control. No live shadow, canary, deploy, rollback, retirement, betting,
funds, public dispatch or production data mutation occurred. No real-world promotion
or deployment outcome is claimed.

The strict frozen version-1 scope model permits only structural candidate exploration,
one explicit board, the two closed operators, a future boundary, positive exposure
cap, a distinct no-ticket fallback and registered hard-brake codes. It rejects
unknown fields, mutable nested scope, protected Actions and D0 `shadow_only` as
control authorization. Validation requires an externally supplied exact reviewed
content hash and approval reference. Migration 44 provides a separate human-only
append-only `approve_pilot_scope_contract` Action; the control Action and runtime
resolver require its persisted review identity as well as the hash/reference. Tests
exercise invalid/missing review and hypothetical hash validation, not an approved
control record.

## Prospective Proof

Migration 42 keeps the preregistered human shadow window and its winner/scope/cutoff/
invariant binding. The D2 online policy runner accepts a registered challenger only
through a matching stored human shadow decision inside that window; replay/archive
status and fixture claims do not authorize a prospective run. Migration 43 adds an
append-only protected-source receipt inserted atomically by `seal_discovery_world`.
It binds world, policy, before/after hashes, receipt hash and seal Action. The recorder
independently fingerprints its read-only source before and after work. Mutation or
resource overrun commits a failure diagnostic and leaves the world unsealed.

Promotion validation reads sealed worlds, D2 shadow runs, stored seal hashes and
receipts, and the frozen D4 tournament pool. It excludes worlds before the shadow
authorization, outside the closed window, from development/tournament or replay,
unsealed or altered worlds, duplicate derivative clusters and mismatched protection
receipts. Open windows or insufficient independent worlds deny promotion. Action
decisions require the latest scoped predecessor and strictly later decision time;
canary/deploy require the earlier distinct human-approved fallback and separate
reviewed scope record. No synthetic evidence is promoted into runtime authority.

## Runtime And Brake

The read-only runtime resolver selects the latest event for the exact family/scope,
derives exposure from persisted world lineage (never trusting a lower caller count),
checks effective boundary, board, cap, contract hash, external review and persisted
human review, and returns unchanged authority for shadow, out-of-scope, unreviewed,
exhausted or braked requests. An approved controller carries policy, deployment and
scope hash lineage; the D2 recorder binds that lineage only to isolated fixture
worlds. Live controlled recording is deliberately closed until the independent
scope and business-boundary approvals exist. The protected candidate/ticket workflow
remains authoritative.

After a failure-node Action commits, the recorder sends its Action ID to the brake
monitor. The monitor rereads committed Action and node facts, selects only a code
registered on the current deployment, and invokes `trip_policy_brake` with the exact
fact ID/hash. The Action independently checks that code, policy, node and hash and
restores only the recorded fallback. Repeated monitoring is idempotent; the braked
candidate cannot start another shadow run. The next safe brake boundary and pending
human disposition remain visible. Protected mutation and resource overrun produce
committed diagnostic facts instead of silent self-reports.

The read-only promotion projection includes scoped latest events, replay winner and
proof hash, windows/end/effective count, scope hash and approval reference, effective
boundary, brake conditions, rollback target, brake event and pending disposition.
Old schema queries do not migrate stores: schema 40/41 require migration 42, and
schema 42 requires receipt migration 43. Migrations 40-42 were not rewritten;
43 and 44 are additive. No query creates a missing database.

## Temporary-Store Proof And Gates

RED-GREEN tests cover the strict scope, missing/mismatched review, absent/replayed/
late/duplicate/unsealed prospective evidence, protected receipt, challenger Action
authorization, scoped concurrency, cap/boundary/out-of-scope resolution, committed
brake fact and one-shot fallback, and read-only projection. A temporary source and
shadow store comparison verifies identical protected fingerprints before/after a
sealed D2 fixture world. Another temporary store commits a real failure-node Action,
trips one brake, checks the exact registered code and fallback, then rejects reuse.

Still open: Jun's D5 review, a real completed D4 tournament winner, a separately
approved human shadow window and decision, fresh independent prospective worlds,
closed window, human review of a new scope revision and no-ticket fallback, and
separate human canary/deploy/rollback decisions. Those are operational gates; fixture
tests and this document do not satisfy them. D7 must not infer an approved controller
from this code-completion evidence.

## Verification

- Focused discovery, governance, migration, read-only projection, protected ticket,
  RSI and CLI suite: exited 0 after final code edits.
- Targeted Ruff over D6 discovery, ontology Action/repository/read, CLI and test
  paths: `All checks passed!`.
- `git diff --check`: exited 0; staged diff checked again before commit.
- Fresh `uv run pytest -q` after the final code edits: reached 100%, exited 0;
  two third-party websocket deprecation warnings in the operator UI test.
- All tests and proof stores were temporary; unrelated dirty/untracked paths were
  not staged or modified for D6.
