# Implementation Plan: OpenClaw Telegram Bridge

**Branch**: `036-openclaw-telegram-bridge` | **Date**: 2026-04-26 | **Spec**: `.specify/specs/036-openclaw-telegram-bridge/spec.md`

## Summary

Add an OpenClaw-facing operational bridge over the existing Nutmeg CLI. The bridge
does not replace Nutmeg's services and does not mutate OpenClaw bindings. It
provides documentation and a constrained router so an OpenClaw Telegram agent can
invoke Nutmeg safely.

## Architecture

- `docs/integrations/openclaw-telegram-command-manual.md`: full Telegram intent
  and command contract.
- `docs/integrations/openclaw-nutmeg-agent-instruction.md`: short OpenClaw agent
  instruction.
- `docs/integrations/openclaw-botfather-commands.txt`: BotFather command list.
- `scripts/openclaw/nutmeg_command_router.py`: allowlisted command router with
  validation, confirmation gates, execution lock, and JSON envelope output.
- `tests/test_openclaw_router.py`: command mapping and safety tests.

## Testing

Use test-first router tests with mocked subprocess execution for envelope
behavior. Use live local smoke only for safe demo commands.

## Constraints

- Do not expose secrets.
- Do not let OpenClaw execute arbitrary shell.
- Do not run Nutmeg's Telegram daemon when OpenClaw owns the same bot token.
- Keep all live/write/dispatch actions behind explicit confirmations.
