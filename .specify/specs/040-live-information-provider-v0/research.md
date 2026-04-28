# Research: Live Information Provider v0

## Decision: Explicit source manifest

**Decision**: v0 uses an operator-provided JSON manifest listing local paths and remote URLs. Each source carries reliability, tags, teams, fixture ids, and enabled state.

**Rationale**: A manifest provides auditability and prevents arbitrary scraping. It also gives future Telegram/OpenClaw and subscription workflows a stable config artifact.

**Alternatives considered**:

- Free-form URL CLI arguments: rejected because source metadata and reliability labels would be lost.
- Auto-discovery from websites/search: rejected as scraping and non-deterministic.
- Hard-coded source list: rejected because the operator needs local control.

## Decision: Opt-in live fetch with injected fetcher

**Decision**: Remote URLs are fetched only when `live_fetch=True`; tests inject a fake fetcher while production uses bounded HTTP GET.

**Rationale**: This preserves no-network default behavior and deterministic tests while allowing live operation when explicitly requested.

**Alternatives considered**:

- Always fetch when a URL appears: rejected because it surprises local workflows and tests.
- Shelling out to curl: rejected because it is harder to inject and validate.

## Decision: Local file cache with stale fallback

**Decision**: Remote response bodies are cached by URL hash with metadata. Fresh cache is used without network; stale cache can be used only as a partial fallback when live fetch fails.

**Rationale**: Latest information should not make daily workflows brittle. Stale fallback is useful but must be labeled.

**Alternatives considered**:

- Store cache in SQLite/DuckDB: rejected for v0 because cache entries are replaceable source artifacts, not long-term facts.
- No stale fallback: rejected because it reduces operator resilience during provider outages.

## Decision: Reuse 039 digest contract

**Decision**: Remote JSON/RSS content normalizes into existing `InformationItem`, `InformationSourceHealth`, and `FixtureInformationDigest` outputs.

**Rationale**: The AI-native client and CLI already consume this contract. Extending the parser/provider preserves compatibility.

**Alternatives considered**:

- Introduce a separate live-news payload: rejected because it would duplicate client rendering and source-ledger logic.
