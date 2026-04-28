# Feature Specification: IM Bot Adapter

**Feature Branch**: `024-im-bot-adapter`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: Continue unfinished Phase 1 interface work by adding a no-network IM bot adapter skeleton that can route text commands to the existing operator match brief workflow.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Parse match brief bot messages (Priority: P1)

As the private operator, I want a simple IM-style message like `/brief epl-001 Should I back Arsenal?` to be parsed into a fixture id and query.

**Independent Test**: Call the parser with valid/invalid messages and verify structured commands or truthful unsupported-command errors.

### User Story 2 - Execute a bot match brief through existing workflow (Priority: P1)

As the private operator, I want the bot adapter to reuse the existing guarded agent workflow and render a compact message-safe response.

**Independent Test**: Inject a stub workflow, process a `/brief` message, and verify the response contains match title, verdict, confidence, reasons, caveats, and agent nodes.

### User Story 3 - Provide no-network CLI dry-run (Priority: P1)

As the maintainer, I want a CLI command that exercises the bot adapter locally without connecting to Telegram/Discord.

**Independent Test**: Stub the workflow behind `nutmeg bot-dry-run`, verify text and JSON output, and verify failures exit non-zero with the error.
