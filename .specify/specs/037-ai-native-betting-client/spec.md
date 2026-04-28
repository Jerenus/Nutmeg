# Feature Specification: AI-Native Betting Client

**Feature Branch**: `037-ai-native-betting-client`  
**Created**: 2026-04-26  
**Status**: Verified (2026-04-26)  
**Input**: User requested an AI-native software application client for Nutmeg, designed around betting-analysis assistance as the first principle, able to analyze the latest matches with the latest available data and information, and suitable for future subscription-mode use.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Triage today's betting opportunities (Priority: P1)

As an operator or future subscriber, I want to open the client and immediately see which upcoming or in-progress matches deserve betting-analysis attention, so I can focus on the strongest opportunities instead of manually running many commands.

**Why this priority**: This is the primary daily-use loop and the clearest subscription value: turn live fixture, market, and context data into a ranked decision queue.

**Independent Test**: With seeded fixtures, odds, value-board outputs, and match-brief outputs, a user can open the daily view and identify the top ranked matches, the reason each match is interesting, and which inputs are missing or stale without leaving the client.

**Acceptance Scenarios**:

1. **Given** current fixture, odds, and analysis data are available, **When** the user opens the daily view, **Then** the client shows ranked match cards with kickoff, league, verdict class, confidence, value/edge status, freshness, and suggested next action.
2. **Given** a match lacks odds, lineup, player, news, or tactical inputs, **When** it appears in the daily view, **Then** the card remains visible but clearly labels unavailable sections and avoids presenting a false value call.
3. **Given** a fixture is live or close to kickoff, **When** the daily view ranks opportunities, **Then** the client highlights live-status and late-data risk before showing any betting-analysis conclusion.

---

### User Story 2 - Inspect one match as an AI-native analysis workspace (Priority: P1)

As a user, I want a match detail page that combines market, tactical, player, news, and model-vs-market evidence into one explainable analysis, so I can understand why Nutmeg leans toward value, watch, avoid, or no-bet.

**Why this priority**: A subscription client cannot be just a dashboard; it must turn existing Nutmeg intelligence into a decision workspace with traceable reasons and counterarguments.

**Independent Test**: Select one seeded fixture and verify the match workspace displays Nutmeg's verdict, confidence, model-vs-market edge, market movement, tactical context, player availability, news/information summary, caveats, and source/freshness ledger.

**Acceptance Scenarios**:

1. **Given** a match has a generated brief and value-board candidate, **When** the user opens the match workspace, **Then** the client presents the core judgment, reasons, counterargument, confidence, and risk caveats before secondary detail panels.
2. **Given** market evidence conflicts with tactical or team evidence, **When** the user opens the match workspace, **Then** the client displays the conflict and lowers or qualifies the actionability class rather than hiding the disagreement.
3. **Given** the latest information includes injuries, lineup changes, or relevant news, **When** the user reads the match workspace, **Then** the client attributes each claim to a source and timestamp.

---

### User Story 3 - Ask grounded follow-up questions (Priority: P1)

As a user, I want to ask natural-language follow-ups such as "is the Asian handicap still playable?" or "what changed since this morning?" and receive a grounded answer, so the client feels like an analyst rather than a static report.

**Why this priority**: AI-native value comes from conversation over structured evidence, but betting assistance requires strict grounding and refusal when evidence is insufficient.

**Independent Test**: Ask follow-up questions against a fixture with complete, stale, and missing inputs; verify answers cite available evidence, show uncertainty, and refuse unsupported claims.

**Acceptance Scenarios**:

1. **Given** relevant evidence exists for the selected match, **When** the user asks a follow-up, **Then** the client answers with a concise judgment, supporting facts, counterpoint, confidence, and source/freshness references.
2. **Given** the user asks for facts that are unavailable, speculative, or outside Nutmeg's data scope, **When** the client responds, **Then** it says what is missing and offers the safest next action such as refresh, wait, or no opinion.
3. **Given** generated wording conflicts with deterministic Nutmeg outputs, **When** an answer is produced, **Then** deterministic verdicts, probabilities, and caveats take precedence.

---

### User Story 4 - Use subscription-ready access and personalization (Priority: P2)

As a future subscriber, I want my saved matches, preferences, alerts, and access level to follow my account, so the client can evolve from a private tool into a paid product without mixing users' state.

**Why this priority**: Subscription readiness is a product constraint now, even if the first deployment remains owner-only.

**Independent Test**: Two seeded users with different entitlements and watchlists see isolated state, different gated content, and no cross-user leakage.

**Acceptance Scenarios**:

1. **Given** a user has a basic entitlement, **When** they access a premium analysis section or alert type, **Then** the client explains the restriction and does not reveal gated content.
2. **Given** two users follow different matches, **When** each opens their dashboard, **Then** watchlists, alerts, preferences, and prediction history remain isolated.
3. **Given** an operator account is used during Phase 1, **When** subscription features are disabled, **Then** the same screens work in owner-only mode without requiring a public billing flow.

---

### User Story 5 - Track alerts and calibration outcomes (Priority: P2)

As a serious user, I want to save opportunities, receive meaningful change alerts, and review past predictions, so the application improves decision discipline instead of encouraging impulsive bets.

**Why this priority**: The first principle is betting-analysis assistance, so the client must support disciplined review and not only pre-match excitement.

**Independent Test**: Save a match, trigger simulated odds/news/lineup changes, record a prediction, add the result, and verify the review view shows calibration and outcome feedback.

**Acceptance Scenarios**:

1. **Given** a watched match has a material odds, lineup, injury, news, or value-edge change, **When** alerts are enabled, **Then** the client creates one concise alert with before/after context and the updated actionability class.
2. **Given** a user records a prediction or simulated pick, **When** the match outcome is available, **Then** the client supports outcome review and shows calibration metrics without presenting the result as guaranteed future performance.
3. **Given** repeated alerts occur for the same match, **When** the user views notifications, **Then** the client groups related changes to avoid spam and decision fatigue.

### Edge Cases

- Latest data is unavailable because a provider is down, a quota is exhausted, or a fixture has not been synced.
- Odds are stale, suspended, removed, or differ materially across providers/bookmakers.
- News or information items cannot be verified, are duplicates, or conflict with official lineup/injury data.
- The fixture is postponed, abandoned, rescheduled, already finished, or has ambiguous identity across providers.
- The user asks for guaranteed profit, actual bet placement, sportsbook account connection, or jurisdiction-specific legal advice.
- A user is not entitled to a premium section, has an expired subscription, or attempts to access another user's saved state.
- AI-generated language is more confident than the deterministic evidence supports.
- Event-data visualizations are unavailable and only proxy tactical visuals exist.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The client MUST provide an AI-native daily match feed that ranks upcoming and live-relevant matches by betting-analysis interest.
- **FR-002**: Ranked match cards MUST show fixture identity, competition, kickoff time, live/pre-match state, verdict class, confidence, value/edge status, and suggested next action.
- **FR-003**: The client MUST make data freshness visible on every match card and match workspace, including last updated time for fixture, odds, team/player, tactical, and news/information sections when available.
- **FR-004**: The client MUST display unavailable or stale evidence explicitly and MUST avoid value, stake, or confidence claims when minimum evidence is not met.
- **FR-005**: The match workspace MUST combine Nutmeg's match brief, model-vs-market value output, odds snapshot, market movement, tactical evidence, player availability, relevant news/information, caveats, and source attribution.
- **FR-006**: Every match analysis MUST include an actionability class chosen from: value, lean, watch, avoid, or no-bet.
- **FR-007**: Every actionable analysis MUST include a counterargument or risk note alongside the positive case.
- **FR-008**: The conversational analyst MUST answer follow-up questions only from available match, market, player, tactical, and news/information evidence.
- **FR-009**: The conversational analyst MUST refuse or qualify requests that are unsupported, speculative, stale, or outside football betting-analysis assistance.
- **FR-010**: Deterministic Nutmeg outputs MUST take precedence over generated prose when the two disagree.
- **FR-011**: The client MUST support source attribution for externally derived facts, including provider/source name, retrieval or publication time where known, and the related match or entity.
- **FR-012**: The client MUST support watchlists for matches and competitions.
- **FR-013**: The client MUST support alerts for material changes in odds, line movement, value edge, lineup, injury, fixture status, and relevant news/information.
- **FR-014**: Alerts MUST summarize what changed, why it matters, and whether the actionability class changed.
- **FR-015**: The client MUST support recording user predictions or simulated picks and reviewing outcomes with calibration metrics.
- **FR-016**: The product MUST NOT place bets, connect to sportsbook accounts, automate wagering, promise profit, or present analysis as financial advice.
- **FR-017**: The client MUST show responsible-gambling and risk-disclosure language in betting-analysis contexts.
- **FR-018**: User state MUST be isolated by user identity, including preferences, watchlists, alerts, prediction history, and subscription entitlement.
- **FR-019**: The client MUST support owner-only Phase 1 use while preserving entitlement boundaries for future paid subscribers.
- **FR-020**: Subscription gating MUST prevent non-entitled users from accessing premium match detail, alerts, history, or advanced analysis sections.
- **FR-021**: The client MUST expose a data-health view or status indicator showing whether latest fixture, odds, news/information, and analysis refreshes are healthy, stale, or failing.
- **FR-022**: The client MUST support Chinese-first product copy and analysis display, while allowing English source names, team names, and technical market labels where required for accuracy.
- **FR-023**: The client MUST be usable on desktop and mobile-width screens for daily triage, match inspection, and follow-up questions.
- **FR-024**: The client MUST preserve an audit trail of generated betting-analysis outputs sufficient to review what evidence was visible at decision time.
- **FR-025**: The first release MUST reuse Nutmeg's existing analytical outputs as the source of truth and MUST NOT introduce a separate client-side football model or odds-pricing logic.

### Development Constraints and Product Guardrails

- **DC-001**: Betting-analysis assistance is the first-principles product goal; every primary screen MUST help the user decide whether a market is interesting, risky, stale, or not worth action.
- **DC-002**: Truthfulness outranks engagement; the client MUST prefer "no opinion" or "wait for data" over confident but weakly grounded analysis.
- **DC-003**: AI-native behavior means conversational orchestration, prioritization, explanation, memory, and follow-up over grounded evidence; it does not permit untraceable claims.
- **DC-004**: The application MUST avoid dark patterns that encourage compulsive gambling, alert spam, or urgency unsupported by data.
- **DC-005**: Subscription design MUST separate account entitlement from objective football data so shared facts can be reused while user behavior remains private.
- **DC-006**: Implementation planning MUST follow Spec Kit artifacts and Superpowers reliability gates: task coverage review before implementation, TDD before code changes, and verification-before-completion before claiming done.
- **DC-007**: Client work MUST preserve the existing Nutmeg service boundaries and use the application layer as an orchestration/client layer rather than duplicating CLI internals.

### Key Entities *(include if feature involves data)*

- **Client User**: A person using the application, with identity, preferences, language choice, responsible-use acknowledgement, and account state.
- **Subscription Entitlement**: The user's access level, plan state, feature gates, and limits for premium analysis, alerts, and history.
- **Match Opportunity**: A fixture as ranked for betting-analysis interest, including actionability class, confidence, edge/value status, and freshness state.
- **Match Workspace**: The detailed view of one match, composed of brief, value analysis, odds, tactics, player availability, news/information, caveats, and source ledger.
- **Evidence Item**: A source-attributed fact, metric, model output, market observation, or news/information item used in analysis.
- **Freshness Ledger**: The set of timestamps, source names, and stale/unavailable flags attached to a match or answer.
- **Conversational Analysis Session**: A grounded question-answer exchange tied to a match, league, watchlist, or daily feed context.
- **Watchlist Item**: A saved match, team, competition, market, or player context that can drive alerts and dashboard personalization.
- **Alert**: A user-facing notification about a material evidence or actionability change.
- **Prediction Record**: A user's recorded judgment or simulated pick and the later outcome/calibration review attached to it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a seeded daily-use scenario, users can identify the top three betting-analysis opportunities, their actionability classes, and their main caveats in under 2 minutes.
- **SC-002**: 100% of match cards and match workspaces in acceptance tests show data freshness or unavailable-state indicators for fixture, odds, tactical/player, and news/information sections.
- **SC-003**: In seeded stale, missing, and conflicting-data scenarios, the client avoids unsupported value calls and displays the blocking issue in 100% of cases.
- **SC-004**: For locally available match evidence, a follow-up question receives either a grounded answer or a truthful refusal within 10 seconds in 95% of test runs.
- **SC-005**: Entitlement tests show 100% isolation between two users' watchlists, alerts, prediction records, and gated premium sections.
- **SC-006**: Users can save a match, receive a simulated material-change alert, and review the before/after analysis state in under 1 minute.
- **SC-007**: Users can record a prediction or simulated pick and later review outcome/calibration feedback without leaving the client.
- **SC-008**: Audit review confirms that no client workflow places wagers, connects sportsbook accounts, promises profit, or hides responsible-use disclosures.
- **SC-009**: The primary daily feed, match workspace, and follow-up analyst are usable on both desktop and mobile-width screens in acceptance testing.

## Assumptions

- The first client release is a browser/PWA-style application surface, not a native iOS or Android app.
- Phase 1 remains owner-only or private beta, but account and entitlement boundaries are designed for future paid subscribers.
- Existing Nutmeg CLI/services remain the authoritative analysis engine for fixtures, odds, value board, match brief, player profile, tactical visuals, eval/review, and daily-run logic.
- A future news/information provider may be added; until then, the client must represent news/information availability truthfully.
- The product is an analysis and education assistant for adults; it does not provide legal, financial, or sportsbook execution services.
- Chinese is the primary user-facing language for the first release, with accurate English names and market labels retained where necessary.
- OpenClaw Telegram can remain an operator/notification channel, but the primary subscription client experience is the browser/PWA surface.
