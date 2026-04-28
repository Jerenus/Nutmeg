# Feature Specification: Popular Matches Ranking

**Feature Branch**: `028-popular-matches-ranking`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: Continue Phase 1 daily-operator usability by ranking local/live fixture candidates for the question "what are today's popular matches?".

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Rank fixture candidates by popularity (Priority: P1)

As the private operator, I want local fixture candidates ranked by a deterministic popularity score so the most relevant matches surface before lower-interest fixtures.

**Independent Test**: Build a mixed fixture list with a smaller nearby match and a later elite matchup, run the ranker, and verify descending score order, tier labels, and human-readable scoring reasons.

### User Story 2 - Expose a popular matches CLI (Priority: P1)

As the operator, I want a CLI command that answers "popular matches" directly from local/demo fixtures with JSON/text output and suggested `/brief` messages.

**Independent Test**: Run `popular-matches --league epl --days 3 --demo --format json` and verify ranked items include rank, score, tier, reasons, fixture identity, and suggested bot messages.

### User Story 3 - Reuse ranking inside today briefs (Priority: P2)

As the operator, I want `today-briefs` to optionally sort by popularity while preserving the existing kickoff-order default.

**Independent Test**: Run `today-briefs --sort popularity --demo --format json` and verify the payload records the sort mode and each item includes popularity details.

## Functional Requirements

- **FR-001**: The ranker MUST be deterministic and require no network calls.
- **FR-002**: The score MUST combine competition weight, team prominence, matchup/rivalry boosts, kickoff proximity, and live/scheduled status when available.
- **FR-003**: Every ranked fixture MUST include a numeric score, tier, and at least one human-readable reason.
- **FR-004**: `popular-matches` MUST support `--league`, `--days`, `--limit`, `--demo`, `--query`, and `--format text|json`.
- **FR-005**: JSON output MUST stay token/secret-free and include suggested `/brief` messages for immediate follow-up.
- **FR-006**: `today-briefs` MUST keep kickoff order by default and only switch to popularity when `--sort popularity` is provided.
