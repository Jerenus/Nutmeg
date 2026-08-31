# 26113 Rule Hardening Design

Date: 2026-08-31  
Status: Approved through the 2026-08-30 RULEBOOK adjudications and Jun's instruction
to complete all remaining development work

## 1. Scope

Close the two incomplete code paths introduced by the 26113 review:

1. machine-check the C9-C12 probation rules without adding football judgment; and
2. make the Zucai deployment bonus anchor use exactly the latest 12 eligible official
   Renjiu issues while accepting the provider's per-winning-stake floor rounding.

The implementation preserves the existing split between authored inputs and deterministic
checks. The main loop decides whether an opening-round crash marker applies, authors fair
probabilities, chooses ticket faces, and adjudicates every WARN. Code validates marker
vocabulary, interval membership, official facts, and deployment arithmetic only.

## 2. Audit Contract

`Leg.crash_markers` accepts a closed vocabulary:

- `opening_promoted_vs_paper`
- `opening_new_coach_debut`

The audit produces these non-blocking findings:

- `opening_upset_double`: a known crash marker is present and the retained leg has fewer
  than three faces;
- `flagged_double_not_full`: a registered directional flag is expressed with exactly two
  faces;
- `false_direction_band`: `top1 - top2` is in `[0.05, 0.10)` and the leg is not full;
- `draw_underpriced_band`: draw fair is in `[0.29, 0.32)` and draw is absent;
- `crash_marker_off_lexicon`: an authored crash marker is outside the closed vocabulary.

All five findings are WARN. Existing ERROR behavior, including C1 naked directional flags,
does not change. A dropped match is absent from `legs`, so it remains a legal response and
does not receive a finding.

Unknown crash markers must not silently disappear. They are reported without treating the
invented marker as evidence that C9 fired. JSON loading remains backward compatible when
`crash_markers` is absent.

## 3. Deployment Anchor Contract

The deployment gate owns a public constant `RENJIU_HISTORY_WINDOW = 12`. Callers may retain
the `history_window` input field for explicit auditability, but its value must equal 12.
Missing, boolean, non-integer, or any other integer value is a source-contract error.

The cohort contains the 12 highest numeric official issue numbers strictly before
`history_as_of_issue`. Later or equal issues are excluded. Fewer than 12 eligible rows is a
source error; the gate does not shrink its window.

The product operator projection passes the same constant rather than deriving a window from
available row count. Therefore CLI and browser reports cannot disagree about the bonus
anchor.

## 4. Official Payout Validation

For a Renjiu history row:

```text
expected_pool = sale_amount * 0.64
paid_pool = stake_amount * stake_count
floor_loss = expected_pool - paid_pool
```

The row is consistent only when `floor_loss` is at least zero, within floating-point epsilon,
and strictly less than `stake_count`. This models an official stake amount floored by less
than CNY 1 for each winning stake. It accepts the real 26111 high-winner-count row and rejects
overpayment or a shortfall of CNY 1 or more per winning stake.

Both the official response parser and deployment cohort validator call the same method.

## 5. Data Flow

```text
authored legs JSON
    -> legs_from_dict
    -> audit_legs
    -> C9-C12/lexicon WARN findings
    -> human adjudication

official gameNo=90 history
    -> parse_renjiu_history_item
    -> floor-rounding validation
    -> fixed 12-row cohort
    -> deterministic deployment report/exit code
    -> human deployment adjudication
```

No new persistence type, Action, schema migration, or background process is required.

## 6. Verification

Focused tests cover:

- every C9-C12 trigger, non-trigger, lower boundary, and upper boundary;
- full-cover and dropped-match-compatible behavior;
- unknown crash marker warning and backward-compatible JSON parsing;
- exactly-12 window enforcement in the domain function, CLI fixture, and product query;
- 26111 floor-rounding acceptance, parser acceptance, true underpayment rejection, and
  overpayment rejection;
- existing 26103/26104 deployment replays under the fixed 12-row cohort.

Completion also requires decision/product regressions, five-domain pytest, ruff, compileall,
pre-commit, and read-only CLI replay. Production ontology and scoreboard data are not written.

## 7. Explicit Exclusions

- no automatic classification of promoted teams, paper strength, opening round, or coach
  debut;
- no automatic face, drop-match, ticket, deployment, or empty-position choice;
- no change to ERROR override authority or `ConfirmDispatch`;
- no scoreboard cutover, launchd change, soak, ReleaseApproval, or production Action;
- no changes, staging, or commits for the scheduler operation files, the Codex handoff file,
  or the 26113 PDF rendering script currently present in Jun's worktree.
