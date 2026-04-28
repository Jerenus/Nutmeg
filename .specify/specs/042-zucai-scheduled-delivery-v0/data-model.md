# Data Model: Zucai Scheduled Delivery v0

## ZucaiScheduleSlot

- `name`: `afternoon` or `revision`.
- `label`: Human-facing Chinese label used in captions and reports.
- `scheduled_time`: Reference local time (`16:00` or `18:30`).

Validation:
- Unknown slot names are rejected with a clear validation error.

## ZucaiIssueRegistryEntry

- `issue_id`: Traditional足彩 issue id, for example `26068`.
- `enabled`: Boolean, default true.
- `active_dates`: List of `YYYY-MM-DD` strings when this issue should run.
- `issue_file`: Path to the 14-match issue snapshot.
- `odds_file`: Optional path to base odds snapshot.
- `overrides_file`: Optional path to base analyst overrides.
- `revision_odds_file`: Optional odds path used only by the `revision` slot.
- `revision_overrides_file`: Optional overrides path used only by the `revision` slot.
- `notes`: Optional operator notes.

Validation:
- Disabled entries are ignored.
- Entries without issue id or issue file are ignored with warnings.
- Relative file paths resolve relative to the registry file first, then the current working directory.
- `active_dates` takes precedence over sale-date inference.

## ZucaiScheduledRunRecord

- `run_date`: `YYYY-MM-DD` date string.
- `slot`: `afternoon` or `revision`.
- `issue_id`: Issue id.
- `status`: Result status such as `dry_run`, `sent`, `generated`, `skipped_no_issue`, `skipped_duplicate`, `config_missing`, or `failed`.
- `generated_at`: ISO timestamp.
- `report_json_path`: Optional path to the report JSON.
- `markdown_path`: Optional path to the Markdown artifact.
- `pdf_path`: Optional path to the PDF artifact.
- `dispatch_status`: Optional Telegram dispatch status.
- `warnings`: List of non-fatal warnings.

Validation:
- Duplicate detection uses `run_date + slot + issue_id` for records with generated/sent/dry-run status.
- Skipped no-issue records do not block later runs if the registry is updated.

## ZucaiScheduledRunResult

- `run_date`, `slot`, `slot_label`, `issue_id`, `status`, `generated_at`.
- `report`: Included only for active issue runs.
- `artifacts`: Report artifact paths, if generated.
- `dispatch`: Telegram dispatch summary.
- `warnings`: Registry and orchestration warnings.
- `skipped_reason`: Machine-readable skip reason when no report is generated.
