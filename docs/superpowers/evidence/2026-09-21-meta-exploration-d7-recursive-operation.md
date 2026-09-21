# Dream-RSI D7 Recursive Operation As-Built (Code and Fixtures Only)

Date: 2026-09-22
Design: `docs/superpowers/specs/2026-09-21-dream-rsi-meta-exploration-v1-design.md`
Plan: `docs/superpowers/plans/2026-09-21-dream-rsi-meta-exploration-d7.md`

## Authority boundary

D7's version-1 information/drift artifact is a **proposed, frozen test contract**, not
an operator-approved artifact. Its canonical proposed hash is
`bda3be2dd7b4545bb0323453346564474c2bfa08e17872349302979f81e8f23b`.
The numbers (three independent new clusters, two days between rounds, one new
action/failure/stratum, three drift samples, 0.05 material gain, 0.2 branch growth,
0.1 worst-stratum decline) are fixture choices, **not Jun's approved limits**.
No approved trigger/drift hash, approval record, scheduler or human Action was
created. The read-only readiness projection always includes `contract_unapproved`,
and the artifact cannot authorize a tournament or recursive runtime cycle.

D0's duplicate key, archive capacity 12, per-lineage cap 3 and minimum action
Jaccard distance 0.2 are loaded or checked against the existing pilot contract;
they were not revised. D6 scope remains unreviewed and inactive. No real tournament,
shadow, canary, deploy, rollback, protected ticket/funds Action, public dispatch or
production-runtime data mutation occurred.

## Implementation and isolated proof

- A strict frozen Pydantic contract rejects unknown fields, calendar-only triggers,
  unapproved/authority claims, and changes to D0 cluster/archive rules. Readiness
  counts only sealed, manifest-valid independent clusters after the latest completed
  frozen pool, and reports action/failure/stratum changes separately. Missing replay
  integrity/coverage, failed optimizer gates and the unapproved contract block
  operational readiness. An independent cluster is required even for other signals;
  round spacing remains a separate block.
- Direct D4 tournament Action creation checks the append-only exposure ledger, prior
  frozen holdout cutoff, sealed strictly later hidden world, derivative clusters and
  D5 generator input IDs/clusters. The existing D4 completion Action still inserts
  holdout exposure facts atomically with its result, and a failed creation inserts
  no tournament or exposure.
- Archive admission/eviction is a deterministic proposal over the unchanged D0
  limits. It rejects ineligible, too-similar, over-lineage or winner-as-stepping-stone
  proposals and evicts a dominated clone before a unique retained member. It never
  edits a policy row, decides a tournament winner or grants deployment; existing D4
  completion remains the only persistence path.
- Drift compares discovery quality, node/round count, parallelism, recovery,
  diversity and strata, preserving a comparison hash. Missing or small samples are
  explicit. Branch growth without material quality gain produces `hold_for_review`.
  A brake signal is possible only for a code supplied from the persisted D6
  deployment's registered hard conditions; no signal invokes a brake Action.
- `uv run nutmeg discovery iteration --data-dir <path>` projects lineage, frozen
  tournament timeline, current protected/exposed holdouts, archive, data mode, trigger
  blocks and drift. It uses read-only SQLite connections and does not create a
  database, migration, tournament, deployment or scheduler job.

A temporary SQLite fixture completed two separate D4 tournaments. Three new sealed
independent clusters met the synthetic cluster trigger before the second tournament;
the first tournament/proof remained unchanged. A newly frozen strictly later hidden
holdout was exposed only by the second completion, while the earlier exposed slice
became development. The second result evidence charged extra branch nodes with no
quality gain; the operator timeline reported `hold_for_review`. The synthetic
archive retained its original D4 winner; the Action ledger contained zero protected
ticket, funds, RSI/deployment or brake Actions. Empty and old-schema CLI tests
compared store bytes before/after. These fixtures do **not** demonstrate real D2
world readiness, effective improvement, prospective promotion or live recursion.

## Verification and remaining gates

Strict RED-GREEN tests were observed for the contract, independent-cluster trigger,
holdout rotation including direct Action bypass, archive limits, drift, and read-only
timeline. The final focused protected suite reached 100% and exited 0 after the
duplicate-action guard. Targeted Ruff reported `All checks passed!`; both `git diff
--check` and staged `git diff --cached --check` exited 0. A fresh full `uv run
pytest -q` after the final code edit reached 100% and exited 0, with two
third-party websocket deprecation warnings. Code commit `8969fdc` passed staged
Ruff and the ontology pre-commit subset; its hook restored unrelated dirty
worktree changes. The full-suite command is repeated after this final evidence
edit; its final exit status is reported in the delivery handoff.

Still required before any real second cycle: Jun's D5/D6 review; genuine D2 sealed
prospective worlds, D3 replay integrity and D5 optimizer coverage; explicit review
and approval of exact trigger/drift numbers and hash; a separate human D4 tournament
request; strictly later sealed hidden holdout; and the existing D6 human gates for
any prospective control. A fixture hash or this evidence cannot satisfy any of them.
