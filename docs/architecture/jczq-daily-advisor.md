# JCZQ Daily Advisor

`jczq-daily-advisor` is the repeatable daily竞彩足球 mixed-parlay analysis workflow. It does not use fixed match numbers. Each run fetches the current Sporttery calculator-style payload, scans all sellable matches and pools, then generates an explainable Chinese report for the operator.

## Commands

```bash
uv run nutmeg jczq-daily-advisor --provider live --date today --format json
uv run nutmeg jczq-daily-advisor --provider sample --date 2026-04-26 --output-dir .nutmeg-data/jczq-smoke --format json
uv run nutmeg jczq-daily-advisor --provider live --date today --dispatch-telegram --no-dry-run --format json
uv run nutmeg jczq-daily-advisor --provider live --date today --revision-text "不要比分，提高到100倍" --format json
```

OpenClaw safe router:

```bash
python3 scripts/openclaw/nutmeg_command_router.py jczq-daily-advisor --provider live --date today
python3 scripts/openclaw/nutmeg_command_router.py jczq-daily-advisor --provider live --date today --dispatch-telegram --confirm-dispatch
```

## Daily Analysis Path

The workflow follows the same method every day while adapting to the actual slate:

1. Load sellable竞彩足球 matches and odds for HAD, HHAD, TTG, CRS, and HAFU.
2. Identify the public-friendly direction in each match from low fixed odds and team/league context.
3. Classify each match as a strong-favorite, open-tempo, cautious-game, or balanced-disagreement spot.
4. Build candidate legs from all available mixed-pools, not only win/draw/win.
5. Separate stable legs from leverage legs: low-odds HAD legs can support the report, while HHAD/TTG/HAFU/CRS carry multiplier risk.
6. Generate four plan types: final main plan, high-odds inspiration plan, contrarian public-heat avoidance plan, and extreme small-stake plan.
7. Multiply leg odds to show estimated total odds and 2-yuan theoretical return.
8. Save the context so Telegram follow-up questions can revise the same day’s plan.

## Bot Usage

When Nutmeg owns the Telegram polling runner, the BotAdapter supports:

```text
/jczq
/jczq final
/jczq revise 规避大众盘口
/jczq revise 不要比分，提高到100倍
```

Natural-language竞彩 follow-ups also route to the same safe workflow, for example:

```text
今天竞彩不要比分，提高到100倍，规避大众盘口
把今天竞彩足球最终方案发我
```

The bot replies with the rendered report text. Revisions are persisted under `.nutmeg-data/jczq/daily/<date>/context.json` and increment the revision version.

## Scheduling

The daily noon LaunchAgent has been retired. Generate JCZQ reports manually or
install a new schedule only after its rules, Telegram destination, and review
workflow are redefined.

The workflow sends analysis text only; it never places bets or connects to
sportsbook accounts.

## Safety Boundary

The report is analysis assistance only. It must not claim certainty, guaranteed profit, arbitrage, or bet execution. High-odds inspiration plans are explicitly high variance and suitable only for small-stake entertainment.
