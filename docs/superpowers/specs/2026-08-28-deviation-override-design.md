# Prescription Deviation And User Override Design

Date: 2026-08-28
Status: Approved by the engineering handoff and operator continuation instruction

## Goal

Make every ticket-versus-prescription deviation name a registered RULEBOOK rule, and
provide an explicit human-only audit override that records rejected ERROR findings as
typed Adjudications instead of relying on a handwritten bet note.

## Input Contract

The existing legs document may add:

```json
{
  "issue": "26111",
  "prescription": {"1": "31", "2": "31"},
  "deviation_registry": [
    {
      "match_no": 1,
      "rule_ids": ["m-单选"],
      "reason": "Operator knowingly selects the single face.",
      "user_override": true
    }
  ],
  "legs": {"1": {"faces": "3"}}
}
```

The audit derives diffs from `prescription` and `legs`; it never trusts a declared
diff. A changed, added, or removed match without at least one known RULEBOOK ID emits
WARN `unnamed_prescription_deviation`. Historical documents without `prescription`
remain unchanged.

## Override Semantics

Default audit behavior is unchanged: any ERROR exits 1. `--user-override` is an
explicit operator attestation. Each ERROR match must have a registry entry with a
known rule ID, nonblank reason, and `user_override=true`. Missing registration keeps
the audit blocked.

ERROR findings remain visible and unchanged in output. The command groups all ERRORs
for one match into one `record_adjudication` Action so C1+C4+C5 on one naked leg counts
as one operator intervention. Each Action uses:

- actor role `judge_operator`, assigned by the CLI;
- subject type `ticket_audit_finding` and a deterministic subject ID;
- decision `override`;
- one rejected-evidence reference per original ERROR;
- alternative payload containing issue, match number, ticket/prescription faces,
  rule IDs, reason, and full findings;
- deterministic idempotency material, making retries exactly-once.

Only after every Action commits or resolves as an idempotent hit does the explicit
override path exit 0. AI roles and unattended flows receive no new permission, and
the command never dispatches a ticket.

## Scoreboard Registration

An override of a single-face leg is tagged `user_naked_wheels` in the structured
alternative. The intervention projector deterministically emits the registered-count
denominator from these Adjudications. It does not invent a win/loss numerator before
an authoritative result and match/issue identity link exist.

## Alternatives Rejected

- One Adjudication per ERROR overcounts legs with multiple audit codes.
- One Adjudication per whole ticket loses the per-leg `user_naked_wheels` unit.
- Turning ERROR into WARN mutates the original evidence and weakens default/AI gates.

## Explicit Exclusions

- automatic dispatch or betting;
- AI or deterministic-system override authority;
- natural-language rule inference;
- outcome grading without authoritative identity/result links;
- production database migration or direct `scoreboard.json` writes.
