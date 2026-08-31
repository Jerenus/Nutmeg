# Phase-Aware Operator Workbench Evidence

Date: 2026-08-31  
Branch: `feat/phase-aware-operator-workbench`  
Base: `main` at `5e3c813`  
Verified head before this evidence commit: `904150c`  
Runtime: Python 3.13.11 through `uv`

## Delivered slices

- `dee4b16` `docs(product): plan phase-aware operator workbench`
- `b350d33` `feat(product): define operator workbench contracts`
- `ad7405a` `feat(product): parse current operator artifacts`
- `a2e6d99` `feat(product): resolve current operator task`
- `e1189fb` `feat(product): assemble phase-aware operator tasks`
- `e760734` `feat(product): expose governed operator actions`
- `d219158` `feat(product): open focused operator workbench`
- `f7c0219` `feat(product): guide judgment and ticket comparison`
- `f8121ab` `feat(product): present governed deployment gate`
- `0d5f69f` `feat(product): surface protected confirmation lifecycle`
- `4f04d39` `feat(product): guide judge-only postmatch review`
- `c131343` `feat(product): explain evidence and recovery states`
- `aeb605d` `test(product): cover operator workbench in browser`
- `904150c` `fix(product): recognize resolved rx adjudications`

## Automated verification

Focused operator suite:

```bash
UV_FROZEN=1 uv run pytest \
  tests/product/test_operator_contracts.py \
  tests/product/test_operator_artifacts.py \
  tests/product/test_operator_state.py \
  tests/product/test_operator_queries.py \
  tests/product/test_operator_actions.py \
  tests/product/test_operator_api.py \
  tests/product/test_operator_ui.py \
  tests/product/test_operator_e2e.py \
  tests/product/test_operator_browser.py -q
```

Result: 113 tests collected and passed. The only warnings were two upstream
`websockets`/uvicorn deprecations; there were no unawaited-work or leaked-resource
warnings.

Affected domain and legacy product regression:

```bash
UV_FROZEN=1 uv run pytest \
  tests/decision/test_zucai_optimizer.py \
  tests/decision/test_zucai_deployment.py \
  tests/decision/test_legs_audit.py \
  tests/ontology/test_workflow_actions.py \
  tests/ontology/test_protected_ticket_actions.py \
  tests/ontology/test_telegram_confirmation_e2e.py \
  tests/product/ -q
```

Result: 399 tests collected and passed.

Five-domain completion gate:

```bash
UV_FROZEN=1 uv run pytest \
  tests/decision/ tests/ontology/ tests/product/ tests/analytics/ tests/migration/ -q
```

Result: 1,014 tests collected and passed.

Repository quality gates:

```bash
UV_FROZEN=1 uv run ruff check .
UV_FROZEN=1 uv run python -m compileall nutmeg tests
UV_FROZEN=1 uv run pre-commit run --all-files
```

Result: ruff passed, compileall exited 0, and all four pre-commit hooks passed.

## Governed lifecycle evidence

`test_operator_confirmation_books_one_and_timeout_explains_shadow` drives the actual
protected confirmation service and Telegram bot runner with a fake client. It records:

- one owner callback handled;
- one ticket placement and one cash transaction;
- one ledger debit equal to the bound audited artifact amount;
- `confirm_ticket_placement` committed by `judge_operator`;
- one sibling confirmation expired and exactly one shadow recorded;
- the expired task rendered `未确认，按未出票处理` and `没有入账`.

The temporary read/write replay at `/tmp/nutmeg-operator-verify.LHIESV` also completed
the existing operational chain without production mutation:

```text
decision-sense: 25 matches
decision-backfill: 49 market baseline shadows
decision-settle: 49 Read+Ticket settlements
calibrate: 0 factor verdicts
PDF: 68097 bytes
decision-close: 0 tickets / CNY 0, dry-run
```

## Read-only production smoke

The acceptance process was started against the production data directory without any
POST request:

```bash
NUTMEG_DATA_DIR=/Users/jz71/Projects/Nutmeg/.nutmeg-data \
  uv run nutmeg app --host 127.0.0.1 --port 8790
```

Observed operator projection:

```text
selected.task_id = zucai:26112
selected.state = judge_matches
selected.deadline_at = 2026-08-28T22:00:00+08:00
current item = ADJ-4
selected option = 开赛前首发公布时复核(01:00-03:00 BJ)
primary action = 保存并进入下一步
```

`GET /api/v1/operator/tasks` returned valid versioned JSON. The maintenance route
`GET /system/command-center?date=2026-08-28` returned HTTP 200.

Production Playwright screenshots:

- `/Users/jz71/.openclaw/tmp/nutmeg-operator-acceptance-20260831/production-26112-1440x900.png`
  (198,505 bytes)
- `/Users/jz71/.openclaw/tmp/nutmeg-operator-acceptance-20260831/production-26112-390x844.png`
  (170,138 bytes)

Both viewports passed the explicit geometry checks: no horizontal escape, header/phase/
main separation, full-width long-title wrapping, evidence before the form, a 48 px
primary action contained inside the viewport, and no console/page errors. Visual review
confirmed that the real ADJ-4 title, evidence, controls, and button do not overlap.
Normal workflow text contained no raw JSON, `pre`, schema health strip, Action ID,
content hash, or forecast revision ID.

## Safety and authority

Verification performed no production POST, real Telegram dispatch, real placement,
funds action, scoreboard write/cutover, launchd change, or automated ticket selection.
The browser did not submit the visible form. `ConfirmDispatch` remains owner-only;
judgment, candidate choice, deployment adjudication, and grading remain explicit
`judge_operator` actions. Empty position is exposed only where the deterministic gate or
an explicit material-indistinguishability adjudication permits it.

## Approved-design deviations

1. JCZQ enters this workbench from existing protected ticket artifacts, so its current
   implemented phases begin at confirmation/ledger/result. No second JCZQ issue/prep/rx
   artifact source was invented. Zucai implements the full artifact-driven judgment,
   ticket comparison, audit, deployment, confirmation, ledger, and review projection.
2. Browser acceptance used the repository's installed Python Playwright client because
   the session did not expose the in-app Node REPL browser-control entry point. It drove
   the same local Chromium engine at the approved desktop/mobile viewports and added
   explicit production geometry and console assertions.

There are no other known deviations from the approved design.
