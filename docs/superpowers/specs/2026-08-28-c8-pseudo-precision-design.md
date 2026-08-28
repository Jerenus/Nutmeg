# C8 Pseudo-Precision Audit Design

Date: 2026-08-28  
Status: Approved by the 2026-08-28 engineering handoff and the operator's continue instruction

## Goal

Turn RULEBOOK `伪精确锚定` into a deterministic WARN without asking code to judge
source prose. A leg that moves at least 5 percentage points from its authored prior
must name at least one official or confirmed-structural evidence tier.

## Contract

`Leg` and `TicketLegDraft` gain two optional, explicitly authored inputs:

- `prior`: the three-outcome market baseline before judgment;
- `adjustment_evidence_tiers`: zero or more values from `official`,
  `confirmed_structural`, `inference`, and `motivation`.

The existing `fair` field remains the final belief. The audit computes net movement
as total variation distance:

```text
net_offset = sum(abs(fair[outcome] - prior[outcome])) / 2
```

This is the same deterministic probability-shift measure used by Read validation.
At `net_offset >= 0.05`, absence of `official` or `confirmed_structural` emits C8
`pseudo_precision_anchor` at WARN level. The exact 5pp boundary triggers.

## Compatibility And Validation

Historical legs without `prior` are not reinterpreted and do not trigger C8. Unknown
evidence-tier names are rejected when a protected `TicketLegDraft` is constructed;
the standalone JSON audit parser preserves authored strings and C8 treats them as
non-anchors. This keeps the CLI useful for surfacing incomplete legacy drafts while
the formal product contract stays typed.

The protected ticket model serializes both fields so the authoritative audit behaves
the same through CLI and M4 composition. No evidence URL, quote, team name, or prose is
classified by code.

## Output

C8 reports the calculated net offset and the authored tier list. It is WARN only and
does not change the existing `has_blocking` exit behavior. The operator/main loop
decides whether the authored evidence tier is valid and whether to revise the leg.

## Explicit Exclusions

- no automatic evidence-authority inference;
- no probability adjustment or reset performed by code;
- no change to ERROR policy or ticket dispatch;
- no production data mutation or historical ticket rewrite.

