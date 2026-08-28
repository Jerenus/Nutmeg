# Telegram Confirmation Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Close B9 confirmation on Telegram by reusing M4 protected ticket Actions, atomically writing the ledger only after an owner callback, recording deadline non-placement as shadow, and optionally delivering night-calibration reports.

**Architecture:** Migration 16 adds one immutable ticket-shadow object and deterministic Action. A focused `TelegramTicketConfirmationService` issues existing challenges, renders nonce-only inline callbacks, consumes owner callbacks through existing `ConfirmTicketPlacement`, and expires due offered artifacts. Telegram polling remains the transport loop; all money, nonce, artifact, and permission invariants stay in the ontology kernel.

**Tech Stack:** Python 3.12, SQLAlchemy Core/SQLite, Typer, httpx Telegram API, existing notification ledger, pytest.

---

## File structure

- Modify `nutmeg/ontology/repository/schema_tickets.py`: `ticket_shadow_records` table.
- Modify `nutmeg/ontology/repository/tickets.py`: shadow model CRUD, nonce lookup, due query.
- Modify `nutmeg/ontology/repository/migrations.py`: guarded migration 16 and deterministic permission.
- Modify `nutmeg/ontology/actions/protected_ticket_actions.py`: `MarkTicketShadow` typed Action.
- Create `nutmeg/services/telegram_ticket_confirmation.py`: protected orchestration and message rendering.
- Modify `nutmeg/interfaces/bot/telegram.py`: inline keyboard, callback answers, callback routing and counters.
- Modify `nutmeg/interfaces/cli/__init__.py`: current-kernel confirmation-service wiring.
- Create `nutmeg/interfaces/cli/ticket_confirmation.py`: owner request/preview command.
- Modify `nutmeg/interfaces/cli/decision.py`: optional night-report notification.
- Modify `nutmeg/interfaces/cli/__init__.py`: register ticket-confirmation CLI module.
- Modify `docs/sop/RUNBOOK.md`: B9 confirmation command and B9b optional report delivery.
- Add focused ontology, service, bot, CLI, decision, and E2E tests listed below.

No scheduler, launchd, connector, probability, composition, audit arithmetic, production data, rx,
or scoreboard JSON file is modified.

### Task 1: Migration 16 ticket shadow persistence

**Files:**
- Modify: `nutmeg/ontology/repository/schema_tickets.py`
- Modify: `nutmeg/ontology/repository/tickets.py`
- Modify: `nutmeg/ontology/repository/migrations.py`
- Test: `tests/ontology/test_ticket_shadow_migration.py`

- [x] **Step 1: Write failing migration and repository tests**

Test a fresh database and a v15-upgrade fixture. Assert migration 16 is idempotent, creates
`ticket_shadow_records`, and grants only `deterministic_system` the `mark_ticket_shadow`
permission. Add repository roundtrip assertions for:

```python
TicketShadowRow(
    ticket_shadow_id="tsh-1",
    ticket_artifact_id="tat-1",
    confirmation_id="tc-1",
    reason="deadline_unconfirmed",
    deadline_at=DEADLINE.isoformat(),
    marked_at=AFTER_DEADLINE.isoformat(),
    action_id="ACT-shadow",
)
```

The test must seed the referenced artifact, confirmation, and Action using the existing M4
helpers before inserting the row.

- [x] **Step 2: Verify RED**

Run:

```bash
UV_FROZEN=1 uv run pytest tests/ontology/test_ticket_shadow_migration.py -v
```

Expected: import/table failures because `TicketShadowRow` and migration 16 do not exist.

- [x] **Step 3: Add schema, row model, repository methods, and migration**

Add this table:

```python
ticket_shadow_records = Table(
    "ticket_shadow_records",
    metadata,
    Column("ticket_shadow_id", Text, primary_key=True),
    Column(
        "ticket_artifact_id",
        Text,
        ForeignKey("audited_ticket_artifacts.ticket_artifact_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column(
        "confirmation_id",
        Text,
        ForeignKey("ticket_confirmation_challenges.confirmation_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("reason", Text, nullable=False),
    Column("deadline_at", Text, nullable=False),
    Column("marked_at", Text, nullable=False),
    Column(
        "action_id",
        Text,
        ForeignKey("actions.action_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
)
```

Add the frozen repository row and methods:

```python
@dataclass(frozen=True, slots=True)
class TicketShadowRow:
    ticket_shadow_id: str
    ticket_artifact_id: str
    confirmation_id: str
    reason: str
    deadline_at: str
    marked_at: str
    action_id: str


def insert_shadow(self, row: TicketShadowRow) -> None:
    self._connection.execute(insert(st.ticket_shadow_records).values(**asdict(row)))


def shadow_for_artifact(self, artifact_id: str) -> TicketShadowRow | None:
    row = self._connection.execute(
        select(st.ticket_shadow_records).where(
            st.ticket_shadow_records.c.ticket_artifact_id == artifact_id
        )
    ).mappings().first()
    return None if row is None else TicketShadowRow(**dict(row))


def confirmation_by_nonce_hash(self, nonce_hash: str) -> ConfirmationChallengeRow | None:
    row = self._connection.execute(
        select(st.ticket_confirmation_challenges).where(
            st.ticket_confirmation_challenges.c.nonce_hash == nonce_hash
        )
    ).mappings().first()
    return None if row is None else ConfirmationChallengeRow(**dict(row))
```

Migration 16 creates only the new table and inserts:

```python
("mark_ticket_shadow", "deterministic_system")
```

Guard the permission insert with an existence query so the migration is idempotent on both
upgraded and freshly created databases.

- [x] **Step 4: Verify GREEN and commit**

```bash
UV_FROZEN=1 uv run pytest \
  tests/ontology/test_ticket_shadow_migration.py \
  tests/ontology/test_m4_ticket_migration.py tests/migration/ -q
git add nutmeg/ontology/repository/schema_tickets.py \
  nutmeg/ontology/repository/tickets.py nutmeg/ontology/repository/migrations.py \
  tests/ontology/test_ticket_shadow_migration.py
UV_FROZEN=1 git commit -m "feat(ontology): add deterministic ticket shadow records"
```

### Task 2: Typed deadline shadow Action and due query

**Files:**
- Modify: `nutmeg/ontology/actions/protected_ticket_actions.py`
- Modify: `nutmeg/ontology/repository/tickets.py`
- Test: `tests/ontology/test_ticket_shadow_actions.py`

- [x] **Step 1: Write failing Action tests**

Use the existing protected-ticket setup to create and approve two artifacts and issue a
confirmation for each. Assert:

- before deadline, `mark_ticket_shadow` raises `deadline has not passed`;
- after deadline, `deterministic_system` commits one `ticket_shadow` and creates no formal
  Ticket or CashTransaction;
- `judge_operator` and `ai_analyst` are denied;
- a placed artifact cannot be shadowed;
- repeating with the same idempotency key replays, while a different key finds the existing
  shadow and does not duplicate;
- `due_shadow_candidates(as_of)` includes only challenged, deadline-passed artifacts without
  placement/shadow.

- [x] **Step 2: Verify RED**

```bash
UV_FROZEN=1 uv run pytest tests/ontology/test_ticket_shadow_actions.py -v
```

Expected: import failures for `MarkTicketShadowRequest` and missing due query.

- [x] **Step 3: Implement the request and Action**

```python
@dataclass(frozen=True, slots=True)
class MarkTicketShadowRequest:
    ticket_artifact_id: str
    confirmation_id: str
    reason: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.requested_at, "requested_at")
        if self.reason != "deadline_unconfirmed":
            raise ValueError("ticket shadow reason must be deadline_unconfirmed")
```

The handler loads artifact and confirmation, verifies binding, rejects placement/prior shadow,
requires `deadline_at <= requested_at`, inserts `TicketShadowRow`, and returns
`ObjectRef("ticket_shadow", ticket_shadow_id)`.

Add repository query:

```python
def due_shadow_candidates(self, as_of: str) -> list[tuple[str, str]]:
    rows = self._connection.execute(
        select(
            st.audited_ticket_artifacts.c.ticket_artifact_id,
            func.max(st.ticket_confirmation_challenges.c.confirmation_id),
        )
        .join(
            st.ticket_confirmation_challenges,
            st.ticket_confirmation_challenges.c.ticket_artifact_id
            == st.audited_ticket_artifacts.c.ticket_artifact_id,
        )
        .outerjoin(
            st.ticket_placements,
            st.ticket_placements.c.ticket_artifact_id
            == st.audited_ticket_artifacts.c.ticket_artifact_id,
        )
        .outerjoin(
            st.ticket_shadow_records,
            st.ticket_shadow_records.c.ticket_artifact_id
            == st.audited_ticket_artifacts.c.ticket_artifact_id,
        )
        .where(
            st.audited_ticket_artifacts.c.deadline_at <= as_of,
            st.ticket_placements.c.ticket_placement_id.is_(None),
            st.ticket_shadow_records.c.ticket_shadow_id.is_(None),
        )
        .group_by(st.audited_ticket_artifacts.c.ticket_artifact_id)
        .order_by(st.audited_ticket_artifacts.c.ticket_artifact_id)
    ).all()
    return [(str(row[0]), str(row[1])) for row in rows]
```

- [x] **Step 4: Verify GREEN and commit**

```bash
UV_FROZEN=1 uv run pytest tests/ontology/test_ticket_shadow_actions.py \
  tests/ontology/test_ticket_confirmation.py -q
git add nutmeg/ontology/actions/protected_ticket_actions.py \
  nutmeg/ontology/repository/tickets.py tests/ontology/test_ticket_shadow_actions.py
UV_FROZEN=1 git commit -m "feat(tickets): record deadline-unconfirmed shadow"
```

### Task 3: Telegram inline callback transport

**Files:**
- Modify: `nutmeg/interfaces/bot/telegram.py`
- Test: `tests/test_telegram_bot.py`

- [x] **Step 1: Write failing client and runner tests**

Add tests proving:

```python
client.send_message(
    chat_id=42,
    text="confirm",
    reply_markup={"inline_keyboard": [[{"text": "confirmed placed", "callback_data": "ntc:x"}]]},
)
```

sends exact `reply_markup`, while existing calls omit the key. Test
`answer_callback_query(callback_query_id="cb-1", text="recorded")` calls
`answerCallbackQuery` without exposing the bot token in body/log data.

Add a fake confirmation handler with `handle_callback` and `expire_due`. Feed one allowlisted
callback update and assert it never calls `BotAdapter.handle_message`, increments
`callbacks_handled`, and invokes maintenance even on an empty poll. Unauthorized callbacks are
denied and never delegated.

- [x] **Step 2: Verify RED**

```bash
UV_FROZEN=1 uv run pytest tests/test_telegram_bot.py -v -k "callback or reply_markup"
```

Expected: unexpected keyword/missing method and callback ignored failures.

- [x] **Step 3: Implement transport and optional handler protocol**

Change `send_message` to include `reply_markup` only when non-`None`; add
`answer_callback_query`. Extend `TelegramPollSummary` with defaulted integer fields
`callbacks_handled=0` and `shadows_marked=0`.

`TelegramBotRunner` accepts `confirmation_handler=None`. For a callback update it resolves chat
ID, applies the same allowlist, delegates only string data beginning `ntc:`, and calls
`client.answer_callback_query`. After updates, call `confirmation_handler.expire_due()` and put
the returned count in the summary. Ordinary message behavior remains byte-for-byte compatible.

Extend daemon aggregation and payload with the two counters.

- [x] **Step 4: Verify GREEN and commit**

```bash
UV_FROZEN=1 uv run pytest tests/test_telegram_bot.py -q
git add nutmeg/interfaces/bot/telegram.py tests/test_telegram_bot.py
UV_FROZEN=1 git commit -m "feat(telegram): route owner confirmation callbacks"
```

### Task 4: Protected Telegram confirmation service

**Files:**
- Create: `nutmeg/services/telegram_ticket_confirmation.py`
- Test: `tests/test_telegram_ticket_confirmation.py`

- [x] **Step 1: Write failing service tests**

Use a temporary initialized kernel and existing M4 helpers. Test:

1. `request_confirmation(..., dry_run=True)` issues a durable challenge, renders exact stored
   amount/hash/deadline/selections, produces callback data matching `^ntc:[A-Za-z0-9_-]+$` and
   at most 64 bytes, makes no Telegram call, and exposes no nonce in `to_public_dict()`.
2. Non-dry-run sends one inline keyboard to an allowlisted chat.
3. `handle_callback` hashes the token, resolves the challenge, writes a canonical Telegram
   attestation receipt through existing `ConfirmTicketPlacement`, and leaves one Ticket, one
   placement, and one negative stake CashTransaction.
4. Receipt bytes and Action payload omit the plaintext nonce.
5. Duplicate callback ID replays without double debit; unknown token and unauthorized chat fail.
6. `expire_due(now)` commits one shadow per candidate and is idempotent.

- [x] **Step 2: Verify RED**

```bash
UV_FROZEN=1 uv run pytest tests/test_telegram_ticket_confirmation.py -v
```

Expected: module import failure.

- [x] **Step 3: Implement focused service and DTOs**

Create:

```python
@dataclass(frozen=True, slots=True, repr=False)
class PreparedConfirmation:
    ticket_artifact_id: str
    confirmation_id: str
    expires_at: str
    text: str
    reply_markup: dict[str, object]
    _callback_data: str

    @property
    def callback_data(self) -> str:
        return self._callback_data

    def to_public_dict(self) -> dict[str, object]:
        return {
            "ticket_artifact_id": self.ticket_artifact_id,
            "confirmation_id": self.confirmation_id,
            "expires_at": self.expires_at,
            "message_preview": self.text,
            "callback_bytes": len(self._callback_data.encode("ascii")),
        }
```

`TelegramTicketConfirmationService` receives `kernel`, `telegram_client`, `allowed_chat_ids`,
and `now_fn`. `request_confirmation` calls existing `issue_ticket_confirmation` as
`judge_operator`, reads the artifact, creates `ntc:<nonce>`, validates length, renders the
message, and optionally sends it.

`handle_callback` accepts the Telegram callback dict, verifies owner chat and prefix, resolves
the challenge by SHA-256, reads its artifact, builds canonical receipt bytes without callback
data, and calls existing `confirm_ticket_placement` with:

```python
actor_id=f"operator:telegram:{chat_id}"
actor_role=ActorRole.JUDGE_OPERATOR
idempotency_key=f"telegram:confirm:{callback_query_id}"
placement_mode="manual"
external_reference=f"telegram:{callback_query_id}"
```

`expire_due` opens one UoW for candidate IDs, then calls `mark_ticket_shadow` per candidate as
`system:telegram-confirmation` / `deterministic_system` with stable idempotency keys.

- [x] **Step 4: Verify GREEN and commit**

```bash
UV_FROZEN=1 uv run pytest tests/test_telegram_ticket_confirmation.py \
  tests/ontology/test_ticket_confirmation.py -q
git add nutmeg/services/telegram_ticket_confirmation.py \
  tests/test_telegram_ticket_confirmation.py
UV_FROZEN=1 git commit -m "feat(tickets): bridge Telegram to protected placement"
```

### Task 5: Wiring and `ticket-confirmation request` CLI

**Files:**
- Create: `nutmeg/interfaces/cli/ticket_confirmation.py`
- Modify: `nutmeg/interfaces/cli/__init__.py`
- Test: `tests/test_ticket_confirmation_cli.py`

- [x] **Step 1: Write failing CLI tests**

Monkeypatch a fake service and settings. Assert help exposes required data/artifact options and
defaults to dry-run. Assert dry-run outputs canonical JSON with no nonce/callback data and no
client call. Assert `--no-dry-run` rejects a chat outside the configured owner allowlist and
uses the sole owner when `--chat-id` is omitted. Uninitialized/pending-migration roots exit 1.

- [x] **Step 2: Verify RED**

```bash
UV_FROZEN=1 uv run pytest tests/test_ticket_confirmation_cli.py -v
```

Expected: missing `ticket-confirmation` command.

- [x] **Step 3: Implement wiring and CLI**

Register a Typer group:

```python
ticket_confirmation_app = _cli.typer.Typer(help="Protected owner ticket confirmation")
_cli.app.add_typer(ticket_confirmation_app, name="ticket-confirmation")
```

The `request` command validates an initialized/current kernel built from explicit `--data-dir`,
resolves the owner chat, builds `TelegramTicketConfirmationService`, uses an explicit aware
`--requested-at`, and prints `PreparedConfirmation.to_public_dict()` plus
`dispatch_state: dry_run|sent` in canonical JSON. Catch configuration/domain errors and exit 1.

Update `build_telegram_bot_runner` to create one client and, when the explicit data-root kernel
is current, inject the confirmation service. No handler is installed on an unhealthy kernel;
normal text routing remains available and protected callbacks answer with an unavailable error.

- [x] **Step 4: Verify GREEN and commit**

```bash
UV_FROZEN=1 uv run pytest tests/test_ticket_confirmation_cli.py \
  tests/test_telegram_bot.py -q
git add nutmeg/interfaces/cli/ticket_confirmation.py \
  nutmeg/interfaces/cli/__init__.py tests/test_ticket_confirmation_cli.py
UV_FROZEN=1 git commit -m "feat(cli): request protected ticket confirmation"
```

### Task 6: Night-calibration report delivery

**Files:**
- Modify: `nutmeg/interfaces/cli/decision.py`
- Test: `tests/decision/test_zucai_night.py`

- [x] **Step 1: Write failing CLI tests**

Patch `run_night_calibrate` to return a fixed report and patch the notification-service factory.
Assert:

- without `--dispatch-telegram`, publish is never called and stdout remains the report;
- with `--dispatch-telegram --dry-run`, publish receives `dry_run=True`, exact report body,
  issue/date dimensions, and SHA-256 semantic fingerprint;
- failed required delivery exits 1;
- no-dry-run is explicit and forwarded unchanged.

- [x] **Step 2: Verify RED**

```bash
UV_FROZEN=1 uv run pytest tests/decision/test_zucai_night.py -v -k telegram
```

Expected: missing option/publish assertions fail.

- [x] **Step 3: Implement notification adapter**

Add `--dispatch-telegram` and `--dry-run/--no-dry-run`. Build a
`NotificationRequest.text` with:

```python
kind="zucai.night-calibration"
business_key=issue
stage=date
semantic_fingerprint=hashlib.sha256(report.encode("utf-8")).hexdigest()
subject=f"{issue} 夜间校准 {date}"
text=report
```

Call the existing notification service only when dispatch is requested, echo its redacted
status, and exit 1 when a required delivery is unsuccessful.

- [x] **Step 4: Verify GREEN and commit**

```bash
UV_FROZEN=1 uv run pytest tests/decision/test_zucai_night.py \
  tests/test_notification_service.py tests/test_notification_telegram.py -q
git add nutmeg/interfaces/cli/decision.py tests/decision/test_zucai_night.py
UV_FROZEN=1 git commit -m "feat(decision): deliver night calibration through ledger"
```

### Task 7: Full dry-run confirmation and timeout E2E

**Files:**
- Create: `tests/ontology/test_telegram_confirmation_e2e.py`
- Modify: `docs/sop/RUNBOOK.md`

- [x] **Step 1: Write the isolated E2E test**

The test must:

1. create forecasts, account, quotes, clean legs, batch, approval, and two artifacts through
   existing M4 Actions;
2. request both confirmations in dry-run and capture prepared callbacks;
3. feed one callback update through `TelegramBotRunner` with a fake client;
4. assert one formal Ticket, placement, receipt artifact, and one negative stake transaction;
5. advance the injected clock past the sibling artifact deadline and poll an empty update list;
6. assert exactly one shadow, no second Ticket/CashTransaction, and summary counters
   `callbacks_handled=1`, `shadows_marked=1` across the two polls;
7. query Actions and prove `confirm_ticket_placement` actor role is `judge_operator`,
   `mark_ticket_shadow` is `deterministic_system`, and no AI role has either permission.

- [x] **Step 2: Verify the E2E test**

```bash
UV_FROZEN=1 uv run pytest tests/ontology/test_telegram_confirmation_e2e.py -v
```

Expected: pass with no network, production data, or dispatch.

- [x] **Step 3: Update RUNBOOK**

In B9, after audit/deployment approval, document:

```text
nutmeg ticket-confirmation request --ticket-artifact-id ... --data-dir ... --no-dry-run
```

State that only the Telegram owner button consumes the second stage; deadline-unconfirmed is
recorded as shadow and never enters the ledger. In B9b append optional
`--dispatch-telegram --no-dry-run` for the morning report. Do not change CONSTITUTION.

- [x] **Step 4: Commit E2E and SOP**

```bash
git add tests/ontology/test_telegram_confirmation_e2e.py docs/sop/RUNBOOK.md
UV_FROZEN=1 git commit -m "docs(sop): wire Telegram confirmation and night report"
```

### Task 8: Completion verification

- [x] **Step 1: Run focused and full checks**

```bash
UV_FROZEN=1 uv run ruff check .
UV_FROZEN=1 uv run pytest tests/ontology/ tests/product/ tests/decision/ \
  tests/test_telegram_bot.py tests/test_telegram_ticket_confirmation.py \
  tests/test_ticket_confirmation_cli.py tests/test_notification_service.py \
  tests/test_notification_telegram.py
UV_FROZEN=1 uv run pytest -q
UV_FROZEN=1 uv run python -m compileall -q nutmeg
UV_FROZEN=1 pre-commit run --all-files
git diff --check main...HEAD
git diff --check
```

Expected: all commands exit 0.

- [x] **Step 2: Smoke help and dry-run evidence**

```bash
UV_FROZEN=1 uv run nutmeg ticket-confirmation request --help
UV_FROZEN=1 uv run nutmeg zucai-night-calibrate --help
```

Archive the relevant test output showing:

```text
callback -> confirm_ticket_placement committed -> ledger delta = -artifact amount
deadline -> mark_ticket_shadow committed -> ledger delta = 0
night report -> notification status = dry_run
```

- [x] **Step 3: Audit branch scope**

```bash
git status --short
git log --oneline main..HEAD
git diff --stat main...HEAD
```

Expected: clean branch; only declared Package 2 files; no production data, scheduler, launchd,
cutover, or connector changes.

## Execution Record (2026-08-28)

- `uv run pytest tests/ontology/test_telegram_confirmation_e2e.py -v`: 1 passed.
  The dry-run chain records one owner callback as `confirm_ticket_placement`, one
  negative ledger transaction, and one deadline sibling as `mark_ticket_shadow`
  with zero ledger delta.
- Permission query: `confirm_ticket_placement -> judge_operator`;
  `mark_ticket_shadow -> deterministic_system`; neither Action grants an AI role.
- Night calibration notification tests preserve `dry_run` transport behavior.
- `uv run ruff check .`: All checks passed; `uv run pytest -q`: 1,417 tests
  collected, exit 0; compileall and `pre-commit run --all-files` also exited 0.
- No migration was applied to production, and no real Telegram dispatch occurred.

## Explicit exclusions

- Do not apply migration 16 to `.nutmeg-data` in this branch.
- Do not call Telegram with a real token or run any `--no-dry-run` verification.
- Do not modify `docs/nutmeg-scheduler-operations.md`,
  `scripts/openclaw/nutmeg_scheduler_ops.py`, or `tests/test_nutmeg_scheduler_ops.py`.
- Do not grant AI any approval, confirmation, placement, shadow, or funds permission.
- Do not implement automatic betting, connector placement, launchd restoration, scoreboard
  cutover, soak, or ReleaseApproval.
