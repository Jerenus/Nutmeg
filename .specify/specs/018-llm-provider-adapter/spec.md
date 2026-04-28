# Feature Specification: LLM Provider Adapter

**Feature Branch**: `018-llm-provider-adapter`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: Add a real but default-off LLM synthesis provider adapter behind the guarded agent synthesis seam.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Keep LLM synthesis default-off (Priority: P1)

As the Nutmeg operator, I want generated synthesis to stay disabled unless explicitly enabled and configured, so local runs do not accidentally call paid providers.

**Independent Test**: Build agent workflow settings without enable flag/key and verify no provider is injected.

### User Story 2 - Call provider through a stable adapter (Priority: P1)

As the maintainer, I want a Portkey-compatible adapter that turns deterministic analysis into a chat completion request and extracts text safely.

**Independent Test**: Use `httpx.MockTransport` to verify request headers/body and response extraction without network.

### User Story 3 - Surface provider configuration truthfully (Priority: P2)

As the operator, I want `doctor` to show whether agent synthesis is enabled/configured without revealing secrets.

**Independent Test**: CLI doctor JSON reports synthesis enabled/configured flags and selected model, not API key.
