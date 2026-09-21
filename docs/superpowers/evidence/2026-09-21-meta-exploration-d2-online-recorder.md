# Meta-Exploration D2 Online Recorder As-Built

Date: 2026-09-21 (final verification before 13:06:54 UTC)
Spec: `docs/superpowers/specs/2026-09-21-dream-rsi-meta-exploration-v1-design.md`
Plan: `docs/superpowers/plans/2026-09-21-dream-rsi-meta-exploration-d2.md`

## Result For Review

D2 implements a bounded structural-baseline recorder, isolated shadow storage,
read-only frozen candidate input, and descriptive readiness projection. Temporary
fixture runs seal a root, immutable attempt nodes, and STOP; the test independently
recomputes and compares the sealed manifest. A fixture, including one built from a
real-source temporary business database, is marked `historical_replay_source` and
contributes zero prospective worlds. **No live prospective run was executed.**

The default readiness mode is `record_only`. D3 replay integrity, action overlap,
and unavailable-branch measurements remain unknown, so counts alone cannot enable
baseline comparison or an optimizer in the operational projection.

## Frozen Inputs And Isolation

- Canonical pilot SHA-256: `842c96bce8745ff2ae6b2249ab7d8c5e1771fc7d693581952db01863d029f08f`.
- Canonical incumbent SHA-256: `a9dad2f5f7db577edabc379edfe60a61322e978ef9b1c2e42282040dd142e55a`.
- Representative fixture cutoff: `2026-09-21T07:00:00+00:00`; registered policy:
  `structural-baseline-v1`. A second temporary business-source fixture used the
  frozen request at `2026-09-04T08:00:10+00:00` and was explicitly historical.
- The source is opened SQLite `mode=ro` plus `query_only`; the recorder hashes all
  source tables before and after work. It rejects path aliases, changed source
  fingerprints, unverified requests, expired or mismatched approval scope, and
  unregistered/mismatched baseline policies before any prospective world is created.
  Business-source fingerprints were unchanged in the temporary fixture tests.
- Work executes outside Action transactions. Real-mode shards use killable processes;
  fixture-mode shards use deterministic in-process tests. Attempt nodes record actual
  or explicitly unknown costs, failures, artifact hashes, and linked bounded retries.
  Candidate budget excess leaves the world unsealed with durable attempt diagnostics.
  Action response loss reuses the idempotency key without re-executing the shard.
- `discovery shadow-run` additionally requires an exact, pre-existing approval file,
  a pre-registered operator-owned baseline, a recent prospective cutoff, and a
  pre-existing distinct shadow store. The recorder repeats scope/time/registration
  checks for callers bypassing the CLI. A supplied local JSON approval file is not
  cryptographically signed; **no actual operator approval file or live scope is
  claimed by this evidence**.

## Verification

Fresh checks after the last runtime/test edit on 2026-09-21:

| Check | Exit | Observation |
| --- | --- | --- |
| Discovery, D1 world/policy Actions, CLI, protected ticket/RSI/candidate/replay/bands regressions | 0 | 140 tests collected and passed |
| `uv run ruff check nutmeg/discovery nutmeg/ontology/discovery nutmeg/interfaces/cli/discovery.py tests/discovery tests/test_cli_discovery.py` | 0 | All checks passed |
| `git diff --check` | 0 | No whitespace errors |
| `uv run pytest -q` | 0 | 3,779 tests collected; 100% with no failures; two third-party websockets deprecation warnings |
| `git status --short .nutmeg-data` | 0 | No production runtime changes |

Fixture assertions cover independent seal-hash recomputation, stable visibility
despite parallel completion order, immutable business-source fingerprints, historical
readiness exclusion, failed/no-solution terminal states, a linked retry, timeout,
invalid artifact, exhausted budgets, missing/mismatched approval, and backdated
historical-input rejection. They do **not** constitute a prospective sample.

## Plan Differences And Next Gate

The candidate-input adapter reuses the worker's existing read-only
`_candidate_generation_inputs` function directly rather than relocating it to a new
shared module. This keeps the authoritative worker unchanged while both readers use
the same assembly; it does not claim a worker lease. Implementation accumulated in
the pre-existing dirty worktree and is delivered as one scoped D2 commit rather
than the per-task commits suggested by the plan. Neither difference changes the
frozen pilot or baseline artifacts.

D2 evidence requires Jun's review before D3 implementation. A separately approved
prospective scope is still needed before any live shadow run. D2 does not authorize
historical backfill, tournaments, challengers, promotion, protected Actions, funds,
ticket placement, or public dispatch.
