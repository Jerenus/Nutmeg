# Research: Content Publisher v0

## Decision: Use Zucai report JSON as the v0 input contract

**Rationale**: Existing Zucai modules already parse issue data, merge odds/overrides, compute recommendations, write reports, schedule delivery, and verify sample data. Consuming the report JSON avoids duplicating betting-analysis logic and keeps content production as a separate publisher layer.

**Alternatives considered**:
- Parse issue/odds files directly: rejected because it would duplicate recommendation assembly.
- Depend on scheduled delivery run records: rejected because content should work for ad hoc reports too.
- Start from generic fixtures only: rejected because the PRD specifically targets traditional Zucai analysis results.

## Decision: Separate candidate scoring from content generation

**Rationale**: Scoring is deterministic, testable, and auditable. LLM generation is creative and variable. Separating the two lets the operator see why a match was selected before judging generated copy.

**Alternatives considered**:
- Let the LLM pick matches: rejected because topic selection needs repeatable reliability and explicit scoring dimensions.
- Pick only highest confidence matches: rejected by PRD; content-worthiness is not the same as prediction confidence.

## Decision: Use OpenClaw CLI adapter behind an LLM provider seam

**Rationale**: The user asked to use the current OpenClaw LLM connection. The adapter calls `openclaw infer model run --json --model <model> --prompt <prompt>` and extracts output text. Tests inject fake providers and do not call OpenClaw.

**Alternatives considered**:
- Direct OpenAI/Portkey HTTP calls: rejected because user requested OpenClaw and local OpenClaw already owns model/provider configuration.
- Agent conversation through `openclaw agent`: rejected because agent prompts/tool policies are optimized for Telegram operation, not a clean one-shot content-generation contract.
- No LLM/deterministic templates only: rejected because the workflow is intentionally LLM-heavy.

## Decision: Compliance checker is local and deterministic after LLM output

**Rationale**: Compliance cannot rely on the same creative model that generated the copy. The PRD red lines are deterministic enough for a local rule engine that classifies blocked phrases, high-risk certainty/stimulus words, medium-risk odds/model tendencies, and disclaimer presence.

**Alternatives considered**:
- LLM-only compliance review: rejected because it is less reproducible and harder to test.
- Manual-only review: rejected because the system must output `risk_level` and `risk_reasons` for every content pack.

## Decision: Artifact boundary replaces auto-publishing in v0

**Rationale**: The PRD excludes automatic publishing in MVP. JSON and Markdown files provide a safe handoff for human review and later platform-specific automation.

**Alternatives considered**:
- Direct Douyin/Zhihu/WeChat posting: rejected as out of MVP scope and higher compliance/platform risk.
- Only stdout output: rejected because review/archive workflows need durable artifacts.
