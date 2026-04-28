# Data Model: AI-Native Betting Client

## ClientUser

Represents a person using the client.

**Fields**:
- `user_id`: Stable user identifier; required on all mutable user state.
- `display_name`: Human-readable label.
- `language`: User-facing language preference; first release defaults to Chinese.
- `responsible_use_acknowledged_at`: Timestamp when the user acknowledged risk language.
- `created_at`, `updated_at`: Audit timestamps.

**Validation rules**:
- `user_id` is required and must not be blank.
- `language` defaults to `zh-CN` when unset.
- Betting-analysis screens must not hide responsible-use language when acknowledgement is absent.

## SubscriptionEntitlement

Represents access level and subscription-readiness gates.

**Fields**:
- `user_id`: Owner of the entitlement.
- `plan`: One of `owner`, `free`, `basic`, `premium`, or `expired`.
- `premium_match_detail_enabled`: Whether advanced match workspace sections are visible.
- `alerts_enabled`: Whether alert creation and delivery are enabled.
- `history_enabled`: Whether prediction/audit history is visible.
- `status`: One of `active`, `trial`, `expired`, or `disabled`.
- `valid_until`: Optional expiration timestamp.

**Validation rules**:
- Non-entitled users must receive a restriction explanation without hidden premium facts.
- Owner-only mode maps to `owner` entitlement and bypasses public billing requirements.

## MatchOpportunity

Represents one ranked match card in the daily feed.

**Fields**:
- `fixture_id`, `league`, `home_team`, `away_team`, `kickoff_at`, `status`.
- `rank`, `score`, `tier`, `reasons` from popularity/value/analysis signals.
- `actionability`: One of `value`, `lean`, `watch`, `avoid`, or `no-bet`.
- `confidence`: Existing Nutmeg confidence label when available.
- `edge_status`: Positive edge, no edge, unknown, or unavailable.
- `freshness`: FreshnessLedger summary.
- `suggested_action`: Inspect, watch, refresh, record, or no opinion.

**Validation rules**:
- Missing odds or stale evidence forces `edge_status` to `unknown` or `unavailable`.
- A card must remain visible when evidence is incomplete, but it must not present a false value call.

## MatchWorkspace

Detailed one-match analysis workspace.

**Fields**:
- `fixture`: Match identity and status.
- `judgment`: Verdict, confidence, reasons, counterargument, and caveats from Nutmeg analysis.
- `value`: Model-vs-market candidate details when available.
- `market`: Odds snapshot, fair probabilities, market movement, and bookmaker disagreement notes.
- `tactics`: Tactical summary and visual artifact references.
- `players`: Availability and player-context notes.
- `information`: Source-attributed news/information items or truthful unavailable state.
- `freshness`: FreshnessLedger.
- `audit_id`: AnalysisAuditRecord identifier for decision-time review.

**Validation rules**:
- Deterministic verdict, probabilities, caveats, and stale-data flags override generated prose.
- Actionable analysis requires a counterargument or risk note.

## EvidenceItem

A source-attributed fact, metric, model output, or information item.

**Fields**:
- `evidence_id`: Stable identifier inside an audit record or workspace.
- `kind`: Fixture, odds, market movement, model, tactical, player, news, provider health, or user note.
- `source_name`: Provider or internal Nutmeg component.
- `source_url`: Optional external reference.
- `published_at`: Optional source publication timestamp.
- `retrieved_at`: Timestamp when Nutmeg obtained the item.
- `summary`: Short human-readable statement.
- `staleness`: Fresh, stale, unavailable, or conflicting.

**Validation rules**:
- Externally derived facts require `source_name` and at least one timestamp when known.
- Unverified information must not be promoted to an actionable claim.

## FreshnessLedger

Freshness state for a match, card, workspace, or answer.

**Fields**:
- `fixture_updated_at`.
- `odds_updated_at`.
- `team_player_updated_at`.
- `tactical_updated_at`.
- `information_updated_at`.
- `analysis_generated_at`.
- `health`: Healthy, stale, partial, or failing.
- `blocking_reasons`: Reasons preventing an actionable call.

**Validation rules**:
- Missing or stale required evidence must be visible wherever actionability appears.
- A failing provider must not be hidden behind a confident conclusion.

## ConversationalAnalysisSession

A grounded question-answer exchange tied to a user and context.

**Fields**:
- `session_id`, `user_id`.
- `fixture_id`: Optional when the question is match-specific.
- `question`: User's original prompt.
- `answer`: Grounded response or truthful refusal.
- `evidence_ids`: Evidence items used in the answer.
- `verdict_alignment`: Whether the answer agrees with deterministic Nutmeg outputs.
- `created_at`.

**Validation rules**:
- Answers must cite or reference available evidence.
- Unsupported, stale, speculative, or out-of-scope requests must be refused or qualified.

## WatchlistItem

A saved match, competition, team, market, or player context.

**Fields**:
- `watchlist_id`, `user_id`.
- `target_type`: Fixture, league, team, market, or player.
- `target_id`: Stable target identifier.
- `alert_preferences`: Material changes that should create alerts.
- `created_at`, `updated_at`.

**Validation rules**:
- Watchlist entries are always user-scoped.
- Duplicate entries for the same user and target should update preferences rather than create spam.

## Alert

A material change notification.

**Fields**:
- `alert_id`, `user_id`, `fixture_id`.
- `change_type`: Odds, line movement, value edge, lineup, injury, fixture status, information, or provider health.
- `before_summary`, `after_summary`.
- `actionability_before`, `actionability_after`.
- `severity`: Info, watch, important, or blocking.
- `group_key`: Key used to group repeated changes.
- `created_at`, `read_at`.

**Validation rules**:
- Alerts must summarize what changed and why it matters.
- Repeated changes for the same match and type should be grouped to avoid alert spam.

## PredictionRecord

A user-recorded judgment or simulated pick and outcome review.

**Fields**:
- Existing prediction fields from Nutmeg prediction storage.
- `user_id`: Required owner.
- `source_audit_id`: Optional decision-time analysis audit.
- `client_notes`: User note captured from the client.

**Validation rules**:
- Prediction review must not imply guaranteed future performance.
- Records are isolated by user.

## AnalysisAuditRecord

Snapshot of evidence visible at decision time.

**Fields**:
- `audit_id`, `user_id`, `fixture_id`.
- `actionability`, `confidence`, `verdict`.
- `evidence_snapshot`: Serialized evidence summaries and freshness ledger.
- `generated_text`: Optional generated answer or brief shown to user.
- `created_at`.

**Validation rules**:
- Audit records must not store secrets.
- Audit records must preserve enough evidence to explain later why the client showed a conclusion or refusal.
