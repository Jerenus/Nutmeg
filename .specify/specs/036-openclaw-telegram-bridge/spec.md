# Feature Specification: OpenClaw Telegram Bridge

**Feature Branch**: `036-openclaw-telegram-bridge`  
**Created**: 2026-04-26  
**Status**: Verified  
**Input**: Expose Nutmeg's completed CLI functions to an OpenClaw-managed Telegram bot through a complete command manual and safe local router.

## User Scenarios & Testing

### User Story 1 - OpenClaw can understand how to operate Nutmeg (Priority: P1)

As the operator, I want a complete command manual so OpenClaw can map Telegram
messages to Nutmeg functions without inventing commands.

**Independent Test**: Review `docs/integrations/openclaw-telegram-command-manual.md`
for supported actions, examples, safety gates, and response rules.

### User Story 2 - OpenClaw invokes Nutmeg safely (Priority: P1)

As the operator, I want a constrained router that validates actions and arguments
before executing Nutmeg CLI commands.

**Independent Test**: Run `tests/test_openclaw_router.py` and verify unknown
actions, live sync, dispatch, and write operations are gated.

### User Story 3 - Telegram bot setup is operationally clear (Priority: P2)

As the operator, I want a short OpenClaw instruction and BotFather command list
so the Telegram bot can expose predictable commands.

**Independent Test**: Read `docs/integrations/openclaw-nutmeg-agent-instruction.md`
and `docs/integrations/openclaw-botfather-commands.txt`.

## Functional Requirements

- **FR-001**: Provide an OpenClaw-readable Telegram command manual.
- **FR-002**: Provide a short OpenClaw agent instruction.
- **FR-003**: Provide a BotFather command list.
- **FR-004**: Provide a safe router script for supported Nutmeg actions.
- **FR-005**: Router MUST reject unsupported actions.
- **FR-006**: Router MUST require confirmation for live sync, writes, and real Telegram dispatch.
- **FR-007**: Router MUST serialize execution to reduce DuckDB lock conflicts.
- **FR-008**: Router output MUST be a JSON envelope.
- **FR-009**: Tests MUST cover command mapping, safety gates, name preservation, and execution envelope.
- **FR-010**: OpenClaw SHOULD be configured with a dedicated `nutmeg` Telegram account and `nutmegbot` agent binding when credentials are available.

## Success Criteria

- **SC-001**: `python3 scripts/openclaw/nutmeg_command_router.py --print-command popular --league epl --days 3` returns a JSON command envelope.
- **SC-002**: `python3 scripts/openclaw/nutmeg_command_router.py sync --league epl --days 14` fails with a confirmation error.
- **SC-003**: Router focused tests pass.
- **SC-004**: Full verification passes.

## Verification Evidence

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_openclaw_router.py -q` -> 6 passed.
- `python3 scripts/openclaw/nutmeg_command_router.py --print-command popular --league epl --days 3` -> JSON command envelope.
- `python3 scripts/openclaw/nutmeg_command_router.py sync --league epl --days 14` -> rejected with `--confirm-live` requirement.
- `python3 scripts/openclaw/nutmeg_command_router.py seed-demo --league epl` -> JSON envelope with seeded demo output.
- `python3 scripts/openclaw/nutmeg_command_router.py popular --league epl --days 3 --demo` -> JSON envelope with demo popular matches.
- `openclaw channels add --channel telegram --account nutmeg --name Nutmeg --token-file <temp-token-file>` -> added Telegram account.
- `openclaw agents add nutmegbot --workspace /Users/jz71/.openclaw/workspace --bind telegram:nutmeg --non-interactive --json` -> added agent and binding.
- Follow-up fix moved `nutmegbot` to `/Users/jz71/.openclaw/workspaces/nutmeg` because the shared workspace contains `BOOTSTRAP.md` and can hijack `/start` with identity setup prompts.
- `openclaw agents set-identity --agent nutmegbot --name "Nutmeg" --emoji "⚽" --theme "Football analysis operator" --json` -> identity set.
- Telegram `setMyCommands` -> `ok=true`, 20 commands.
- `openclaw config validate` -> config valid.
- `openclaw channels status --probe` -> Telegram `nutmeg` account reports bot `@jerenusNutmeg_bot`, tokenFile, works.
- `uv run ruff check .` -> all checks passed.
- `python3 -m compileall nutmeg scripts/openclaw` -> pass.
- `bash scripts/verify.sh` -> 181 passed.
