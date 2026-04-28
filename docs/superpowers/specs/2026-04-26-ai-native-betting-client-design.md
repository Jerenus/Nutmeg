# AI-Native Betting Client Design

Date: 2026-04-26  
Related Spec: `../../../.specify/specs/037-ai-native-betting-client/spec.md`

## Decision

Build the next Nutmeg product slice as a browser/PWA-style AI-native client for betting-analysis assistance. The client is subscription-ready but owner/private-beta friendly. It must make the latest match, market, player, tactical, and information context understandable as a decision workflow rather than as a raw dashboard.

## Context

Nutmeg already has a usable CLI and OpenClaw Telegram loop: fixture sync, odds snapshots, fair probability, market intelligence, value board, match brief, popular matches, player profile, tactical visuals, eval/review, daily-run, and safe Telegram routing are complete. The client should not duplicate this logic. It should turn those outputs into an application surface with account state, entitlement gates, watchlists, alerts, AI-native follow-up, freshness, and responsible-use constraints.

## Product Principle

Betting-analysis assistance is the first principle. Every primary screen should answer one of four questions:

1. Which matches deserve attention now?
2. Why is this market interesting or dangerous?
3. What changed since the last look?
4. What should be reviewed after the result?

The client must never place bets, connect sportsbooks, promise profit, or hide uncertainty.

## Approaches Considered

### Recommended: Web/PWA subscription client first

This gives the cleanest path to accounts, subscriptions, responsive UI, analysis workspaces, alerts, and future paid access while preserving the current Nutmeg engine. It can later be packaged for mobile if usage proves it.

### Native mobile app first

This would make push notifications feel natural, but it introduces app-store distribution, payment, and platform complexity before the product workflow is validated.

### Telegram-plus-light-web hybrid

This is fastest from the current OpenClaw setup, but it is too constrained for a future subscription product and would make complex match workspaces awkward.

## Core Experience

- Daily feed: ranked match cards with verdict class, confidence, edge/value state, latest-data status, and suggested next action.
- Match workspace: four-part judgment, value-board comparison, market movement, tactical context, player availability, information/news, caveats, and source ledger.
- Conversational analyst: grounded follow-up questions tied to match evidence, with refusal when data is missing or stale.
- Watchlists and alerts: material changes in odds, lineups, injuries, news, fixture status, and value edge.
- Prediction review: record simulated picks or judgments, attach outcomes, and inspect calibration.
- Subscription readiness: account, entitlement, premium gates, isolated user state, and owner-only fallback.

## Data Flow

The client consumes Nutmeg's existing analytical outputs as authoritative facts. Generated text may summarize, prioritize, and answer follow-ups, but deterministic verdicts, probabilities, caveats, and freshness metadata must win when there is disagreement. Every externally derived claim needs source and timestamp context.

## Reliability Process

Development should continue through Spec Kit and Superpowers:

1. Create and validate the feature specification.
2. Generate plan/tasks from the spec.
3. Run the Superpowers task coverage review before implementation.
4. Implement with TDD and no client-side duplication of model logic.
5. Run verification-before-completion with acceptance evidence before marking complete.

## Key Risks

- Data freshness can be confused with live truth unless the UI makes timestamps unavoidable.
- AI prose can overstate weak evidence unless deterministic analysis constrains it.
- Subscription UX can leak premium facts through previews unless entitlement boundaries are tested.
- Alerting can encourage impulsive behavior unless alerts are grouped and framed as evidence changes.
