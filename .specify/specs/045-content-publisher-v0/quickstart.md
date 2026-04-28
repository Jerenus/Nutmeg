# Quickstart: Content Publisher v0

## 1. Generate or reuse a Zucai report JSON

```bash
uv run nutmeg zucai-report \
  --issue-id 26068 \
  --output-dir .nutmeg-data/zucai \
  --format json
```

Copy the `artifacts.report_json_path` value from JSON output.

## 2. Generate content with OpenClaw LLM

```bash
uv run nutmeg content-pack \
  --report-file .nutmeg-data/zucai/zucai-26068-report.json \
  --limit 3 \
  --output-dir .nutmeg-data/content \
  --llm-mode openclaw \
  --openclaw-model nyu-openai-chat/gpt-5.5 \
  --format json
```

Expected:
- JSON output includes candidates, packs, risk levels, compliance checklist, and artifact paths.
- Markdown artifact is suitable for human review before manual platform posting.

## 3. Deterministic smoke mode for local verification

```bash
uv run nutmeg content-pack \
  --report-file nutmeg/content/samples/26068-content-report.json \
  --limit 1 \
  --output-dir .nutmeg-data/content-smoke \
  --llm-mode deterministic \
  --format json
```

Expected:
- Exactly one content pack.
- Exactly five titles.
- Both short and long disclaimers are present.
- `publish_recommendation` is `publish`, `review`, or `skip` based on compliance gates.

## 4. Review gate before publishing

Before copying content to a platform, check:
- `risk_level` is not `HIGH` or `BLOCKED`.
- `publish_recommendation` is `publish` or manually approved `review`.
- No title sounds like betting recommendation.
- The short-video and long-form disclaimers remain intact.
- The copy explains variables and uncertainty instead of telling users what to buy.
