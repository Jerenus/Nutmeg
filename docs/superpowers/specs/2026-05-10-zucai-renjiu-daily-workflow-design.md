# Zucai Renjiu Daily Workflow Design

Feature date: 2026-05-10
Scope: Daily traditional Zucai 任选9 workflow that can be triggered by natural language and produces three budget tiers.

## Goal

Create a repeatable daily workflow for traditional Chinese Sports Lottery 胜负彩/任选9 that turns a natural-language request into a complete Renjiu decision pack. The workflow should produce three 任选9 tickets in distinct budget bands, explain the reasoning, identify the recommended ticket, render durable artifacts, and optionally send a PDF via the configured Nutmeg Telegram bot.

The workflow is analysis-only. It never places bets, never connects to sportsbooks, and must state that outputs are entertainment analysis, not guaranteed outcomes.

## Natural-Language Triggers

The workflow should be reachable from chat/bot/operator text without requiring the user to remember a CLI command. Trigger examples:

- `今天任选9怎么打`
- `今天任九方案`
- `今天传统足彩任九`
- `做今天的14选9`
- `给我三档任九预算方案`
- `today's renjiu plan`
- `today's zucai 9-pick plan`

When triggered, the system should run the full workflow through output and Telegram dispatch if Telegram dispatch is enabled for the caller/context. It should not stop after data collection unless there is a fatal data gap.

## Proposed CLI Surface

The underlying command should be explicit and scriptable:

```bash
uv run nutmeg zucai-renjiu-daily \
  --date today \
  --output-dir .nutmeg-data/zucai \
  --dispatch-telegram \
  --no-dry-run
```

Useful options:

- `--date YYYY-MM-DD|today|yesterday`: target issue date.
- `--issue-id ISSUE`: override automatic active issue selection.
- `--budget-profile default|lean|aggressive`: defaults to `default`.
- `--dispatch-telegram/--no-dispatch-telegram`: send the PDF to configured chat IDs.
- `--dry-run/--no-dry-run`: preserve existing Telegram safety pattern.
- `--format text|json`: machine-readable output for automations.

## Outputs

For each run, write artifacts under `.nutmeg-data/zucai/daily/<run-date>/renjiu/`:

- `analysis.md`: complete human-readable analysis.
- `analysis.json`: structured issue, odds, diagnostics, tickets, and recommendation.
- `analysis.pdf`: PDF report for Telegram and mobile review.
- `context.json`: frozen inputs used to reproduce the decision.

The PDF and Markdown include:

1. Issue ID, sale stop, odds snapshot time, and source list.
2. Three Renjiu tickets:
   - conservative: roughly 64-100 yuan.
   - recommended/main: roughly 100-200 yuan.
   - aggressive: roughly 200-400 yuan.
3. The single recommended ticket and why.
4. Fourteen-match table with picks, risk labels, odds, and reasoning.
5. The five least confident matches.
6. Market-hotspot vs fact-conflict corrections.
7. Review checklist for next-day grading.

## Data Flow

1. Resolve issue:
   - Prefer active entry in `.nutmeg-data/zucai/issues.json` for the target date.
   - If no active issue exists, parse the latest official schedule source when available.
   - If exactly 14 matches cannot be resolved, fail loudly.

2. Resolve odds:
   - Prefer issue-specific odds snapshot from registry.
   - If missing and JCZQ context exists for the same date, map issue matches to JCZQ HAD odds by team/date.
   - If a match cannot be mapped or a HAD row is missing, mark a fatal data gap unless the user explicitly supplies odds.

3. Compute diagnostics:
   - Market structure: strong favorite, comfort favorite, balanced/coinflip, draw-friendly, hot direction.
   - Poisson signal where JCZQ candidates exist: low-goals, 0:0, 1-goal, and any strong disagreement.
   - Concentration risk: avoid overloading one match if it appears in other same-day JCZQ plans or obvious public-hot positions.
   - Fact context: team news, injuries, schedule pressure, title/relegation/European motivation, derby/cup dynamics. Fact context must cite or name the source in the report.

4. Find conflicts:
   - Flag low-priced favorites whose facts do not justify single-banker use.
   - Flag public-hot away favorites in near-coinflip markets.
   - Flag matches with model low-goals evidence that make draw protection more attractive.
   - If facts and market agree, keep the model pick rather than forcing a contrarian call.

5. Rank uncertainty:
   - Score each match by three-way odds closeness, coinflip/draw-friendly flags, low-goals draw pressure, shallow favorite price, and fact/market disagreement.
   - Select the five least confident matches.
   - Tickets should usually exclude the hardest uncertainty, unless a tier intentionally buys coverage there.

6. Generate tickets:
   - Conservative: minimize coverage count, choose the cleanest nine matches, target 64-100 yuan.
   - Main/recommended: balance risk and payout, target 100-200 yuan.
   - Aggressive: include more contrarian or conflict-correction positions, target 200-400 yuan.
   - All tickets must state omitted matches,注数,金额, and key failure modes.

7. Render and dispatch:
   - Render Markdown, JSON, and PDF.
   - If Telegram dispatch is requested and not dry-run, send the PDF with a concise caption.

## Natural-Language Integration

Add recognition in the bot adapter / command parser for Renjiu trigger phrases. The natural-language path should call the same service as the CLI to avoid duplicate logic.

Expected response shape in chat:

- Short confirmation that the workflow ran.
- Recommended ticket line.
- Artifact paths.
- Telegram dispatch status.

## Error Handling

Fail loud and do not guess when:

- No 14-match issue can be found.
- Fewer or more than 14 matches are parsed.
- Odds are missing for any included issue match.
- Team mapping from issue to JCZQ is ambiguous.
- Telegram is requested but bot token or chat IDs are missing.

Non-fatal warnings:

- Fact sources unavailable; report should proceed with `fact_context_status=unavailable` and avoid fact-driven corrections.
- Some Poisson signals unavailable; report should proceed using market and odds diagnostics only.

## Testing Strategy

- Unit tests for budget-bounded ticket generation.
- Unit tests for least-confident-five ranking.
- Unit tests for market/fact conflict correction rules.
- CLI tests for `zucai-renjiu-daily --format json` with fixture data.
- Bot parser tests for Chinese and English natural-language triggers.
- PDF smoke test: file starts with `%PDF` and includes the three ticket labels via text extraction when possible.
- Telegram dispatch dry-run test reusing existing sender seam.

## Non-Goals

- No automatic purchase or betting execution.
- No guaranteed-hit language.
- No full web cockpit UI in this slice.
- No automatic override of user-supplied final plans without explicit confirmation.

## Open Decisions Closed By User

- The workflow should produce three budget tiers rather than one final ticket or a full 14-match-only package.
- The workflow must be triggerable through natural language, not only by a CLI command.
