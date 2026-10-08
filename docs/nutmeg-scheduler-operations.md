# Nutmeg Scheduler Operations

> **状态（2026-10-02）：部分过时。** 仍有效：`scripts/openclaw/nutmeg_scheduler_ops.py run-strict --stage am`（launchd 08:00 与 OpenClaw 17:15 都跑它；体彩列表完全为空记为合法空盘）、`build-context`、失败/恢复事件去重。**已退役**：`nutmeg-handoff.json` 交接、18:20 每日最终决策与 18:40 补跑、`decision-close` 收盘与闸门（2026-10-01 起真票路径是 `betslip preview` → 500 app → `betslip register`，OpenClaw GPT 判断链停用）。现役调度见 `docs/ops/2026-09-20-scheduled-dataflows.md` 与 `docs/ARCHITECTURE.md` §2。

The scheduler keeps deterministic project commands separate from model-driven
judgment. The `com.nutmeg.decision.am` LaunchAgent owns the official morning
stage; settlement belongs to `com.nutmeg.day.settle` and closing odds come from
the rsi loop's titan007 backfill (see `docs/ops/2026-09-20-scheduled-dataflows.md`).
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

- `run-strict --stage am` runs `decision-am` with `--format json` and returns
  nonzero when a structured sub-step fails. It does not search human-readable
  output for success markers. On success it writes a compact
  `daily/<date>/scheduler-context.json` for agent use and prints `NUTMEG_OK`;
  on failure it prints `NUTMEG_FAILED` and publishes one `operations.failure`
  notification.
- `build-context` can regenerate that bounded context without rerunning AM.
- The retired `close` / `settle` stages (`retry-settlement`, `validate-preclose`,
  `verify-close`) were removed on 2026-09-23 together with their LaunchAgents.

## Delivery Failures

Since 2026-10-08 the notification ledger is `.nutmeg-data/notifications/ledger.jsonl`
(`nutmeg/notifications/notify.py`: one line per send attempt, dedupe on kind + key +
fingerprint, a failed send is retried by the next call with the same identity). On first
use it imported every delivered row from the old `.nutmeg-data/state/state.db`, which is
kept read-only together with `.nutmeg-data/notifications/artifacts/`.

The `notification-status/show/retry` commands were removed 2026-10-03 (no use in
the prior month); the four-table SQL outbox itself was removed 2026-10-08.

- Upstream stage failures publish one deduplicated `operations.failure` text
  notification. A later successful rerun publishes one `operations.recovered`.
  Preclose failures use a short user-safe summary rather than raw paths or stack
  traces.
- The bounded 18:40 recovery decision runs only when the 18:20 decision did not
  produce a frozen handoff. It performs one retry; there is no retry loop.
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
