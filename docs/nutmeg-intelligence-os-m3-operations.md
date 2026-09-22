# Intelligence OS (M3 match investigation) · 运维说明

> 2026-09-22 从 README 迁出（README 只保留入口）。M4/M5/M6 的对应文档在同目录。
> 当前 `nutmeg app` 处于 `legacy_read_only`，日常路径走 `decision-web`（见 README「每日界面」）。

Initialize the Ontology Kernel v2 store, then launch the local API:

```bash
uv run nutmeg ontology init
uv run nutmeg app
```

The local application opens at `http://127.0.0.1:8788/`. Its current
workspaces are the Command Center (`/`), Data Operations (`/operations`),
temporal Match Investigation Room (`/matches/<match_id>?as_of=...`), and
typed lineage pages (`/lineage/<object_type>/<object_id>`). The visible
`as_of` cutoff applies to identity, evidence, markets, workflow objects,
Bundles, and Forecasts; later records are never pulled into the page.

Product reads and writes use Ontology Kernel v2 exclusively. Team identity,
Claim status, AgentProposal resolution, Adjudication, and Forecast mutations
obtain a local CSRF session and use the same typed Action Gateway as the API.
Browser assets contain no devig, readiness, probability-simplex, ticket,
payout, or settlement arithmetic. SSE reconnect resumes from a session-scoped
durable cursor and visibly marks the page offline without changing domain
readiness.

The optional provider is disabled by default. Deterministic investigation
remains usable with no provider. To enable the guarded Portkey-compatible
copilot, set both variables before launching the loopback app:

```bash
NUTMEG_AGENT_SYNTHESIS_ENABLED=true \
NUTMEG_PORTKEY_API_KEY=<secret> \
uv run nutmeg app
```

A cited AgentProposal is not a fact and cannot bypass a verified
`source_conflict_unresolved` block. AI cannot verify Claims or commit
Forecasts; those transitions remain human `judge_operator` Actions. M3 never
creates, approves, dispatches, or settles a Ticket, moves funds, restores
schedulers, or contacts a real model during tests. `decision-web` remains a
legacy workshop and is not a product data source.
