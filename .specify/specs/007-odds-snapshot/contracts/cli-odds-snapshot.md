# CLI Contract: odds-snapshot

## Command

`uv run nutmeg odds-snapshot --fixture-id <fixture_id> [--format text|json]`

## JSON contract

```json
{
  "fixture": {
    "fixture_id": "1379304",
    "league_code": "epl",
    "kickoff_at": "2026-04-25 14:00:00+00:00",
    "home_team": "Liverpool",
    "away_team": "Crystal Palace"
  },
  "provider": {
    "name": "api-football",
    "updated_at": "2026-04-24T06:16:30+00:00",
    "bookmaker_count": 12
  },
  "markets": {
    "match_winner": {
      "status": "available",
      "outcomes": [
        {
          "outcome_key": "home",
          "best_odds": 1.48,
          "average_odds": 1.45,
          "fair_probability": 0.63,
          "fair_odds": 1.59,
          "bookmaker_count": 10
        }
      ]
    }
  },
  "history": {
    "match_winner": {
      "market_key": "match_winner",
      "line": null,
      "points": [
        {
          "captured_at": "2026-04-24T05:16:30+00:00",
          "provider": "api-football",
          "market_key": "match_winner",
          "line": null,
          "outcome_probabilities": {"home": 0.62},
          "outcome_fair_odds": {"home": 1.613},
          "outcome_best_odds": {"home": 1.48},
          "bookmaker_count": 10
        }
      ],
      "drift_vs_current": {"home": 0.01},
      "movement": "moving",
      "movement_span": 0.01
    }
  },
  "deferred_sections": []
}
```

## Behavioral guarantees

- Unknown fixture id exits cleanly with a non-zero code and a readable error.
- Missing provider configuration exits cleanly with a non-zero code and a readable error.
- Markets that cannot be normalized or completed remain explicit with `status` values such as `incomplete` or `unavailable`.
- Raw bookmaker prices and derived fair probabilities stay distinct in both text and JSON views.
- When historical odds points exist for a canonical market, the snapshot includes a `history` block with persisted points plus derived `drift_vs_current`, `movement`, and `movement_span` summaries.
- Provider selection is configuration-driven; providers that do not satisfy the current fixture-linked contract must fail truthfully instead of fabricating a fixture match.
