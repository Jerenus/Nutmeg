# Data Model: Zucai Odds Source v0

## ZucaiOddsSyncResult

- `generated_at`: ISO timestamp.
- `issue_id`: Issue id.
- `slot`: `afternoon` or `revision`.
- `captured_at`: Odds capture timestamp.
- `source_label`: Source label.
- `source_url`: Optional source URL.
- `source_path`: Optional source file path.
- `parsed_count`: Number of valid odds rows.
- `odds_path`: Written odds snapshot path.
- `registry_path`: Updated registry path.
- `warnings`: Non-fatal warnings.

## Odds Snapshot

Uses the existing 041 format:

- `issue_id`
- `captured_at`
- `sources`
- `matches`: rows with `match_no`, `home`, `draw`, `away`, optional `providers`

Validation:
- Must have exactly 14 valid rows for a complete issue snapshot.
- Odds must be positive floats.
