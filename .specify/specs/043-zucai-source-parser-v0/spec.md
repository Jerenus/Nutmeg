# Feature Specification: Zucai Source Parser v0

**Feature Branch**: `043-zucai-source-parser-v0`  
**Created**: 2026-04-26  
**Status**: Verified (2026-04-26)  
**Input**: Continue the unfinished automated Zucai work by adding a source parser that can discover traditional足彩14场 issues for the day and populate the registry/snapshots used by scheduled delivery.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Parse a trusted schedule source into issue snapshots (Priority: P1)

As the operator, I want Nutmeg to parse an official or trusted schedule notice into structured issue snapshots, so I do not need to hand-write the 14-match issue JSON before every scheduled run.

**Why this priority**: Scheduled delivery depends on `.nutmeg-data/zucai/issues.json`. Without parser support, daily automation still needs manual registry maintenance.

**Independent Test**: Provide a local official-like schedule notice file containing at least one traditional足彩胜负游戏（14场和任选9场） issue; run the parser; verify one issue JSON is written with exactly 14 ordered matches, sale timing, draw date, and source metadata.

**Acceptance Scenarios**:

1. **Given** a source notice with one valid 14-match issue, **When** parsing runs, **Then** Nutmeg writes a `*-issue.json` snapshot with 14 matches and the correct issue id.
2. **Given** a source notice with multiple issue attachments, **When** parsing runs, **Then** Nutmeg writes one issue snapshot per valid 14-match issue.
3. **Given** an attachment for non-14-match games, **When** parsing runs, **Then** Nutmeg ignores it without creating a malformed Zucai issue.

---

### User Story 2 - Generate or update the scheduled issue registry (Priority: P1)

As the operator, I want parsed issues to update the scheduled registry, so `zucai-auto-run` can determine whether today has an active issue and stay silent when it does not.

**Why this priority**: This directly closes the gap in 042 by making scheduled delivery data-driven rather than manually configured.

**Independent Test**: Parse a schedule notice whose sale-stop date is the run date; verify `.nutmeg-data/zucai/issues.json` includes an enabled entry with `active_dates`, `issue_file`, and preserved existing odds/override paths when present.

**Acceptance Scenarios**:

1. **Given** a parsed issue with sale-stop date equal to the run date, **When** registry sync completes, **Then** the registry marks that issue active for the run date.
2. **Given** an existing registry entry for the same issue with odds or override paths, **When** source sync rewrites the issue snapshot, **Then** those operator-maintained paths are preserved.
3. **Given** no issue active for the requested date, **When** sync completes, **Then** the registry is still updated with parsed future/past issues and the result reports no active issue for the run date.

---

### User Story 3 - Provide safe CLI and optional live fetch (Priority: P2)

As the operator, I want a CLI command that can parse local files by default and optionally fetch a trusted URL only when explicitly enabled, so automation remains testable and does not make surprise network calls.

**Why this priority**: Live source pages are useful but brittle; local-first parsing keeps tests deterministic and preserves the no-surprise-network rule.

**Independent Test**: Run the CLI against a bundled local source file; verify JSON output. Run with `--source-url` without `--live-fetch`; verify it refuses instead of fetching.

**Acceptance Scenarios**:

1. **Given** a local source file, **When** `zucai-source-sync` runs, **Then** it writes issue snapshots and registry JSON without network access.
2. **Given** a source URL but no live-fetch flag, **When** the command runs, **Then** it exits with a clear validation error and makes no request.
3. **Given** source parsing finds warnings, **When** JSON output is requested, **Then** warnings are exposed without hiding successfully parsed issues.

### Edge Cases

- Source file is missing, empty, malformed HTML, or contains no 14-match issues.
- Source text includes attachment summary lines before detailed tables.
- Competition names are omitted on repeated rows and must carry forward from the previous row.
- One attachment has fewer or more than 14 match rows and must be skipped with a warning.
- Sale-stop time is missing; active date falls back to draw date if available.
- Existing registry contains manual odds/override paths for the issue and must not lose them.
- Source URL fetch is requested without explicit `--live-fetch`.
- Remote source fetch fails or exceeds bounds; command returns a clear error.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Nutmeg MUST expose a `zucai-source-sync` command that parses a local source file by default.
- **FR-002**: Nutmeg MUST parse traditional足球彩票胜负游戏（14场和任选9场） issue sections from official-like schedule text or HTML.
- **FR-003**: Nutmeg MUST write one valid 14-match issue snapshot per parsed issue.
- **FR-004**: Nutmeg MUST skip non-14-match sections and malformed 14-match sections with warnings rather than writing invalid issue files.
- **FR-005**: Nutmeg MUST preserve sale start, sale stop, draw date, source label, and source URL when available.
- **FR-006**: Nutmeg MUST infer registry `active_dates` from sale-stop date first, then draw date.
- **FR-007**: Nutmeg MUST update the scheduled issue registry with parsed issues and issue file paths.
- **FR-008**: Nutmeg MUST preserve existing registry odds/override/revision paths for issues that are refreshed by source parsing.
- **FR-009**: Nutmeg MUST expose JSON CLI output with parsed count, written issue paths, active issue ids for the run date, registry path, and warnings.
- **FR-010**: Nutmeg MUST reject `--source-url` unless `--live-fetch` is explicitly provided.
- **FR-011**: Nutmeg MUST avoid default network calls in tests and normal local-file use.
- **FR-012**: Nutmeg MUST document source parser usage, boundaries, and how it feeds `zucai-auto-run`.
- **FR-013**: Nutmeg MUST keep the parser limited to schedule/registry generation and avoid betting execution or guaranteed-profit claims.

### Key Entities *(include if feature involves data)*

- **Zucai Source Notice**: Local file or explicitly fetched trusted page containing issue schedule attachments.
- **Parsed Zucai Issue**: Structured 14-match issue derived from a source notice.
- **Zucai Source Sync Result**: CLI-facing summary of parsed issues, written files, registry update, active issues, and warnings.
- **Zucai Scheduled Registry Entry**: Existing 042 registry entry updated by parser output.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A bundled source notice sample can generate a valid 26068 issue snapshot with exactly 14 matches.
- **SC-002**: The parser-generated registry enables `zucai-auto-run --date 2026-04-26 --slot afternoon` to find issue 26068 without a hand-written registry.
- **SC-003**: Existing odds/override paths survive a source sync refresh in tests.
- **SC-004**: `--source-url` without `--live-fetch` fails safely with no network request.
- **SC-005**: Focused parser/CLI tests and full repository verification pass after implementation.

## Assumptions

- v0 targets official-like Chinese schedule notices whose detailed sections include issue id, competition, sequence number, home team, away team, match date, sale start, sale stop, and draw date.
- v0 generates issue snapshots and registry entries only; odds snapshot automation remains a follow-on feature.
- Live fetch is opt-in and bounded; local sample tests remain the source of deterministic verification.
