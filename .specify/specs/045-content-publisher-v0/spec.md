# Feature Specification: Content Publisher v0

**Feature Branch**: `045-content-publisher-v0`  
**Created**: 2026-04-26  
**Status**: Verified (2026-04-26)  
**Input**: User asked to read `/Users/jz71/clawd/nutmeg-content-prd.md` and design/implement an independent content-production publisher module on top of existing Nutmeg/Zucai outputs. MVP outputs: 抖音 60 秒口播稿, 公众号/知乎长文版, 合规风险检查清单, and 5 title candidates. LLM generation should use the currently connected OpenClaw LLM interface.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Select publish-worthy matches from existing Zucai analysis (Priority: P1)

As the operator, I want Nutmeg to inspect an existing Zucai report and choose 1-3 matches that are worth turning into public sports-analysis content, so I do not spend time manually finding story angles in a 14-match issue.

**Why this priority**: Content creation starts with topic selection. The PRD explicitly says the module should not pick only the most confident match; it should pick the most explainable, attention-worthy, and compliance-safe match.

**Independent Test**: Given a bundled Zucai report JSON, run content selection and verify each candidate includes attention, content, model-stability, compliance, final priority, and a selection reason.

**Acceptance Scenarios**:

1. **Given** a valid Zucai report with 14 recommendations, **When** content generation starts, **Then** Nutmeg ranks candidates and returns at most the requested limit.
2. **Given** matches with notes, risk flags, popular competitions, or explainable odds/rationale, **When** scoring runs, **Then** those matches receive higher content priority than low-context matches.
3. **Given** a match whose recommendation is too aggressively framed, **When** scoring runs, **Then** its compliance score is reduced before LLM generation.

---

### User Story 2 - Generate multi-format content through OpenClaw LLM with validated structure (Priority: P1)

As the operator, I want Nutmeg to turn the selected match context into platform-ready drafts, so I can quickly edit and publish sports-analysis content without writing from scratch.

**Why this priority**: The requested MVP is content production. OpenClaw LLM is the primary creative generation step, but the result must be structured and machine-checkable before review.

**Independent Test**: Inject a fake LLM provider returning JSON and verify the service produces exactly 5 titles, a short-video script, a long article, observation points, uncertainty factors, and required disclaimers.

**Acceptance Scenarios**:

1. **Given** a selected match and deterministic Zucai evidence, **When** the LLM provider returns valid content JSON, **Then** the content pack contains the four requested outputs.
2. **Given** the LLM omits a required disclaimer, **When** post-processing runs, **Then** Nutmeg appends the required disclaimer before compliance assessment.
3. **Given** the LLM returns prose around a JSON object, **When** parsing runs, **Then** Nutmeg extracts the JSON object instead of failing unnecessarily.
4. **Given** the OpenClaw provider fails or returns invalid JSON, **When** content generation runs, **Then** Nutmeg records a warning and creates a conservative safe draft rather than silently publishing unvalidated text.

---

### User Story 3 - Gate every content pack through compliance risk checks (Priority: P1)

As the operator, I want every title, script, and article checked against the PRD compliance boundary, so generated content stays in sports analysis and avoids gambling promotion.

**Why this priority**: The PRD makes compliance a hard product requirement. A content module that cannot classify `LOW | MEDIUM | HIGH | BLOCKED` is unsafe.

**Independent Test**: Run the compliance checker against safe sports-analysis text, text with a prediction tendency, text with high-risk wording, and text with explicit betting instructions; verify risk levels and reasons match the PRD.

**Acceptance Scenarios**:

1. **Given** content containing betting instructions or private-group/paid-pick language, **When** compliance runs, **Then** risk is `BLOCKED` and publish recommendation is `skip`.
2. **Given** content containing high-risk certainty or stimulus words, **When** compliance runs, **Then** risk is at least `HIGH` and publish recommendation is `skip`.
3. **Given** content with model/odds tendency but balanced risk language and disclaimer, **When** compliance runs, **Then** risk is `MEDIUM` and publish recommendation is `review`.
4. **Given** purely explanatory sports analysis with disclaimers, **When** compliance runs, **Then** risk can be `LOW` and publish recommendation is `publish`.

---

### User Story 4 - Produce JSON and Markdown artifacts for human review (Priority: P2)

As the operator, I want a CLI command that writes JSON and Markdown artifacts, so the generated pack can be reviewed, edited, archived, or copied into Douyin/WeChat/Zhihu workflows later.

**Why this priority**: v0 does not auto-publish to external platforms. Artifact generation is the safe boundary between production and manual publishing.

**Independent Test**: Run the CLI with a local Zucai report, fake or deterministic LLM mode, and an output directory; verify JSON and Markdown files are written and CLI JSON exposes paths.

**Acceptance Scenarios**:

1. **Given** a valid report file and output directory, **When** `content-pack` runs, **Then** Nutmeg writes a batch JSON file and Markdown review file.
2. **Given** JSON output is requested, **When** the command completes, **Then** stdout contains structured batch output, not only human prose.
3. **Given** no output directory is provided, **When** the command runs, **Then** Nutmeg can still return structured output without external platform publishing.

### Edge Cases

- Report file is missing, malformed, or does not contain 14 Zucai matches/recommendations.
- The requested candidate limit is less than 1 or greater than the report size.
- LLM output is invalid JSON, includes markdown fences, omits fields, returns too many/few titles, or includes sensitive words.
- A generated title is compliant but the body is high risk; the final risk must reflect the highest risk across all generated surfaces.
- Content contains required disclaimers but also contains betting instructions; disclaimers must not lower `BLOCKED` risk.
- A match has no odds data, no notes, and only a weak recommendation; it should rank lower and expose low-content warnings.
- OpenClaw CLI is unavailable or times out; the command must fail clearly or use an explicit non-publishing safe fallback depending on mode.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Nutmeg MUST expose an independent content-publisher service that consumes existing Zucai report JSON instead of duplicating Zucai analysis logic.
- **FR-002**: Nutmeg MUST score each match with `attention_score`, `content_score`, `model_stability_score`, `compliance_score`, `final_content_priority`, and `selection_reason`.
- **FR-003**: Nutmeg MUST select at most the requested number of candidates, defaulting to 3 and supporting the MVP 1-3 match use case.
- **FR-004**: Nutmeg MUST use an LLM provider seam for content generation; the default operator path MUST call OpenClaw's `infer model run` interface with the configured model.
- **FR-005**: The LLM prompt MUST include structured match context, PRD compliance boundaries, required output schema, and explicit instructions to avoid betting instructions, profit claims, paid-pick/private-group calls, and platform-gambling links.
- **FR-006**: Nutmeg MUST parse and validate LLM output into the required fields: 5 titles, short-video script, long article, key observation points, uncertainty factors.
- **FR-007**: Nutmeg MUST enforce the short-video disclaimer: `以上只是赛前数据观察，不构成任何投注建议，理性看球。`
- **FR-008**: Nutmeg MUST enforce the long-form disclaimer: `本文仅基于公开信息进行足球赛事数据分析和规则科普，不构成任何投注建议，也不引导任何形式的下注。比赛结果具有不确定性，请理性看待。`
- **FR-009**: Nutmeg MUST output a compliance checklist for every generated content pack using the PRD's hard review questions.
- **FR-010**: Nutmeg MUST classify final content risk as `LOW`, `MEDIUM`, `HIGH`, or `BLOCKED`, with machine-readable `risk_reasons`.
- **FR-011**: Nutmeg MUST map risk to `publish_recommendation`: `LOW -> publish`, `MEDIUM -> review`, `HIGH/BLOCKED -> skip`.
- **FR-012**: Nutmeg MUST mark explicit betting instructions, profit claims, paid-pick/private-group calls, or gambling-platform lead-in text as `BLOCKED` even if disclaimers are present.
- **FR-013**: Nutmeg MUST mark sensitive certainty/stimulus wording at least `HIGH`.
- **FR-014**: Nutmeg MUST mark odds/handicap/model-result tendency at least `MEDIUM` unless the text is purely rules/data education without result tendency.
- **FR-015**: Nutmeg MUST write JSON and Markdown review artifacts when an output directory is provided.
- **FR-016**: Nutmeg MUST provide CLI JSON output suitable for OpenClaw/router consumption and future platform automation.
- **FR-017**: Nutmeg MUST not auto-publish to Douyin, WeChat, Zhihu, Xiaohongshu, or any external platform in v0.
- **FR-018**: Nutmeg MUST document the workflow gates that make each step reliable for the next step: input validation, candidate scoring, LLM schema validation, disclaimer enforcement, compliance gate, artifact review.

### Key Entities *(include if feature involves data)*

- **Content Candidate**: A scored match extracted from a Zucai report with explainability and compliance dimensions.
- **Content Generation Draft**: LLM-generated structured text for titles, short-video script, long article, observations, and uncertainty factors.
- **Compliance Assessment**: Risk level, reasons, and checklist result for all publishable surfaces.
- **Content Pack**: One match's complete reviewed output and publish recommendation.
- **Content Batch**: A run-level collection of candidates, content packs, artifacts, warnings, LLM provider metadata, and source report metadata.
- **Content Artifacts**: JSON and Markdown files intended for human review, not external publishing.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A bundled 26068 Zucai sample report can produce at least one content pack with exactly 5 titles, a short script, a long article, a compliance checklist, and a publish recommendation.
- **SC-002**: Compliance tests classify safe, medium-risk, high-risk, and blocked examples according to the PRD risk semantics.
- **SC-003**: CLI JSON output includes `content_priority`, `selection_reason`, `risk_level`, `risk_reasons`, `titles`, `short_video_script`, `long_article`, `compliance_checklist`, and artifact paths when written.
- **SC-004**: Generated content contains the required short-video and long-form disclaimers before final compliance assessment.
- **SC-005**: Focused content service/CLI tests, lint, compile, and full repository verification pass after implementation.

## Assumptions

- v0 consumes existing Zucai report JSON as the source of truth. Upstream source parsing, scheduled delivery, odds collection, and Zucai recommendation generation remain owned by existing modules.
- v0 creates artifacts for manual review and does not automate external account publishing.
- OpenClaw's configured model provider is available locally as `openclaw infer model run`; tests inject fake providers and avoid live LLM calls.
- The module is Chinese-first because the requested platforms and PRD language are Chinese.
- Deterministic safe fallback drafts are allowed only to preserve auditability when LLM output is invalid; they do not count as approved publishing and remain subject to compliance gates.
