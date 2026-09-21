# Dream-RSI Meta-Exploration v1 - Total Design

Date: 2026-09-21

Status: Architecture approved; written specification awaiting operator review

Owner: Nutmeg operator workflow

Scope: Governed improvement of exploration policy, beginning with structural candidate discovery

## 1. Executive decision

Nutmeg will keep the existing RSI experiment-governance layer and add a separate
Discovery Harness. The new layer improves the policy that decides where to branch,
which branch to continue, how much work to run in parallel, and when to stop. It does
not replace the football ontology, alter football judgment rules, or automate betting.

The governing split is:

```text
Ontology = durable truth, identity, lineage, permissions, Actions, audit, history
Discovery Harness = exploration runtime, legal action selection, execution, replay
Evaluator = frozen task-quality and cost measurement
Human gate = shadow/canary/deploy/rollback authority
```

The system is complete only when the same exploration policy can operate against both
an online environment and a prefix-only replay environment, candidates are compared
against the incumbent on frozen historical worlds, and a replay winner must still pass
prospective shadow before human deployment.

## 2. Purpose

The current Nutmeg system can govern experiments, preserve candidate lineage, isolate
historical replay, and require human deployment. It cannot yet perform the central
Dream-RSI recursion:

```text
deployed exploration policy pi_t
  -> online discovery worlds and trees T_t
  -> frozen historical world pool
  -> candidate policy generation
  -> prefix-only replay tournament including pi_t
  -> prospective shadow
  -> human-approved pi_(t+1)
  -> new online trees that pi_t might not have reached
```

This design adds that recursion without weakening Nutmeg's existing ontology, SOP,
replay isolation, deterministic audit, or protected funds boundary.

## 3. Source interpretation

This design uses the Dream-RSI paper and project description as a mechanism reference,
not as an implementation dependency. As of the review date, the public Dream-RSI
repository publishes explanatory material and the paper but not a complete reference
implementation or reproduction harness. Nutmeg therefore adopts the paper's contracts
and tests them locally rather than claiming source-level compatibility.

Primary external references reviewed for this design:

- project explanation: <https://www.dream-rsi.com/#idea>
- paper: <https://www.dream-rsi.com/assets/dream-rsi.pdf>
- public repository: <https://github.com/zhengkid/Dream-RSI>

The mechanisms carried forward are:

1. Online work creates a discovery tree rather than a flat result list.
2. A policy observes only the currently revealed tree prefix.
3. A continuation action selects one or more revealed frontier nodes.
4. Online continuation creates new child nodes; replay continuation reveals only
   children that already exist in the sealed historical tree.
5. Candidate policies are evaluated across multiple frozen historical worlds.
6. The incumbent policy is always a tournament candidate.
7. A winner is deployed to online work so future worlds expand the historical support.
8. Quality, execution cost, and parallel-search behavior are evaluated together.

Nutmeg deliberately changes two details:

- Evaluation is lexicographic, not an unconstrained weighted sum, because safety,
  legality, and no-leakage may not be traded for better task scores.
- Deployment remains a human Action and never includes real-money automation.

## 4. Current as-built truth

### 4.1 Capabilities retained

The following existing capabilities are foundations, not rewrite targets:

- append-only Experiment, Duty, Observation, Grade, Verdict, Deployment, and
  Amendment records;
- typed Actions with deny-by-default roles, idempotency, atomic business/audit commit,
  optimistic version checks, and outbox events;
- immutable artifacts and time-bounded evidence;
- hard separation of historical replay from prospective evidence;
- Forecast, candidate-set revision, audit, selection/no-ticket, settlement, review,
  and score projections;
- candidate revision lineage with parent, delta, and rationale;
- human-only deployment and protected ticket/funds Actions;
- explicit missing, stale, rejected, degraded, and blocked states.

### 4.2 Gaps this design closes

| Gap | Current behavior | v1 target |
| --- | --- | --- |
| Executable exploration policy | Parameters or fixed workflow code | Versioned policy revision with one deployed incumbent |
| Discovery tree | Business candidate lineage only | Runtime tree containing every continuation, artifact, diagnostic, score, and cost |
| Environment parity | Online workflow and historical replay have different semantics | One policy interface over online and replay adapters |
| Replay visibility | A flat corpus may be visible at once | Only reset state plus explicitly revealed child nodes are visible |
| Policy comparison | Static variant ranking | Frozen multi-world tournament including incumbent |
| Recursive deployment | A winner may become only an experiment draft | Human-approved policy becomes the next online controller |
| Meta-exploration score | Primarily a business residual | Safety-first discovery quality, robustness, cost, and parallel efficiency |
| Truth documentation | Several specs describe different completion states | This document is the v1 target and gap authority |

### 4.3 Explicit distinctions

These three structures are related but not interchangeable:

- A **Candidate Set Revision tree** records the lineage of business candidate sets.
- A **Historical Replay Run** re-executes a governed business workflow in isolation.
- A **Discovery Tree** records the choices and results of an exploration policy.

A DiscoveryNode may reference a Candidate Set Revision or a Historical Replay Run,
but neither object becomes a DiscoveryNode merely because it has a parent link.

## 5. Scope

### 5.1 In scope for v1

- first-class ontology records for worlds, nodes, policies, replay runs, tournaments,
  and policy deployments;
- one common exploration environment contract;
- online tree recording in shadow mode;
- prefix-only replay of sealed trees;
- deterministic policy tournament with temporal holdout and stratified reporting;
- a constrained policy-development boundary;
- human-approved shadow, canary, deployment, and rollback;
- a single pilot adapter for structural candidate generation and deterministic audit;
- status, lineage, diagnostics, and export sufficient to reproduce a tournament.

### 5.2 Out of scope for v1

- modifying evidence weights, judgment rules, falsifiers, audit codes, or staking logic;
- using deep-research agents as the first pilot;
- creating autonomous football facts, Forecast approvals, ticket approvals, dispatch,
  funds Actions, or public messages;
- allowing replay results to count as prospective RSI observations or verdict evidence;
- simulating an unobserved historical branch;
- arbitrary policy code with unrestricted filesystem, network, database, or Action
  access;
- replacing the current RSI experiment lifecycle;
- declaring any existing F-series experiment successful or complete.

## 6. Architecture

```text
Operator / policy-development agent
                 |
                 v
       ExplorationPolicyRevision
                 |
                 v
        Discovery Harness runtime
       /          |              \
OnlineEnvironment ReplayEnvironment Frozen Evaluator
       |          |              |
resource adapters |              |
       |          |              |
       +---- typed Actions -------+
                 |
                 v
          Ontology Kernel v2
  World / Node / Replay / Tournament / Deployment
                 |
                 v
   projections / outbox / observatory / audit
```

### 6.1 Responsibility boundary

The ontology stores what exists, what is linked, who was allowed to change it, and
what happened. It does not choose a branch or call an external model.

The harness chooses legal exploration actions and invokes adapters. External or
long-running work occurs outside the ontology transaction. Its result is then committed
through typed Actions. A failed external call produces an explicit failed attempt or
diagnostic; it never leaves a half-committed node.

The evaluator consumes a frozen node artifact and returns a deterministic measurement.
It may not create evidence, alter the task, or inspect unrevealed replay nodes.

## 7. First-class ontology objects

All records are append-only or revisioned. Mutable status is projected from events;
history is never overwritten.

### 7.1 DiscoveryWorld

A DiscoveryWorld is one complete exploration task with immutable inputs.

Required attributes:

- `world_id`, task family, business date, lane, and stratum labels;
- frozen input-manifest hash and referenced ontology/artifact versions;
- task contract, legal action schema, evaluator revision, and resource budget;
- creation cutoff, seal time, provenance mode (`prospective_online` or
  `historical_replay_source`);
- root-node reference and terminal state;
- isolation identity proving which store may be written.

Invariants:

- The input manifest, evaluator revision, cutoff, and budget cannot change after the
  first node is committed.
- A world is replay-eligible only after it is sealed.
- A prospective world may write only to its declared shadow namespace during v1.
- A historical source world can never create prospective RSI evidence.

### 7.2 DiscoveryNode

A DiscoveryNode represents one revealed state in a world tree.

Required attributes:

- `node_id`, `world_id`, parent node, depth, sibling order, and creation sequence;
- continuation action and policy decision that produced it;
- workspace/artifact manifest hash and referenced business objects;
- execution status, diagnostic codes, start/end times, latency, resource cost, and
  retry lineage;
- evaluator result, terminal reason, and whether the node remains a legal frontier;
- visibility sequence used by prefix-only replay.

Invariants:

- The root has no parent; every other node has exactly one parent in the same world.
- Artifact and evaluator results are immutable after node commit. Corrections append a
  superseding node-evaluation event.
- A node cannot reference evidence recorded after the world cutoff.
- A retry is a new attempt linked to the failed node; it does not erase failure cost.
- Business objects remain governed by their own Actions. A node reference does not
  approve or mutate them.

### 7.3 ExplorationPolicyRevision

A policy revision is executable decision logic constrained to the exploration API.

Required attributes:

- `policy_revision_id`, family, parent revision, source and artifact hash;
- policy interface version and constraints version;
- creation actor/source, rationale, and declared change summary;
- deterministic configuration and random-seed policy;
- compatible world families and maximum resource permissions;
- validation result and lifecycle projection.

Invariants:

- Policy artifacts are immutable and content-addressed.
- A policy may inspect only the observation passed by the environment.
- A policy may return only legal exploration actions.
- The model, evaluator, task definition, Action permissions, and business rules are not
  editable through a policy revision.
- Exactly one deployed incumbent may exist per policy family and scope.

### 7.4 PolicyReplayRun

A replay run is one policy evaluated on one sealed world.

Required attributes:

- policy and world references;
- initial visible state and ordered decision rounds;
- actions requested, actions accepted/rejected, and revealed node IDs per round;
- stop reason, budget use, failures, and final selected solution;
- evaluator revision, aggregate outcome, complete trace hash, and reproducibility data.

Invariants:

- Replay reads from an immutable sealed world.
- Reset exposes only the root and allowed root metadata.
- Continue reveals only recorded children of selected visible frontier nodes.
- Missing historical children return `branch_unavailable`; they are never synthesized.
- The run cannot mutate the source world or any production/prospective object.

### 7.5 PolicyTournament

A tournament compares a frozen candidate set on a frozen world pool.

Required attributes:

- tournament ID, policy family, incumbent, challengers, and candidate-set hash;
- frozen world-pool manifest and temporal train/holdout boundary;
- evaluator/aggregation revisions and lexicographic decision contract;
- per-policy, per-world results; stratum summaries; exclusion reasons;
- winner, ties, disqualification reasons, and complete reproduction hash.

Invariants:

- The incumbent is mandatory. A tournament missing it is invalid.
- Candidate and world manifests freeze before the first replay run.
- Worlds newer than the declared temporal boundary cannot enter the development set.
- Ties resolve to the incumbent unless the frozen contract defines an objective,
  non-performance tie-break that was registered before evaluation.
- A tournament winner is not automatically deployed.

### 7.6 PolicyDeployment

A deployment records human control over an exploration policy.

Required attributes:

- policy family and revision;
- decision (`shadow`, `canary`, `deploy`, `hold`, `rollback`, `retire`);
- scope, effective boundary, evidence references, human actor, reason, and
  superseded deployment;
- rollback target and automatic brake conditions.

Invariants:

- Only the human operator may enter shadow/canary/deployed state, expand scope, retire
  a policy, or waive a warning.
- Replay success alone permits at most `shadow` eligibility.
- Full deployment requires fresh prospective worlds not used in policy development.
- A deterministic brake may only reduce authority and restore the last human-approved
  incumbent named by the deployment. It cannot select a new policy or resume the
  braked policy.
- A human rollback decision confirms or changes the post-brake disposition without
  editing history.
- No policy deployment grants ticket, dispatch, funds, or public-output authority.

## 8. Typed Action contract

The minimum v1 Action set is:

| Action | Authority | Effect |
| --- | --- | --- |
| `create_discovery_world` | deterministic system or operator | Freeze task, inputs, evaluator, and budget |
| `start_discovery_run` | deterministic system | Bind policy and environment to a world |
| `record_discovery_node` | deterministic system | Atomically commit one completed continuation result |
| `record_discovery_failure` | deterministic system | Append failed attempt and diagnostics |
| `seal_discovery_world` | deterministic system | Close online mutation and publish replay manifest |
| `register_policy_revision` | operator | Admit an immutable candidate policy artifact |
| `start_policy_replay` | deterministic system | Create isolated policy-world replay envelope |
| `finish_policy_replay` | deterministic system | Commit trace, score, and stop reason |
| `create_policy_tournament` | operator | Freeze candidates, worlds, and evaluation contract |
| `finish_policy_tournament` | deterministic system | Commit results and computed winner |
| `approve_policy_deployment` | operator only | Shadow, canary, deploy, hold, rollback, or retire |
| `trip_policy_brake` | deterministic system | Stop a policy and restore only its recorded approved fallback |

Every Action uses the existing action ledger, role policy, idempotency, expected-version
checks, and outbox. Rejected and failed Actions remain auditable.

## 9. Common environment contract

Online and replay implement the same policy-visible behavior:

```text
reset(world) -> Observation
observed() -> Observation
legal_actions() -> list[ExplorationAction]
continue_batch(actions) -> Observation
stop(selection, reason) -> TerminalObservation
```

`Observation` contains only:

- world metadata explicitly marked policy-visible;
- revealed nodes and their policy-visible artifacts, diagnostics, scores, and costs;
- current frontier;
- remaining round, node, cost, and wall-time budgets;
- legal action identifiers and stable failure codes.

It does not contain hidden children, future scores, tournament outcomes, later evidence,
or the identity of the policy that originally generated a replay tree.

### 9.1 Exploration actions

v1 has only three action forms:

- `CONTINUE(node_id, continuation_spec)`: continue one visible frontier node;
- `CONTINUE_BATCH(items)`: continue multiple visible frontier nodes in one decision
  round, subject to concurrency and budget limits;
- `STOP(selected_node_ids, reason)`: end the world and return selected solutions.

The pilot may restrict `continuation_spec` to a closed, deterministic vocabulary. New
action forms require a later spec revision.

### 9.2 Online semantics

For each accepted continuation, the online environment:

1. reserves budget and creates an execution attempt;
2. invokes the declared resource adapter outside the ontology transaction;
3. captures immutable artifacts, diagnostics, timing, and actual cost;
4. invokes the frozen evaluator;
5. commits the child node through a typed Action;
6. returns the newly revealed observation to the policy.

Timeout, tool failure, invalid artifact, evaluation failure, or budget exhaustion is a
visible node/attempt outcome. The harness may continue another branch if legal.

### 9.3 Replay semantics

For each accepted continuation, the replay environment:

1. verifies that the parent is visible and on the current frontier;
2. resolves only children already stored in the sealed source world;
3. reveals the matching child or returns `branch_unavailable`;
4. charges the historical recorded cost under the tournament's frozen cost policy;
5. appends the decision round to the replay trace.

Replay never calls the online resource adapter, executes the original model, rebuilds a
business workflow, or evaluates an invented child.

## 10. Policy contract and sandbox

A policy is a pure decision component from the harness perspective:

```text
decide(observation) -> CONTINUE | CONTINUE_BATCH | STOP
```

It may maintain state only through an explicit state blob returned with each decision.
The blob is size-bounded, versioned, and stored in the run trace. Hidden process memory
cannot be required for reproducibility.

The policy-development process may change only this bounded policy component and its
declared configuration. It may not change:

- the base task agent or model;
- world inputs or cutoff;
- the evaluator or aggregation order;
- ontology permissions or Action handlers;
- football judgment, audit, settlement, or funds rules;
- replay visibility rules;
- the tournament world pool after results become visible.

Candidate policies that violate the interface, exceed permissions, or depend on
undeclared resources are disqualified, not repaired during scoring.

### 10.1 Candidate policy generation

One policy-development round consumes only:

- the incumbent policy and its declared source artifact;
- development-world traces and evaluator diagnostics;
- the policy interface and constraint version;
- the maximum candidate count and development budget fixed before the round.

It produces zero or more immutable challenger revisions, each with a parent, rationale,
and change summary. The unchanged incumbent is inserted into the candidate set by the
tournament service, not left to the development agent's discretion.

The policy developer cannot read the time-forward holdout, prospective shadow results,
hidden replay nodes, or tournament results from the round it is currently generating.
Candidate generation stops before tournament execution; candidates cannot be patched
after seeing their scores. A later change is a new policy revision and a new tournament.

## 11. Evaluation and tournament selection

### 11.1 Per-world evaluation

The evaluator produces separate fields, not a single opaque utility:

- invariant violations and leakage findings;
- task validity and deterministic audit outcome;
- best discovered solution quality;
- solution coverage and diversity;
- robustness diagnostics;
- total nodes, decision rounds, actual cost, latency, retries, and failures;
- effective parallelism and unused/overspent budget;
- stop quality, including whether more work was available when the policy stopped.

### 11.2 Lexicographic order

Policies are compared in this strict order:

1. **Safety and isolation**: no leakage, permission breach, protected Action, or
   production write. Any violation disqualifies the policy.
2. **Validity**: all selected outputs satisfy task schema and deterministic audit.
3. **Discovery quality**: compare the frozen task-quality vector, not ticket profit.
4. **Robustness**: temporal holdout performance, worst-stratum behavior, failure
   recovery, and sensitivity to world composition.
5. **Cost**: fewer nodes, lower declared resource cost, and lower latency for equivalent
   preceding dimensions.
6. **Parallel efficiency**: useful concurrent work without duplicated or abandoned
   exploration.

No lower tier can compensate for a loss in a higher tier. Numeric aggregation inside a
tier must be declared before the tournament and remain visible in the result.

### 11.3 World pool discipline

The tournament world pool must:

- contain only sealed, reproducible worlds;
- identify worlds used during candidate development;
- reserve a later time-forward holdout not visible during policy revision;
- report at least lane, competition/league, channel, market/odds band, board size, and
  failure/degraded strata when those labels exist;
- prevent duplicate or derivative worlds from silently overweighting one event;
- retain failed and no-solution worlds rather than selecting only successful history.

### 11.4 Selection rule

A challenger wins only if it:

- is not disqualified;
- is no worse than the incumbent on every higher-priority tier;
- improves at least one declared tier by the frozen minimum materiality rule;
- does not breach the worst-stratum brake;
- remains superior on the time-forward holdout.

Otherwise the incumbent remains the winner. This is a conservative replay guarantee,
not a claim that future online performance cannot regress.

## 12. Prospective deployment loop

The lifecycle is:

```text
draft -> validated -> replay_eligible -> tournament_winner
      -> shadow -> canary -> deployed -> superseded/braked/rolled_back/retired
```

- `validated` proves interface, determinism, and permission compliance.
- `replay_eligible` permits historical evaluation only.
- `tournament_winner` has no production authority.
- `shadow` runs on new worlds but does not control the existing business workflow.
- `canary` may control only the declared structural-discovery pilot scope.
- `deployed` becomes the incumbent for that scope at a business boundary.
- any registered hard invariant failure invokes `trip_policy_brake`, stops new work for
  that policy, and restores its recorded approved incumbent; the operator reviews
  before any resumption or scope expansion.

Prospective shadow results are stored as new worlds and may enter later tournaments
only after sealing. They never retroactively change the tournament that selected the
policy.

### 12.1 Continuous iteration cadence

Each newly sealed online world increments the eligible historical pool but does not
silently modify an existing tournament. A new tournament receives a new frozen world
manifest and runs only when its registered cadence condition is met, such as a minimum
count of new worlds or an operator-requested review.

Every round reports changes in discovery quality, nodes used, decision rounds,
effective parallelism, failure recovery, solution diversity, stratum coverage, and
policy behavior relative to its parent. Material drift without clear quality gain is a
hold signal, not evidence of improvement. The cadence may become more conservative as
the world pool grows; it may not reuse a holdout as hidden development data.

## 13. v1 pilot: structural candidate discovery and audit

### 13.1 Why this pilot

The first pilot is the structural candidate-generation/audit layer because it has:

- frozen, inspectable inputs;
- deterministic candidate and audit outputs;
- explicit terminal outcomes including no-ticket;
- existing candidate-set revision lineage;
- lower model stochasticity and shorter feedback than deep research;
- no need to change football evidence or probability judgment.

### 13.2 World definition

One pilot world represents one frozen board-level structural task. Its manifest
contains the committed Forecast/Judgment Prescription inputs, legal candidate-building
operations, audit revision, budget, and cutoff. The world root is the empty or baseline
candidate state declared by the adapter.

### 13.3 Node meaning

One node contains one structural continuation result:

- parent structural state;
- continuation operation and parameters from the closed pilot vocabulary;
- referenced Candidate Set Revision, candidates, and audit results;
- valid/invalid/no-op/failed diagnostic;
- frozen quality vector and actual execution cost.

Candidate Set Revisions remain the business lineage authority. DiscoveryNodes add the
policy choice, execution diagnostics, visibility order, and cost needed for Dream-RSI.

### 13.4 Shadow-only first milestone

The existing candidate workflow remains authoritative. The harness shadows the same
task and records a tree without changing Forecasts, candidate selection, tickets, or
no-ticket state. A shadow run must use an isolated namespace and prove zero production
business writes before its world can be sealed.

## 14. Interaction with existing RSI governance

RSI and Discovery Harness form two nested but distinct learning loops:

- RSI evaluates a registered football or structural hypothesis using prospective
  samples, grades, falsifiers, verdicts, and human deployment.
- Discovery Harness evaluates how effectively an exploration policy searches for
  candidate solutions under a fixed task and evaluator.

A tournament may propose a new policy revision. It does not create an RSI verdict. An
RSI grade may be referenced by a world evaluator only if the world contract explicitly
declared it and its cutoff permits it. Replay-mode grades still cannot enter prospective
verdicts.

The legacy `rsi dream` static variant ranking remains available for its existing
experiments but is no longer described as the complete Dream-RSI implementation. It is
a bounded predecessor and may later become one adapter or policy-generation input.

## 15. Failure, recovery, and degraded operation

- **Adapter timeout**: record the failed attempt and charged cost; expose retry only if
  the world contract allows it.
- **Invalid artifact**: do not create a successful child; retain artifact hash and
  validation diagnostics.
- **Evaluator failure**: node remains unscored and non-selectable; evaluator retry must
  use the same immutable artifact and evaluator revision.
- **Action commit failure**: external work may have completed, but the node is not
  durable. Recovery uses the execution receipt and idempotency key.
- **Unknown replay branch**: return `branch_unavailable`; do not fall back to online
  execution within the replay run.
- **Budget exhaustion**: force a terminal observation. A policy that fails to stop is
  stopped by the harness with an explicit reason.
- **Policy crash or invalid action**: record the round failure and terminate or apply
  the frozen failure policy; never guess the policy's intended action.
- **World corruption or manifest mismatch**: quarantine the world from tournaments.
- **Prospective invariant breach**: stop the run, block sealing, trip the deployment
  brake, and preserve evidence for operator review.

## 16. Observability and operator views

The operator must be able to answer without reading raw tables:

- Which policy is incumbent, in shadow, in canary, held, or rolled back?
- Which worlds are online, sealed, replay-eligible, quarantined, or incomplete?
- What did the policy see at each round, and why was each continuation legal?
- Which branches were unavailable during replay?
- What solution was selected, at what cost, and what stronger branches remained?
- How did challenger and incumbent compare on every world and stratum?
- Did any candidate fail leakage, permission, audit, or robustness gates?
- Which new online worlds have entered the historical pool since the last deployment?

The default view is an operational timeline and comparison table. A graph view is
optional; the ontology is not justified by graph visualization.

## 17. Functional requirements

- **FR-001**: The system must freeze every world before exploration results can be
  compared across policies.
- **FR-002**: Every non-root discovery node must identify one parent, one producing
  policy decision, immutable outputs, diagnostics, and actual cost.
- **FR-003**: Online and replay environments must present the same observation and
  legal-action contract to a policy.
- **FR-004**: Replay must reveal only recorded children of visible nodes and must never
  synthesize an unobserved branch.
- **FR-005**: Every replay trace must be reproducible from sealed manifests without
  production writes or external model/tool execution.
- **FR-006**: Every tournament must include the incumbent and freeze candidates,
  worlds, evaluator, aggregation, and tie rules before execution.
- **FR-007**: Tournament selection must follow the lexicographic order in section 11.
- **FR-008**: Replay outcomes must not alter prospective RSI samples, verdicts,
  deployments, business decisions, or money state.
- **FR-009**: A replay winner must pass fresh prospective shadow before it is eligible
  for canary or deployment.
- **FR-010**: Only the human operator may approve shadow, canary, deploy, resume,
  rollback disposition, or retire decisions; the deterministic system may only trip a
  preregistered brake that reduces authority and restores the recorded fallback.
- **FR-011**: Policy execution must be unable to invoke undeclared resources or
  protected business Actions.
- **FR-012**: The pilot must record shadow discovery trees without changing the current
  candidate workflow's authoritative terminal state.
- **FR-013**: Failed attempts, invalid actions, timeouts, retries, and unavailable
  replay branches must be explicit and included in cost/robustness evaluation.
- **FR-014**: The operator must be able to reconstruct every tournament result and
  deployment decision from ontology lineage and immutable artifacts.
- **FR-015**: The system must retain the previous incumbent, trip the automatic brake
  only on preregistered hard conditions, and support governed rollback disposition at
  the next safe boundary.

## 18. Acceptance scenarios

### A. Online tree recording

Given a frozen structural pilot world and the current incumbent policy, when the
policy continues two frontier nodes in parallel, then two child attempts are recorded
with immutable artifacts, audit results, cost, and one visibility sequence; production
candidate selection and ticket state remain unchanged.

### B. Prefix-only replay

Given the sealed world from A, when a challenger chooses a child not recorded under a
visible parent, then replay returns `branch_unavailable`, reveals no sibling score, and
performs no online work.

### C. Incumbent protection

Given a tournament manifest without the deployed incumbent, when tournament creation
is requested, then the Action is rejected and no replay runs start.

### D. Safety dominates score

Given a challenger that finds a higher-quality structural result but attempts a
protected or future-reading Action, when results are aggregated, then the challenger
is disqualified rather than ranked first.

### E. Holdout protection

Given a challenger that wins development worlds but violates the frozen worst-stratum
brake on the time-forward holdout, when selection runs, then the incumbent remains the
winner.

### F. Prospective gate

Given a valid replay winner with no prospective shadow worlds, when deployment is
requested, then deployment is rejected while shadow authorization remains available.

### G. Human authority

Given an AI or deterministic actor, when it requests shadow, canary, deploy, resume,
retire, or a discretionary rollback target, then the Action is rejected and audited.
The deterministic actor may invoke only the preregistered brake transition.

### H. Rollback

Given a canary policy that triggers a hard invariant failure, when the brake is
evaluated, then `trip_policy_brake` stops new canary runs, the deployment's recorded
incumbent is restored for the next safe boundary, and both states remain visible in
history. The braked policy cannot resume without a new human Action.

## 19. Measurable success criteria

- **SC-001**: One real structural pilot world can be recorded online, sealed, and
  replayed by incumbent and challenger with identical policy-visible contracts.
- **SC-002**: Repeating a replay run with the same policy/world manifests yields the
  same trace hash, terminal selection, score vector, and charged cost.
- **SC-003**: A replay visibility test proves zero access to unrevealed child IDs,
  artifacts, scores, and later evidence.
- **SC-004**: A shadow pilot acceptance run causes zero changes to production Forecast,
  candidate terminal, Ticket, placement, Settlement, RSI prospective, or funds rows.
- **SC-005**: Every committed node and replay round has complete parent/action/artifact/
  diagnostic/evaluator/cost lineage; missing lineage blocks world sealing.
- **SC-006**: Tournament reports cover 100% of candidates across 100% of eligible
  worlds or give an explicit machine-readable exclusion/failure reason.
- **SC-007**: Every tournament includes the incumbent, uses a frozen temporal holdout,
  and reports worst-stratum behavior before naming a winner.
- **SC-008**: No policy can directly write ontology tables or invoke protected ticket,
  dispatch, funds, verdict, or deployment Actions.
- **SC-009**: A deployment attempt without human identity and prospective shadow
  evidence is rejected in all tests.
- **SC-010**: The operator can identify the incumbent, latest tournament basis,
  prospective status, and rollback target from one status view.

## 20. Delivery sequence

Implementation is divided into independently reviewable milestones:

1. **D0 - As-built and contract lock**: approve this spec; record the current RSI and
   replay gaps; wrap the current fixed exploration behavior as the baseline incumbent;
   freeze the pilot task and evaluator contract.
2. **D1 - Ontology foundation**: add the six object families, typed Actions,
   permissions, projections, and immutable manifests. No harness execution yet.
3. **D2 - Online recorder**: run the incumbent against the structural pilot in shadow
   and seal discovery trees. Existing behavior remains authoritative.
4. **D3 - Prefix replay**: implement the common environment contract and replay only
   recorded children; prove visibility and production isolation.
5. **D4 - Tournament**: add incumbent-mandatory candidate comparison, temporal holdout,
   strata, lexicographic selection, and reproducible reports.
6. **D5 - Constrained policy development**: admit candidate policy revisions while
   freezing task agent, evaluator, permissions, and business rules.
7. **D6 - Prospective promotion**: run replay winners in shadow, then permit
   human-approved canary/deploy/rollback for the pilot scope only.
8. **D7 - Recursive operation**: each new sealed online world extends the historical
   pool; rerun tournaments on a declared cadence and monitor drift.

No milestone may be collapsed into a direct production cutover. Each milestone gets a
separate implementation plan, tests, evidence, and review gate.

## 21. Migration and compatibility

- Existing RSI tables and registered experiments remain unchanged.
- Existing Candidate Set Revisions remain authoritative business records.
- Existing historical replay runs remain workflow replay records and may be referenced
  as evidence; they are not auto-converted into discovery worlds.
- Existing `rsi dream` outputs remain readable and are labeled `static_variant_replay`.
- Worlds begin accumulating only after D2; old history is not backfilled by pretending
  an exploration policy made choices that were never recorded.
- A later explicit importer may create `historical_replay_source` worlds only when
  original stepwise visibility, children, artifacts, scores, and costs are provable.

## 22. Assumptions

- Jun remains the sole deployment authority.
- Ontology v2 Actions, immutable artifacts, outbox, product query projections, and
  isolated historical replay remain available foundations.
- The structural pilot exposes a closed continuation vocabulary and deterministic
  evaluator before D2 begins.
- Resource cost can be measured consistently enough to compare runs; uncertain cost is
  represented as missing/estimated and cannot silently become zero.
- The first policy family controls exploration only, not football probability or funds.

## 23. Supersession and authority

This document supplements, rather than replaces, the RSI persistence, measurement,
JCZQ ontology cutover, and historical replay designs.

For the meaning of Dream-RSI in Nutmeg, this document supersedes earlier statements
that equated any of the following with a complete Dream-RSI implementation:

- static `rsi dream` variant ranking;
- Candidate Set Revision parent/delta lineage alone;
- full-workflow historical replay alone;
- replay-mode experiment grades alone.

Existing SOP authority, experiment falsifiers, decision rules, audit rules, prospective
sample isolation, and human deployment gates remain unchanged unless a later approved
spec names and changes them explicitly.

## 24. Exit gate for specification phase

The specification phase is complete when Jun approves this document and confirms that
implementation planning may begin with D0/D1. Approval of this spec does not approve a
production policy deployment, a change to any football rule, or any funds action.
