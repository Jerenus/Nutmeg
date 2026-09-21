# Dream-RSI Meta-Exploration v1 Delivery Map

Date: 2026-09-21

Authority: `docs/superpowers/specs/2026-09-21-dream-rsi-meta-exploration-v1-design.md`

This map indexes the independent plans. Writing all plans does **not** complete their
tasks, create prospective evidence, pass coverage gates or authorize deployment.
Every execution milestone still requires fresh tests, evidence and Jun's review before
the next milestone is implemented. Plans D3-D7 describe future work against D2's
planned interfaces; refine an affected downstream plan against the accepted as-built
interface before beginning that milestone, without silently weakening the spec.

| Stage | Plan | Delivered/required result | Execution gate |
| --- | --- | --- | --- |
| D0 | `2026-09-21-dream-rsi-meta-exploration-d0.md` | Frozen pilot and incumbent contracts; completed | Evidence accepted before D1 |
| D1 | `2026-09-21-dream-rsi-meta-exploration-d1.md` | Six Ontology families and guarded storage; completed | D1 evidence review before D2 |
| D2 | `2026-09-21-dream-rsi-meta-exploration-d2.md` | Isolated online shadow trees and readiness metrics | D1 review; no production run without distinct operational approval |
| D3 | `2026-09-21-dream-rsi-meta-exploration-d3.md` | Shared environment and sealed-prefix replay | D2 as-built reviewed; real replay needs real sealed D2 world |
| D4 | `2026-09-21-dream-rsi-meta-exploration-d4.md` | Baseline-only frozen tournament and ranking proof | D3 as-built, data gate, reviewed selection contract and human tournament Action |
| D5 | `2026-09-21-dream-rsi-meta-exploration-d5.md` | Closed generator and optional bounded evolution | D4 as-built; optimizer-enabled gate; operator registers proposals |
| D6 | `2026-09-21-dream-rsi-meta-exploration-d6.md` | Fresh shadow, scoped human promotion and reduce-only brake | D5 as-built; human shadow/scope/canary/deploy decisions each separate |
| D7 | `2026-09-21-dream-rsi-meta-exploration-d7.md` | Effective-information trigger, holdout rotation, archive/drift | D6 as-built; reviewed trigger/drift contract; new human tournament decision |

## Contract decisions before execution

1. D0 pilot remains `shadow_only`; D6 canary/deploy requires a new **prospectively
   approved** scope revision, not a reinterpretation of D0.
2. D4 must freeze the numerical materiality rule, within-tier aggregation, missing-cost
   treatment and worst-stratum brake before the first scored tournament. D0 fixes the
   evaluator fields/order but does not supply those numbers.
3. D7 must freeze information-trigger and drift thresholds before the first recursive
   round. Neither elapsed time nor raw world count alone may trigger a tournament.
4. D5 migration 41 and D6 migration 42 must not mutate the applied D1 migration 40.
5. No synthetic test world counts as a prospective world. D3 and later may be
   functionally implemented and tested while real-world readiness remains blocked.

## Requirement ownership

| Spec requirement | Owning stage(s) |
| --- | --- |
| FR-001, FR-002 | D1 foundation; D2 online lineage and seal |
| FR-003 | D3 shared observation/action protocol |
| FR-004, FR-005 | D1 trace storage; D3 exact prefix replay and reproduction |
| FR-006, FR-007 | D1 tournament freeze; D4 baseline scoring and selection proof |
| FR-008 | D1 isolation; D3 replay no prospective writes; D4 no promotion |
| FR-009, FR-010 | D1 authority; D6 fresh prospective gate and human decisions |
| FR-011, FR-012, FR-013 | D2 closed shadow work/failures; D3 sandbox/failed replay |
| FR-014 | D1 lineage; D4 proof/report; D6 deployment provenance |
| FR-015 | D1 brake; D6 runtime/rollback; D7 drift review |
| FR-016, FR-017 | D1 policy fields; D5 generator context and frozen surfaces |
| FR-018 | D2 coverage projection; D3 availability; D5 hard optimizer gate; D7 cadence |
| FR-019, FR-020 | D1 archive facts; D4 admission; D5 parent eligibility; D7 eviction |
| FR-021 | D1 exposure ledger; D4 initial holdout; D7 strict rotation |
| FR-022 | D2 effective-world report; D7 preregistered information trigger |

## Verification discipline

Each plan names focused red/green tests and a final full-suite/lint check. Evidence
records actual command, exit, failures, frozen artifact hashes, protected-state diff,
and which acceptance scenarios were only exercised with temporary fixtures. Recheck
all changed files against the worktree before any commit; preserve unrelated changes.
No plan step runs real betting, funds, public dispatch or changes football judgment.
