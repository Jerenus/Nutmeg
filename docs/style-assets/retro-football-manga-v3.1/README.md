# Retro Football Manga v3.1 Global Asset Pack

Retro Football Manga v3.1 is Nutmeg's default short-video animation system for daily football match analysis.

It upgrades v3 from a pure art-direction pack into a production-factor pack. Every daily match should inherit the same style, recurring modules, platform rules, quality gates, and compliance boundaries before match-specific team elements are injected.

## Core Positioning

Original 1980s retro youth-football manga animation, refined for Douyin and Xiaohongshu short-video distribution:

- polished hand-inked line art;
- cel-shaded animation color;
- aged manga paper grain;
- speed lines, concentration lines, sweat close-ups, dramatic eyes;
- fixed opening hook, tactical notebook, simulated replay, retro scoreboard, and closing suspense card;
- fictionalized teams and characters, never real crests, real player likenesses, official sponsors, or named IP imitation.

## Files

- `style-bible.md` — visual system, continuity rules, and forbidden directions.
- `episode-template.md` — 6x10s focus episode and 4x15s standard episode structures.
- `prompt-template.md` — prompt assembly order, master prompt, negative prompt, and platform factors.
- `series-packaging.md` — fixed recurring modules that make the daily output feel like one series.
- `shot-library.md` — reusable shots and transition grammar.
- `platform-output.md` — Douyin and Xiaohongshu packaging outputs.
- `quality-checklist.md` — approval gates before spending more Seedance tokens.
- `team-injection-schema.json` — match-specific fictional team and character injection contract.

## Daily Workflow

1. Generate or review match analysis.
2. Convert real teams into fictional teams using `team-injection-schema.json`.
3. Select the focus or standard episode template.
4. Assemble prompts with the v3.1 production factors.
5. Generate only Segment 01 as a style test.
6. Approve against `quality-checklist.md` before generating remaining segments.
7. Output Douyin vertical video plus Xiaohongshu cover/card materials.

## Runtime Copy

Canonical source lives in `docs/style-assets/retro-football-manga-v3.1/`.

The pipeline may copy it to `.nutmeg-data/style-assets/retro-football-manga-v3.1/` for runtime use.
