# Nutmeg v0.3 Design Gap Audit

Date: 2026-04-25  
Updated: 2026-04-26

This audit compares `Nutmeg-DESIGN-v0.3.md` against the current Spec Kit slices,
code graph, feature registry, and CLI surfaces. The conclusion is that Nutmeg is
well aligned with the Phase 1 foundation and early Sprint 1/2 usable-agent path,
but it is not yet complete against the full v0.3 product roadmap.

## Alignment Summary

| v0.3 area | Current implementation | Consistency |
|---|---|---|
| CLI-first private tool | Typer CLI, shared services, local DuckDB/SQLite, no-network demo paths | High |
| IM bot first, Web later | Telegram transport, polling daemon, offset persistence, dry-run adapter | High |
| Sprint 0 fixtures + storage + tracing | API-Football fixtures sync, DuckDB fixture cache, SQLite sync metadata, LangSmith tracing seam | High |
| Sprint 1 data snapshot | soccerdata, Transfermarkt, API-Football context, weather/geocode cache, player identity aliases | High |
| Odds snapshot and fair probability | API-Football and The Odds API provider paths, no-vig fair probabilities, odds history, provider health | High |
| Assertive four-part judgment | Deterministic analysis service and match brief workflow produce judgment, reasons, counterargument, confidence | Medium-high |
| Multi-agent architecture | Router and workflow seam exist; expert agents are not yet first-class independent tools | Medium |
| Sprint 2 tactical visuals/models | Tactical synthesis plus local SVG shot-map, lineup-network, and xG-trend proxy artifacts exist; true event models remain future work | Medium-high |
| Sprint 3 model-vs-market value board | Deterministic Dixon-Coles-lite value board and Kelly sizing exist | Medium-high |
| Sprint 4 player module | Local-first player profile, market facts, availability, and similar-player surface exist | Medium-high |
| Sprint 6 eval/review/scheduler | Local eval dataset, Brier review, prediction storage, and daily operator command exist | Medium-high |

## Core Product Gaps

### Closed P0 - Model-Based Value Board

`Nutmeg-DESIGN-v0.3.md` Sprint 3 calls for Dixon-Coles/Poisson model probability,
model-vs-market comparison, value board, and Kelly sizing. This is now covered
by `.specify/specs/031-value-board-v0/`.

### Closed P1 - Player Profile v0

The design requires player profile aggregation, season metrics, injury state,
market value history, similar players, and radar/pizza visuals. The local-first
profile and similarity surface is now covered by
`.specify/specs/032-player-profile-v0/`; radar/pizza visuals remain part of the
future event/visualization provider track.

### Closed P1 - Eval and Review Loop

The design requires LangSmith eval datasets and weekly real-pick review with
Brier Score. The local starter dataset, prediction recording, outcome updates,
and review CLI are now covered by `.specify/specs/033-eval-and-review-loop/`.

### Closed P1 - Daily Operator Schedule

The design requires daily incremental pulls and weekly fixture push. The bot can
run, and `daily-run` now chains sync, ranking, value board, optional briefs, and
dry-run-gated Telegram dispatch.

Implemented spec: `.specify/specs/034-daily-operator-schedule/`

### Closed P2 - Tactical Visualization v0 / Closed v0 - Event Models

The tactical module explains lineup/trend/market context in text and emits local
SVG visual artifacts via `.specify/specs/035-tactical-visuals-v0/`.
The event-data modeling seam is now covered for v0 by
`.specify/specs/038-event-data-tactical-models-v0/`: local StatsBomb-like JSON
loading, normalized event records, pass networks, xT-lite, VAEP-lite, and
deterministic SVG artifacts.

Future specs can still add live/open-data downloads, mplsoccer rendering, and
trained xT/VAEP calibration once the event abstraction has enough usage.

### Closed P1 - Latest Information Provider v0

The AI-native client requirement for latest data and资讯 now has a local-first
provider seam via `.specify/specs/039-news-information-provider-v0/`.

Implemented scope:

- deterministic JSON and RSS/Atom-style local source parsing;
- normalized source-attributed fixture updates with reliability labels;
- deduplication, fixture/team filtering, source-health warnings, and unavailable
  failure states;
- `nutmeg fixture-information` text/JSON CLI output;
- Web/PWA match workspace rendering of item titles, source names, reliability
  labels, and rumor/unverified warnings.

The live/cache extension is now covered by
`.specify/specs/040-live-information-provider-v0/`: explicit source manifests,
opt-in HTTP/RSS/JSON fetch, local cache, fresh-cache reads, stale-cache fallback,
and client/CLI manifest controls.

Future specs can still add authenticated paid APIs, scheduled refresh, stronger
rate-limit ledgers, and persistent source-health analytics without changing the
digest contract.

## Completion Priority

Application completeness should prioritize end-to-end operator value over broad
but shallow parity with every research item. The highest leverage path is:

1. Keep `daily-run`, `popular-matches`, `value-board`, `match-brief`, and
   `tactical-visuals` as the practical operator loop.
2. Improve calibration with larger historical datasets and real outcome review.
3. Add event-data provider support only when true StatsBomb/mplsoccer/xT/VAEP
   functionality becomes worth the extra data and dependency cost.
4. Add authenticated/scheduled information providers only after the manifest/cache path has been calibrated against daily operator usage.
