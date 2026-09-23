# Dream-RSI v1 Pilot Objective Restatement: Cost Pruning

Date: 2026-09-22

Status: Accepted by Jun (chat, 2026-09-22) as the honest objective of the current pilot

Supplements: `2026-09-21-dream-rsi-meta-exploration-v1-design.md` section 13

## 1. What the 2026-09-22 review found

The structural candidate pilot, as frozen in D0 and implemented in D2-D7, is a
degenerate search problem:

- Every recorded world is a root, one flat layer of `enumerate_template_shard`
  children, and a `stop` node. Depth is always 1.
  `execute_template_shard` reads only the frozen snapshot; a parent node carries no
  state, so a deeper continuation would be identical to a depth-1 one.
- The incumbent runs every template shard. Under prefix-only replay a challenger can
  reveal only recorded children, so its visible set is a subset of the incumbent's.
  The three `discovery_quality` fields are monotone in that subset, and the selector
  vetoes any per-band regression. A challenger can therefore never beat the incumbent
  on quality; it can only tie on quality and win on `cost` or `parallel_efficiency`.
- Two of the four D5 program fields (`budget_allocation`, `stop_quality_threshold`)
  cannot change any trace at depth 1. `batch_limit` is clipped by
  `max_concurrency = 4`, and the incumbent's single all-shard batch is rejected by
  replay on any world with more than four templates.
- The recursion's payoff term, "new online trees that pi_t might not have reached",
  is empty for this pilot: every promoted policy explores a sub-multiset of the
  incumbent's shards on an identical frozen snapshot.

## 2. Restated objective

The pilot's purpose is **to run the whole governed loop end to end on real inputs**,
not to discover better structural candidates. The only improvement it can legitimately
demonstrate is:

> A challenger that ties the incumbent on every `discovery_quality` field across the
> frozen pool and holdout, and does so with fewer attempt nodes and less wall time.

Expected outcomes are lowered accordingly:

| Claim | Allowed under this restatement |
| --- | --- |
| Better structural candidates than the current workflow | No |
| Better `best_objective_probability_by_band` than the incumbent | No (impossible by construction) |
| Fewer shards for the same result | Yes, and only after the D4 readiness gate |
| Proof that recording, sealing, replay, tournament, promotion and brake work on real data | Yes, this is the goal |
| Evidence for the Dream-RSI recursion producing unreachable trees | No |

## 3. What stays frozen

- The pilot contract `experiments/discovery/structural-candidate-v1.contract.json`
  (canonical hash `842c96bc…f08f`) and the incumbent artifact are unchanged.
- The D4 selection contract is unchanged; it already permits "tie on quality, win on
  cost" and nothing else, which is exactly the restated objective.
- The D7 iteration contract numbers are unchanged; its approval is recorded in the
  artifact itself and bound to the proposed hash.

## 4. Known limitation to fix before the first real world with more than 4 templates

Replay rejects the incumbent's all-shard batch when `len(templates) > 4`
(`nutmeg/discovery/environment.py`, concurrency budget). The operator envelope editor
offers up to eight `pass-N-1` templates per JCZQ board. Options, to be decided
prospectively as a pilot-contract revision, not a silent interpreter change:

1. raise `budgets.max_concurrency` to 8 and re-freeze the pilot contract hash; or
2. define the incumbent's `all_template_shards` step as "batch in chunks of
   `max_concurrency` across rounds" and re-freeze the baseline artifact hash.

Until one is chosen, a real world must be recorded from a board whose envelope declares
at most four templates, or the tournament preparation will report the incumbent as
`branch_unavailable`.

## 5. What would make a non-degenerate pilot

Either of these would restore the recursion's payoff term and is out of scope for v1:

- a compositional operator whose result conditions the next continuation (parent
  state that matters), or
- a shard space too large for the incumbent to enumerate under budget, so that
  policies genuinely choose which regions to explore.

## 7. Input source changed to the decision lane (2026-09-23)

Jun ruled option A: the 8788 operator app and its operator_v2 write path are retired. The world input now comes from the day's decision-lane files (`jczq-legs-base.json` + `reads.json` + `sporttery_markets.json`) via `nutmeg discovery shadow-run --source-day`; see `docs/superpowers/specs/2026-09-23-discovery-day-source-design.md`. The pilot contract, evaluator and baseline are unchanged; `authoritative_workflow.generator` will be re-frozen through a D7 revision once the generator moves out of `nutmeg/product`.
