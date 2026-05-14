# JCZQ Web Cockpit Design

## Goal

Build a local-first Web cockpit for the full JCZQ daily decision lifecycle: generate a frozen brief, manage GPT/Claude/human debate, build versioned A-E/D2 tickets through structured forms, export final Markdown/JSON artifacts, run structured next-day review, and feed strategy-memory iteration.

This is a decision-workflow application, not an automated betting executor. It must preserve the current CLI/Markdown workflow while adding a SQLite-backed local Web app that makes the workflow auditable, repeatable, and easier to review.

## Product Scope

The MVP is a **local personal workstation**.

- The server binds to `127.0.0.1` by default.
- No login, multi-user auth, LAN exposure, token auth, user accounts, sessions, or permissions in MVP.
- The design should not make future token auth impossible.
- Direct wager placement, sportsbook account integration, guaranteed-profit claims, and remote SaaS features are out of scope.

## Technical Stack

- Backend: FastAPI.
- Frontend: Jinja templates with HTMX for incremental form updates.
- Database: SQLite, stored under the selected JCZQ output directory.
- Artifacts: existing `.nutmeg-data/jczq/daily/YYYY-MM-DD/...` Markdown/JSON files remain visible and first-class.
- No React/Vite SPA and no Streamlit/Gradio prototype in MVP.

## Data Ownership

The MVP is **SQLite-first for structured application state** and **artifact-preserving for audit/model collaboration**.

SQLite stores structured state used by Web pages, validation, review, and reporting:

- Daily workspace status and timestamps.
- Match list, role tags, goal lines, coinflip/comfort/strong-banker flags.
- Odds snapshot fields surfaced by the daily brief.
- HAD implied probabilities and prior gaps.
- Poisson candidate legs and edge values.
- Auto-ticket candidates.
- GPT/Claude/human analysis metadata and content snapshots.
- Ticket versions, tickets, legs, stakes, odds, theoretical returns, best-pick flags, and extra-budget flags.
- Rule validation findings.
- Review results at ticket and leg level.
- Decision events.

Markdown/JSON artifacts remain visible and are never hidden or removed by the Web app:

- `brief.md`
- `shared-brief.md`
- `gpt-analysis.md`
- `claude-analysis.md`
- `human-notes.md`
- `disagreements.md`
- `final-plan.md`
- `final-plan.json`
- `decision-log.json`
- `review.md` when present

The Web app starts building SQLite state from the first day it is used. Historical `.nutmeg-data` backfill is explicitly out of MVP scope. Existing historical directories remain readable as files but are not auto-imported.

If SQLite state and artifacts diverge for the current day, the UI must surface an artifact drift warning instead of silently overwriting either side.

## Daily Lifecycle

Each day is represented by a state machine:

```text
empty
→ brief_generated
→ workspace_initialized
→ gpt_submitted
→ claude_submitted
→ compared
→ human_discussing
→ finalized
→ reviewed
```

The Web app may run local lifecycle tasks directly and must record task status, logs, errors, and decision events. Supported MVP actions:

- Generate today's brief through the existing daily brief service/script.
- Initialize debate workspace through `JczqDebateWorkspaceService.initialize_workspace`.
- Save GPT/Codex analysis and Claude analysis content.
- Compare analyses through `JczqDebateWorkspaceService.compare_workspace`.
- Save human notes.
- Build/finalize ticket versions through the structured Plan Builder.
- Export `final-plan.md` and `final-plan.json` from SQLite ticket state.
- Run or supplement next-day review.

Network-backed odds fetching is allowed only through the existing daily brief path. Failures must be visible and must not produce guessed recommendations.

## Page Model

The MVP exposes these pages:

### Dashboard

Shows daily workspaces and current status for today and recent dates created after Web launch.

Required information:

- Date.
- Lifecycle status.
- Brief generated at.
- Debate workspace status.
- GPT/Claude/human content status.
- Final plan version.
- Review status.
- Action buttons for allowed next steps.

### Daily Workspace

The daily workspace has sections or tabs for:

- Brief.
- Match Board.
- Debate Room.
- Plan Builder.
- Final Plan.
- Review Lab.

### Brief Viewer

Shows both the raw brief artifact and structured data loaded into SQLite.

Required structured views:

- Match table.
- Bucket counts and flags.
- Poisson +EV legs.
- Strong-opposition legs.
- Auto tickets.
- Rules and diagnostics present in the brief.

### Match Board

Shows one card per match with:

- Match number, league, teams, role, goal line.
- Tags such as comfort, strong banker, coinflip, high volatility, Poisson alpha, low-goal, open-rhythm, contrarian candidate.
- Candidate legs and model signals available for Plan Builder.

### Debate Room

Uses the semi-automatic agent workflow:

- GPT/Codex analysis may be written by the local agent or pasted into the Web UI.
- Claude analysis is manually pasted into the Web UI or saved to `claude-analysis.md`.
- Direct API calls to OpenAI or Claude are out of MVP scope.

Required capabilities:

- Display shared brief hash/path.
- Edit/save GPT analysis.
- Edit/save Claude analysis.
- Edit/save human notes.
- Run compare.
- Display consensus, GPT-only, Claude-only, dropped/strong-opposed legs, and conflict matches.
- Preserve `human-notes.md`; never overwrite it automatically.

### Plan Builder

The Plan Builder is **structured-first**.

- Ticket data is entered and edited through forms backed by SQLite.
- `final-plan.md` and `final-plan.json` are generated artifacts, not the primary editing surface.
- Human rationale and discussion fields may use Markdown.
- Supported ticket ids in MVP: A, B, C, D, E, D2.
- Supported fields: ticket id, kind, name, stake, best-pick flag, extra-budget flag, rationale, legs.
- Supported leg fields: match number, league, home team, away team, pool, play, pick, odds, goal line, Poisson edge, note.
- The system automatically computes total odds and theoretical return.
- Every finalization creates a version, e.g. `v1`, `v2`, `v3`.
- Current final version is exported to `final-plan.md` and `final-plan.json`.

### Final Plan Viewer

Displays the current final version and generated artifacts.

Required information:

- Version.
- Source/actor.
- Tickets ordered safest to wildest.
- Stake allocation.
- Best pick.
- Total odds and theoretical returns.
- Validation findings.
- Decision log.
- Links/paths to generated artifacts.

### Review Lab

The Review Lab provides structured next-day review and allows manual correction.

Required behavior:

- Run the existing `jczq-daily-review` flow where possible.
- Record ticket-level and leg-level review rows.
- Allow manual entry/correction of match results and leg settlement status when automatic data is missing or incomplete.
- Record actual return, profit/loss, failed leg, strategy tags, and human review notes.
- Export or update review artifacts.
- Update SQLite state and strategy-memory summary when review is confirmed.

## Validation Policy

Validation is two-tiered.

### Hard Rules

Hard-rule violations block ticket save/finalization:

- Missing date, ticket id, match number, pool, pick, odds, or stake.
- Odds are not positive numbers.
- Stake is negative.
- A ticket contains mutually exclusive legs.
- A ticket contains illegal same-match combinations.
- HAD odds `<= 1.40` enter A/B/C ticket kinds.
- Coinflip matches use HAD legs in A-D.
- HHAD legs have no explicit goal line.
- A-D tickets use hafu legs.
- Poisson strong-opposition legs with edge `<= -20%` enter A-D.
- Final plan budget is inconsistent unless a ticket is explicitly marked `extra_budget`.

### Soft Warnings

Soft-rule warnings are shown but may be accepted by the human decision maker:

- Same match repeated across too many tickets.
- Narrative is overly concentrated.
- Poisson edge between `-15%` and `-20%`.
- High-odds leg lacks model support.
- Multiple favorite-collapse legs are chained in one ticket.
- Extreme ticket overuses `0:0` scorelines.
- Poisson solo is diluted by a second leg.
- Strategy-memory sample size is too small.

## Narrative And Correlation Diagnostics

The MVP should include simple deterministic diagnostics that can run on ticket drafts:

- Narrative tags per leg and ticket.
- Ticket-level narrative concentration warning.
- Cross-ticket match exposure warning.
- Same-match mutual exclusion detection for obvious combinations.
- Reverse-cover warning, such as one ticket using `001 平` while another uses `001 主胜`.

These diagnostics are advisory unless they overlap with a hard rule.

## Persistence Model

The SQLite schema should support these core concepts:

- `jczq_days`: daily workspace status.
- `jczq_matches`: structured match rows.
- `jczq_candidate_legs`: structured candidate legs.
- `jczq_analyses`: GPT/Claude/human analysis records.
- `jczq_ticket_versions`: final-plan versions.
- `jczq_tickets`: tickets within a version.
- `jczq_ticket_legs`: legs within a ticket.
- `jczq_validation_findings`: hard and soft validation results.
- `jczq_decision_events`: append-only lifecycle and human decision log.
- `jczq_reviews`: ticket-level review rows.
- `jczq_leg_reviews`: leg-level review rows.

The implementation may use the Python standard `sqlite3` module for MVP. SQLAlchemy is optional but not required.

## Non-Goals

The MVP must not include:

- User accounts or login.
- LAN deployment or SaaS deployment.
- OpenAI/Claude automatic API calls.
- Automated betting or wager execution.
- Historical artifact backfill.
- React/Vite SPA.
- Drag-and-drop ticket editing.
- Multi-user collaboration.
- Cross-bookie reference odds.
- Scheduled odds drift collection.

## Acceptance Criteria

1. A local FastAPI app can be created and bound to localhost.
2. The Dashboard shows a daily workspace created from Web usage.
3. A user can generate or load a daily brief and initialize a debate workspace.
4. Structured match and candidate leg data are stored in SQLite from launch-day workflows.
5. GPT/Claude/human analysis can be saved and rendered through the Web UI.
6. The Web UI can run comparison and show disagreement output.
7. A user can build A/B/C/D/E/D2 tickets through forms backed by SQLite.
8. Total odds and theoretical return are computed automatically.
9. Hard-rule violations block ticket save/finalization.
10. Soft warnings are shown without blocking finalization.
11. Finalization creates a version and exports `final-plan.md` and `final-plan.json`.
12. Review Lab can record structured ticket/leg results and manual corrections.
13. Existing Markdown/JSON artifacts remain visible under `.nutmeg-data` and are not hidden or deleted.
14. Tests cover storage, validation, ticket calculations, service lifecycle operations, and core Web routes.
