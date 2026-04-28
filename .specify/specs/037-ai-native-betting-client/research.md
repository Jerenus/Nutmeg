# Research: AI-Native Betting Client

## Decision: Build a server-rendered PWA-style client inside the Python monolith

**Rationale**: Nutmeg is currently Python-first with CLI and bot surfaces. A server-rendered PWA avoids introducing a Node build pipeline while still supporting desktop and mobile-width browsers, subscription screens, source ledgers, and responsive match workspaces.

**Alternatives considered**:
- Separate SPA frontend: more flexible visual tooling, but premature complexity for a private-beta product.
- Native mobile app: stronger mobile push experience, but app distribution and payment complexity come too early.
- Telegram-only expansion: fastest from current OpenClaw setup, but too constrained for a subscription client.

## Decision: Keep existing Nutmeg services as the source of truth

**Rationale**: The repository already provides daily-run, popular matches, value board, match brief, odds snapshots, player profile, tactical visuals, prediction review, and provider health. The client should aggregate these outputs rather than duplicate football models or odds-pricing logic.

**Alternatives considered**:
- Client-side model logic: rejected because it would drift from deterministic Nutmeg outputs.
- New web-only analysis service: rejected because it would bypass tested CLI/service boundaries.

## Decision: Add CLI parity for every new client aggregation

**Rationale**: The constitution requires CLI-first, bot-ready workflows. New client payloads should be callable as JSON commands before or alongside web routes so tests, OpenClaw, and future bots can reuse the same logic.

**Alternatives considered**:
- Web-only routes: rejected as a constitution violation.
- Existing commands only: insufficient because the client needs subscription-aware, freshness-aware aggregation payloads.

## Decision: Store user/client state in SQLite and keep objective football facts shared

**Rationale**: Existing architecture splits shared facts from mutable state. Watchlists, entitlements, preferences, alerts, conversational sessions, and audit records are user-specific. Fixture, odds, value, tactical, and player facts remain shared and reusable.

**Alternatives considered**:
- Store all client state in DuckDB: rejected because mutable per-user behavior should stay isolated from analytical shared facts.
- Introduce PostgreSQL now: rejected until real multi-user usage justifies migration.

## Decision: Implement grounded follow-up as deterministic-first answering

**Rationale**: Betting-analysis support needs truthfulness. The first slice should build answers from available match workspace evidence, refuse unsupported requests, and let deterministic verdicts override generated language. Optional LLM synthesis can be layered later behind existing guarded provider seams.

**Alternatives considered**:
- Free-form LLM chat: rejected because it can overstate weak evidence.
- No conversation: rejected because AI-native follow-up is part of the product value.

## Decision: Treat news/information as a source-ledger capability with truthful absence

**Rationale**: The current project does not have a full news provider. The client still needs places to display source-attributed information, but first-release behavior must label news unavailable when no verified source exists.

**Alternatives considered**:
- Add a live news provider immediately: rejected as too broad for the client foundation slice.
- Hide news entirely: rejected because the spec requires latest information readiness and future provider integration.

## Decision: Entitlement gates exist before public billing

**Rationale**: Subscription readiness requires plan state and gated premium sections, but Phase 1 can use local seeded entitlements without a payment provider. This keeps account boundaries testable before monetization.

**Alternatives considered**:
- Add Stripe/payment now: rejected as premature.
- Ignore entitlements until SaaS: rejected because it risks later rewrite and user-state leakage.

## Decision: Responsible-use constraints are product requirements, not copy polish

**Rationale**: The product is betting-analysis assistance. It must avoid bet execution, guaranteed-profit claims, dark patterns, and alert spam from the first client surface.

**Alternatives considered**:
- Add disclaimers only at the footer: rejected because the constraints must affect actionability, alerts, and answer behavior.
