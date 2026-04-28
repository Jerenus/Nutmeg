# Content Publisher v0 Design

## Goal

Turn Nutmeg's existing traditional Zucai analysis output into compliant, human-reviewable sports-analysis content drafts for platforms such as Douyin, WeChat official accounts, Zhihu, and future vertical football communities.

The module does not answer "怎么买". It answers: "这场为什么值得关注，关键变量是什么，公开数据能说明什么，还有哪些不确定性？"

## Recommended Approach

Use a separate content publisher layer:

```text
Zucai report JSON
-> deterministic candidate scoring
-> OpenClaw LLM structured generation
-> schema validation and disclaimer enforcement
-> deterministic compliance gate
-> JSON/Markdown human-review artifacts
```

This is better than embedding content generation into Zucai because Zucai should remain the analysis/report workflow, while content publishing has different concerns: topic selection, platform copywriting, compliance, and artifact handoff.

## Alternatives Considered

1. **LLM-only selector/generator**: Faster to prototype, but weak auditability and hard to verify.
2. **Template-only content**: Very safe and testable, but does not meet the user's LLM-heavy workflow goal.
3. **Independent content publisher with LLM provider seam**: Recommended. It keeps deterministic gates around creative generation and uses OpenClaw as the live model interface.

## Components

- `nutmeg.domain.content`: candidate, draft, checklist, assessment, pack, batch, artifact dataclasses.
- `nutmeg.services.content`: report loading, candidate scoring, prompt building, OpenClaw provider, LLM JSON extraction, fallback draft generation, compliance checks, artifact rendering.
- `nutmeg.interfaces.cli content-pack`: CLI contract for local use and future OpenClaw router wrapping.
- `docs/architecture/content-publisher.md`: workflow gates and compliance boundary.

## Reliability Gates

1. **Input gate**: Load a Zucai report JSON and require usable issue/match/recommendation structure.
2. **Selection gate**: Score every match using explicit dimensions; selected candidates carry `selection_reason`.
3. **LLM schema gate**: The LLM must return JSON fields. Parser can extract fenced/prose-wrapped JSON; missing fields are filled with conservative safe defaults and warnings.
4. **Disclaimer gate**: Required short and long disclaimers are appended before compliance assessment.
5. **Compliance gate**: Local deterministic rules classify `LOW | MEDIUM | HIGH | BLOCKED` and map to `publish | review | skip`.
6. **Artifact gate**: v0 writes review artifacts only. No external platform receives content automatically.

## Scope Boundaries

In scope:
- 1-3 selected matches from a Zucai report.
- Douyin 60-second oral script.
- WeChat/Zhihu long-form article.
- Five safe title candidates.
- Compliance checklist, risk reasons, and publish recommendation.
- JSON and Markdown artifacts.

Out of scope:
- Direct Douyin/WeChat/Zhihu posting.
- Video editing, voiceover, comments, or private-message automation.
- Betting execution, sportsbook linking, paid picks, private groups, or profit claims.

## Testing Strategy

- Unit tests for compliance classification across LOW/MEDIUM/HIGH/BLOCKED examples.
- Unit tests for candidate scoring and selection from a sample Zucai report.
- Unit tests with fake LLM provider for schema parsing and disclaimer enforcement.
- Unit tests for OpenClaw provider payload extraction using mocked subprocess execution.
- CLI tests for JSON output and artifacts using deterministic mode.
- Full verification with lint, compile, repository verify script, and graph refresh.
