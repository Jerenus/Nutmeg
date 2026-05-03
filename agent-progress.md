# Agent Progress

## Session goal

Complete Sprint 1 richer pre-match snapshot plus the first odds snapshot / fair probability path.

## Current status

- Sprint 0 real fixture sync is implemented and still passing.
- Sprint 1 snapshot now includes `soccerdata`, market value, probable lineups, bench depth, environment context, and matchup/trend context.
- Fixture rows now preserve provider team ids to support downstream context calls.
- Transfermarkt is used for market value, probable-lineup inference, and bench-depth heuristics; Open-Meteo + Nominatim provide venue/weather/travel context.
- API-Football adapters now support injuries, sidelined availability, team splits, head-to-head summaries, and fixture referee normalization when a key is configured.
- The snapshot no longer fabricates unavailable upstream fields; missing fields remain explicit `null`/unavailable.
- `fixture-snapshot --format json` now preserves clean stdout even when providers emit noisy logs.
- `005-player-identity-materialization` and `006-prematch-snapshot-expansion` are implemented and locally verified.
- `007-odds-snapshot` is implemented and locally/live verified.
- The Odds API secondary-provider path now has a real fixture-to-event reconciliation layer plus cached event links for mapped leagues.

## Completed this session

- Added a dedicated `odds-snapshot` CLI with API-Football-backed pre-match odds normalization and fair-probability aggregation.
- Added `nutmeg/domain/odds.py` and `nutmeg/services/odds.py` to keep the odds provider boundary replaceable.
- Added canonical market coverage for `match_winner`, `btts`, and `totals_2_5` with no-vig fair probabilities and fair odds.
- Added odds architecture/spec verification artifacts and a live EPL odds acceptance pass.
- Added The Odds API fixture-to-event reconciliation, persisted provider event links, and secondary-provider normalization for canonical pre-match markets.
- Added league-level The Odds API sport-key mappings so the secondary provider can resolve local fixtures into upstream event ids without changing the consumer-facing odds contract.

- Added the `005-player-identity-materialization` and `006-prematch-snapshot-expansion` Spec Kit slices plus implementation coverage.
- Extended fixtures to persist referee metadata in the shared DuckDB cache.
- Implemented Transfermarkt-backed market-value lookup, probable-lineup inference, and bench-depth context.
- Implemented API-Football injuries, sidelined availability, team statistics, head-to-head summaries, and fixture referee normalization.
- Implemented environment assembly with venue geocoding, kickoff local time, weather, and away-travel context.
- Added Nominatim fallback geocoding when Open-Meteo cannot resolve stadium names directly.
- Extended `nutmeg fixture-snapshot` text/JSON rendering, docs, tests, and continuity artifacts for the richer snapshot.
- Verified `reference-refresh --league epl --season 2025` end-to-end and a cache-backed richer snapshot acceptance path with live weather/travel data.

## Completed this session

- Added `008-analysis-judgment-v0` as the first agent-facing analysis slice.
- Added deterministic analysis domain models and `AnalysisService` to synthesize snapshot + odds evidence into Nutmeg's four-part house judgment format.
- Added `analyze-match` CLI in text/JSON forms and kept intent classification visible in the payload.
- Added service and CLI coverage for decisional intent, unavailable-odds truthfulness, and insufficient-evidence failure paths.

## Completed this session · tactics synthesis

- Added `009-tactics-synthesis-v0` to deepen the first analysis workflow before full agent orchestration.
- Extended the analysis contract with `tactical_summary` and `conflict_state` so future agents can reuse richer evidence buckets.
- Added deterministic tactical extraction from lineup, matchup-trend, and bench-depth snapshot context.
- Added contradiction handling so team-context vs market-context disagreement explicitly lowers confidence.
- Updated CLI rendering and tests so richer evidence remains visible in both JSON and text forms.

## Completed this session · market shape

- Added `010-market-shape-expansion` to deepen the analysis workflow with richer odds interpretation.
- Extended the analysis evidence contract with `market_shape_summary`.
- Reused `match_winner`, `totals_2_5`, and `btts` to classify open-game vs lower-event market texture.
- Added explicit caveats when market-shape coverage is partial instead of silently flattening the odds view.
- Updated CLI rendering and tests so multi-market evidence remains visible and verified.

## Completed this session · asian handicap expansion

- Added `011-asian-handicap-expansion` coverage across API-Football, The Odds API, the odds snapshot service, and deterministic analysis.
- Broadened canonical Asian handicap lines to `0.25 / 0.5 / 0.75 / 1.0 / 1.25 / 1.5 / 1.75 / 2.0 / 2.25 / 2.5`.
- Normalized provider-specific handicap formats such as API-Football `Home -2` and The Odds API spread points into stable `asian_handicap_*` market keys.
- Added analysis market-shape language for stronger handicap pressure when lines of `2.0+` are available.
- Added CLI JSON contract coverage for handicap-pressure evidence.

## Completed this session · odds event cache recovery

- Added `012-odds-event-cache-recovery` to make The Odds API fixture-to-event cache self-healing.
- Added explicit `OddsEventRepository.delete_event()` and DuckDB-backed invalidation.
- The Odds API adapter now retries exactly once when a cached event odds endpoint returns stale/not-found status, then stores the replacement mapping.
- Recovery failure now names the stale cached event and preserves the reconciliation failure reason.

## Completed this session · market intelligence signals

- Added `013-market-intelligence-signals` to consume existing odds history and bookmaker quotes inside deterministic analysis.
- `AnalysisService` now appends material match-winner movement/drift to market evidence.
- Elevated bookmaker disagreement now appears as a caveat and caps otherwise-high confidence to medium.
- Added CLI JSON/text contract coverage proving the signals stay inside existing evidence arrays.

## Completed this session · provider health metrics

- Added `014-provider-health-metrics` with an adapter-local The Odds API health snapshot.
- The health snapshot tracks cache hits/misses, reconciliation attempts/failures, stale refresh attempts/successes, last event id, and last error.
- Metrics stay outside the canonical odds snapshot contract until a dedicated status/health surface is introduced.

## Completed this session · historical fixtures ingestion

- Added `015-historical-fixtures-ingestion` for recent historical fixture caching and rest-days context.
- `fixtures-sync` now accepts `--past-days` and requests a combined historical/upcoming provider date window.
- `DuckDbFixtureRepository` can find the latest finished prior fixture for a team.
- `FixtureSnapshotService` now fills `environment.home_rest_days` and `environment.away_rest_days` from cached finished fixtures when available.

## Remaining natural next slices

1. Connect the first LangGraph-backed agent execution path.
2. Add odds movement trigger thresholds/configuration once real historical samples accumulate.
3. Expose provider health through a dedicated CLI/status command if operational monitoring becomes necessary.
4. Add historical fixture backfill/live acceptance using real API-Football credentials.
5. Refresh graph assets once the codebase has enough structural density.


## Completed this session · agent execution path

- Added `016-agent-execution-path` as the first LangGraph-compatible agent workflow over deterministic analysis.
- Added `MatchAnalysisAgentWorkflow` and `MatchAnalysisAgentResult` with node trace, status, analysis payload, and truthful error field.
- Added `agent-analyze-match` CLI in text/JSON forms.
- Workflow uses LangGraph when available and a deterministic fallback otherwise, with no LLM calls in this slice.


## Completed this session · agent LLM synthesis guard

- Added `017-agent-llm-synthesis` with an optional synthesis provider seam in `MatchAnalysisAgentWorkflow`.
- Generated text is stored as `generated_synthesis` and guarded against drifting from deterministic verdict/confidence.
- No-provider runs remain successful and explicitly record `synthesis_skipped`.
- `agent-analyze-match` JSON/text output now includes generated synthesis when present.


## Completed this session · LLM provider adapter

- Added `018-llm-provider-adapter` with a default-off Portkey-compatible synthesis provider.
- Added `NUTMEG_AGENT_SYNTHESIS_ENABLED`; provider injection requires both the enable flag and `NUTMEG_PORTKEY_API_KEY`.
- `PortkeySynthesisProvider` posts deterministic analysis evidence to `/chat/completions` and extracts assistant text under mock-tested behavior.
- `doctor` now reports synthesis enabled/configured/model fields without leaking keys.


## Completed this session · agent status CLI

- Added `019-agent-status-cli` with a no-network `agent-status` command.
- Status output reports agent executor, LangGraph availability, synthesis readiness/model, and odds-provider health capability.
- JSON/text outputs avoid secret leakage and are covered by CLI tests.


## Completed this session · live acceptance scripts

- Added `020-live-acceptance-scripts` with `scripts/acceptance.sh`.
- Default `--dry-run` prints a no-network acceptance plan; `--local` runs no-network checks.
- `--live` is explicit and fails fast without `NUTMEG_API_FOOTBALL_KEY`.
- Added `make acceptance` and README acceptance instructions.

## 2026-04-25 - 021-graph-refresh

- Completed `021-graph-refresh` to satisfy the graph-native workflow required by AGENTS.md.
- Added `scripts/refresh_graph.py`, a deterministic no-network AST import graph generator.
- Generated `graphify-out/GRAPH_REPORT.md` and `graphify-out/graph.json` with module communities, high-degree modules, and dependency edges.
- Added `make graph` and documented graph refresh/review in `docs/architecture/overview.md`.
- Focused verification: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_graph_refresh.py -q` -> 3 passed.

## 2026-04-25 - 022-provider-health-persistence

- Completed `022-provider-health-persistence` to persist The Odds API provider health across process/CLI invocations.
- Added `odds_provider_health` DuckDB schema and `DuckDbOddsProviderHealthRepository`.
- Extended `TheOddsApiClient` with optional health repository injection, cumulative restored counters, and persistence after fetch/error paths.
- `agent-status` now reports persisted The Odds API health without network calls and without leaking provider keys.
- Refreshed graph assets after adding the new health repository dependency path.
- Focused verification: provider-health/odds/CLI suite -> 50 passed.

## 2026-04-25 - 023-operator-match-brief

- Completed `023-operator-match-brief` to expose a single operator-facing pre-match brief command.
- Added `nutmeg match-brief` with text and JSON output over the existing guarded agent workflow.
- Brief payload includes fixture identity, judgment, confidence, core reasons, tactical/market evidence, caveats, agent nodes, and optional generated synthesis.
- Failure paths preserve workflow errors and exit non-zero without fabricating sections.
- Focused CLI verification: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_cli.py -q` -> 32 passed.

## 2026-04-25 - 024-im-bot-adapter

- Completed `024-im-bot-adapter` as a no-network IM bot adapter skeleton for Phase 1 CLI+IM readiness.
- Added `nutmeg.interfaces.bot.adapter` with `/brief <fixture_id> <query>` parsing, structured bot responses, and compact message-safe match brief rendering.
- Added `nutmeg bot-dry-run --message ...` in text/JSON modes so bot behavior is locally testable without Telegram/Discord credentials or network calls.
- Failure paths preserve workflow/parser errors and exit non-zero from the dry-run command.
- Focused verification: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_bot_adapter.py tests/test_cli.py -q` -> 38 passed.

## 2026-04-25 - 025-today-briefs

- Completed `025-today-briefs` to list local fixture candidates and optionally fan out match briefs without manually typing fixture ids.
- Added `nutmeg today-briefs --league epl --days N [--demo]` for text/JSON candidate lists with suggested `/brief` bot messages.
- Added `--briefs` mode to reuse the existing guarded match brief workflow per fixture while recording per-fixture failures rather than aborting the whole list.
- Empty local-cache output is truthful and suggests `fixtures-sync` or `--demo`.
- Focused CLI verification: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_cli.py -q` -> 37 passed.

## 2026-04-25 - 026-telegram-bot-transport

- Completed `026-telegram-bot-transport` as the first real IM transport seam.
- Added Telegram Bot API client with injectable HTTP client for no-network tests.
- Added Telegram runner that filters owner allowlisted chat ids, routes allowed messages through the existing BotAdapter, and sends denial messages to unauthorized chats.
- Added `telegram-bot-status` and `telegram-bot-poll-once` CLI commands without leaking bot tokens.
- Focused verification: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_telegram_bot.py tests/test_cli.py -q` -> 42 passed.

## 2026-04-25 - 027-telegram-bot-daemon

- Completed `027-telegram-bot-daemon` to turn one-shot Telegram polling into a controlled daemon loop.
- Added `TelegramPollingDaemon` with offset propagation, aggregate counts, configurable sleep interval, `max_polls` bounded execution, and graceful `KeyboardInterrupt` summaries.
- Added `telegram-bot-run` CLI text/JSON output without leaking bot tokens; `--max-polls` supports local/cron validation while omitted `--max-polls` supports supervised long-running use.
- Updated README and feature-list continuity for the daemon slice.
- Focused verification: `uv run ruff check nutmeg/interfaces/bot/telegram.py nutmeg/interfaces/bot/__init__.py nutmeg/interfaces/cli.py tests/test_telegram_bot.py tests/test_cli.py` -> pass; `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_telegram_bot.py tests/test_cli.py -q` -> 45 passed.

## 2026-04-25 - 028-popular-matches-ranking

- Added `028-popular-matches-ranking` to answer the operator question "today有哪些热门比赛" from local/demo fixture candidates.
- Added `MatchPopularityRanker` with deterministic no-network scoring across competition weight, team prominence, elite/rivalry boosts, kickoff proximity, and live status.
- Added `nutmeg popular-matches` text/JSON output with rank, score, tier, reasons, fixture identity, and suggested `/brief` messages.
- Extended `today-briefs --sort popularity` while preserving kickoff-order as the default.
- Focused verification: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_popularity.py tests/test_cli.py -q` -> 44 passed; `uv run ruff check nutmeg/services/popularity.py nutmeg/interfaces/cli.py tests/test_popularity.py tests/test_cli.py` -> pass.
- Full verification after `027` and `028`: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q`, `uv run ruff check .`, `python3 -m compileall nutmeg`, `bash scripts/verify.sh` -> pass; verify script reports 146 passed.

## 2026-04-25 - 029-bot-llm-fallback

- Added `029-bot-llm-fallback` so the bot can answer `/start`/`help` deterministically and route unsupported natural-language messages or failed `/brief` attempts to an optional GPT-5.5 fallback.
- Added `OpenAiBotFallbackProvider` over OpenAI Responses API `/responses` using existing `httpx`, default-off settings, and `gpt-5.5` as the configurable default model.
- Wired fallback into `bot-dry-run` and Telegram runner construction while preserving the deterministic `/brief` path as primary behavior.
- Updated `doctor`, `agent-status`, and `telegram-bot-status` to expose fallback enabled/configured/model booleans without leaking secrets.
- Focused verification: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_llm_provider.py tests/test_bot_adapter.py tests/test_cli.py -q` -> 54 passed; touched-file ruff -> pass.
- Live fallback smoke reached OpenAI but returned 401, so the local/global OpenAI API key currently present is not authorized; set a valid `NUTMEG_OPENAI_API_KEY` before expecting GPT-5.5 replies in Telegram.
- Full verification after `029`: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q`, `uv run ruff check .`, `python3 -m compileall nutmeg`, `bash scripts/verify.sh` -> pass; verify script reports 151 passed.

## 2026-04-25 - 030-telegram-offset-persistence

- Added `030-telegram-offset-persistence` so Telegram polling no longer depends on manually remembering `--offset`.
- Added `TelegramOffsetStore` with safe read/write behavior and invalid-file fallback.
- `TelegramPollingDaemon` now writes `next_offset` after every successful poll when a store is configured.
- `telegram-bot-run` now uses `.nutmeg-data/state/telegram-bot.offset` by default, supports `--offset-file`, `--no-offset-file`, and preserves explicit `--offset` override behavior.
- Focused verification: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_telegram_bot.py tests/test_cli.py -q` -> 52 passed; touched-file ruff -> pass.
- Live smoke: `uv run nutmeg telegram-bot-run --timeout 2 --poll-interval 0 --max-polls 1 --format json` resumed from `.nutmeg-data/state/telegram-bot.offset` with `offset_source=store`.
- Full verification after `030`: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q`, `uv run ruff check .`, `python3 -m compileall nutmeg`, `bash scripts/verify.sh` -> pass; verify script reports 155 passed.

## 2026-04-25 - v0.3 design gap audit and 031-value-board-v0

- Audited `Nutmeg-DESIGN-v0.3.md` against the current specs, code graph, CLI commands, and feature registry.
- Recorded the application-completeness gaps in `docs/architecture/design-gap-audit.md`: value board, player profile, eval/review loop, daily operator schedule, and tactical visuals/models.
- Added planned spec packages for `032-player-profile-v0`, `033-eval-and-review-loop`, and `034-daily-operator-schedule`.
- Implemented `031-value-board-v0` as the highest-priority Sprint 3 gap.
- Added `nutmeg.models.dixon_coles.DixonColesLiteModel` with deterministic match-winner probabilities from recent xG matchup context.
- Added `nutmeg.domain.value` and `nutmeg.services.value.ValueBoardService` to compare model probability vs match-winner market fair probability, rank edges, and size quarter-Kelly.
- Added `nutmeg value-board` text/JSON CLI and documented it in `docs/architecture/value-board.md` plus README.
- Focused verification: pricing/value/CLI tests -> 5 passed; full CLI-focused suite -> 50 passed; touched-file ruff -> pass; `feature-list.json` validated.
- Full verification after `031`: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q`, `uv run ruff check .`, `python3 -m compileall nutmeg`, `bash scripts/verify.sh`, and graph refresh all passed; verify script reports 160 passed and graph has 64 modules / 100 edges.

## 2026-04-25 - 032/033/034 core completeness pass

- Completed `032-player-profile-v0` with `nutmeg player-profile`, local identity resolution, Transfermarkt market profile lookup, cached player season metrics, availability cache, and deterministic similar-player scoring.
- Added `nutmeg/domain/players.py`, `nutmeg/services/players.py`, `docs/architecture/player-profile.md`, plus `sd_player_season_cache` and `player_availability_cache` schema contracts.
- Completed `033-eval-and-review-loop` with local `eval-run`, starter eval dataset, three-way Brier Score, SQLite prediction storage, `prediction-record`, `prediction-outcome`, and `prediction-review`.
- Added `nutmeg/domain/evals.py`, `nutmeg/services/evals.py`, `nutmeg/models/scoring.py`, `nutmeg/storage/prediction_repository.py`, and `docs/architecture/eval-review-loop.md`.
- Completed `034-daily-operator-schedule` with `nutmeg daily-run`, optional live fixture sync, popularity ranking, value board inclusion, optional brief fan-out, and explicit dry-run-gated Telegram dispatch.
- Added `nutmeg/domain/operations.py`, `nutmeg/services/operations.py`, and `docs/architecture/daily-operator.md`.
- Focused verification passed: new-feature suite with CLI (`tests/test_player_profile_service.py tests/test_scoring.py tests/test_eval_service.py tests/test_prediction_repository.py tests/test_operations_service.py tests/test_cli.py`) -> 57 passed; touched-file ruff -> pass.
- Full verification after `032/033/034`: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q`, `uv run ruff check .`, `python3 -m compileall nutmeg`, `bash scripts/verify.sh`, and graph refresh all passed; verify script reports 171 passed and graph has 72 modules / 115 edges.
- Smoke checks passed serially: `eval-run --dataset starter --format json`, `prediction-review --format json`, `daily-run --league epl --days 0 --limit 3 --format json`, and `player-profile --league epl --season 2025 --team Arsenal --player "Bukayo Saka" --format json`.

## 2026-04-25 - 035-tactical-visuals-v0

- Completed `035-tactical-visuals-v0` to close the local tactical visualization gap from `Nutmeg-DESIGN-v0.3.md`.
- Added `nutmeg/domain/tactics.py` and `nutmeg/services/tactics.py` with deterministic SVG tactical artifacts: shot-map proxy, lineup-network proxy, and recent xG trend.
- Added `nutmeg tactical-visuals --fixture-id ... [--output-dir ...]` with text/JSON output and stable optional SVG file writes.
- Fixed the local-first runtime path by adding `FixtureSnapshotService.build_snapshot(..., live_context=False)` and using it from tactical visuals, avoiding API-Football/weather live calls for demo or cached fixtures.
- Added regression coverage proving tactical visuals request local snapshot context and snapshot local context skips live provider clients.
- Documented the feature in `docs/architecture/tactical-visuals.md`, README, `feature-list.json`, and `.specify/specs/035-tactical-visuals-v0/verification.md`.
- Verification: focused tactical/snapshot/CLI tests -> 13 passed; `uv run nutmeg tactical-visuals --fixture-id epl-001 --format json` -> 3 artifacts; `uv run ruff check .` -> pass; `python3 -m compileall nutmeg` -> pass; `bash scripts/verify.sh` -> 175 passed; graph refresh -> 74 modules / 118 edges.

## 2026-04-26 - 036-openclaw-telegram-bridge

- Completed `036-openclaw-telegram-bridge` so OpenClaw can operate Nutmeg through Telegram without arbitrary shell access.
- Added `scripts/openclaw/nutmeg_command_router.py`, a safe router over allowlisted Nutmeg CLI actions with argument validation, JSON envelopes, confirmation gates, and `.nutmeg-data/state/openclaw-router.lock` serialization.
- Added OpenClaw-facing docs: `docs/integrations/openclaw-telegram-command-manual.md`, `docs/integrations/openclaw-nutmeg-agent-instruction.md`, and `docs/integrations/openclaw-botfather-commands.txt`.
- Added design/plan docs in `docs/superpowers/` and spec artifacts under `.specify/specs/036-openclaw-telegram-bridge/`.
- Added `/Users/jz71/.openclaw/workspace/NUTMEG-TELEGRAM.md` and a `TOOLS.md` pointer so OpenClaw workspace sessions know the Nutmeg router entrypoint.
- Added an OpenClaw workspace `AGENTS.md` rule so `nutmegbot` and football/Nutmeg Telegram messages read `NUTMEG-TELEGRAM.md` before answering.
- Configured OpenClaw through official CLI: added Telegram account `nutmeg`, added agent `nutmegbot`, bound `telegram:nutmeg`, set identity `Nutmeg` / `⚽`, and validated `~/.openclaw/openclaw.json`.
- Fixed token persistence by storing the bot token in `/Users/jz71/.openclaw/credentials/telegram-nutmeg-token` with mode `600`; channel probe reports `@jerenusNutmeg_bot` works.
- Set the Telegram BotFather command menu from `docs/integrations/openclaw-botfather-commands.txt`; Bot API returned `ok=true` for 20 commands.
- Verification: router tests -> 6 passed; print-command smoke -> JSON command envelope; unsafe sync without confirmation -> rejected; demo seed/popular router smoke -> success; OpenClaw config validation -> pass; `uv run ruff check .` -> pass; `python3 -m compileall nutmeg scripts/openclaw` -> pass; `bash scripts/verify.sh` -> 181 passed.
- Fixed OpenClaw bootstrap misrouting by moving `nutmegbot` to the dedicated `/Users/jz71/.openclaw/workspaces/nutmeg` workspace, adding a Chinese-only `systemPromptOverride`, backing up stale Telegram sessions, and tightening the shared workspace Nutmeg fallback instructions.
- Verification after the routing fix: `openclaw agent --agent nutmegbot --message "/start" --json` returned the Chinese Nutmeg menu with no bootstrap or unsupported command drift; `openclaw agent --agent nutmegbot --message "今天有哪些热门比赛？" --json` used one router tool call and returned Chinese popular-match suggestions with full `/brief <fixture_id> 这场比赛怎么看？` commands; `/brief epl-001` defaulted to the safe query and truthfully reported insufficient evidence instead of fabricating analysis.
- Switched `nutmegbot` to `nyu-openai-chat/gpt-5.5` with fallback `nyu-openai/gpt-5.4`. Direct Responses-mode `nyu-openai/gpt-5.5` was rejected for tool-result continuation with a `store=false` item persistence error, so the working GPT-5.5 path is the Chat Completions compatibility provider. Verification: `/start` and "今天有哪些热门比赛？" both used GPT-5.5 with no fallback; the popular-match flow made one router `exec` call and returned Chinese brief suggestions.
- Switched OpenClaw's global default model to `nyu-openai-chat/gpt-5.5` with fallback `nyu-openai/gpt-5.4`; default-inheriting agents now list GPT-5.5. Verification: `taskbot` smoke used GPT-5.5 with no fallback, `nutmegbot` `/start` still used GPT-5.5, and all Telegram channels reconnected after Gateway restart.

## 2026-04-26 - Real daily operator cycle hardening

- Ran the first live daily operator cycle for EPL with `daily-run --live-sync --briefs --dry-run`.
- Live sync succeeded and wrote fixture `1379305` Manchester United vs Brentford from API-Football.
- Fixed a direct CLI DuckDB concurrency issue found during parallel operator smokes by adding `nutmeg.storage.duckdb_utils.connect_analytics_db()` and routing Nutmeg-owned DuckDB connections through a process-level file lock.
- Fixed `match-brief` natural-language routing: "Give me the pre-match operator brief." and "这场比赛怎么看？" now classify as decisional rather than informational.
- Fixed real-mode fixture filtering so persisted demo fixtures are ignored when real provider fixtures exist; applied consistently to fixture listing and value-board fixture scanning.
- Live `match-brief 1379305` now succeeds with verdict `Lean Manchester United pre-match.` and high confidence.
- Live `value-board` now scans only the real fixture and returns one strong candidate: Brentford away value against API-Football match-winner market.
- Recorded prediction `1` for Manchester United vs Brentford using market probabilities and the match-brief home pick, with notes flagging the value-board disagreement for post-match calibration.
- Fixed `daily-run` sync metadata persistence: the command now commits its state session after running, so `doctor` sees daily-run live sync records. A lightweight `daily-run --days 0 --live-sync` smoke wrote sync run id `8`.
- Verification: focused affected tests passed, `uv run ruff check nutmeg tests` passed, `python3 -m compileall nutmeg scripts/openclaw` passed, `bash scripts/verify.sh` passed with `184 passed`, `doctor` reports `33/33` passing features and latest sync from 2026-04-26, and graph refresh wrote 75 modules / 125 edges.

## 2026-04-26 - 037-ai-native-betting-client

- Completed the AI-native betting-analysis client from spec through implementation, preserving Nutmeg services as the source of truth and avoiding wager execution/sportsbook integration.
- Added client domain/state/service/web modules for actionability, freshness, evidence, entitlements, watchlists, grouped alerts, audit records, conversations, and client prediction records.
- Added FastAPI/Jinja Web/PWA surface: `/client`, `/client/status`, `/client/matches/{fixture_id}`, `/client/api/feed`, `/client/api/status`, `/client/api/matches/{fixture_id}`, `/client/api/matches/{fixture_id}/questions`, `/client/api/watchlist`, `/client/api/alerts`, and `/client/api/predictions`.
- Added JSON CLI parity: `client-status`, `client-feed`, `client-match`, `client-question`, `client-watchlist`, `client-alerts`, `client-prediction-record`, and `client-web`.
- Added Chinese-first UI controls for saved opportunities, grouped material-change alerts, and simulated prediction records with explicit responsible-use copy: "模拟记录，不是下注".
- Updated README usage, `feature-list.json`, `docs/architecture/ai-native-client.md`, `pyproject.toml` package-data wheel configuration, and `.specify/specs/037-ai-native-betting-client/verification.md`.
- Verification: US5 target suite -> 9 passed; focused client suite -> 47 passed; wheel inspection confirmed web templates/static assets; `uv run ruff check .` -> pass; `python3 -m compileall nutmeg` -> pass; `bash scripts/verify.sh` -> 231 passed; graph refresh -> 81 modules / 132 edges.

## 2026-04-26 - 038-event-data-tactical-models-v0

- Completed the next development slice after all prior specs were verified: local-first event-data tactical models.
- Added `nutmeg.domain.event_data` with normalized football events, quality state, pass-network, xT-lite, VAEP-lite, visual artifact, and tactical report dataclasses.
- Added `nutmeg.services.event_data` with a local StatsBomb-like/simplified JSON provider, bundled sample discovery, pass-network aggregation from completed passes, deterministic `xT-lite-v0`, `VAEP-lite-heuristic-v0`, and pure SVG artifact generation.
- Added bundled sample data at `nutmeg/event_data/samples/epl-001-events.json` and verified it is included in the built wheel.
- Added `nutmeg event-tactical-models --fixture-id ... [--events-file ...] [--output-dir ...] --format json` with no-network behavior and unavailable-section reporting.
- Updated docs and registry: `docs/architecture/event-data-tactical-models.md`, `docs/architecture/design-gap-audit.md`, README, `feature-list.json`, and `.specify/specs/038-event-data-tactical-models-v0/verification.md`.
- Verification: targeted event-data/CLI tests -> 13 passed; CLI sample smoke -> 13 events, 6 pass-network edges, 8 xT-lite actions, 7 VAEP-lite players, 3 artifacts; artifact smoke wrote three SVGs; `uv run ruff check .` -> pass; `python3 -m compileall nutmeg` -> pass; `bash scripts/verify.sh` -> 244 passed; graph refresh -> 84 modules / 134 edges.

## 2026-04-26 - 039-news-information-provider-v0

- Completed the local-first latest information/news provider slice for the AI-native betting-analysis client.
- Added `nutmeg.domain.information` with `InformationItem`, `InformationSourceHealth`, `FixtureInformationDigest`, and reliability labels: `official`, `credible`, `rumor`, and `unverified`.
- Added `nutmeg.services.information` with bundled sample discovery, local JSON parsing, RSS/Atom-style parsing, fixture/team filtering, URL/title-source deduplication, source-health warnings, and client-compatible digest payloads.
- Added sample data at `nutmeg/information/samples/epl-001-information.json`, producing three deduplicated `epl-001` updates across official, credible, and rumor labels.
- Added `nutmeg fixture-information --fixture-id ... [--sources-file ...] --format text|json` and documented the CLI contract in README and `docs/architecture/information-provider.md`.
- Wired `FixtureInformationService` into the AI client builder and passed home/away team context from `ClientService.match_workspace()` into providers.
- Updated `/client/matches/{fixture_id}` to render information item titles, source names, reliability labels, source count/latest timestamp, and rumor/unverified warnings.
- Added no-provider regression coverage so the client reports `Information unavailable.` with `status=unavailable`, empty items, and warning details rather than leaking the internal method name.
- Updated `docs/architecture/ai-native-client.md`, `docs/architecture/design-gap-audit.md`, `feature-list.json`, and `.specify/specs/039-news-information-provider-v0/verification.md`; marked the 039 spec `Verified (2026-04-26)`.
- Verification: RED Web rendering test failed on missing information item text; RED unavailable-payload test failed with `KeyError: 'status'`; focused GREEN suite -> 12 passed; wheel inspection included the sample JSON; `uv run ruff check .` -> pass; `python3 -m compileall nutmeg` -> pass; `bash scripts/verify.sh` -> 256 passed; graph refresh -> 87 modules / 136 edges.

## 2026-04-26 - 040-live-information-provider-v0

- Completed the live/cache extension for Nutmeg's information provider, preserving the 039 digest contract while adding explicit source manifests and opt-in remote refresh.
- Added `InformationSourceDefinition` and `InformationCacheEntry` to `nutmeg.domain.information` with JSON-serializable contracts for source manifests and cache metadata.
- Added `LiveInformationProvider` and `HttpFetchResult` in `nutmeg.services.information`: manifest loading, local/remote source validation, bounded HTTP fetch seam, URL-hash cache writes, fresh-cache reads without network, stale-cache fallback after fetch failure, and source-health warning propagation.
- Added `nutmeg/information/samples/epl-001-sources.json` as a safe sample manifest with an enabled local source and disabled example remote source.
- Extended `fixture-information` with manifest/cache/live controls: `--sources-config`, `--cache-dir`, `--live-fetch`, `--cache-ttl-seconds`, `--timeout-seconds`, and `--max-bytes`.
- Extended `client-match` with explicit information manifest/cache/live flags and added `ClientService.set_information_provider()` so the AI-native client can reuse the same provider seam without duplicating refresh logic or changing user-state isolation.
- Fixed a source-default retagging bug exposed by the sample CLI smoke: manifest-level fixture/team defaults now apply only to items missing item-level fixture/team tags, so an explicit `epl-999` item is not pulled into `epl-001`.
- Updated documentation and registry: README, `docs/architecture/information-provider.md`, `docs/architecture/ai-native-client.md`, `docs/architecture/design-gap-audit.md`, `feature-list.json`, and `.specify/specs/040-live-information-provider-v0/verification.md`; marked the 040 spec `Verified (2026-04-26)`.
- Verification: baseline `scripts/verify.sh` -> 256 passed; RED tests failed on missing domain entities, missing CLI/client helper methods, and the retagging regression; focused GREEN suite -> 25 passed; sample manifest CLI smoke -> complete / 3 items / 3 sources; wheel inspection included both information sample JSON files; `uv run ruff check .` -> pass; `python3 -m compileall nutmeg` -> pass; `bash scripts/verify.sh` -> 271 passed; graph refresh -> 87 modules / 136 edges.

## 2026-04-26 - 041-zucai-14match-workflow-v0

- Completed `041-zucai-14match-workflow-v0` so traditional Chinese Sports Lottery 胜负彩14场/任选9场 is now a reusable Nutmeg workflow instead of an ad hoc PDF-generation task.
- Added `nutmeg.domain.zucai` and `nutmeg.services.zucai` for structured issue snapshots, latest odds snapshots, analyst overrides, deterministic baseline recommendations, full14/任九 plan generation, Markdown/PDF report artifacts, Telegram document dispatch metadata, and file-driven outcome grading.
- Added bundled no-network issue 26068 sample data under `nutmeg/zucai/samples/`: issue, odds, overrides, and outcomes.
- Added `zucai-report` and `zucai-grade` CLI commands plus OpenClaw router action `zucai-report` with `--confirm-dispatch` safety for real Telegram sends.
- Extended Telegram Bot API client with `send_document()` for PDF attachments without token leakage in payloads.
- Added docs: `docs/architecture/zucai-14match-workflow.md`, Spec Kit artifacts, README usage, OpenClaw command manual/agent instructions, BotFather command entry, and workspace Nutmeg Telegram instructions.
- Added `reportlab>=4,<5` as a dependency for Chinese-capable PDF rendering and verified sample files are included in the built wheel.
- Verification: focused Zucai/CLI/Telegram/router suite passed, `uv run ruff check .` passed, `python3 -m compileall nutmeg scripts/openclaw` passed, `bash scripts/verify.sh` passed with `283 passed`, and graph refreshed to 90 modules / 138 edges.

## 2026-04-26 - 042-zucai-scheduled-delivery-v0

- Started and implemented the scheduled delivery slice for traditional足彩14场 recurring use.
- Added `zucai-auto-run` design/spec artifacts for quiet daily checks, 16:00 first report, 18:30 revision confirmation, duplicate prevention, local issue registry, and explicit Telegram dispatch.
- Added `nutmeg.domain.zucai_schedule` and `nutmeg.services.zucai_schedule` for slot definitions, registry entries, scheduled run results, run records, active issue selection, slot-specific artifact directories, and duplicate detection.
- Extended `ZucaiWorkflowService` with a custom dispatch caption seam so scheduled reports can label `16:00首版分析` and `18:30修正确认` without duplicating Telegram send logic.
- Added bundled scheduled registry sample `nutmeg/zucai/samples/scheduled-issues.json` and launchd templates under `scripts/launchd/` for 16:00 and 18:30 jobs.
- Added README and architecture docs for registry format, launchd enablement, no-issue silence, run records, and responsible-use boundaries.
- Verification for 042: RED failed on missing `nutmeg.services.zucai_schedule`; GREEN focused suite passed with 11 tests; CLI smokes covered no-issue skip, afternoon PDF, revision PDF, duplicate skip, and force rerun; `uv run ruff check .` passed; `python3 -m compileall nutmeg scripts/openclaw` passed; `bash scripts/verify.sh` passed with 294 tests; graph refreshed to 92 modules / 143 edges; wheel inspection included scheduled registry sample.

## 2026-04-26 - 043-zucai-source-parser-v0

- Started and implemented the source parser slice that feeds scheduled Zucai delivery without requiring hand-written issue registries.
- Added `nutmeg.domain.zucai_source` and `nutmeg.services.zucai_source` for parsed issue results, source sync results, HTML/text normalization, official-like 14-match section parsing, issue snapshot writing, registry merge, active-date inference, and safe opt-in URL fetch validation.
- Added bundled sample source notice `nutmeg/zucai/samples/26068-source-notice.html` and `zucai-source-sync` CLI.
- Registry sync writes `*-issue.json`, updates `issues.json`, infers active dates from sale-stop date, and preserves existing odds/override/revision paths.
- Added docs and README usage showing source sync followed by `zucai-auto-run`.
- Verification for 043: RED failed on missing `nutmeg.services.zucai_source`; GREEN focused parser/CLI suite passed with 8 tests; CLI smoke parsed bundled source into active 26068 registry and `zucai-auto-run` generated a `%PDF`; `uv run ruff check .` passed; `python3 -m compileall nutmeg scripts/openclaw` passed; `bash scripts/verify.sh` passed with 302 tests; graph refreshed to 94 modules / 147 edges; wheel inspection included source and scheduled samples.

## 2026-04-26 - 044-zucai-odds-source-v0

- Started and implemented the odds source slice that feeds scheduled Zucai delivery with generated 16:00 and 18:30 odds snapshots.
- Added `nutmeg.domain.zucai_odds_source` and `nutmeg.services.zucai_odds_source` for odds sync results, local HTML/text odds parsing, complete 14-row validation, odds snapshot writing, registry field updates, and safe opt-in URL fetch validation.
- Added bundled afternoon/revision odds source samples for issue 26068 and `zucai-odds-sync` CLI.
- Slot semantics: `afternoon` writes `odds_file`; `revision` writes `revision_odds_file` while preserving issue and override paths.
- Added docs and README examples showing source sync -> odds sync -> scheduled report.
- Verification for 044: RED failed on missing `nutmeg.services.zucai_odds_source`; GREEN focused odds/CLI suite passed with 8 tests; CLI smoke covered source sync -> afternoon odds sync -> revision odds sync -> revision auto-run PDF using 18:30 odds; `uv run ruff check .` passed; `python3 -m compileall nutmeg scripts/openclaw` passed; `bash scripts/verify.sh` passed with 310 tests; graph refreshed to 96 modules / 150 edges; wheel inspection included all Zucai source/odds samples.

## 2026-04-26 - 045-content-publisher-v0

- Started the content-production publisher slice from `/Users/jz71/clawd/nutmeg-content-prd.md`.
- Design decision: keep Zucai analysis as the source of truth and add a separate `content` publisher layer for candidate scoring, OpenClaw LLM generation, deterministic compliance gates, and review artifacts.
- Added Spec Kit docs under `.specify/specs/045-content-publisher-v0/` and the Superpowers design doc `docs/superpowers/specs/2026-04-26-content-publisher-design.md`.
- Added content domain/service/CLI MVP: scored candidates from Zucai report JSON, `OpenClawContentLlmProvider`, deterministic test provider, schema validation, disclaimer enforcement, LOW/MEDIUM/HIGH/BLOCKED compliance assessment, JSON/Markdown artifacts, and `content-pack` CLI.
- Added bundled no-network sample `nutmeg/content/samples/26068-content-report.json`.
- Verification for 045: RED focused tests failed on missing `nutmeg.services.content` and `content-pack`; GREEN focused content/CLI suite passed with 9 tests; deterministic CLI smoke produced one 5-title review pack; OpenClaw GPT-5.5 smoke produced `llm_status=generated`, `risk=MEDIUM`, and no warnings; `uv run ruff check .` passed; `python3 -m compileall nutmeg scripts/openclaw` passed; `bash scripts/verify.sh` passed with 319 tests; wheel inspection included the content sample; graph refreshed to 99 modules / 152 edges.

## 2026-04-26 - 046-jczq-mixed-parlay-report-v0

- Completed `046-jczq-mixed-parlay-report-v0`, turning the ad hoc竞彩足球4关高赔混合投注 request into a reusable Nutmeg workflow.
- Added `nutmeg.domain.jczq` and `nutmeg.services.jczq` with Sporttery calculator provider, sample provider, deterministic two-combo 4-leg selection profiles, JSON contracts, Markdown/PDF artifacts, and dry-run/real Telegram document dispatch status handling.
- Added bundled no-network sample payload `nutmeg/jczq/samples/mixed-calculator-20260426.json`.
- Added `nutmeg jczq-mixed-report --provider live|sample --pdf --format json` and OpenClaw safe router action `jczq-mixed-report`, including `--confirm-dispatch` protection for real Telegram sends.
- Fixed an existing OpenClaw content-provider CLI resolution bug exposed by full verification: boolean-like `OPENCLAW_CLI=1` is now ignored instead of being treated as the executable path.
- Updated docs/registry/specs: `docs/architecture/jczq-mixed-report.md`, README, OpenClaw command manual/instructions, `feature-list.json`, Spec Kit 046 artifacts, and graph assets.
- Verification: focused JCZQ service/CLI/router suite passed, sample CLI smoke wrote a `%PDF`, live Sporttery smoke returned official update `2026-04-26 18:51:44` and wrote a `%PDF`, `uv run ruff check .` passed, `python3 -m compileall nutmeg scripts/openclaw` passed, `bash scripts/verify.sh` passed with 327 tests, and graph refreshed to 101 modules / 154 edges.

## 2026-04-26 - 045-content-publisher-v0 Bot Runtime Follow-up

- Completed Nutmeg Bot `/content` runtime verification for the content publisher. Root cause for Bot-only fallback was `OPENCLAW_CLI=1` in the OpenClaw agent exec environment being treated as an executable path.
- Hardened `OpenClawContentLlmProvider` command resolution: boolean-like OpenClaw env values are ignored, namespaced/real CLI values still work, and CLI-not-found warnings now include the attempted path for future diagnosis.
- Verified `OPENCLAW_CLI=1` router smoke returns `llm_status=generated`; verified `nutmegbot` `/content nutmeg/content/samples/26068-content-report.json` returns generated content with no fallback and writes `.nutmeg-data/content/content-pack-26068-20260426T105446+0000.{json,md}`.
- Verification: focused content/router suite passed with 19 tests; `uv run ruff check .` passed; `python3 -m compileall nutmeg scripts/openclaw` passed; `bash scripts/verify.sh` passed with 327 tests; OpenClaw Telegram account `nutmeg` reports running/connected/probe_ok for `@jerenusNutmeg_bot`.

## 2026-05-01 - jczq-daily-advisor-v0

- Added a dynamic `jczq-daily-advisor` workflow that scans current Sporttery sellable JCZQ matches and mixed pools without hard-coded match numbers.
- Generated repeatable Chinese daily reports with main, high-odds inspiration, contrarian, and extreme small-stake plans using HAD/HHAD/TTG/CRS/HAFU odds multiplication.
- Added saved daily context and revision handling so `/jczq revise <想法>` can recalculate from the existing slate without refetching.
- Wired CLI, BotAdapter `/jczq` commands, OpenClaw router action, docs, and a 12:00 launchd template; installed the LaunchAgent at `~/Library/LaunchAgents/com.nutmeg.jczq.daily-noon.plist`.
- Verification: focused JCZQ daily/Bot/CLI/router suites passed, Bot natural-language竞彩 revision routing works, live Sporttery smoke returned today’s five-match slate, ruff and compileall passed, and `bash scripts/verify.sh` passed with 463 tests.
