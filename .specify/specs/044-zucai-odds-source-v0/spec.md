# Feature Specification: Zucai Odds Source v0

**Feature Branch**: `044-zucai-odds-source-v0`  
**Created**: 2026-04-26  
**Status**: Verified (2026-04-26)  
**Input**: Continue the Zucai automation chain by adding odds source parsing so 16:00 and 18:30 scheduled reports can use generated odds snapshots instead of manually maintained odds files.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Parse odds source into a 14-match odds snapshot (Priority: P1)

As the operator, I want Nutmeg to parse a trusted odds table into the existing Zucai odds snapshot format, so scheduled reports can include current average odds evidence.

**Why this priority**: The report engine already consumes `odds_file`; this feature removes the manual odds snapshot step for the recurring workflow.

**Independent Test**: Provide a local odds source file for issue 26068 with 14 rows of home/draw/away odds; run the parser; verify it writes a valid odds JSON with issue id, captured time, source metadata, and exactly 14 positive odds rows.

**Acceptance Scenarios**:

1. **Given** a valid odds source with 14 rows, **When** odds sync runs, **Then** Nutmeg writes `26068-odds.json` in the existing 041 odds snapshot contract.
2. **Given** an odds source with missing or non-positive odds rows, **When** parsing runs, **Then** Nutmeg skips invalid rows and reports warnings instead of writing a misleading complete snapshot.
3. **Given** a source with provider names, **When** snapshot is written, **Then** provider metadata is preserved per match where available.

---

### User Story 2 - Update scheduled registry for afternoon and revision odds (Priority: P1)

As the operator, I want odds sync to write the right registry field for 16:00 and 18:30, so `zucai-auto-run` automatically uses the correct odds snapshot for each scheduled report.

**Why this priority**: The user's 18:30 report is intended as a correction based on later reference data. Slot-specific odds files are required for that decision-confirmation workflow.

**Independent Test**: Run odds sync once for `afternoon` and once for `revision`; verify the registry has `odds_file` and `revision_odds_file`, and `zucai-auto-run --slot revision` uses the revision odds.

**Acceptance Scenarios**:

1. **Given** slot `afternoon`, **When** odds sync completes, **Then** the registry entry for the issue contains `odds_file`.
2. **Given** slot `revision`, **When** odds sync completes, **Then** the registry entry for the issue contains `revision_odds_file` without overwriting `odds_file`.
3. **Given** the registry already contains issue/override paths, **When** odds sync updates the entry, **Then** those paths are preserved.

---

### User Story 3 - Provide safe CLI and optional live fetch (Priority: P2)

As the operator, I want a local-first CLI that can optionally fetch a trusted odds URL only when explicitly enabled, so odds automation remains deterministic and safe.

**Why this priority**: Odds pages can be unstable and remote fetching must be explicit. Local fixtures and cached pages are the reliable default.

**Independent Test**: Run `zucai-odds-sync` against a bundled local odds source and verify JSON output. Run with `--source-url` but no `--live-fetch`; verify a validation error and no request.

**Acceptance Scenarios**:

1. **Given** a local odds source file, **When** CLI runs, **Then** it writes an odds snapshot and updates registry without network access.
2. **Given** a source URL without live-fetch, **When** CLI runs, **Then** it exits with a clear validation error.
3. **Given** parsing warnings, **When** JSON output is requested, **Then** warnings are exposed.

### Edge Cases

- Source file is missing, malformed, or contains no odds table.
- Odds source has fewer/more than 14 valid match rows.
- Odds values use commas, Chinese labels, or whitespace around numbers.
- Registry does not yet contain the issue; odds sync creates a minimal enabled entry.
- Registry contains `issue_file` and overrides from 043/manual work; odds sync must preserve them.
- `revision` slot odds must not overwrite afternoon/base odds.
- URL mode without `--live-fetch` must fail safely.
- Remote fetch failure must return a clear validation error.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Nutmeg MUST expose a `zucai-odds-sync` command that parses local odds files by default.
- **FR-002**: Nutmeg MUST parse issue id, captured timestamp, source metadata, and 14 match odds rows from official-like odds text/HTML.
- **FR-003**: Nutmeg MUST write odds snapshots compatible with `ZucaiWorkflowService.load_odds`.
- **FR-004**: Nutmeg MUST reject or warn on malformed odds rows and avoid writing invalid complete snapshots.
- **FR-005**: Nutmeg MUST support slot `afternoon` by updating registry field `odds_file`.
- **FR-006**: Nutmeg MUST support slot `revision` by updating registry field `revision_odds_file`.
- **FR-007**: Nutmeg MUST preserve existing registry fields such as `issue_file`, `overrides_file`, and `revision_overrides_file`.
- **FR-008**: Nutmeg MUST expose JSON CLI output with issue id, slot, odds path, registry path, parsed row count, and warnings.
- **FR-009**: Nutmeg MUST reject `--source-url` unless `--live-fetch` is explicitly provided.
- **FR-010**: Nutmeg MUST avoid default network calls in local-file use.
- **FR-011**: Nutmeg MUST document how odds sync feeds `zucai-auto-run` 16:00 and 18:30 reports.
- **FR-012**: Nutmeg MUST keep odds sync as analysis input generation only: no betting execution, no sportsbook connection, and no guaranteed-profit claims.

### Key Entities *(include if feature involves data)*

- **Zucai Odds Source**: Local file or explicitly fetched trusted page containing 3/1/0 odds rows.
- **Parsed Zucai Odds Snapshot**: Existing 041 odds snapshot contract with issue id, captured time, sources, and match odds.
- **Zucai Odds Sync Result**: CLI-facing summary of parsed rows, written odds file, registry update, and warnings.
- **Zucai Scheduled Registry Entry**: Existing 042 registry entry updated with `odds_file` or `revision_odds_file`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A bundled local odds source sample writes a 26068 odds snapshot with 14 rows.
- **SC-002**: Afternoon odds sync updates registry `odds_file` and revision odds sync updates `revision_odds_file` without overwriting each other.
- **SC-003**: `zucai-auto-run --slot revision` uses the revision odds snapshot after sync.
- **SC-004**: `--source-url` without `--live-fetch` fails safely with no network request.
- **SC-005**: Focused odds/CLI tests and full repository verification pass after implementation.

## Assumptions

- v0 focuses on average decimal home/draw/away odds for each match; deeper bookmaker movement analysis is deferred.
- v0 accepts local cached HTML/text as the normal source. Live fetch exists only as an explicit trusted-source option.
- Odds snapshots are analysis evidence only and do not imply guaranteed outcomes.
