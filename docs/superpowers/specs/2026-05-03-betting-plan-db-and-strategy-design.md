# Betting Plan DB And Strategy Design

## Goal

Persist each finalized daily betting plan to DuckDB and use those records for the next-day review, while changing the daily strategy output from one-size-fits-all high odds into a stable-base plus opportunity-ticket portfolio.

## Strategy Rules

Nutmeg will classify daily plans into four roles:

- `stable_base`: foundation tickets intended for repeatable daily participation.
- `balanced`: moderate-risk tickets that allow one or two protected variables.
- `opportunity`: bold tickets used when there is a logical anti-public edge.
- `extreme`: very small stake inspiration tickets using high-variance markets.

The strategy should not chase cold outcomes for their own sake. It should become bold only when the evidence points to structural opportunity: comfortable favorites in the 1.75-2.05 range, season-late draw/upset climates, strong favorites with rotation or motivation risk, market narratives that are too easy to explain, or correlated league-level instability.

## Persistence

The analytics DuckDB database will gain four tables:

- `betting_plan_runs`: one finalized daily/issue-level run.
- `betting_plans`: one row per ticket in a run.
- `betting_plan_legs`: one row per ticket leg or Zucai match selection.
- `betting_plan_reviews` and `betting_leg_reviews`: settled review rows created the next day.

Jczq daily advisor and Zucai report generation can both record final plans. Review commands can write back hit counts, original settled odds, and same-match/same-play oracle odds.

## Review Behavior

The Jczq review will continue to read the JSON context for human-readable match data, but it will also persist review rows to DuckDB. Okooo result parsing will keep actual result labels and settled odds. Review output will include original hit status and the same-match/same-play correct-direction odds, making it clear whether the day had investable opportunity without implying guaranteed profit.

## Scope

This design adds persistence and Jczq review odds analytics first. Zucai records are stored in the same tables from generated report data; existing Zucai file-based grading remains available and can be extended with payout math later.
