# Meta-Exploration D4-D7 Review And Follow-Up Fixes

Date: 2026-09-22
Reviewer: Fable (three parallel read-only audits plus direct verification), accepted by Jun in chat on 2026-09-22
Scope: `docs/superpowers/evidence/2026-09-21-meta-exploration-d4-*.md` through `d7-*.md`, the code under `nutmeg/discovery`, `nutmeg/ontology/discovery`, the three discovery Action modules, migrations 40-44 and the discovery CLI

## 1. Review verdict

D4-D7 are **accepted at the isolated-code and fixture level**. Engineering completeness
is high and the safety guards are real. The review also found that the pilot task is
structurally degenerate and that the production business substrate the pilot reads
from does not exist yet. Neither finding is a code defect in D4-D7; both are recorded
here so later sessions do not over-read the fixture evidence.

| Area | Finding |
| --- | --- |
| Tests at review time | Discovery-focused suite 355 passed; full `uv run pytest -q` exit 0; Ruff clean |
| Spec traceability | FR-001..FR-022 all covered by tests with real assertions; scenarios B-L covered; SC-002/003/005..015 covered; SC-001, SC-004 and scenario A remain fixture-level because no real prospective world exists |
| Migration hygiene | Migration 40 body untouched by 41-44; every discovery table has no-update/no-delete triggers; migration checksums are hand-written fingerprints that do not cover DDL text |
| Production store | `.nutmeg-data/ontology/ontology.db` was auto-migrated to schema 44 by the hourly `com.nutmeg.rsi.sweep` job on 2026-09-21 (09:00, 18:00, 19:00, 20:00 UTC); all 23 discovery tables hold 0 rows |
| Pilot substrate | Every operator_v2 table a world reads (envelopes, judgments, prescriptions, candidate sets, structure templates, generation requests) holds 0 rows in production |
| Design fit | Depth-1 trees with an exhaustive incumbent; challengers can only tie on quality and win on cost; see `docs/superpowers/specs/2026-09-22-dream-rsi-pilot-cost-pruning-restatement.md` |
| Process | D4-D7 were built in one night under Jun's broad "finish D3-D7" instruction; per-milestone reviews were collapsed into this document |

Points where an audit opinion was rejected after checking the code:

- "Seal hash includes wall-clock cost, so re-recording is not idempotent." The seal
  fingerprints the tree as recorded, including actual cost that replay later charges.
  That is the intended meaning of a seal; SC-002 concerns replay reproducibility on a
  sealed world, which holds. Not a defect.
- "Pilot `protected_actions` and `frozen_surfaces` lists are never enforced." The
  lists are declarative; enforcement lives in role permissions, `ReplayActionContext`
  and `validate_change_surfaces`, all covered by tests. Acceptable; noted as a
  documentation gap.

## 2. Fixes applied in this session

| Item | Change | Test |
| --- | --- | --- |
| Register the incumbent without writing Python | `nutmeg discovery register-baseline --data-dir <shadow> --by <human>` runs the operator-only `register_policy_revision` Action, validates the artifact against the pilot contract, refuses reruns and refuses the production data directory | `tests/test_cli_discovery.py::test_register_baseline_*` |
| Production-store denylist | `reject_production_store` refuses any shadow target equal to or inside the repository's `.nutmeg-data`; applied to `register-baseline` and `shadow-run` | `tests/test_cli_discovery.py::test_shadow_run_refuses_shadow_store_inside_production_data_directory` |
| Single readiness computation | `world_pool.assess_baseline_readiness` now builds `CoverageWorld`/`ReplayMetrics` and delegates to `readiness.assess_readiness`; the tournament Action and the operator projection can no longer disagree; reason names unified (`sealed_worlds`, `replay_integrity`, ...) | `tests/discovery/test_world_pool.py` |
| Isolated-mode retry | The retry gate no longer requires a known candidate count, so timeouts and crashes from the killable process path get their one linked retry | `tests/discovery/test_online_recorder.py::test_timeout_with_unknown_cost_still_gets_one_linked_retry` |
| Iteration-contract approval | `IterationContract` gains `approved` status with `approved_by`, `approved_at`, `approval_ref` and `approves_proposed_hash`; approval is valid only when bound to the canonical hash of the proposed numbers; `review_new_information` reads approval from the validated artifact only; read service and CLI report `pending_human_approval` from the artifact | `tests/discovery/test_iteration_contract.py`, `tests/discovery/test_iteration_readiness.py::test_validated_approved_contract_lifts_only_the_approval_block` |
| CLI docstring | The module and Typer help no longer describe the command group as read-only | — |

Approval recorded: `structural-iteration-v1` numbers unchanged, proposed hash
`bda3be2dd7b4545bb0323453346564474c2bfa08e17872349302979f81e8f23b`, approved by
`op:jun` on 2026-09-22 (chat instruction on review item 5). Changing any number now
requires a new approval record; `test_approved_numbers_cannot_change_without_a_new_approval`
enforces it. Approval grants no runtime authority; `runtime_authority` stays `false`.

Verification after the fixes: discovery-focused suite (`tests/discovery`,
`tests/test_cli_discovery.py`, `tests/ontology/test_discovery_*.py`) 349 collected,
exit 0; targeted Ruff clean.

## 3. Still open

- **First real world is blocked by the operator_v2 release gates, not by the harness.**
  Production candidate generation exists only when `NUTMEG_OPERATOR_SURFACE_MODE=active`,
  which requires the four Jun-only exercise gates, a clean worktree with matching commit
  pins and a signing key, and arms the ticket-confirmation and settlement workers. The
  official-sale slate manifest that the Today view depends on has no producer in the
  repository. See the runbook in the session report of 2026-09-22.
- The `max_concurrency = 4` replay clip versus up-to-eight templates per board
  (restatement document, section 4) needs a prospective pilot-contract revision.
- Migration checksums should hash migration source, or a test should pin migration 40's
  checksum constant.
- Real-mode crash handling in `run_shard_isolated` has no test that actually crashes a
  spawned child.
