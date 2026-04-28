# Analysis Agent Execution Path

Nutmeg now has a first agent workflow surface separate from the deterministic
`analyze-match` command. The `agent-analyze-match` CLI command builds a
`MatchAnalysisAgentWorkflow`, runs the existing `AnalysisService`, and returns a
structured workflow result with:

- `status`: `succeeded` or `failed`
- `nodes`: execution trace such as `classify_intent -> analyze_match -> synthesize_result`
- `analysis`: the existing deterministic analysis payload when evidence is sufficient
- `error`: truthful failure reason when analysis cannot be produced

The workflow uses LangGraph when the optional dependency is importable and falls
back to an equivalent deterministic executor otherwise. This keeps Phase 1
runnable while preserving a graph-native seam for future LLM/tool nodes.


## Generated synthesis guard

The workflow now accepts an optional synthesis provider. The provider is called
only after deterministic analysis succeeds. Generated text is stored separately
as `generated_synthesis` and never replaces the deterministic `analysis`
payload. A lightweight guard requires generated text to mention the deterministic
verdict and confidence; if it does not, the workflow fails truthfully with
`Generated synthesis failed evidence guard.`

When no provider is configured, the workflow still succeeds and records the
`synthesis_skipped` node. This keeps the CLI usable without live LLM credentials
while preserving a safe seam for future LLM-backed narration.


## Portkey-compatible provider adapter

Generated synthesis remains default-off. `build_synthesis_provider()` returns a
provider only when `NUTMEG_AGENT_SYNTHESIS_ENABLED=true` and
`NUTMEG_PORTKEY_API_KEY` is configured. The adapter posts deterministic analysis
evidence to `/chat/completions`, extracts assistant text, and then the workflow
 guard still validates verdict/confidence before trusting `generated_synthesis`.

`nutmeg doctor --format json` reports synthesis enabled/configured flags and the
selected model, but never prints the provider API key.


## Agent status surface

`nutmeg agent-status` is a no-network readiness command for operational checks.
It reports the current agent executor (`langgraph` or deterministic fallback),
LangGraph availability, synthesis enabled/configured/model fields, and odds
provider health-metric capability. It never prints provider API keys.
