# Zucai Deployment Gate Design

Date: 2026-08-28
Status: Approved by the engineering handoff and operator continuation instruction

## Goal

Replace handwritten deployment arithmetic with a deterministic report after the
Zucai leg audit: capital utilization, the cap-optimal structure, its break-even bonus,
the official historical median Renjiu bonus, and a governed exit state.

## Authored Input

```json
{
  "issue": "26104",
  "period_cap_yuan": 1600,
  "history_as_of_issue": "26104",
  "history_window": 14,
  "candidates": [
    {"id": "M1296", "stake_yuan": 1296, "hit_probability": 0.21256}
  ]
}
```

The main loop authors the candidate structures, hit probabilities, cap, history
window, and history cutoff. Choosing whether three or fourteen prior issues represent
the current regime is judgment and therefore does not enter code.

## Deterministic Arithmetic

Candidates above the cap are excluded. The remaining candidate with maximum
`hit_probability` is the cap-optimal structure; equal P is broken by lower stake and
then ID. The report computes:

```text
capital_utilization = stake / period_cap
break_even_bonus = stake / hit_probability
median_bonus = median(official Renjiu stakeAmount in the authored history cohort)
break_even_to_median = break_even_bonus / median_bonus
equivalent_max_winning_stakes = floor(median_sale * 0.64 / break_even_bonus)
```

Official history comes from sporttery gameNo=90. History parsing deliberately ignores
the 14-result string so an official `*` cancellation does not discard valid bonus and
sales facts. For each row, `saleAmount * 0.64 / stakeCount` must agree with the official
single bonus within published-yuan rounding tolerance.

## Gate States And Exit Codes

- `PASS`, code 0: ratio `<= 0.95`;
- `REVIEW`, code 2: `0.95 < ratio < 2.2`;
- `REDUCE_OR_EMPTY`, code 3: ratio `>= 2.2`;
- invalid/missing input or official history, code 1.

REVIEW and REDUCE_OR_EMPTY say to build a lower-stake version only by dropping whole
matches and rerun the gate. Empty slate is the fallback only when no such version can
clear the gate. The program never edits a ticket, selects dropped matches, records an
exemption, or dispatches.

## Historical Acceptance

The replay cohort ending before 26104 has official median bonus CNY 6,446.50. The
recorded 26103 cap structure needs CNY 14,412, about 2.2x median, so the gate returns
REDUCE_OR_EMPTY, consistent with the empty-slate precedent. The 26104 M1296 structure
needs CNY 6,097, about 0.95x median, so it returns PASS, consistent with the recorded
compromise ticket.

## Explicit Exclusions

- football judgment, payout forecasting, or history-window selection;
- face optimization (T6);
- automatic reduction, empty-slate selection, or dispatch;
- production data writes, scoreboard cutover, or Adjudication creation.
