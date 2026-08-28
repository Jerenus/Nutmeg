# C8 Pseudo-Precision Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add deterministic C8 WARN coverage for 5pp-or-greater unanchored probability shifts.

**Architecture:** Extend the authored leg contract with an optional prior and structured evidence tiers. Reuse total-variation arithmetic from Read validation; do not infer evidence quality from prose. Preserve backward compatibility for historical legs without the new fields.

**Tech Stack:** Python 3.12 dataclasses, existing `legs_audit` validator, pytest, Ruff.

---

## File Structure

- `nutmeg/decision/legs_audit.py`: C8 calculation, finding, and standalone JSON parsing.
- `nutmeg/ontology/tickets/models.py`: protected-ticket typed fields and serialization.
- `tests/decision/test_legs_audit.py`: trigger, non-trigger, boundary, and parser tests.
- `tests/ontology/test_ticket_composition.py`: protected-ticket round-trip test.
- `docs/sop/RULEBOOK.md`: mark `伪精确锚定` as C8 and register the code.

### Task 1: C8 RED tests

- [x] Add a pure-inference 6pp shift test expecting `pseudo_precision_anchor` WARN.
- [x] Add official and confirmed-structural anchor tests expecting no C8.
- [x] Add 4.99pp and exact 5.00pp boundary tests.
- [x] Add a historical leg-without-prior test expecting no C8.
- [x] Run `uv run pytest tests/decision/test_legs_audit.py -q -k pseudo_precision` and confirm the missing-field/API failure.

### Task 2: Minimal C8 implementation

- [x] Add optional `prior` and `adjustment_evidence_tiers` fields to `Leg`.
- [x] Compute `sum(abs(fair-prior))/2` only when `prior` is present.
- [x] Emit WARN code `pseudo_precision_anchor` at a tolerance-safe `>= 0.05` boundary when no strong tier exists.
- [x] Parse both fields in `legs_from_dict`.
- [x] Run `uv run pytest tests/decision/test_legs_audit.py -q` and confirm green.

### Task 3: Protected ticket propagation

- [x] Write a failing `TicketLegDraft.to_dict/from_dict/audit_leg` round-trip test.
- [x] Run `uv run pytest tests/ontology/test_ticket_composition.py -q -k adjustment` and confirm RED.
- [x] Add typed fields, validation, serialization, parsing, and `audit_leg` forwarding.
- [x] Run the focused ontology test and all decision audit tests.

### Task 4: Governance mapping

- [x] Change the RULEBOOK `伪精确锚定` code column from pending to `C8 (WARN)`.
- [x] Add C8 to the audit mapping table.
- [x] Run `uv run ruff check nutmeg/decision/legs_audit.py nutmeg/ontology/tickets/models.py tests/decision/test_legs_audit.py tests/ontology/test_ticket_composition.py`.
- [x] Run `uv run pytest tests/decision/test_legs_audit.py tests/ontology/test_ticket_composition.py tests/ontology/test_protected_ticket_actions.py tests/product/test_m4_api.py tests/product/test_m4_contracts.py -q`.
- [x] Commit implementation and governance docs as separate commits.

## Execution Record (2026-08-28)

- Focused audit/ticket propagation suite: 36 passed.
- `uv run ruff check .`: All checks passed; `uv run pytest -q`: 1,396 tests
  collected, exit 0.
- CLI replay with a 6.0pp shift and only `inference/motivation` evidence returned
  exit 0 and `0 ERROR / 1 WARN [pseudo_precision_anchor]`.
- Read-only 26111 SFC486 replay proved backward compatibility: its legacy legs have
  no authored prior/evidence tiers, so C8 adds no retrospective finding while the
  existing structural audit remains unchanged.

## Explicit Exclusions

- Natural-language authority classification;
- automatic belief changes or ticket changes;
- production ontology or `.nutmeg-data` writes;
- any ERROR override behavior (T4 scope).
