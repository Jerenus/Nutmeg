# Meta-Exploration D0 As-Built And Gap Matrix

Date: 2026-09-21
Spec: `docs/superpowers/specs/2026-09-21-dream-rsi-meta-exploration-v1-design.md`

## Retained foundations

| Capability | Current authority | D0 decision |
| --- | --- | --- |
| Atomic typed writes | `ActionService` + `OntologyUnitOfWork` | Reuse unchanged |
| Candidate enumeration | `nutmeg.product.operator_candidates:enumerate_band_candidates` | Baseline binding only |
| Candidate audit | Candidate-set `audit_policy_version` and current deterministic audit | Freeze reference; do not fork rules |
| Business lineage | Candidate Set Revision | Reference from future DiscoveryNode; never replace |
| Workflow replay | Historical Replay Run | Keep distinct from policy replay |
| RSI governance | Experiment/Duty/Observation/Grade/Verdict/Deployment | Keep distinct from discovery tournament |

## Missing before D1

| Gap | First owning milestone |
| --- | --- |
| DiscoveryWorld / DiscoveryNode persistence | D1 |
| ExplorationPolicyRevision persistence | D1 |
| PolicyReplayRun / Tournament / Deployment persistence | D1 |
| Discovery typed Actions and permissions | D1 |
| Online shadow recorder | D2 |
| Prefix-only replay environment | D3 |
| Tournament evaluator | D4 |
| Candidate generators beyond baseline | D5 |

## Non-equivalence rules

- Candidate Set Revision is business lineage, not a Discovery Tree.
- Historical Replay Run is workflow replay, not a PolicyReplayRun.
- A policy artifact is executable intent, not deployment authority.
- Archive admission is generation eligibility, not tournament victory.

## D0 execution statement

No harness execution in D0. The D0 changes do not write `.nutmeg-data`, production
candidate, RSI observation, verdict, deployment, ticket, dispatch, funds, or
public-output state. Pre-existing unrelated worktree changes are not D0 evidence.

## Frozen artifacts

Canonical SHA-256 values from `nutmeg.discovery.contracts.canonical_hash`:

- `experiments/discovery/structural-candidate-v1.contract.json`: `842c96bce8745ff2ae6b2249ab7d8c5e1771fc7d693581952db01863d029f08f`
- `experiments/discovery/structural-baseline-v1.policy.json`: `a9dad2f5f7db577edabc379edfe60a61322e978ef9b1c2e42282040dd142e55a`

## D1 entry gate

D1 may begin only after both artifacts parse strictly, their canonical hashes are
recorded here, the complete focused test file and affected candidate tests pass,
and Jun reviews and approves this evidence. D0 does not grant runtime authority.
