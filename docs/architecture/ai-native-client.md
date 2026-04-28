# AI-Native Betting Client

The AI-native client is a browser/PWA-style application surface over existing Nutmeg analysis services. It must keep betting-analysis assistance grounded in deterministic Nutmeg outputs, visible freshness, source attribution, user-state isolation, and responsible-use constraints.

## Current Slice

Implemented scope for the first MVP slice:

- `nutmeg client-status --format json` exposes client health, entitlement, and responsible-use state.
- `nutmeg client-feed --league epl --days 3 --demo --format json` returns a ranked daily opportunity feed.
- `/client/api/status` returns the same status payload for the browser client.
- `/client/api/feed` returns daily match opportunity cards for application use.
- `/client` renders a Chinese-first responsive daily feed page.
- `/client/manifest.webmanifest` exposes the PWA manifest.
- `nutmeg client-match --fixture-id ... --format json` and `/client/api/matches/{fixture_id}` expose the match workspace.
- `nutmeg client-question --fixture-id ... --question ... --format json` and the question endpoint support grounded follow-up.
- `nutmeg client-watchlist`, `nutmeg client-alerts`, and `nutmeg client-prediction-record` provide CLI parity for saved matches, grouped alerts, and calibration records.
- `/client/api/watchlist`, `/client/api/alerts`, and `/client/api/predictions` expose the same state flows for the Web/PWA client.

## Daily Feed Rules

Daily feed cards combine existing Nutmeg fixture ranking and value-board outputs. The client does not price matches itself. When a value-board candidate exists, the card can become `value`; when odds/value evidence is unavailable, the card remains visible but downgrades to `watch` and shows a blocking freshness reason.

Live or near-kickoff matches are also downgraded to `watch` with `wait_for_late_data`, because late team news and suspended markets can make pre-match conclusions stale.

## Guardrails

- No client workflow places bets, connects to sportsbooks, automates wagering, or promises profit.
- The responsible-use copy is shown in betting-analysis contexts.
- Stale or missing evidence blocks confident value claims.
- User-specific state is stored outside shared objective football facts and remains keyed by `user_id`.

## Match Workspace Rules

The match workspace packages the deterministic Nutmeg judgment, value-board edge, market context, tactical/player context, source-attributed information digest, caveats, and a source ledger into one decision page. `nutmeg client-match --fixture-id ... --format json` and `/client/api/matches/{fixture_id}` expose the same payload.

The information panel is backed by `FixtureInformationService` when wired by the CLI builder. It shows the digest summary, latest timestamp/source count when available, item titles, source names, reliability labels, and warnings. Missing local source data renders as unavailable instead of implying there is no news. Rumor or unverified items remain labeled and do not increase actionability by themselves. `client-match` can also accept an explicit information source manifest and local cache controls so operator/client workflows reuse the same opt-in live information provider seam.

The workspace writes an audit record for the evidence visible at decision time. Audit snapshots are redacted before storage so secret-like keys such as API keys, tokens, passwords, and secrets are not persisted.

If market and tactical context conflict, the workspace downgrades actionability to `watch` and adds a `market/tactical conflict` caveat. Deterministic verdicts and caveats remain the source of truth.

## Grounded Follow-Up Rules

`nutmeg client-question --fixture-id ... --question ... --format json` and `/client/api/matches/{fixture_id}/questions` answer from the current match workspace evidence. The answer repeats the deterministic Nutmeg verdict and confidence instead of letting generated wording override the analysis.

Requests to place bets, connect wagering accounts, guarantee profit, or leave the football-analysis scope are refused with a clear reason. Conversation records are stored as user-scoped state so later audit/review can see what evidence supported an answer.

## Entitlement and User-State Isolation

Owner mode receives full local access without public billing. Non-owner users can be assigned local entitlements such as `basic`, `premium`, or `expired`. Premium match workspace sections are gated before rendering or serialization, so restricted users see an upgrade message without hidden value-edge or market facts.

Watchlists, alerts, audit records, conversations, and entitlements are stored by `user_id`. Shared football facts remain reusable, but user behavior and access state stay isolated.

## Alerts and Calibration Rules

Saved opportunities are stored as watchlist rows keyed by `user_id`, `target_type`, and `target_id`. Re-saving the same match updates alert preferences instead of creating duplicate rows.

Material alerts are intentionally narrow. Supported change types are odds, lineup, injury, fixture status, information, and value-edge changes. Alerts use `fixture_id:change_type` as the grouping key so repeated changes update the existing alert instead of spamming the user. The UI copy frames alerts as discipline and review prompts, not as urgent calls to bet.

Client prediction recording links a simulated pick to the analysis audit id that was visible when the user made the judgment. The integration writes through the existing prediction repository, preserving the eval/review loop as the calibration source of truth. When a user records a pick from the Web/PWA page, the copy says "模拟记录，不是下注" to keep the no-execution boundary explicit.
