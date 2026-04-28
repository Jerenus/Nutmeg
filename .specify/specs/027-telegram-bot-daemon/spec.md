# Feature Specification: Telegram Bot Daemon

**Feature Branch**: `027-telegram-bot-daemon`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: Continue Telegram bot work by adding a controlled polling daemon loop on top of `telegram-bot-poll-once`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run repeated polling safely (Priority: P1)

As the private operator, I want a polling loop that repeatedly calls the existing Telegram runner, advances offsets, sleeps between polls, and reports aggregate counts.

**Independent Test**: Inject a fake runner and sleep function, run with `max_polls=2`, and verify two poll calls, next offset propagation, aggregate counts, and sleep calls.

### User Story 2 - Stop gracefully on interruption (Priority: P1)

As the operator, I want Ctrl-C / KeyboardInterrupt to produce a truthful summary instead of a stack trace.

**Independent Test**: Fake a runner that raises `KeyboardInterrupt` after one poll and verify the daemon returns an interrupted summary with prior counts preserved.

### User Story 3 - Expose controlled CLI daemon mode (Priority: P1)

As the maintainer, I want a CLI command for running the daemon with `--max-polls` for local/cron validation and JSON output.

**Independent Test**: Monkeypatch the daemon builder, run `telegram-bot-run --max-polls 2 --format json`, and verify summary fields and no token leakage.
