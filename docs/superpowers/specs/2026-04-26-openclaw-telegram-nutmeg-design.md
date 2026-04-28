# OpenClaw Telegram Nutmeg Integration Design

Date: 2026-04-26

## Purpose

Expose Nutmeg's completed CLI-first football analysis system through an
OpenClaw-managed Telegram bot without duplicating football logic inside
OpenClaw. OpenClaw acts as the conversational operator and invokes Nutmeg through
a constrained command router.

## Decision

Use OpenClaw as the Telegram entrypoint and Nutmeg as the execution engine:

```text
Telegram -> OpenClaw agent -> Nutmeg command manual -> safe router -> uv run nutmeg ... --format json
```

This is safer than giving OpenClaw unrestricted shell access. The router owns
the allowlist, argument validation, serialization lock, and JSON response
envelope. Nutmeg keeps the source of truth for fixtures, snapshots, odds,
analysis, value board, player profiles, daily operation, and tactical visuals.

## Scope

In scope:

- Complete OpenClaw-readable command manual.
- OpenClaw agent instruction for Telegram behavior.
- BotFather `/setcommands` command list.
- Safe Python router under `scripts/openclaw/`.
- Tests for command allowlisting, validation, live/write confirmations, and
  subprocess envelope behavior.
- OpenClaw Telegram account/agent wiring through official OpenClaw CLI.

Out of scope for this slice:

- Running a long-lived OpenClaw daemon from this repository.
- Building a Web UI.

## Safety Rules

- OpenClaw must not invoke arbitrary shell commands for Nutmeg.
- Commands must be routed through `scripts/openclaw/nutmeg_command_router.py`.
- Live provider sync requires an explicit confirmation flag.
- Telegram dispatch and prediction writes require explicit confirmation flags.
- Router executions are serialized with a file lock to avoid DuckDB single-file
  lock conflicts.
- Responses must be summarized in Chinese; raw JSON is for diagnostics only.

## Success Criteria

- A human or OpenClaw agent can read the manual and map common Telegram requests
  to exact Nutmeg commands.
- The router can print commands without executing them.
- The router rejects unknown commands and unsafe live/write actions without
  confirmation.
- The router can execute a safe demo command and emit a machine-readable JSON
  envelope.
- OpenClaw has a `nutmeg` Telegram account bound to a `nutmegbot` agent without
  exposing tokens.
