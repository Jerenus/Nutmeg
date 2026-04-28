# Data Model: Traditional Zucai 14-Match Workflow v0

## ZucaiIssue

- `issue_id`: issue number such as `26068`.
- `game_type`: `sfc14` for traditional 14-match win/draw/loss pool.
- `sale_start`: optional sale start timestamp.
- `sale_stop`: sale stop timestamp.
- `draw_date`: optional draw/settlement date.
- `sources`: source ledger strings or objects.
- `matches`: exactly 14 `ZucaiMatch` records ordered by `match_no`.

Validation:

- `match_no` must be unique and exactly `1..14`.
- `home_team` and `away_team` must be non-empty.
- Missing timing fields produce warnings but do not block local analysis.

## ZucaiMatch

- `match_no`: 1 through 14.
- `competition`: league/cup label.
- `home_team`, `away_team`.
- `match_date`: date or kickoff string.
- `notes`: optional evidence snippets.
- `risk_flags`: optional strings such as `manager_change`, `fixture_congestion`, `derby`, `relegation_pressure`, `shallow_handicap`.

## ZucaiOddsSnapshot

- `issue_id`.
- `captured_at`: timestamp or source label.
- `sources`.
- `matches`: one or more `ZucaiMatchOdds` records.

## ZucaiMatchOdds

- `match_no`.
- `home`, `draw`, `away`: latest average decimal odds mapped to `3`, `1`, `0`.
- `providers`: optional provider-level odds rows.

Validation:

- Odds must be positive decimals when present.
- Missing matches are allowed but produce per-match warnings.

## ZucaiRecommendation

- `match_no`.
- `pick`: normalized unique string containing `3`, `1`, and/or `0`.
- `primary`: strongest single code.
- `confidence`: numeric 0..1.
- `risk_tier`: `banker`, `lean`, `cover`, or `volatile`.
- `rationale`: operator-readable explanation.
- `odds_average`: optional `3/1/0` odds evidence.
- `override_applied`: whether an override replaced baseline.
- `warnings`: per-match warnings.

## ZucaiPlan

- `name`.
- `plan_type`: `full14` or `renjiu`.
- `code`: 14 tokens separated by spaces, each token `3/1/0` combination or `-` for 任九 omission.
- `stake_count`: product of selected token lengths.
- `cost_yuan`: `stake_count * 2`.
- `selected_matches`: match numbers included in the plan.
- `note`.

## ZucaiReport

- `issue`, `generated_at`, `recommendations`, `plans`, `artifacts`, `dispatch`, `warnings`, `sources`.

## ZucaiOutcome

- `issue_id`.
- `results`: map of match number to result code `3`, `1`, or `0`.

## ZucaiGradeReport

- `issue_id`.
- `match_results`: per-match hit/miss/unresolved.
- `plan_results`: per-plan selected hit count, selected count, and covered boolean.
- `warnings`.
