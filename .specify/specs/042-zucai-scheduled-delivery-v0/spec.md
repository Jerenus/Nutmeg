# Feature Specification: Zucai Scheduled Delivery v0

**Feature Branch**: `042-zucai-scheduled-delivery-v0`  
**Created**: 2026-04-26  
**Status**: Verified (2026-04-26)  
**Input**: Automatically check each day whether there is a traditional Chinese Sports Lottery 14-match issue. If present, generate and send a PDF analysis through Nutmeg Bot around 16:00, then send a revised decision-confirmation report around 18:30. If no issue exists, stay silent.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run the scheduled issue check silently (Priority: P1)

As the operator, I want Nutmeg to run a scheduled check for a given date and slot, so it only acts when that day has an active traditional足彩14场 issue.

**Why this priority**: The automation must not create noise on non-issue days. Silent skipping is the first safety rule for a daily scheduled task.

**Independent Test**: Provide a local issue registry with no active issue for the run date; run the auto command for the 16:00 slot; verify the result is `skipped_no_issue`, no PDF is generated, no Telegram dispatch is attempted, and the command exits successfully.

**Acceptance Scenarios**:

1. **Given** a registry with no issue active for the run date, **When** the scheduled command runs, **Then** Nutmeg returns a skipped status and does not send a Telegram message.
2. **Given** a registry with disabled or malformed entries, **When** the scheduled command runs, **Then** Nutmeg ignores invalid entries, records warnings, and remains silent unless a valid active issue is found.
3. **Given** no registry file, **When** the scheduled command runs, **Then** Nutmeg skips without treating the missing registry as a fatal error.

---

### User Story 2 - Generate and send the 16:00 first report (Priority: P1)

As the operator, I want the afternoon slot to generate the first PDF report and dispatch it through Nutmeg Bot, so I can review a timely analysis after more reference data is available.

**Why this priority**: The 16:00 report is the primary daily decision input and must reuse the verified `zucai-report` workflow rather than duplicating analysis logic.

**Independent Test**: Provide a registry entry for the run date with issue/odds/override snapshots; run the auto command for `afternoon` in dry-run Telegram mode; verify a report JSON, Markdown, PDF, dispatch metadata, and run record are written under a slot-specific directory.

**Acceptance Scenarios**:

1. **Given** an active issue for the run date, **When** the `afternoon` slot runs, **Then** Nutmeg builds a 14-match report, writes artifacts, and prepares/sends the PDF according to dispatch mode.
2. **Given** the same slot is run again without force, **When** the prior run has already generated or sent a report, **Then** Nutmeg skips the duplicate and does not send again.
3. **Given** the same slot is run with force, **When** the prior run exists, **Then** Nutmeg regenerates the slot report and writes a new run record.

---

### User Story 3 - Generate the 18:30 revised confirmation report (Priority: P1)

As the operator, I want the revision slot to generate a second report after later odds/news updates, so I can compare it with the afternoon report before final participation decisions.

**Why this priority**: The user explicitly requested a 18:30 revised analysis as decision confirmation. This must be a first-class slot, not an ad hoc rerun.

**Independent Test**: Run the same active issue for `afternoon` and then `revision`; verify both slots write separate artifact directories and separate run records, and the revision caption identifies it as the revised confirmation report.

**Acceptance Scenarios**:

1. **Given** the afternoon slot has already run, **When** the `revision` slot runs, **Then** Nutmeg generates a separate PDF artifact instead of overwriting the afternoon slot.
2. **Given** revision-specific override or odds paths are present in the registry, **When** the `revision` slot runs, **Then** those paths are used for the revised report.
3. **Given** no revision-specific paths exist, **When** the `revision` slot runs, **Then** Nutmeg reuses the base snapshots and labels the report as a revision run.

---

### User Story 4 - Installable schedule templates (Priority: P2)

As the operator, I want ready-to-use local scheduler templates, so I can enable the 16:00 and 18:30 automation without hand-writing launchd or cron commands.

**Why this priority**: The user asked for a real scheduled task. Templates should make activation repeatable while keeping automatic outbound sends explicit.

**Independent Test**: Inspect the generated schedule templates and verify they call the safe `zucai-auto-run` command with the correct slots, times, project working directory, and explicit Telegram dispatch flags.

**Acceptance Scenarios**:

1. **Given** the scheduler templates, **When** the operator reviews them, **Then** they show one 16:00 job and one 18:30 job.
2. **Given** the templates are installed by the operator, **When** the scheduled time arrives, **Then** they run the same CLI command covered by tests.
3. **Given** automatic dispatch is enabled in the template, **When** the command sends a report, **Then** it is still limited to the configured Nutmeg Telegram chat ids.

### Edge Cases

- Registry file is missing, empty, malformed, or contains disabled entries.
- Registry entry references issue/odds/override files with relative paths.
- Registry entry contains base paths plus revision-specific odds/override paths.
- Sale date and active date differ; explicit `active_dates` must take precedence.
- Duplicate scheduler invocations occur for the same date/slot/issue.
- Telegram configuration is missing or sendDocument fails; artifacts and run records remain available.
- PDF rendering fails; the scheduled result records a failed dispatch or artifact warning without crashing the whole scheduler unexpectedly.
- The command runs in dry-run mode during tests or local validation and must not send outbound Telegram messages.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Nutmeg MUST expose a `zucai-auto-run` command that accepts a run date, slot, registry file, output directory, run-record file, dispatch mode, dry-run mode, and force mode.
- **FR-002**: Nutmeg MUST support exactly two named slots for v0: `afternoon` for the 16:00 first report and `revision` for the 18:30 decision-confirmation report.
- **FR-003**: Nutmeg MUST read a local issue registry and find an enabled traditional足彩 issue active for the requested run date.
- **FR-004**: If no active issue exists, Nutmeg MUST return `skipped_no_issue`, generate no PDF, and attempt no Telegram dispatch.
- **FR-005**: Nutmeg MUST resolve registry file paths relative to the registry file first and then relative to the current working directory.
- **FR-006**: Nutmeg MUST call the existing `ZucaiWorkflowService`/`zucai-report` behavior for report generation rather than duplicating recommendation logic.
- **FR-007**: Nutmeg MUST write slot-specific artifacts so afternoon and revision reports do not overwrite each other.
- **FR-008**: Nutmeg MUST record each attempted active-issue run with run date, slot, issue id, status, artifact paths, dispatch status, and warnings.
- **FR-009**: Nutmeg MUST skip duplicate date/slot/issue runs unless force mode is explicitly enabled.
- **FR-010**: Nutmeg MUST allow registry entries to provide revision-specific odds and override files for the `revision` slot.
- **FR-011**: Nutmeg MUST include slot labels in Telegram captions so the operator can distinguish first and revised reports.
- **FR-012**: Nutmeg MUST keep Telegram dispatch dry-run by default and require explicit `--dispatch-telegram --no-dry-run` for real sends.
- **FR-013**: Nutmeg MUST provide local scheduler templates for 16:00 and 18:30 jobs that invoke `zucai-auto-run` with the proper slot.
- **FR-014**: Nutmeg MUST document how to enable, validate, and troubleshoot the scheduled delivery workflow.
- **FR-015**: Nutmeg MUST preserve responsible-use boundaries: no betting execution, no sportsbook connection, no guaranteed-profit language.

### Key Entities *(include if feature involves data)*

- **Zucai Schedule Slot**: Named scheduled run type with a human label and expected local time.
- **Zucai Issue Registry**: Local file listing candidate issues, active dates, snapshot paths, and optional revision-specific paths.
- **Zucai Scheduled Run Record**: Durable local record for one date/slot/issue attempt, including status, artifacts, dispatch, and warnings.
- **Zucai Scheduled Result**: CLI-facing summary returned by one auto-run invocation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Running the command against a no-issue registry exits successfully with `skipped_no_issue` and no Telegram dispatch metadata.
- **SC-002**: Running the afternoon slot against a bundled active sample generates one 14-match PDF report and writes a run record.
- **SC-003**: Running the revision slot for the same sample creates a separate slot directory and a caption that identifies the revision report.
- **SC-004**: Re-running the same date/slot/issue without force returns `skipped_duplicate` and does not send again.
- **SC-005**: Focused service/CLI tests and full repository verification pass after implementation.

## Assumptions

- v0 uses a local issue registry rather than live official-site parsing. A later source-parser spec can populate this registry automatically.
- Scheduled times use the machine's local timezone; the user's target operation timezone is Asia/Shanghai.
- Real Telegram sends are enabled by scheduler configuration only after the operator installs or activates the provided templates.
- The report JSON and Markdown remain canonical records; PDF is the delivery artifact.
