# CLI Contract: Content Publisher v0

## Command

```bash
uv run nutmeg content-pack \
  --report-file <path-to-zucai-report.json> \
  --limit 3 \
  --output-dir .nutmeg-data/content \
  --llm-mode openclaw \
  --openclaw-model nyu-openai-chat/gpt-5.5 \
  --format json
```

## Options

- `--report-file PATH` (required): Existing Zucai report JSON from `zucai-report` or `zucai-auto-run`.
- `--limit INT` (default `3`): Maximum content packs to generate. Values below 1 are rejected.
- `--output-dir PATH` (default `.nutmeg-data/content`): Writes JSON and Markdown artifacts. If explicitly omitted in future adapters, service can run artifact-free.
- `--llm-mode openclaw|deterministic` (default `openclaw`): `openclaw` uses current OpenClaw LLM interface. `deterministic` is for tests/smoke only and still runs compliance gates.
- `--openclaw-model TEXT` (default `nyu-openai-chat/gpt-5.5`): Model id passed to OpenClaw.
- `--format text|json` (default `text`): Human summary or structured JSON.

## JSON Output Shape

```json
{
  "source_report_path": "...",
  "generated_at": "2026-04-26T12:00:00+00:00",
  "llm_provider": "openclaw:nyu-openai-chat/gpt-5.5",
  "candidates": [
    {
      "match_id": "zucai:26068:1",
      "match_name": "曼联 vs 布伦特福德",
      "competition": "英超",
      "match_time": "2026-04-26 21:00",
      "attention_score": 88,
      "content_score": 75,
      "model_stability_score": 62,
      "compliance_score": 80,
      "final_content_priority": 76,
      "selection_reason": "..."
    }
  ],
  "packs": [
    {
      "match_id": "zucai:26068:1",
      "match_name": "曼联 vs 布伦特福德",
      "competition": "英超",
      "match_time": "2026-04-26 21:00",
      "content_priority": 76,
      "selection_reason": "...",
      "risk_level": "MEDIUM",
      "risk_reasons": ["包含赛前倾向或赔率/市场观察，需要人工审核"],
      "titles": ["... five items ..."],
      "short_video_script": "...",
      "long_article": "...",
      "compliance_checklist": [
        {"question": "是否给出了明确投注动作？", "status": "passed", "evidence": ""}
      ],
      "key_observation_points": ["..."],
      "uncertainty_factors": ["..."],
      "disclaimer": "本文仅基于公开信息进行足球赛事数据分析和规则科普，不构成任何投注建议，也不引导任何形式的下注。比赛结果具有不确定性，请理性看待。",
      "publish_recommendation": "review",
      "llm_provider": "openclaw:nyu-openai-chat/gpt-5.5",
      "llm_status": "generated",
      "warnings": []
    }
  ],
  "artifacts": {
    "json_path": ".nutmeg-data/content/content-pack-26068-20260426T120000Z.json",
    "markdown_path": ".nutmeg-data/content/content-pack-26068-20260426T120000Z.md"
  },
  "warnings": []
}
```

## Error Semantics

- Missing or malformed report file exits with code 2 and a clear validation message.
- Invalid limit exits with code 2.
- OpenClaw execution failure in `openclaw` mode exits with code 2 unless a safe fallback is explicitly enabled by the service call.
- Compliance `HIGH` or `BLOCKED` does not fail the command; it returns a content pack with `publish_recommendation=skip` for human review/audit.
