# Nutmeg Intelligence OS M4 Operations Contract

Date: 2026-08-24
Scope: local Ticket and Adjudication Workbench only

## 1. Authority boundary

M4 is a private, single-operator workflow. Start it only on a loopback address:

```bash
UV_FROZEN=1 uv run nutmeg app --host 127.0.0.1 --port 8788
```

Open `http://127.0.0.1:8788/tickets`. Binding a public interface does not turn M4
into a multi-user or remote-authority service. M4 has no live betting connector,
provider dispatch, Telegram dispatch, scheduler, or funds-transfer authority.

The server owns actor identity, composition, C0-C7 audit, budget allocation, hashes,
deadlines, confirmation state, and ledger writes. Browser input is untrusted. AI may
propose analysis but cannot approve a batch, issue a confirmation, or confirm a
placement.

## 2. Two-stage operating flow

1. Select faces and enter explicit judgment facts in the workbench.
2. Create a draft. The server binds every leg to the current committed Forecast and
   quote, calls the authoritative composition and audit functions, writes an immutable
   batch revision, and stores its canonical bytes in CAS.
3. Resolve findings. An `ERROR` can only be removed by changing the slate. Every
   `WARN` needs a human `accept_warning` Adjudication with a reason and an explicit
   `evidence_rejected` list; adjudications do not carry to a superseding revision.
4. Approve the current revision. Approval creates one immutable audited artifact per
   composed ticket. It creates no formal Ticket and no stake debit.
5. On the separate confirmation surface, issue a fresh five-minute confirmation for
   one audited artifact. Compare the displayed hash, amount, currency, channel, and
   deadline with the intended manual placement.
6. After the operator has placed the ticket manually, attach a non-empty receipt,
   enter the external reference, and confirm once. Only this step atomically creates
   the formal Ticket, BetLegs, one negative stake CashTransaction, TicketPlacement,
   receipt artifact/retrieval, and challenge consumption.

The operational invariant is literal: no formal ledger entry means Nutmeg has not
recorded the ticket as placed.

## 3. Hashes, receipts, and empty slates

The approved ticket hash is SHA-256 over the exact canonical audited-ticket bytes in
CAS. A changed leg, Forecast, quote, audit fact, amount, deadline, or Adjudication set
requires a different approved artifact. Never edit a hash, stored payload, SQLite row,
or CAS file to make a confirmation pass.

Manual receipt bytes are stored in CAS. Actions and outbox events contain only receipt
hash, size, content type, and object references. The plaintext confirmation nonce is
returned once and only its SHA-256 digest is durable.

An empty slate is a valid explicit decision. Remove the final leg and approve the
empty revision. It creates no audited ticket artifact, confirmation, formal Ticket,
or CashTransaction.

## 4. Failure and recovery

| Condition | Required response |
| --- | --- |
| `ticket_audit_blocked` | Change the slate. `ERROR` has no override path. |
| `ticket_warning_unadjudicated` | Record the named WARN Adjudication, then approve the same current revision. |
| `ticket_revision_conflict` | Reload history and act on the current revision number. |
| Lost or expired nonce | Issue a new confirmation with a new idempotency key. Do not recover plaintext from storage. |
| Process restart after issue | Reuse the still-fresh nonce held by the operator; the digest and binding survive restart. |
| Response lost after confirm | Replay the exact request with the same idempotency key. A different key must not create a second debit. |
| `confirmation_binding_mismatch` | Stop and compare artifact ID, hash, amount, currency, and channel. Never edit persisted state. |
| `confirmation_stale` | Rebuild and reapprove against the current Forecast. |
| `ticket_deadline_passed` | Do not place or backdate. Create a new valid decision if the market remains available. |
| `ticket_already_placed` or `confirmation_reused` | Inspect the artifact and Action history; do not retry with a new key. |
| `connector_unavailable` | Expected in M4. Use the documented manual flow or stop. |

An interrupted database transaction rolls back Ticket, BetLeg, debit, placement,
receipt metadata, and challenge consumption together. A CAS blob written before that
rollback is content-addressed and harmless; do not delete it during incident response.

## 5. Backup and restore inputs

Stop the app before a filesystem backup. Treat these paths as one recovery unit:

```text
${NUTMEG_DATA_DIR:-.nutmeg-data}/ontology/ontology.db
${NUTMEG_DATA_DIR:-.nutmeg-data}/ontology/artifacts/
```

Also retain the application version and configuration that produced the database.
The SQLite database without CAS loses immutable decision and receipt bytes; CAS
without SQLite loses object identity, Action, ledger, and lineage. Restore into an
isolated data directory first, run the ontology health gate, and inspect counts before
opening the product. Never test a restore against the production data directory.

## 6. Audit surfaces

Prefer versioned, read-only interfaces:

```bash
curl -s http://127.0.0.1:8788/api/v1/system/health
curl -s http://127.0.0.1:8788/api/v1/ticket-batches/TICKET_BATCH_ID
curl -s http://127.0.0.1:8788/api/v1/ticket-artifacts/TICKET_ARTIFACT_ID
curl -s http://127.0.0.1:8788/api/v1/lineage/audited_ticket_artifact/TICKET_ARTIFACT_ID
curl -s 'http://127.0.0.1:8788/api/v1/actions?limit=1000'
curl -s 'http://127.0.0.1:8788/api/v1/events?after=0&limit=1000'
UV_FROZEN=1 uv run nutmeg ontology status
```

For a placed artifact, verify the approved revision and CAS source, confirmation is
consumed, placement references exactly one formal Ticket, ticket lineage references
the committed Forecast revisions, and the ledger contains exactly one negative stake
transaction. The nonce and receipt base64 must not appear in Action or event output.

## 7. Compatibility and prohibitions

`decision-close` and the legacy `ExpressService` retain their immediate-booking
behavior during M4 so existing close/settle workflows remain callable. They are a
tested compatibility path, not the protected workbench's two-stage authority. Do not
mix the two paths for the same intended ticket. Retirement or authority cutover is an
M6 decision.

During M4, never:

- enable or simulate a live connector through browser input;
- call a provider, Telegram, scheduler, or funds endpoint as part of confirmation;
- interpret approval as proof of external placement;
- edit SQLite or CAS directly, delete challenges, or manufacture receipts;
- reuse a nonce, change a confirmation payload under the same idempotency key, or
  backdate a deadline;
- run tests or replays against the production data directory.
