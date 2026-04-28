# JCZQ Mixed Parlay Report

`jczq-mixed-report` turns the user's ad hoc竞彩足球高赔串关 request into a reusable Nutmeg workflow. It reads the official Sporttery calculator-style odds payload, validates that selected matches and pools are still selling, then renders two 4-leg high-odds mixed-parlay combinations.

## Usage

```bash
uv run nutmeg jczq-mixed-report --provider live --pdf --format json
uv run nutmeg jczq-mixed-report --provider sample --output-dir .nutmeg-data/jczq-smoke --pdf --format json
python3 scripts/openclaw/nutmeg_command_router.py jczq-mixed-report --provider live --pdf
```

Real Telegram dispatch uses the same safety posture as other Nutmeg delivery commands: the CLI defaults to dry-run, while the OpenClaw router requires `--confirm-dispatch` before it can build a real dispatch command.

## Boundaries

- This is betting-analysis assistance only. It does not place bets, connect sportsbooks, or guarantee returns.
- Reports include source URL, official update time, odds update time, total odds, and responsible-use warnings.
- Tests and sample mode do not make network calls; live mode explicitly calls the official Sporttery calculator API.

## Downstream Daily Content

The daily match video workflow consumes the same Sporttery calculator-style payload but changes the output goal: instead of producing two mixed-parlay combinations, `daily-content-pack` creates one reviewable content package per sellable match. The public-facing side is stricter than the internal JCZQ report: odds and handicap information may remain in internal analysis, but short-video scripts avoid betting actions, certainty language, and paid/private-group lead-ins.

Seedance prompts are generated as dry-run manifest entries first. External video generation is handled only by `seedance-submit --confirm`, with task IDs and later status updates written back to `seedance-manifest.json` and `seedance-status.json`. Submission defaults to vertical tasks so horizontal backup prompts do not create accidental extra paid jobs.
