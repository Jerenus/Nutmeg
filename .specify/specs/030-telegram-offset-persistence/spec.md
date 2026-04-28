# Feature Specification: Telegram Offset Persistence

**Feature Branch**: `030-telegram-offset-persistence`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: Make Telegram polling usable without manually remembering `--offset` after each restart.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Persist processed Telegram offset (Priority: P1)

As the private operator, I want the Telegram daemon to save `next_offset` after every poll so restarts do not reprocess old updates.

**Independent Test**: Inject a temp offset store and fake runner into `TelegramPollingDaemon`, run two polls, and verify the offset file contains the latest `next_offset`.

### User Story 2 - Resume from stored offset by default (Priority: P1)

As the operator, I want `telegram-bot-run` to use the stored offset automatically when `--offset` is omitted.

**Independent Test**: Monkeypatch the daemon builder and default offset store path, run `telegram-bot-run --max-polls 1 --format json`, and verify the daemon receives the stored offset.

### User Story 3 - Override offset explicitly when needed (Priority: P2)

As the operator, I want manual recovery control with `--offset` while still persisting the next offset after processing.

**Independent Test**: Run the CLI with `--offset 10` and a stored offset of 99, then verify the explicit offset wins.

## Functional Requirements

- **FR-001**: The default offset file MUST live under the configured Nutmeg data directory and be created automatically when needed.
- **FR-002**: `telegram-bot-run` MUST read the stored offset when `--offset` is omitted.
- **FR-003**: Explicit `--offset` MUST override the stored value.
- **FR-004**: The daemon MUST persist `next_offset` after every successful poll where a next offset exists.
- **FR-005**: JSON output MUST include whether persistence was enabled, the offset source, and the offset file path without leaking secrets.
- **FR-006**: Invalid/missing offset files MUST be handled safely by falling back to Telegram's default offset behavior.
