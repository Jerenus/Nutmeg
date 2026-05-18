# Project Repair Design — Betting Assistant Consolidation Follow-up

- **Date**: 2026-05-18
- **Status**: Approved for implementation by operator
- **Scope**: Repair the weekend consolidation so the repository consistently behaves as a focused JCZQ/Zucai betting assistant and keeps OpenClaw integration honest.

## Goal

Restore trust in the current project surface after the consolidation: live workflows should either work or fail loudly with the correct replacement path; OpenClaw must not advertise deleted commands; value-engine signals must map to JCZQ outcomes correctly; R28 retirement must be reflected across daily tooling; and verification commands must be executable again.

## Decisions

1. `jczq-mixed-report` is no longer the live production workflow. Its sample mode remains for the original 046 historical smoke test. Live mode exits with a clear retirement message directing the operator to `jczq-daily-brief -> debate -> final-plan -> PDF`.
2. OpenClaw is a first-class integration surface. Router actions must map only to real CLI commands or explicit retired responses. Deleted non-betting actions are removed from the allowlist and parser.
3. JCZQ value-engine output must be interpreted in JCZQ orientation. When API-Football aligns a fixture with swapped home/away orientation, home/away outcomes are remapped before rendering or constructing parlays.
4. R28 retirement is global. Templates and helper commands must not reconstruct `poisson_solo` / C-ticket workflows.
5. Final-plan PDF dispatch must tolerate unknown EV values. Conflict-engine plans often omit unverified EV and should still render/dispatch.
6. Verification is part of the product surface. `scripts/verify.sh` is restored as the canonical local gate and README/design docs are updated to current commands.

## Components

- **CLI**: `nutmeg/interfaces/cli/jczq.py`, `nutmeg/interfaces/cli/__init__.py`
- **OpenClaw router**: `scripts/openclaw/nutmeg_command_router.py`, `tests/test_openclaw_router.py`
- **Value bridge/parlay**: `nutmeg/services/jczq_value_bridge.py`, `nutmeg/services/jczq_parlay_constructor.py`, tests for swapped orientation
- **Debate/second-leg helpers**: `nutmeg/services/jczq_debate.py`, `nutmeg/services/jczq_second_leg.py`, related tests
- **PDF/final plan**: `nutmeg/services/jczq_final_plan_pdf.py`, tests
- **Verification/docs**: `scripts/verify.sh`, `README.md`, `DESIGN.md`, spec metadata and lint fixes

## Error Handling

- Retired live mixed-report exits code 2 with a clear replacement command path.
- Router rejects unknown/deleted actions before building commands.
- `jczq-second-leg --auto` reads an explicit solo leg if present, otherwise the favorite ticket's first leg; if no usable final plan exists, it reports how to pass `--solo` manually.
- Missing EV renders as `未知` rather than raising.

## Testing Strategy

- Add regression tests before implementation for each behavior.
- Run focused tests after each fix.
- Run final gates: `uv run ruff check .`, `uv run python -m compileall -q nutmeg scripts`, `uv run pytest`, `bash scripts/verify.sh`.
- Add OpenClaw command-existence smoke coverage so router/CLI drift is caught.
