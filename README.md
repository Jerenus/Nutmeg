        # Nutmeg · 过人

        [Foundation Spec](./.specify/specs/001-platform-foundation/spec.md) · [Fixtures Sync Spec](./.specify/specs/002-fixtures-sync/spec.md) · [Fixture Snapshot Spec](./.specify/specs/003-fixture-snapshot/spec.md) · [Pre-Match Snapshot Spec](./.specify/specs/004-pre-match-snapshot/spec.md) · [Architecture](./docs/architecture/overview.md) · [Analysis Judgment](./docs/architecture/analysis-judgment.md) · [Tactics Synthesis](./docs/architecture/tactics-synthesis.md) · [Tactical Visuals](./docs/architecture/tactical-visuals.md) · [Market Shape Expansion](./docs/architecture/market-shape-expansion.md) · [Harness](./docs/process/long-running-agent-harness.md) · [Latest Design](./Nutmeg-DESIGN-v0.3.md)

        Nutmeg is a CLI-first football analysis agent foundation for tactical analysis, odds intelligence, player intelligence, and synthesis-driven judgment.

        The repository is now aligned with `Nutmeg-DESIGN-v0.3.md`:
        - Phase 1 is a private single-user tool with multi-tenant-ready user-state boundaries.
        - Objective football data is stored globally and reused across users.
        - CLI, IM bot, and the owner/private-beta Web/PWA client share the same grounded analysis services.
        - Spec Kit governs planning; Superpowers Bridge enforces TDD and verification.
        - Long-running agent continuity uses `init.sh`, `agent-progress.md`, and `feature-list.json`.

        ## Architecture Snapshot

        ```mermaid
        flowchart TD
            CLI["CLI · Typer"] --> Router
            Bot["IM Bot · Telegram/Discord"] --> Router
            Router{"Router
intent classifier"}
            Router --> Tactics["TacticsAgent"]
            Router --> Odds["OddsAgent"]
            Router --> Player["PlayerAgent"]
            Router --> Synth["SynthesisAgent"]
            Tactics --> Tools["Tools / MCP-ready layer"]
            Odds --> Tools
            Player --> Tools
            Synth --> Tools
            Tools --> Shared["Shared objective data"]
            Shared --> DuckDB[(DuckDB fixtures cache)]
            Tools --> UserState["User-scoped state"]
            UserState --> SQLite[(SQLite state store)]
            Shared --> Sources["API-Football · soccerdata · Transfermarkt · StatsBomb Open"]
            Tactics -. traces .-> LangSmith["LangSmith"]
            Odds -. traces .-> LangSmith
            Player -. traces .-> LangSmith
            Synth -. traces .-> LangSmith
        ```

        ## Confirmed Stack

        - Runtime: Python 3.12+, `uv`, Typer, Rich
        - Architecture: modular monolith, LangGraph-ready agent orchestration, shared-facts/user-state split
        - Storage: DuckDB for shared analytical fixture cache, SQLite for mutable app state, Parquet reserved for archive
        - Reliability: Spec Kit + Superpowers Bridge + TDD + verification-before-completion
        - LLM access: Portkey-first configuration, LangSmith tracing support

        ## Quickstart

        ```bash
        cp .env.example .env
        bash ./init.sh
        uv run nutmeg fixtures --league epl --demo
        uv run nutmeg fixtures-sync --league epl --days 14
        uv run pytest
        ```

        ## Intelligence OS (M1 headless contract)

        Initialize the Ontology Kernel v2 store, then launch the local API:

        ```bash
        uv run nutmeg ontology init
        uv run nutmeg app
        ```

        M1 is API-only; M2 adds the Command Center and Data Operations UI. Product
        reads and writes use Ontology Kernel v2 exclusively, and every mutation passes
        through a governed Action. There is no autonomous funds action or unattended
        betting path. `decision-web` remains a legacy workshop and is not a product
        data source.

        `fixtures-sync` requires `NUTMEG_API_FOOTBALL_KEY`. Without it, the CLI remains usable with demo fixtures.

        To exercise the fuller Sprint 1 snapshot:

        ```bash
        uv run nutmeg seed-demo --league epl
        uv run nutmeg fixture-snapshot --fixture-id epl-001 --format json
        ```

        Snapshot provider behavior:
        - `soccerdata` -> season stats + recent form + shot summary + recent goals/xG/set-piece trends
        - `transfermarkt-datasets` -> market value + probable lineup inference + bench-depth context
        - `API-Football` -> confirmed lineups, injuries, suspensions, head-to-head, and home/away splits when `NUTMEG_API_FOOTBALL_KEY` is configured
        - `Open-Meteo` + `Nominatim` fallback -> venue geocoding, kickoff local time, weather, and away-travel context

        Richer snapshot notes:
        - environment/schedule fields now render in both text and JSON output
        - availability is grouped into injuries, suspensions, returning players, summary, and bench depth
        - matchup/trend sections stay explicit about unavailable provider-backed fields when API-Football is not configured

        In JSON mode, `fixture-snapshot` keeps stdout machine-parseable and routes provider noise away from the JSON payload.

        To refresh the shared local reference/materialized cache:

        ```bash
        uv run nutmeg reference-refresh --league epl --season 2025
        ```

        ## Long-running agent workflow

        1. Run `pwd`, read `agent-progress.md`, `feature-list.json`, and recent git history.
        2. Run `bash ./init.sh` to restore the local environment.
        3. Pick one incomplete feature from `feature-list.json`.
        4. Implement it incrementally, verify it, update `feature-list.json`, then append to `agent-progress.md`.

        ## Useful commands

        ```bash
        uv run nutmeg doctor --format json
        uv run nutmeg fixtures --league epl --next 7
        uv run nutmeg fixtures-sync --days 30
        uv run nutmeg fixture-snapshot --fixture-id epl-001 --format json
        bash scripts/verify.sh
        ```


First analysis workflow:

```bash
uv run nutmeg analyze-match --fixture-id epl-001 --query "Should I back Arsenal?"
```

Operator match brief:

```bash
uv run nutmeg match-brief --fixture-id epl-001 --query "Should I back Arsenal?"
uv run nutmeg match-brief --fixture-id epl-001 --query "Should I back Arsenal?" --format json
```

No-network IM bot adapter dry-run and optional GPT-5.5 fallback:

```bash
uv run nutmeg bot-dry-run --message "/brief epl-001 Should I back Arsenal?"
uv run nutmeg bot-dry-run --message "/brief epl-001 Should I back Arsenal?" --format json
uv run nutmeg bot-dry-run --message "今天有哪些热门比赛？" --format json
```

The bot always answers `/start` and `help` deterministically. Unsupported messages or failed `/brief` attempts can use OpenAI Responses API fallback when configured:

```bash
NUTMEG_OPENAI_API_KEY=...
NUTMEG_BOT_LLM_FALLBACK_ENABLED=true
NUTMEG_BOT_LLM_FALLBACK_MODEL=gpt-5.5
```

The deterministic `/brief <fixture_id> <query>` path remains primary; the LLM fallback is a conversational safety net and does not invent live match facts.

Telegram transport status, one-shot polling, and controlled daemon polling:

```bash
uv run nutmeg telegram-bot-status --format json
uv run nutmeg telegram-bot-poll-once --timeout 1 --format json
uv run nutmeg telegram-bot-run --timeout 10 --poll-interval 2 --max-polls 5 --format json
uv run nutmeg telegram-bot-run --timeout 10 --poll-interval 2
```

`telegram-bot-poll-once` and `telegram-bot-run` require `NUTMEG_TELEGRAM_BOT_TOKEN` and `NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS`.
`telegram-bot-run` persists `next_offset` by default at `.nutmeg-data/state/telegram-bot.offset`, so restarts no longer need manual `--offset`. Use `--offset` only for recovery, `--offset-file` for a custom path, or `--no-offset-file` to disable persistence.
Use `--max-polls` for local/cron validation; omit it only when running a supervised long-lived process.

OpenClaw Telegram integration:

`nutmegbot` is now configured as a project-level Codex entrypoint for this repo.
Telegram/OpenClaw messages should be treated like tasks sent to Codex from
`/Users/jz71/Projects/Nutmeg`, not like a router-only command surface. The
legacy router is still available as a deterministic helper for football command
output:

```bash
python3 scripts/openclaw/nutmeg_command_router.py status
python3 scripts/openclaw/nutmeg_command_router.py --reply-text status
python3 scripts/openclaw/nutmeg_command_router.py --print-command popular --league epl --days 3
python3 scripts/openclaw/nutmeg_command_router.py popular --league epl --days 3
```

Use OpenClaw as the Telegram entrypoint and Nutmeg/Codex as the execution
engine. The OpenClaw-facing project-mode instruction is documented in
`docs/integrations/openclaw-nutmeg-agent-instruction.md`; the legacy router
command reference remains in `docs/integrations/openclaw-telegram-command-manual.md`.
The configured OpenClaw objects are Telegram account `nutmeg`, agent
`nutmegbot`, and binding `telegram:nutmeg`.
OpenClaw's global default model is `nyu-openai-chat/gpt-5.5` with
`nyu-openai/gpt-5.4` as fallback, so default-inheriting OpenClaw agents use the
same GPT-5.5 compatibility path as `nutmegbot`.
`nutmegbot` should point directly at this project root:
`/Users/jz71/Projects/Nutmeg`.
If OpenClaw owns a Telegram bot token, do not run `telegram-bot-run` with the
same token at the same time.

Today/local fixture brief candidates and popularity ranking:

```bash
uv run nutmeg popular-matches --league epl --days 3 --demo --format json
uv run nutmeg today-briefs --league epl --days 3 --demo
uv run nutmeg today-briefs --league epl --days 3 --demo --sort popularity --format json
uv run nutmeg today-briefs --league epl --days 3 --demo --briefs --format json
```

`popular-matches` is no-network and explains each score with competition, team prominence, rivalry, kickoff timing, and live-status reasons.

Model-vs-market value board:

```bash
uv run nutmeg value-board --league epl --days 3 --limit 10 --format json
uv run nutmeg value-board --league epl --days 3 --min-edge 0.05
```

`value-board` compares a deterministic Dixon-Coles-lite Poisson model against
the match-winner market fair probability and ranks positive-edge candidates with
quarter-Kelly sizing. It reports skipped fixtures when snapshot or odds inputs
are unavailable instead of fabricating a value call.

The browser Workshop (judgment cockpit) is served by `nutmeg decision-web` — see
[JCZQ Daily Decision Workflow](#jczq-daily-decision-workflow-decision-ontology)
below. The legacy `client-web`/PWA cluster was buried in the 2026-07-07 Workshop
cutover.

Traditional Zucai 14-match workflow:

```bash
uv run nutmeg zucai-report --issue-id 26068 --pdf --format json
uv run nutmeg zucai-report --issue-id 26068 --pdf --dispatch-telegram --dry-run --format json
uv run nutmeg zucai-grade --report-file .nutmeg-data/zucai/zucai-26068-report.json --outcomes-file nutmeg/zucai/samples/26068-outcomes.json --format json
python3 scripts/openclaw/nutmeg_command_router.py --print-command zucai-report --issue-id 26068 --pdf
```

`zucai-report` is the reusable traditional足彩胜负彩14场/任选9场 workflow.
It reads explicit issue/odds/override JSON snapshots, generates `3/1/0`
recommendations, full14/任九 plans, Markdown/PDF artifacts, and optional
Telegram document dispatch. Dispatch is dry-run by default; real Telegram send
requires `--dispatch-telegram --no-dry-run`. The bundled 26068 sample is
no-network and exists for smoke tests and report template reuse.


Zucai source sync:

```bash
uv run nutmeg zucai-source-sync --source-file nutmeg/zucai/samples/26068-source-notice.html --date 2026-04-26 --output-dir .nutmeg-data/zucai/source-smoke --registry-file .nutmeg-data/zucai/source-smoke/issues.json --format json
uv run nutmeg zucai-auto-run --date 2026-04-26 --slot afternoon --registry-file .nutmeg-data/zucai/source-smoke/issues.json --output-dir .nutmeg-data/zucai/source-smoke/scheduled --run-record-file .nutmeg-data/zucai/source-smoke/scheduled-runs.json --dispatch-telegram --dry-run --format json
```

Zucai odds sync:

```bash
uv run nutmeg zucai-odds-sync --source-file nutmeg/zucai/samples/26068-odds-source-afternoon.html --issue-id 26068 --slot afternoon --captured-at "2026-04-26 16:00 CST" --output-dir .nutmeg-data/zucai/source-smoke --registry-file .nutmeg-data/zucai/source-smoke/issues.json --format json
uv run nutmeg zucai-odds-sync --source-file nutmeg/zucai/samples/26068-odds-source-revision.html --issue-id 26068 --slot revision --captured-at "2026-04-26 18:30 CST" --output-dir .nutmeg-data/zucai/source-smoke --registry-file .nutmeg-data/zucai/source-smoke/issues.json --format json
```

`zucai-odds-sync` parses local odds tables into `*-odds.json` snapshots and
updates the scheduled registry. The `afternoon` slot writes `odds_file`; the
`revision` slot writes `revision_odds_file`, so the 18:30 report can use later
odds without overwriting the 16:00 evidence. URL mode is refused unless
`--live-fetch` is explicitly provided.

`zucai-source-sync` parses an official-like traditional足彩 schedule notice into
valid `*-issue.json` snapshots and updates the registry consumed by
`zucai-auto-run`. Local files are the default. `--source-url` is refused unless
`--live-fetch` is explicitly provided, so tests and normal local runs make no
surprise network calls. This slice only discovers issues/schedules; odds source
automation remains a separate follow-on feature.

Scheduled traditional Zucai delivery:

```bash
uv run nutmeg zucai-auto-run --date 2026-04-26 --slot afternoon --registry-file nutmeg/zucai/samples/scheduled-issues.json --dispatch-telegram --dry-run --format json
uv run nutmeg zucai-auto-run --date 2026-04-26 --slot revision --registry-file nutmeg/zucai/samples/scheduled-issues.json --dispatch-telegram --dry-run --format json
uv run nutmeg zucai-auto-run --date 2026-04-27 --slot afternoon --registry-file nutmeg/zucai/samples/scheduled-issues.json --format json
```

`zucai-auto-run` is the quiet daily wrapper for the 16:00 first report and
18:30 revision/decision-confirmation report. It reads `.nutmeg-data/zucai/issues.json`
by default, skips silently with `skipped_no_issue` when no active issue exists,
writes slot-specific artifacts under `.nutmeg-data/zucai/scheduled/`, records
runs in `.nutmeg-data/zucai/scheduled-runs.json`, and prevents duplicate sends
unless `--force` is provided. launchd templates live in `scripts/launchd/` and
must be reviewed/installed explicitly before real `--dispatch-telegram --no-dry-run`
automation is enabled.

Latest fixture information digest:

```bash
uv run nutmeg fixture-information --fixture-id epl-001 --home-team Arsenal --away-team "Tottenham Hotspur" --format json
uv run nutmeg fixture-information --fixture-id epl-001 --sources-file nutmeg/information/samples/epl-001-information.json
uv run nutmeg fixture-information --fixture-id epl-001 --sources-config nutmeg/information/samples/epl-001-sources.json --format json
```

`fixture-information` reads local JSON/RSS files or an explicit source manifest,
normalizes source-attributed updates, deduplicates repeated reports, and labels
reliability as `official`, `credible`, `rumor`, or `unverified`. Remote RSS/JSON
URLs are never fetched by default; use `--live-fetch` with a trusted manifest to
opt into bounded HTTP refresh and local cache writes. Missing, malformed, failed,
or stale sources return `status=unavailable` or `status=partial` with warnings
instead of fabricated news. The AI-native match workspace renders the same
digest in its information panel.

Player profile and similarity:

```bash
uv run nutmeg player-profile --league epl --season 2025 --team Arsenal --player "Bukayo Saka" --format json
```

Local eval, prediction review, and daily operation:

```bash
uv run nutmeg eval-run --dataset starter --format json
uv run nutmeg prediction-record --fixture-id epl-001 --league epl --home-team Arsenal --away-team "Tottenham Hotspur" --home-probability 0.60 --draw-probability 0.25 --away-probability 0.15 --pick home
uv run nutmeg prediction-review --format json
uv run nutmeg daily-run --league epl --days 3 --format json
```

`daily-run` is dry-run by default. Use `--live-sync` for upstream fixture sync,
`--briefs` for match brief fan-out, and `--dispatch-telegram --no-dry-run` only
when you explicitly want outbound Telegram messages.


Event-data tactical models:

```bash
uv run nutmeg event-tactical-models --fixture-id epl-001 --format json
uv run nutmeg event-tactical-models --fixture-id epl-001 --events-file nutmeg/event_data/samples/epl-001-events.json --output-dir .nutmeg-data/event-models --format json
```

`event-tactical-models` reads local StatsBomb-like or simplified event JSON,
normalizes passes, shots, carries, and defensive actions, then builds
pass-network, `xT-lite-v0`, and `VAEP-lite-heuristic-v0` reports. The labels are
intentional: this v0 slice is deterministic and local-first, not a trained xT or
VAEP parity claim.

Tactical visual artifacts:

```bash
uv run nutmeg tactical-visuals --fixture-id epl-001 --format json
uv run nutmeg tactical-visuals --fixture-id epl-001 --output-dir .nutmeg-data/visuals
```

`tactical-visuals` creates local SVG shot-map, lineup-network, and recent xG
trend artifacts from fixture snapshot context. It labels aggregate/lineup
visuals as proxies and reports missing sections instead of inventing event data.

## Acceptance Checks

Safe local acceptance is no-network by default:

```bash
bash scripts/acceptance.sh --dry-run
make acceptance
```

Live provider acceptance is explicit and fails fast without required keys:

```bash
NUTMEG_API_FOOTBALL_KEY=... bash scripts/acceptance.sh --live --league epl --past-days 7
```

## JCZQ Daily Decision Workflow (Decision Ontology)

The live JCZQ path is the decision-ontology five-verb loop
(sense/read/express/reconcile/calibrate). The legacy brief/debate/tiered/bold
engines were removed in the 2026-07-07 M2 cutover.

```bash
# 1. Morning data ingest + market-baseline shadows (launchd 08:00)
uv run nutmeg decision-am --run-date $(date +%F) --output-dir .nutmeg-data/jczq
# 2. Claude judges each match in the main loop, then lands structured Reads
uv run nutmeg decision-read --reads-file <reads.json> --output-dir .nutmeg-data/jczq
# 3. Closing capture -> tickets from daily/<date>/legs.json -> PDF report (launchd 19:00; no legs.json = legal empty slate)
uv run nutmeg decision-close --run-date $(date +%F) --output-dir .nutmeg-data/jczq
# 4. Next-day settlement: Brier/CLV scoring + factor calibration + review report (launchd 08:10)
uv run nutmeg decision-settle --run-date <yesterday> --output-dir .nutmeg-data/jczq
# Optional: browser Workshop — review drafts, interrogate & co-refine, confirm legs (127.0.0.1 only)
uv run nutmeg decision-web --output-dir .nutmeg-data/jczq
```

`decision-close` and `decision-settle` default to dry-run; Telegram delivery
requires an explicit `--dispatch-telegram --no-dry-run`. Nutmeg remains
analysis assistance only: no bet placement, no sportsbook connection, and no
guaranteed-profit claims.

Formal decision and Zucai reports share a durable notification ledger. The
business report path remains the latest copy, while the exact sent attachment
is retained under `.nutmeg-data/notifications/artifacts/<notification-id>/`.

```bash
uv run nutmeg notification-status --since 7d
uv run nutmeg notification-show --notification-id <id>
uv run nutmeg notification-retry --notification-id <id>
```

Delivery is at-least-once with local deduplication. If a process stops after
Telegram accepts a message but before Nutmeg records the response, the attempt
is marked `uncertain`; retrying it can duplicate the message and the audit
timeline records that risk. A real Telegram smoke remains an explicit outbound
action and must not be performed as part of automated tests or dry-run replay.

## Ontology Kernel v2 — Package 1 (experimental)

A ground-up rebuild of the decision write path is underway. **Package 1** ships
only the transactional kernel — a separate SQLite operational database
(`.nutmeg-data/ontology/ontology.db`), a content-addressed artifact store, typed
and idempotent Actions, deny-by-default permissions, and numbered migrations. It
creates no football-domain objects yet.

```bash
uv run nutmeg ontology init --format json     # apply migrations (idempotent)
uv run nutmeg ontology status --format json    # read-only; never initializes/migrates
```

The five-verb `decision` commands above remain the **current production
interface** until the Package 5 cutover; the decision schedules are intentionally
paused during this approved rebuild and are not re-enabled until the cutover
gates pass. Design: `docs/superpowers/specs/2026-07-20-ontology-kernel-v2-design.md`;
operations: `docs/ontology-kernel-operations.md`.
