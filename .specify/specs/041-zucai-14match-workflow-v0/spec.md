# Feature Specification: Traditional Zucai 14-Match Workflow v0

**Feature Branch**: `041-zucai-14match-workflow-v0`  
**Created**: 2026-04-26  
**Status**: Verified (2026-04-26)  
**Input**: Make traditional Chinese Sports Lottery 14-match pools a reusable Nutmeg feature because the operator will participate every issue.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Build a reusable 14-match issue report (Priority: P1)

As the operator, I want Nutmeg to load a traditional足彩 issue with exactly 14 matches plus latest odds/source snapshots, so I can regenerate a consistent report for each issue instead of writing one-off analysis.

**Why this priority**: This is the recurring core workflow. Without issue normalization and a report payload, PDF, Telegram, and review are not reusable.

**Independent Test**: Provide a structured issue JSON, odds JSON, and optional override JSON; run the report builder; verify 14 normalized matches, recommendations, risk tiers, plan counts, warnings, and source ledger.

**Acceptance Scenarios**:

1. **Given** a valid issue file with 14 matches and latest odds, **When** the report is built, **Then** the payload includes one recommendation per match, generated plans, source metadata, and no fabricated missing data.
2. **Given** per-match analyst overrides, **When** the report is built, **Then** valid override picks/rationales replace baseline picks and invalid overrides are reported as warnings.
3. **Given** an issue file with fewer or more than 14 matches, **When** the report is built, **Then** Nutmeg rejects it with a clear validation error.

---

### User Story 2 - Render and deliver reusable artifacts (Priority: P1)

As the operator, I want Nutmeg to write Markdown/PDF reports and optionally dispatch the PDF through Telegram, so each issue can be archived and sent through the existing Nutmeg bot workflow.

**Why this priority**: The user explicitly asked for PDF delivery through Nutmeg bot and wants the workflow reusable every issue.

**Independent Test**: Run the report command with an output directory and dry-run Telegram dispatch; verify Markdown and PDF paths exist, PDF starts with a valid PDF header, JSON output exposes artifact paths, and dry-run never sends a real message.

**Acceptance Scenarios**:

1. **Given** a valid report request and output directory, **When** Markdown/PDF rendering is enabled, **Then** Nutmeg writes deterministic artifact files and returns their paths.
2. **Given** Telegram dispatch is requested with dry-run mode, **When** the report command runs, **Then** the payload includes the planned caption/chat ids without sending.
3. **Given** real Telegram dispatch is requested but configuration is missing or send fails, **When** the command runs, **Then** the report artifacts remain available and dispatch status explains the failure.

---

### User Story 3 - Review issue results after settlement (Priority: P2)

As the operator, I want to grade an issue after results are known, so Nutmeg can track whether the generated plans covered the actual 14-match and 任九 outcomes.

**Why this priority**: A recurring betting-analysis workflow must close the loop; grading is required before later calibration and subscription-quality claims.

**Independent Test**: Provide a saved report JSON and an outcome JSON; run grading; verify match-level hit/miss flags, plan coverage, hit counts, and unresolved-result warnings.

**Acceptance Scenarios**:

1. **Given** a report and complete outcomes, **When** grading runs, **Then** every match is marked hit/miss according to whether its pick string contains the result code.
2. **Given** plan strings and outcomes, **When** grading runs, **Then** each plan reports whether it covered all selected matches and how many selected matches hit.
3. **Given** incomplete outcomes, **When** grading runs, **Then** unresolved matches are listed without inventing results.

### Edge Cases

- Issue file is missing, malformed, or has duplicate match numbers.
- Odds file is missing, has stale timestamps, or lacks one or more matches.
- Override pick contains characters other than `3`, `1`, `0`, or repeats codes.
- Generated plan contains `-` omissions for 任九 and must count only selected matches.
- PDF rendering dependency fails; JSON/Markdown must remain usable.
- Telegram token or chat ids are missing, or sendDocument returns an error.
- Outcome file contains invalid result codes or unknown match numbers.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Nutmeg MUST represent a traditional足彩 issue with issue id, sale window, draw date, source list, and exactly 14 ordered matches.
- **FR-002**: Nutmeg MUST reject issue payloads that do not contain exactly 14 unique match numbers from 1 through 14.
- **FR-003**: Nutmeg MUST load latest match-winner odds from an explicit structured odds snapshot and attach per-match odds averages when available.
- **FR-004**: Nutmeg MUST generate one recommendation per match using stable `3/1/0` notation, a primary pick, confidence, risk tier, and rationale.
- **FR-005**: Nutmeg MUST support optional analyst override files for per-match pick/rationale/risk adjustments while warning on invalid overrides.
- **FR-006**: Nutmeg MUST generate at least one full 14-match plan and one 任九-style plan, with stake count and estimated cost.
- **FR-007**: Nutmeg MUST expose a JSON CLI contract for generating a report from issue id/files, odds files, override files, and output options.
- **FR-008**: Nutmeg MUST render a Markdown artifact for each generated report.
- **FR-009**: Nutmeg MUST render a PDF artifact when requested and report PDF errors without hiding the rest of the report.
- **FR-010**: Nutmeg MUST support Telegram PDF dispatch through the existing configured bot token/chat ids with dry-run default and no token leakage.
- **FR-011**: Nutmeg MUST expose a JSON CLI contract for grading a saved report against an outcome file.
- **FR-012**: Nutmeg MUST document the workflow, source snapshot format, responsible-use boundaries, and future parser/calibration path.
- **FR-013**: Nutmeg MUST add a bundled deterministic sample for issue 26068 so the workflow can be smoked without network calls.

### Key Entities *(include if feature involves data)*

- **Zucai Issue**: One traditional足彩 issue with sale timing, sources, and 14 matches.
- **Zucai Match**: Match number, competition, home/away teams, kickoff date/time, and optional notes/risk flags.
- **Zucai Odds Snapshot**: Latest per-match `3/1/0` odds averages and optional provider quotes.
- **Zucai Recommendation**: Pick code, primary code, confidence, risk tier, rationale, odds evidence, and override status.
- **Zucai Plan**: Full or 任九 plan string, selected matches, stake count, estimated cost, and note.
- **Zucai Report**: Generated issue-level report with recommendations, plans, artifacts, warnings, and source ledger.
- **Zucai Outcome**: Result code per match used for grading.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A bundled 26068 sample report can be generated from CLI with parseable JSON and 14 recommendations.
- **SC-002**: Markdown and PDF artifacts are written for a sample issue in tests and the PDF has a valid PDF header.
- **SC-003**: Dry-run Telegram dispatch returns dispatch metadata without sending or leaking secrets.
- **SC-004**: Grading tests cover complete and incomplete outcomes with deterministic hit/miss results.
- **SC-005**: Focused tests for service and CLI pass, and existing full verification continues to pass.

## Assumptions

- v0 uses structured local snapshots rather than automatic HTML scraping. A later parser spec can convert official/Sina pages into this format.
- Report recommendations are analysis assistance only and must not claim guaranteed profit or certainty.
- PDF rendering may introduce a small dependency, but JSON/Markdown remain the source of truth.
- Real Telegram dispatch is operator-controlled and disabled by default.
