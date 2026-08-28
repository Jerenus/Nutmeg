# Telegram Confirmation Loop Design

Date: 2026-08-28
Status: Approved by the operator's continuous implementation authorization; formal plan follows
Scope: Package 2 - protected Telegram confirmation, ledger writeback, deadline shadowing,
and night-calibration delivery

## 1. Outcome

Package 2 closes the gap between an approved audited ticket artifact and the operator being
away from the computer. It adds a Telegram confirmation surface on top of the existing M4
protected ticket Actions. It does not create another ticket, audit, budget, or finance path.

The lifecycle is:

```text
approved AuditedTicketArtifact
  -> issue existing five-minute ConfirmationChallenge
  -> send owner-only Telegram message with exact hash/amount/deadline/audit summary
  -> Jun presses "confirmed placed"
  -> consume existing challenge through ConfirmTicketPlacement
  -> formal Ticket + BetLegs + negative CashTransaction + placement receipt
```

If the ticket deadline passes after a Telegram challenge was issued and no placement exists,
a deterministic Action records a durable shadow/non-placement object. It writes no Ticket and
no CashTransaction, making "not in the ledger means not placed" mechanically true.

`zucai-night-calibrate` gains optional delivery through the existing notification ledger. The
report body remains the deterministic output of `run_night_calibrate`; Telegram is only a
transport.

## 2. Constraints

- `CreateTicketBatch`, `ApproveTicketBatch`, `IssueTicketConfirmation`, and
  `ConfirmTicketPlacement` remain authoritative.
- The bot never recomputes selections, amount, audit, ticket hash, or deadline.
- Only configured owner chat IDs may consume a callback. The server assigns
  `judge_operator`; callback payloads cannot choose a role.
- AI roles receive no new protected permission and cannot synthesize a button callback through
  the message router.
- No connector, automatic betting, launchd restoration, or real Telegram dispatch is included
  in verification.
- A Telegram confirmation is an operator attestation that manual placement occurred. Its CAS
  receipt records callback identity, chat/message identity, ticket identity, and timestamp; it
  is not represented as a bookmaker receipt.
- Challenge nonces remain digest-only in SQLite. Plaintext exists only in the outbound button
  and the inbound callback.
- Production schema remains untouched during implementation. Migration 16 is verified only on
  temporary databases; production backup/application occurs only after merge approval.

## 3. Approaches considered

### A. Reuse M4 protected Actions and add a Telegram adapter (selected)

The adapter issues the existing challenge, renders an inline button, and maps an owner callback
back into `ConfirmTicketPlacement`. Timeout is a new deterministic non-placement Action because
the existing finance tables correctly model only placed tickets.

This keeps money conservation, idempotency, nonce binding, receipt CAS, and actor permissions in
their existing authoritative services.

### B. Let the bot write the legacy Zucai ledger directly

This is rejected. It would bypass the ontology Action log, duplicate booking behavior, and make
the JSON/file ledger a second funds path.

### C. Use a text command containing artifact ID and confirmation code

This avoids inline callback support but is rejected. It exposes more identifiers, is easy to
mistype, and lets normal message routing reach a protected operation. A Telegram callback is a
separate update type and gives a cleaner human-presence boundary.

## 4. Callback protocol

Telegram limits `callback_data` to 64 bytes. A `token_urlsafe(32)` nonce is about 43 ASCII
characters, so the protocol is:

```text
ntc:<plaintext nonce>
```

The callback carries no actor, artifact ID, amount, channel, or ticket hash. The handler hashes
the nonce and resolves the durable `ConfirmationChallenge` by `nonce_hash`. All business binding
comes back from the challenge and audited artifact.

`TelegramBotRunner` processes callback updates before normal messages. It obtains the chat ID
from `callback_query.message.chat.id`, enforces the existing owner allowlist, and delegates only
`ntc:` payloads to a dedicated `TelegramTicketConfirmationService`. Other callback types are
ignored. Normal text still goes exclusively through `BotAdapter`.

Successful and failed callbacks call Telegram `answerCallbackQuery`; a success also sends a
plain confirmation message without the nonce. Duplicate delivery reuses the callback-query ID
as the `ConfirmTicketPlacement` idempotency key, replaying the same committed result without a
second debit.

## 5. Outbound confirmation

A new `nutmeg ticket-confirmation request` CLI takes:

```text
--data-dir
--ticket-artifact-id
--chat-id (optional only when exactly one configured owner exists)
--dry-run/--no-dry-run (default dry-run)
```

It builds a healthy current kernel, issues a challenge as server-assigned `judge_operator`, and
renders from the stored artifact:

- channel and ticket identity;
- exact selections from the immutable payload;
- exact amount and currency;
- deadline;
- audit ERROR/WARN counts;
- ticket hash;
- one `confirmed placed` button.

Dry-run still issues the challenge into the explicitly selected data root so the complete
callback path can be tested, but it does not call Telegram. It prints canonical JSON containing
the redacted message preview, callback byte length, confirmation ID, expiry, and dispatch state.
It never prints the nonce or callback data. Tests receive the internal prepared message object
directly and use a fake client to exercise the callback.

Non-dry-run sends only to an allowlisted chat. A send failure leaves an unused challenge and
returns nonzero. Rerunning creates a fresh challenge and button; no funds state has changed.

## 6. Shadow/non-placement object

Migration 16 adds:

```text
ticket_shadow_records
  ticket_shadow_id TEXT PRIMARY KEY
  ticket_artifact_id TEXT NOT NULL UNIQUE FK audited_ticket_artifacts RESTRICT
  confirmation_id TEXT NOT NULL FK ticket_confirmation_challenges RESTRICT
  reason TEXT NOT NULL
  deadline_at TEXT NOT NULL
  marked_at TEXT NOT NULL
  action_id TEXT NOT NULL UNIQUE FK actions RESTRICT
```

`MarkTicketShadow` is allowed only to `deterministic_system`. Its handler requires:

- the artifact and confirmation exist and are bound;
- the artifact deadline is at or before `requested_at`;
- no placement exists;
- no prior shadow record exists.

The Action writes one row and returns `ticket_shadow`. It never consumes a fresh challenge,
because expiry and deadline evidence remain independently inspectable; placement is already
blocked by the passed artifact deadline.

The repository query for due shadow candidates selects only artifacts that have at least one
issued challenge, have passed deadline, and have neither placement nor shadow. This prevents
unoffered approved artifacts from being silently classified.

The Telegram polling daemon receives an optional maintenance callback. After every successful
poll, including a poll with no updates, it invokes `expire_due(now)`. The callback uses the
system clock injected by wiring and records each due shadow with an idempotency key derived from
artifact ID and deadline. No scheduler or launchd file changes are required.

## 7. Telegram API changes

`TelegramBotClient.send_message` gains an optional JSON `reply_markup`; existing callers send
the same body when it is absent. Add `answer_callback_query(callback_query_id, text)`.

`TelegramPollSummary` and daemon summary add `callbacks_handled` and `shadows_marked` counters.
These are deterministic operational counts, not business judgments.

The confirmation service is wired only when the ontology is initialized/current and an owner
allowlist exists. Configuration errors fail the protected callback closed while ordinary bot
messages remain available.

## 8. Night-calibration delivery

`zucai-night-calibrate` adds:

```text
--dispatch-telegram
--dry-run/--no-dry-run
```

Without `--dispatch-telegram`, behavior and stdout remain unchanged. With it, the CLI publishes
a `NotificationRequest.text` whose dedupe dimensions are issue, night date, and SHA-256 of the
report. `--dry-run` uses `NotificationService.publish(..., dry_run=True)` and performs no network
or notification persistence. `--no-dry-run` is a real external dispatch and remains an explicit
operator action.

No report parser, outcome interpretation, rx write, or scoreboard write is added.

## 9. Failure and recovery

- Unauthorized callbacks are denied and never reach the protected service.
- Unknown, malformed, expired, consumed, mismatched, or deadline-passed callbacks write no
  Ticket/CashTransaction.
- A callback retry with the same Telegram callback ID replays the committed placement.
- A second callback ID after placement is rejected without another debit.
- Telegram send failure leaves only a challenge; rerun issues a new one.
- Process restart is supported because challenge binding and shadow candidates are durable.
- Timeout maintenance is idempotent and restart-safe.
- Notification delivery uses the existing retry/dedupe ledger; confirmation messages do not put
  plaintext nonces into that ledger.

## 10. Verification

All tests use temporary ontology/state roots and fake Telegram clients.

The end-to-end dry-run fixture will create and approve an audited artifact through M4, request a
Telegram confirmation, feed the resulting callback update through `TelegramBotRunner`, and
assert exactly one Ticket, placement, receipt, and negative stake transaction. A sibling artifact
advances past its deadline without callback; daemon maintenance records exactly one shadow and
keeps Ticket/CashTransaction counts unchanged.

A report-delivery test runs `zucai-night-calibrate --dispatch-telegram --dry-run` with injected
fixtures and asserts the exact deterministic report is the notification body with no network
call.

## 11. Explicit exclusions

- No automatic or connector betting.
- No AI `ConfirmDispatch` or protected Action permission.
- No production migration, production dispatch, launchd edit, scheduler edit, cutover, or soak.
- No change to ticket composition, audit arithmetic, probability judgment, or placement amount.
- No direct mutation of `.nutmeg-data/scoreboard.json` or rx files.
