# Retro Football Manga v3 Global Asset Pack

This directory defines the global visual and story system for Nutmeg football animation videos.

It is intentionally not tied to a single match. A daily match should add a match-specific team injection file and then generate Seedance prompts from the global templates.

## Files

- `style-bible.md` — global art direction, continuity rules, and forbidden visual directions.
- `episode-template.md` — standard 60-second and 4-scene episode structures.
- `prompt-template.md` — reusable prompt assembly structure and negative prompt.
- `team-injection-schema.json` — schema for adding daily match-specific fictional teams and characters.
- `quality-checklist.md` — approval checklist before spending more video-generation tokens.

## Recommended Workflow

1. Read the match analysis.
2. Convert real teams into fictional teams using `team-injection-schema.json`.
3. Create 2-4 recurring character anchors for the match.
4. Fill the six-scene `episode-template.md` with tactical variables.
5. Assemble prompts using `prompt-template.md`.
6. Generate only Segment 01 as a style test.
7. Run `quality-checklist.md` before generating the rest.

## Runtime Copy

A runtime copy may be written to `.nutmeg-data/style-assets/retro-football-manga-v3/` for local pipeline use. The canonical source is this `docs/style-assets/retro-football-manga-v3/` directory.
