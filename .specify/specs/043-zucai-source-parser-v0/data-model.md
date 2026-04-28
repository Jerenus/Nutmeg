# Data Model: Zucai Source Parser v0

## ZucaiSourceNotice

- `source_label`: Human source label, such as `official schedule`.
- `source_url`: Optional URL for attribution.
- `source_path`: Optional local path.
- `content`: Raw HTML or text.

Validation:
- At least one local file or explicitly live-fetched URL must provide content.

## ParsedZucaiIssue

- `issue_id`: Issue number.
- `issue`: Existing `ZucaiIssue` object with exactly 14 matches.
- `source_label`: Source attribution.
- `source_url`: Optional source URL.
- `warnings`: Non-fatal parsing warnings.

Validation:
- Exactly 14 matches with match numbers 1 through 14.
- Empty home/away team names invalidate the issue section.

## ZucaiSourceSyncResult

- `generated_at`: ISO timestamp.
- `run_date`: Date used to calculate active issues.
- `source_label`, `source_url`, `source_path`.
- `parsed_count`: Number of valid issues parsed.
- `written_issue_paths`: Paths written by issue id.
- `registry_path`: Registry file path.
- `active_issue_ids`: Issue ids active for the run date.
- `warnings`: Non-fatal warnings.

## Registry Merge Record

Uses the 042 registry format with fields:

- `issue_id`
- `enabled`
- `active_dates`
- `issue_file`
- optional preserved `odds_file`, `overrides_file`, `revision_odds_file`, `revision_overrides_file`, `notes`
