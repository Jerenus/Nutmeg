# Nutmeg Bot / OpenClaw Telegram 使用手册

This document now describes the legacy deterministic router command reference.
`nutmegbot` itself is configured as a project-level Codex entrypoint for
`/Users/jz71/Projects/Nutmeg`, not as a router-only Telegram operator.

## Current Bot Scope

Nutmeg Bot through OpenClaw is Nutmeg Project Codex:

- Telegram/OpenClaw messages are treated like tasks sent to Codex from
  `/Users/jz71/Projects/Nutmeg`.
- The bot may perform project development, debugging, review, tests, docs,
  data-pipeline work, and football-analysis workflows.
- The legacy router remains available when deterministic Telegram-friendly
  football command output is useful, but it is not the boundary for the bot.
- Do not fabricate football facts, odds, injuries, lineups, model probabilities,
  or value calls. Use Nutmeg data, the project CLI, the router, or named sources.
- Do not leak `.env`, API keys, Telegram tokens, OpenClaw credentials, or other
  secrets.
- Ask once before public dispatch, real Telegram broadcast, real betting/funds
  action, large destructive deletes, or irreversible system-level operations.

For the active project-mode agent instruction, use:

```text
docs/integrations/openclaw-nutmeg-agent-instruction.md
```

## Startup Reply

For `/start`, `/help`, or `帮助`, the current `nutmegbot` should not present the
old router-only menu. It should say, in Chinese, that it is Nutmeg Project Codex
and can handle project development, CLI/data tasks, tests, docs, debugging, and
football-analysis workflows from the repo root.

## Operating Model

Current project-mode path:

```text
Telegram message
  -> OpenClaw routing (`telegram:nutmeg -> nutmegbot`)
  -> Nutmeg Project Codex in /Users/jz71/Projects/Nutmeg
  -> optional fixed Codex CLI delegation
  -> optional Nutmeg CLI/router/tool execution
  -> concise Chinese result
```

Default Codex CLI delegation for project work:

```bash
/Users/jz71/.nvm/versions/node/v22.22.1/bin/codex exec -C /Users/jz71/Projects/Nutmeg --dangerously-bypass-approvals-and-sandbox "<complete task>"
```

Run project commands from the Nutmeg project root:

```bash
cd /Users/jz71/Projects/Nutmeg
```

Legacy deterministic router helper:

```bash
python3 scripts/openclaw/nutmeg_command_router.py --reply-text <action> [options]
```

The `--reply-text` output is still useful when the desired result is a stable
Telegram-ready Nutmeg football command response. JSON mode remains available for
explicit diagnostics/raw payload requests.

Dry-run a route without executing Nutmeg:

```bash
python3 scripts/openclaw/nutmeg_command_router.py --print-command popular --league epl --days 3
```

The router serializes execution with `.nutmeg-data/state/openclaw-router.lock`
to avoid DuckDB single-file lock conflicts.

## OpenClaw Wiring

Configured OpenClaw objects:

- Telegram account: `nutmeg`
- Agent: `nutmegbot`
- Binding: `telegram:nutmeg -> nutmegbot`
- Workspace: `/Users/jz71/Projects/Nutmeg`
- Model: `nyu-openai-chat/gpt-5.5` with fallback `nyu-openai/gpt-5.4`
- Preferred Codex CLI: `/Users/jz71/.nvm/versions/node/v22.22.1/bin/codex`
- Token storage: `/Users/jz71/.openclaw/credentials/telegram-nutmeg-token`

Use the `nyu-openai-chat/gpt-5.5` provider for this bot. Direct
`nyu-openai/gpt-5.5` over the OpenAI Responses path can answer plain text, but
has historically failed on tool-result continuation because the provider returns
non-persisted `store=false` response items. The Chat Completions compatibility
provider keeps tool calls stable.

Do not run `uv run nutmeg telegram-bot-run` with the same bot token while
OpenClaw owns this `nutmeg` account.

## Response Envelope

The legacy router returns JSON:

```json
{
  "ok": true,
  "action": "popular",
  "command": ["uv", "run", "nutmeg", "..."],
  "returncode": 0,
  "payload": {},
  "stdout": "",
  "stderr": ""
}
```

For router-backed Telegram responses, OpenClaw may use `--reply-text` and send
or summarize the output. Do not paste large raw JSON into Telegram unless the
user explicitly asks for diagnostics.

## Safety Policy

- Project work is not router-only; shell/project edits are allowed in the repo.
- Never reveal secrets from `.env`, credentials files, Telegram token files, or
  OpenClaw state.
- Live provider sync requires explicit intent; public dispatch requires explicit
  confirmation.
- Prediction writes, final-plan writes, and report artifacts are allowed when
  the user asks for that workflow.
- Content generation produces review artifacts only unless the user explicitly
  asks for dispatch/publication and confirms it.
- Nutmeg remains analysis assistance only: no bet placement, no sportsbook
  connection, and no guaranteed-profit claims.
- If a router command returns `ok=false`, report the error and suggest the next
  useful command; do not invent data.

## Supported Actions

### Health and Status

Telegram:

```text
/status
```

Router:

```bash
python3 scripts/openclaw/nutmeg_command_router.py status
python3 scripts/openclaw/nutmeg_command_router.py doctor
python3 scripts/openclaw/nutmeg_command_router.py telegram-status
```

Use `status` for normal health. Use `doctor` for deeper setup diagnostics.

### Demo Seed

Telegram:

```text
/demo
```

Router:

```bash
python3 scripts/openclaw/nutmeg_command_router.py seed-demo --league epl
```

Use this before demo-only tests such as `epl-001`.

### Fixtures

Telegram:

```text
/fixtures epl 7
```

Router:

```bash
python3 scripts/openclaw/nutmeg_command_router.py fixtures --league epl --days 7
python3 scripts/openclaw/nutmeg_command_router.py fixtures --league epl --days 7 --demo
```

This command returns text output in `stdout`, not a structured payload.

### Live Fixture Sync

Telegram:

```text
/sync epl 14
```

Router:

```bash
python3 scripts/openclaw/nutmeg_command_router.py sync --league epl --days 14 --confirm-live
```

Do not use this automatically for casual questions. Prefer cached fixtures first.

### Popular Matches

Telegram:

```text
/popular epl 3
今天有哪些热门比赛？
```

Router:

```bash
python3 scripts/openclaw/nutmeg_command_router.py popular --league epl --days 3 --limit 5
python3 scripts/openclaw/nutmeg_command_router.py popular --league epl --days 3 --limit 5 --demo
```

Reply with rank, teams, kickoff, score/tier, and suggested `/brief` command.

### Today Brief Candidates

Telegram:

```text
/today epl 3
```

Router:

```bash
python3 scripts/openclaw/nutmeg_command_router.py today --league epl --days 3 --limit 5
python3 scripts/openclaw/nutmeg_command_router.py today --league epl --days 3 --limit 5 --briefs
```

Use this when the user asks for the day's match menu. Add `--briefs` only when
the user wants one-pass mini-briefs for each candidate.

### Fixture Snapshot

Telegram:

```text
/snapshot epl-001
```

Router:

```bash
python3 scripts/openclaw/nutmeg_command_router.py snapshot --fixture-id epl-001
```

Summarize venue, kickoff, referee, weather, rest days, injuries, suspensions,
lineups, head-to-head, splits, and trends when present.

### Odds Snapshot

Telegram:

```text
/odds epl-001
```

Router:

```bash
python3 scripts/openclaw/nutmeg_command_router.py odds --fixture-id epl-001
```

Summarize provider, bookmaker count, match-winner fair probabilities, BTTS,
totals, Asian handicap if present, and missing markets.

### Match Brief

Telegram:

```text
/brief epl-001 这场比赛怎么看？
/brief epl-001
这场 epl-001 怎么看？
```

Router:

```bash
python3 scripts/openclaw/nutmeg_command_router.py brief --fixture-id epl-001 --query "这场比赛怎么看？"
```

This is the main analysis command. Reply with:

- Verdict
- Confidence
- 3-5 key reasons
- Market/tactical caveats
- Suggested next command, usually `/odds`, `/snapshot`, or `/visuals`

### Analysis Command

Telegram:

```text
/analyze epl-001 是否支持主队？
```

Router:

```bash
python3 scripts/openclaw/nutmeg_command_router.py analyze --fixture-id epl-001 --query "是否支持主队？"
```

Prefer `/brief` for operator-facing answers. Use `/analyze` for lower-level
deterministic analysis diagnostics.

### Value Board

Telegram:

```text
/value epl 3
有没有价值盘？
```

Router:

```bash
python3 scripts/openclaw/nutmeg_command_router.py value --league epl --days 3 --limit 10
python3 scripts/openclaw/nutmeg_command_router.py value --league epl --days 3 --limit 10 --min-edge 0.05
```

Reply with top candidates, model probability, market fair probability, edge,
and quarter-Kelly sizing. Always state that this is decision support, not a
guarantee.

### Player Profile

Telegram:

```text
/player epl 2025 Arsenal Bukayo Saka
看一下 Bukayo Saka
```

Router:

```bash
python3 scripts/openclaw/nutmeg_command_router.py player --league epl --season 2025 --team Arsenal --player "Bukayo Saka"
```

If the user omits context, default to `league=epl` and `season=2025` only when
the team is clear. Otherwise ask one short clarification.

### Tactical Visuals

Telegram:

```text
/visuals epl-001
给我这场的战术图
```

Router:

```bash
python3 scripts/openclaw/nutmeg_command_router.py visuals --fixture-id epl-001
```

The router writes SVGs under `.nutmeg-data/visuals` through Nutmeg. Reply with
artifact names and paths. State clearly that v0 visuals are proxy SVGs, not
event-data charts.

### Daily Operator Run

Telegram:

```text
/daily epl 3
```

Router:

```bash
python3 scripts/openclaw/nutmeg_command_router.py daily --league epl --days 3
python3 scripts/openclaw/nutmeg_command_router.py daily --league epl --days 3 --briefs
python3 scripts/openclaw/nutmeg_command_router.py daily --league epl --days 3 --live-sync --confirm-live
```

Real Telegram dispatch is intentionally gated:

```bash
python3 scripts/openclaw/nutmeg_command_router.py daily --league epl --days 3 --dispatch-telegram --confirm-dispatch
```

Only use dispatch when the user explicitly asks to send outbound Telegram
messages.


### Content Publisher Review Pack

Telegram:

```text
/content <report_json_path>
生成今天足彩分享文案
基于刚才的足彩报告生成分享文案
```

Router:

```bash
python3 scripts/openclaw/nutmeg_command_router.py content --report-file .nutmeg-data/zucai/zucai-26068-report.json --limit 3
python3 scripts/openclaw/nutmeg_command_router.py content --report-file nutmeg/content/samples/26068-content-report.json --limit 1 --llm-mode deterministic
```

Use this after `zucai-report` or `zucai-auto-run` has produced a report JSON.
If the user asks for "今天足彩分享文案" and no report path is in the current
conversation, first run `zucai-report --issue-id <issue> --pdf`, read
`payload.artifacts.report_json_path`, then run `content --report-file <that path>`.
Reply with the selected match, 5 title candidates, risk level, publish
recommendation, artifact paths, and a concise copyable draft. Do not auto-post
to Douyin, WeChat, Zhihu, Xiaohongshu, private groups, or any external platform.

### Eval and Prediction Review

Telegram:

```text
/eval
/review
```

Router:

```bash
python3 scripts/openclaw/nutmeg_command_router.py eval --dataset starter
python3 scripts/openclaw/nutmeg_command_router.py review
```

Use `/review` to summarize historical prediction quality and Brier Score.

### Prediction Writes

Telegram:

```text
/record ...
/outcome ...
```

Router:

```bash
python3 scripts/openclaw/nutmeg_command_router.py prediction-record \
  --fixture-id epl-001 \
  --league epl \
  --home-team Arsenal \
  --away-team "Tottenham Hotspur" \
  --home-probability 0.60 \
  --draw-probability 0.25 \
  --away-probability 0.15 \
  --pick home \
  --confirm-write
```

```bash
python3 scripts/openclaw/nutmeg_command_router.py prediction-outcome \
  --prediction-id 1 \
  --actual home \
  --confirm-write
```

Only write predictions when the user explicitly gives all fields.

## Natural-Language Routing Rules

- "今天有哪些热门比赛？" -> `popular --league epl --days 3 --limit 5`
- "这几场怎么看？" -> use recent fixture ids from context; if none, run `popular`.
- "帮我看 epl-001" -> `brief --fixture-id epl-001 --query "这场比赛怎么看？"`
- "有没有价值？" with fixture id -> `brief`; without fixture id -> `value`.
- "赔率怎么样？" -> `odds --fixture-id <id>` if id known; otherwise ask for fixture id.
- "战术图" -> `visuals --fixture-id <id>`.
- "Saka 怎么样？" -> if team is clear, `player`; otherwise ask for team.
- "同步一下" -> ask for confirmation before `sync --confirm-live`.
- `/jczq` / "竞彩足球每日分析" / "今天竞彩方案" / "高赔率灵感票" -> run `jczq-daily-advisor --provider live --date today`; if the user gives a natural-language correction such as "不要比分，提高到100倍", pass it as `--revision-text`; dispatch only with explicit confirmation.
- "竞彩足球4关高赔PDF" / "混合投注PDF" / `/jczqpdf` -> run `jczq-mixed-report --provider live --pdf`; dispatch only with explicit confirmation.
- "生成足彩分享文案" / "今天足彩内容" -> if a `report_json_path` is known, run `content --report-file <path> --limit 3`; otherwise run `zucai-report --issue-id <issue> --pdf` first and then run `content` with the returned report path.

## Telegram Formatting Rules

- Use Chinese.
- Keep normal replies under roughly 1200 characters.
- No markdown tables.
- Use bullets for lists.
- Include fixture id in every match-specific answer.
- Do not claim live truth if data is cached or unavailable.
- If the payload has `skipped`, `unavailable_sections`, or `deferred_sections`,
  mention the limitation.

## Startup Checklist

1. Do not run Nutmeg's own `telegram-bot-run` if OpenClaw owns the same bot token.
2. From Nutmeg root, verify:

```bash
python3 scripts/openclaw/nutmeg_command_router.py status
python3 scripts/openclaw/nutmeg_command_router.py --print-command popular --league epl --days 3
```

3. If no cached fixtures exist:

```bash
python3 scripts/openclaw/nutmeg_command_router.py seed-demo --league epl
```

4. For real data, only after user confirmation:

```bash
python3 scripts/openclaw/nutmeg_command_router.py sync --league epl --days 14 --confirm-live
```

### Traditional Zucai 14-Match Report

Telegram:

```text
/zucai 26068
生成26068期足彩14场报告
```

Router:

```bash
python3 scripts/openclaw/nutmeg_command_router.py zucai-report --issue-id 26068 --pdf
python3 scripts/openclaw/nutmeg_command_router.py zucai-report --issue-id 26068 --pdf --dispatch-telegram --confirm-dispatch
```

Use this for traditional Chinese Sports Lottery `胜负彩14场/任选9场` issue reports. The command reads Nutmeg's structured issue/odds/override snapshots, generates `3/1/0` recommendations and plans, writes Markdown/PDF artifacts, and can attach the PDF through Telegram only with explicit dispatch confirmation. Do not describe it as guaranteed betting advice.

## JCZQ Daily Advisor

Use this for the repeatable daily竞彩足球 analysis path, high-odds inspiration tickets, contrarian public-heat avoidance, and user-driven revisions.

```bash
python3 scripts/openclaw/nutmeg_command_router.py jczq-daily-advisor --provider live --date today
python3 scripts/openclaw/nutmeg_command_router.py jczq-daily-advisor --provider live --date today --revision-text "不要比分，提高到100倍"
python3 scripts/openclaw/nutmeg_command_router.py jczq-daily-advisor --provider live --date today --dispatch-telegram --confirm-dispatch
```

The command dynamically scans sellable HAD/HHAD/TTG/CRS/HAFU pools, writes `.nutmeg-data/jczq/daily/<date>/context.json`, and returns the final main plan plus high-odds inspiration/contrarian/extreme plans. Explain that it is small-stake entertainment analysis only, not guaranteed betting advice.

## JCZQ Mixed Parlay Report

Use this legacy artifact workflow when the user specifically asks for a PDF report.

```bash
python3 scripts/openclaw/nutmeg_command_router.py jczq-mixed-report --provider live --pdf
python3 scripts/openclaw/nutmeg_command_router.py jczq-mixed-report --provider live --pdf --dispatch-telegram --confirm-dispatch
```

The command returns JSON with combinations and artifact paths. Real Telegram dispatch requires explicit user confirmation and `--confirm-dispatch`.
