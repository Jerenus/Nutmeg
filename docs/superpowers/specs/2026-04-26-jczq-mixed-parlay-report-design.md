# JCTZQ Mixed Parlay Report v0 Design

Date: 2026-04-26

## Goal

Turn the ad hoc official-odds竞彩足球 4-leg high-odds mixed-parlay report into a reusable Nutmeg workflow that can be run from CLI and OpenClaw/Nutmeg bot.

## Scope

- Fetch current sellable竞彩足球 matches from the official Sporttery calculator API.
- Build two high-odds 4-leg mixed-parlay combinations from available pools: `had`, `hhad`, `ttg`, `hafu`, and `crs`.
- Render JSON, Markdown, and optional PDF artifacts with source URL, official update time, odds update time, estimated total odds, and responsible-use disclaimers.
- Optionally dispatch the generated PDF through the existing Telegram document sender when explicitly requested.
- Add an OpenClaw safe-router action so the bot can invoke the CLI without arbitrary shell execution.

## Non-Goals

- No bet placement, sportsbook connection, payment flow, guaranteed-profit claim, or auto-publishing.
- No hidden scraping. The default live provider calls the documented Sporttery web API used by the official calculator page. Tests use local fixtures/fakes.
- No full optimizer in v0. Selection uses deterministic high-odds profiles that are explainable and bounded.

## Architecture

Add a separate `jczq` domain/service instead of extending `zucai`. Traditional足彩 issue reports and竞彩足球 mixed-parlay reports have different inputs, markets, and artifact semantics. The new service owns Sporttery calculator parsing, deterministic profile selection, artifact rendering, and optional Telegram dispatch.

```text
nutmeg/domain/jczq.py          # report dataclasses and JSON contracts
nutmeg/services/jczq.py        # provider, selector, artifact/PDF rendering, dispatch
nutmeg/interfaces/cli.py       # jczq-mixed-report command and builder
scripts/openclaw/...router.py  # safe router action jczq-mixed-report
```

## Data Flow

1. CLI calls `JczqMixedReportService.build_report()`.
2. Provider returns a normalized calculator payload. Live provider uses `httpx`; tests can inject a fake provider.
3. Service flattens sellable matches by `matchNumStr`, validates requested pools are selling, and applies deterministic 4-leg profiles.
4. Artifacts are written under `.nutmeg-data/jczq` when an output directory is supplied.
5. If `--dispatch-telegram` is set, the service sends the PDF only when a sender, chat allowlist, and rendered PDF exist. CLI keeps dispatch dry-run by default.

## Selection v0

v0 starts with two deterministic profiles because the user asked specifically for “两组4关高赔”. Profiles target high but not absurd odds:

- Combo A: strong-away-team path plus one major-match draw scoreline.
- Combo B: high-goal rhythm plus one draw/half-full-time leg.

Each leg includes explanation text. If a profile leg is unavailable or no longer selling, the command fails truthfully rather than substituting an unreviewed pick.

## Error Handling

- Provider HTTP failures become `JczqProviderError` with a concise CLI error.
- Missing matches, closed pools, or absent odds become `JczqSelectionError`.
- Artifact writing keeps JSON/Markdown as the source of truth; PDF failure is surfaced as a warning if encountered after report construction.
- Telegram dispatch has `skipped`, `dry_run`, `sent`, and `failed` statuses.

## Testing

- Domain/service tests use a local fake Sporttery payload and verify two 4-leg combos, odds products, source metadata, artifact paths, and PDF magic bytes.
- CLI tests monkeypatch the service builder or use a local fake provider to avoid network.
- Router tests verify the safe command envelope and `--dispatch-telegram` confirmation gate.
- Verification runs focused tests, ruff, compileall, and full `scripts/verify.sh` when practical.
