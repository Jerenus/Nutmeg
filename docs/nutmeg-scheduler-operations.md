# Nutmeg Scheduler Operations

The scheduler keeps deterministic project commands separate from model-driven
judgment. LaunchAgents own the official morning, settlement, and close stages;
OpenClaw owns discussion, judgment, retries, and validation around them.

## Daily Handoff

The Nutmeg agent writes `daily/<date>/nutmeg-handoff.json` before close:

```json
{
  "run_date": "YYYY-MM-DD",
  "status": "provisional",
  "position": "ready",
  "updated_at": "ISO-8601 timestamp",
  "summary": "Concise decision summary",
  "questions": [],
  "read_ids": [],
  "explicit_empty_reason": ""
}
```

- `status` is `provisional` at 17:30 and `frozen` after the 18:35 review.
- `position` is `ready` when `legs.json` contains the intended ticket legs.
- `position` is `abstain` for an intentional empty position. In that case,
  `legs.json` must be absent or empty and `explicit_empty_reason` is required.
- `read_ids` identifies the structured Reads created through `decision-read`.
- This file records the operational decision; it does not replace the decision
  ontology, Reads, tickets, or settlement store.

## Operations Command

```bash
uv run python scripts/openclaw/nutmeg_scheduler_ops.py --help
```

- `run-strict` runs an existing daily stage with `--format json` and returns
  nonzero when a structured sub-step or required delivery fails. It no longer
  searches human-readable output for success markers. The AM stage also writes
  a compact `daily/<date>/scheduler-context.json` for agent use.
- `build-context` can regenerate that bounded context without rerunning AM.
- `retry-settlement` reruns only `decision-reconcile` for D-1/D-2, so it is
  idempotent and does not duplicate reports or Telegram delivery. Settle and
  retry runs refresh the current-day scheduler context afterward.
- `validate-preclose` checks the frozen handoff and deterministic legs fields.
- `verify-close` checks the dated PDF and a sent `decision.close.report` in the
  notification ledger; the mutable latest-PDF path and log text are not treated
  as delivery evidence.

## Delivery Failures

The notification ledger lives in `.nutmeg-data/state/state.db`; immutable
attachments live under `.nutmeg-data/notifications/artifacts/`.

```bash
uv run nutmeg notification-status --since 7d
uv run nutmeg notification-show --notification-id <id>
uv run nutmeg notification-retry --notification-id <id>
```

- Upstream stage failures publish one deduplicated `operations.failure` text
  notification. A later successful rerun publishes one `operations.recovered`.
- Telegram transport failures do not recursively generate Telegram alerts;
  launchd keeps the nonzero exit and the durable failed delivery attempts.
- Delivery is at-least-once. An interrupted `sending` attempt becomes
  `uncertain`; retrying it may duplicate a message and is marked accordingly.

## Ownership

- Nutmeg agent: evidence, Reads, provisional legs, user discussion, final freeze.
- Existing CLI: fetch, sense, backfill, reconcile, calibrate, express, and report.
- `decision-close`: the only command allowed to turn frozen legs into tickets and
  dispatch the official close report.
- Codex yolo: confirmed defects and explicit project reviews only.
