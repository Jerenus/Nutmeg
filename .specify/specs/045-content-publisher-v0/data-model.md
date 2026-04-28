# Data Model: Content Publisher v0

## ContentCandidate

Represents one match selected from a Zucai report before generation.

Fields:
- `match_id`: Stable content id, v0 format `zucai:<issue_id>:<match_no>`.
- `match_no`: Zucai match sequence number.
- `match_name`: Human-readable `home_team vs away_team`.
- `competition`: Competition name from the Zucai issue.
- `match_time`: Optional match date/time from the issue.
- `attention_score`: 0-100 score for public attention/focus value.
- `content_score`: 0-100 score for explainability/story material.
- `model_stability_score`: 0-100 score derived from confidence/risk tier.
- `compliance_score`: 0-100 score estimating how safely this can be expressed as sports analysis.
- `final_content_priority`: Weighted 0-100 score used for ranking.
- `selection_reason`: Chinese explanation of why this match was selected.
- `source_recommendation`: Minimal Zucai recommendation context for prompting and audit.

Validation:
- Scores are clamped to 0-100.
- `match_id`, `match_name`, and `selection_reason` are non-empty.

## ContentGenerationDraft

Represents model-generated draft fields before final compliance packaging.

Fields:
- `titles`: Exactly 5 title candidates after normalization.
- `short_video_script`: Douyin/short-video 60-second oral script.
- `long_article`: WeChat/Zhihu long-form article.
- `key_observation_points`: Bullet observations grounded in match context.
- `uncertainty_factors`: Bullet risk/unknown factors.
- `llm_provider`: Provider label such as `openclaw:nyu-openai-chat/gpt-5.5`.
- `llm_status`: `generated`, `fallback`, or `failed`.

Validation:
- Titles must be trimmed and deduplicated to 5 items; safe deterministic titles fill missing slots.
- Short and long content must include required disclaimers before risk assessment.

## ComplianceChecklistItem

Represents one human-review question from the PRD.

Fields:
- `question`: Review question.
- `status`: `passed`, `failed`, or `needs_review`.
- `evidence`: Matched words or rationale.

## ComplianceAssessment

Represents final deterministic safety evaluation across all content surfaces.

Fields:
- `risk_level`: `LOW`, `MEDIUM`, `HIGH`, or `BLOCKED`.
- `risk_reasons`: Machine-readable Chinese reasons.
- `checklist`: List of compliance checklist items.
- `publish_recommendation`: `publish`, `review`, or `skip`.

State rules:
- `BLOCKED` always maps to `skip`.
- `HIGH` maps to `skip`.
- `MEDIUM` maps to `review`.
- `LOW` maps to `publish`.

## ContentPack

Represents one match's complete content output.

Fields:
- Candidate metadata: `match_id`, `match_name`, `competition`, `match_time`, `content_priority`, `selection_reason`.
- Compliance metadata: `risk_level`, `risk_reasons`, `compliance_checklist`, `publish_recommendation`.
- Content: `titles`, `short_video_script`, `long_article`, `key_observation_points`, `uncertainty_factors`, `disclaimer`.
- LLM metadata: `llm_provider`, `llm_status`, `warnings`.

## ContentArtifacts

Represents durable review outputs.

Fields:
- `json_path`: Optional path to batch JSON artifact.
- `markdown_path`: Optional path to Markdown review artifact.

## ContentBatch

Represents one run.

Fields:
- `source_report_path`: Input report path.
- `generated_at`: ISO timestamp.
- `llm_provider`: Provider label used by the run.
- `candidates`: Ranked candidates.
- `packs`: Generated content packs.
- `artifacts`: JSON/Markdown artifact paths.
- `warnings`: Run-level warnings.
