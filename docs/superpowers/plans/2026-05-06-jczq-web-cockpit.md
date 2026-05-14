# JCZQ Web Cockpit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build the MVP local FastAPI/Jinja/HTMX/SQLite JCZQ Web Cockpit described in `docs/superpowers/specs/2026-05-06-jczq-web-cockpit-design.md`.

**Architecture:** Add a focused SQLite repository for structured daily state, a service layer that bridges existing JCZQ brief/debate/review artifacts, a validator for hard/soft ticket findings, and a FastAPI app with server-rendered pages and form endpoints. The implementation preserves `.nutmeg-data` Markdown/JSON artifacts and exports final plans from structured ticket state.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, HTMX-style forms, sqlite3, pytest, Typer CLI.

---

## File Structure

- Create `nutmeg/storage/jczq_web_repository.py`: SQLite schema, CRUD, versioned tickets, review persistence.
- Create `nutmeg/services/jczq_web.py`: application service, brief ingestion, debate integration, ticket validation/finalization, artifact rendering, review recording.
- Create `nutmeg/interfaces/jczq_web.py`: FastAPI app factory and routes.
- Create `nutmeg/interfaces/web/templates/jczq/*.html`: local cockpit templates.
- Create `nutmeg/interfaces/web/static/jczq/app.css`: minimal local-first styling.
- Modify `nutmeg/interfaces/cli.py`: optional `jczq-web` command that starts uvicorn on `127.0.0.1`.
- Create `tests/test_jczq_web_repository.py`: storage tests.
- Create `tests/test_jczq_web_service.py`: service, validation, finalization, review tests.
- Create `tests/test_jczq_web_routes.py`: FastAPI route tests.
- Append `tests/test_cli.py`: CLI launch command smoke test with monkeypatched uvicorn.

## Task 1: SQLite Repository

**Files:**
- Create: `nutmeg/storage/jczq_web_repository.py`
- Test: `tests/test_jczq_web_repository.py`

- [x] **Step 1: Write failing repository tests**

Create tests for initializing schema, upserting days, analyses, ticket versions, tickets/legs, findings, and reviews.

- [x] **Step 2: Verify RED**

Run: `uv run pytest tests/test_jczq_web_repository.py -q`
Expected: import/module missing failure.

- [x] **Step 3: Implement repository**

Use `sqlite3`, explicit schema creation, dictionary row output, and JSON strings for tags/details.

- [x] **Step 4: Verify GREEN**

Run: `uv run pytest tests/test_jczq_web_repository.py -q`
Expected: all repository tests pass.

## Task 2: Service Layer And Validation

**Files:**
- Create: `nutmeg/services/jczq_web.py`
- Test: `tests/test_jczq_web_service.py`

- [x] **Step 1: Write failing service tests**

Cover launch-day brief ingestion from Markdown, semi-automatic analysis saving, compare integration, ticket odds calculations, hard-rule blocking, soft warnings, final-plan export, and manual review persistence.

- [x] **Step 2: Verify RED**

Run: `uv run pytest tests/test_jczq_web_service.py -q`
Expected: import/module missing failure.

- [x] **Step 3: Implement service**

Expose `JczqWebCockpitService` with methods: `dashboard`, `load_brief`, `initialize_debate`, `save_analysis`, `compare_debate`, `draft_ticket_version`, `finalize_version`, `record_review`, `workspace`.

- [x] **Step 4: Verify GREEN**

Run: `uv run pytest tests/test_jczq_web_service.py -q`
Expected: all service tests pass.

## Task 3: FastAPI Routes And Templates

**Files:**
- Create: `nutmeg/interfaces/jczq_web.py`
- Create: `nutmeg/interfaces/web/templates/jczq/layout.html`
- Create: `nutmeg/interfaces/web/templates/jczq/dashboard.html`
- Create: `nutmeg/interfaces/web/templates/jczq/workspace.html`
- Create: `nutmeg/interfaces/web/templates/jczq/partial_status.html`
- Create: `nutmeg/interfaces/web/static/jczq/app.css`
- Test: `tests/test_jczq_web_routes.py`

- [x] **Step 1: Write failing route tests**

Use FastAPI `TestClient` to assert dashboard, workspace, save-analysis, compare, draft-ticket, finalize, and review routes call service and render expected content.

- [x] **Step 2: Verify RED**

Run: `uv run pytest tests/test_jczq_web_routes.py -q`
Expected: app factory missing failure.

- [x] **Step 3: Implement routes/templates**

Use Jinja pages and plain forms. Keep design minimal but usable: daily status, brief, analyses, ticket forms, validation findings, final plan paths, and review form.

- [x] **Step 4: Verify GREEN**

Run: `uv run pytest tests/test_jczq_web_routes.py -q`
Expected: all route tests pass.

## Task 4: CLI Entrypoint

**Files:**
- Modify: `nutmeg/interfaces/cli.py`
- Modify: `tests/test_cli.py`

- [x] **Step 1: Write failing CLI test**

Add a test that monkeypatches `uvicorn.run`, invokes `nutmeg jczq-web --output-dir <tmp> --host 127.0.0.1 --port 8765`, and asserts uvicorn receives the FastAPI app object and localhost host.

- [x] **Step 2: Verify RED**

Run: `uv run pytest tests/test_cli.py::test_jczq_web_command_starts_localhost_app -q`
Expected: command missing failure.

- [x] **Step 3: Implement command**

Create repository/service/app and call `uvicorn.run(app, host=host, port=port)` with default host `127.0.0.1`.

- [x] **Step 4: Verify GREEN**

Run: `uv run pytest tests/test_cli.py::test_jczq_web_command_starts_localhost_app -q`
Expected: test passes.

## Task 5: Full Verification

**Files:**
- All created/modified files.

- [x] **Step 1: Run focused tests**

Run: `uv run pytest tests/test_jczq_web_repository.py tests/test_jczq_web_service.py tests/test_jczq_web_routes.py tests/test_cli.py::test_jczq_web_command_starts_localhost_app -q`
Expected: all focused tests pass.

- [x] **Step 2: Run broader safety tests**

Run: `uv run pytest tests/test_jczq_debate_service.py tests/test_cli.py::test_jczq_debate_init_command_creates_workspace tests/test_cli.py::test_jczq_debate_compare_command_returns_conflicts tests/test_cli.py::test_jczq_debate_finalize_command_writes_final_plan -q`
Expected: existing debate tests still pass.

- [x] **Step 3: Compile and diff checks**

Run: `python3 -m compileall nutmeg` and `git diff --check`.
Expected: compile succeeds and diff has no whitespace errors.

## Spec Coverage Self-Review

- Local personal workstation: Task 3/4 implement localhost app and CLI defaults.
- SQLite-first state: Task 1/2 implement repository/service persistence.
- Artifacts preserved: Task 2 finalization writes artifacts without deleting existing files.
- Semi-automatic debate: Task 2/3 save analysis and compare.
- Structured-first Plan Builder: Task 1/2/3 ticket forms and version tables.
- Hard/soft validation: Task 2 service tests and validator.
- Review Lab: Task 1/2/3 review rows and form.
- Tests: Tasks 1-5 cover storage, service, routes, CLI, and regression checks.


## Verification Evidence

Completed on 2026-05-06 with these fresh checks:

- `uv run pytest tests/test_jczq_web_repository.py tests/test_jczq_web_service.py tests/test_jczq_web_routes.py tests/test_cli.py::test_jczq_web_command_starts_localhost_app -q` → 11 passed.
- `uv run pytest -q` → full test suite passed.
- `uv run ruff check nutmeg/storage/jczq_web_repository.py nutmeg/services/jczq_web.py nutmeg/interfaces/jczq_web.py tests/test_jczq_web_repository.py tests/test_jczq_web_service.py tests/test_jczq_web_routes.py tests/test_cli.py` → all checks passed.
- `python3 -m compileall nutmeg` → compile succeeded.
- `git diff --check` → no whitespace errors.
