# Eval and Review Loop

Nutmeg now has a local evaluation and prediction review loop so generated
judgments can be checked and calibrated over time.

## Local Eval

`eval-run` reads JSON datasets from `nutmeg/evals/`. A case defines expected
keywords and an output sample. The current starter dataset is deliberately
local-only and does not require LangSmith or live provider credentials.

```bash
uv run nutmeg eval-run --dataset starter --format json
```

The runner returns total, passed, failed, and per-case missing keyword evidence.
LangSmith can still be layered on top later; local eval remains the fallback.

## Prediction Review

Prediction tracking stores match-winner probabilities in SQLite state storage and
later resolves them with actual outcomes. Review reports:

- total predictions
- resolved predictions
- average three-way Brier Score
- picked-outcome accuracy

```bash
uv run nutmeg prediction-record \
  --fixture-id epl-001 \
  --league epl \
  --home-team Arsenal \
  --away-team "Tottenham Hotspur" \
  --home-probability 0.60 \
  --draw-probability 0.25 \
  --away-probability 0.15 \
  --pick home

uv run nutmeg prediction-outcome --prediction-id 1 --actual home
uv run nutmeg prediction-review --format json
```

## Scoring

The Brier implementation uses the three match-winner outcomes `home`, `draw`,
and `away`, requiring probabilities to sum to one. Lower score is better.

