# Meta-Exploration D3 Prefix Replay As-Built

Date: 2026-09-21
Spec: `docs/superpowers/specs/2026-09-21-dream-rsi-meta-exploration-v1-design.md`
Plan: `docs/superpowers/plans/2026-09-21-dream-rsi-meta-exploration-d3.md`

## Review Result

D3 adds a shared policy-visible observation/action interface, incremental shadow
environment, verified sealed-tree loader, prefix-only replay environment and
registered baseline runner. Fixture worlds prove root-only reset, exact recorded
child revelation, a linked failed-attempt retry, branch-unavailable accounting,
deterministic reruns and isolation from the temporary business store. The
`finish_replay` Action independently checks the persisted seal, action-child
sequence, observation/state hashes, recorded costs, failures and selectable STOP
targets before committing a trace. Trace hashes bind the source seal, evaluator,
cost policy, seed, rounds and completion.

This is **fixture-level functional evidence**, not SC-001 real-world readiness.
D2 evidence has no sealed real prospective world. No real online shadow run,
operator-registered challenger replay, tournament, candidate generation,
canary or deployment was performed.

## Frozen Inputs And Isolation

- D0 pilot canonical SHA-256: `842c96bce8745ff2ae6b2249ab7d8c5e1771fc7d693581952db01863d029f08f`.
- D0 incumbent canonical SHA-256: `a9dad2f5f7db577edabc379edfe60a61322e978ef9b1c2e42282040dd142e55a`.
- Tests use a registered `structural-baseline-v1` and temporary `historical_replay_source`
  worlds. Their world/seal IDs are fixture-dependent and are not production IDs.
- Replay accepts a sealed manifest, pilot and registered policy. It accepts no
  executable adapter or production source connection. Missing branches return
  `branch_unavailable` without revealing a child; unknown historical cost stays
  unknown rather than being converted to zero. Fixture tests compare the
  temporary business database fingerprint before and after replay.
- The D2 recorder's transient failures can be retried once as separately
  metered, linked attempt nodes. D3 treats that chain as one requested
  continuation but charges and reveals every attempt in order. An unrelated
  duplicate `(parent, continuation)` remains invalid.

## Verification And Limits

The D3-focused/protected command collected 157 tests and exited 0:

`uv run pytest tests/discovery tests/ontology/test_discovery_policy_actions.py tests/ontology/test_discovery_world_actions.py tests/ontology/test_replay_actions.py tests/ontology/test_protected_ticket_actions.py tests/ontology/test_rsi_actions.py -q`

`uv run ruff check nutmeg/discovery nutmeg/ontology/actions/discovery_policy_actions.py tests/discovery tests/ontology/test_discovery_policy_actions.py`
and `git diff --check` both exited 0 after the final runtime edit.

After the final runtime edit, `uv run pytest -q` collected 3,826 tests and
exited 0 (two third-party websockets deprecation warnings). This run followed
the 157-test focused/protected check above. The explicit root-selection
regression failed before the Action guard and passed afterward.

No `.nutmeg-data` files were changed for D3. Other existing changes in decision,
experiment, script and memory files are outside this milestone and are not staged.
Task 4's optional outbound model/tool monkeypatch is not claimed: replay has no
adapter/tool dependency in its constructor, and the fixture proof exercises that
structural boundary. Invalid policy actions are rejected before execution; this
evidence does not claim a scored prospective invalid-action rate.

## Next Gate

Jun must review this D3 evidence before D4 implementation. D4 additionally needs
the numerical selection contract (materiality, within-tier aggregation,
missing-cost treatment and worst-stratum brake) reviewed and frozen **before**
any tournament scoring. Fixture replay does not authorize either scoring or a
real prospective run.
