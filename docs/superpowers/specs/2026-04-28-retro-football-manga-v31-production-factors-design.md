# Retro Football Manga v3.1 Production Factors Design

## Goal

Upgrade Nutmeg's daily football animation workflow from a loose retro manga style into a repeatable short-video series system. The production process must carry platform, continuity, quality, and compliance factors into every generated review pack and Seedance manifest.

## Approved Direction

Use an original 1980s retro youth-football manga animation base, then add short-video column packaging:

- polished hand-inked line art, cel shading, old manga paper grain, speed lines, concentration lines, sweat close-ups;
- fixed series modules: opening hook card, manga cover/tunnel standoff, weapon card, counterweapon card, tactical notebook, simulated replay, retro scoreboard, closing suspense card;
- vertical-first composition with large faces, large ball, readable Chinese title cards, and clear first-two-second hook;
- daily match teams are fictionalized from broad city/color/tactical identity only; no real crests, sponsors, official kits, player likenesses, named IP, or gambling visuals;
- public scripts remain sports-analysis content and keep the responsible-viewing disclaimer.

## Production Factors

The pipeline should expose these factors in generated artifacts so every day's prompts inherit them:

1. Platform retention: first 2 seconds must have a strong visual/text hook.
2. Vertical readability: 9:16 scenes prioritize large faces, ball, scoreboard, and 1-3 readable keywords.
3. Series packaging: fixed opening, tactical notebook, simulated replay, retro scoreboard, and closing suspense card recur across matches.
4. Character continuity: fictional team colors, player numbers, hairstyles, and roles must stay stable across a match episode.
5. Retro manga craft: refined black linework, cel-shaded color, paper grain, speed-line grammar, and no rough sketch look.
6. Distribution split: Douyin video emphasizes hook/retention; Xiaohongshu packaging adds cover/title and image-card-friendly tactical notes.
7. Compliance: no real IP/club marks/player likenesses; no betting action language; no result displayed as certainty.

## Artifact Changes

Create a new canonical style asset directory:

`docs/style-assets/retro-football-manga-v3.1/`

Files:

- `README.md`: workflow and relationship to v3.
- `style-bible.md`: updated visual/continuity rules.
- `episode-template.md`: 6x10s focus and 4x15s standard structures with short-video hook modules.
- `prompt-template.md`: prompt assembly, positive prompt, negative prompt, and platform factors.
- `series-packaging.md`: fixed recurring modules and UI language.
- `shot-library.md`: repeatable camera/animation shot bank.
- `platform-output.md`: Douyin and Xiaohongshu outputs.
- `quality-checklist.md`: approval gates before spending more Seedance tokens.
- `team-injection-schema.json`: match-specific fictional team injection contract.

## Code Changes

Update `nutmeg/services/daily_content.py` so review packs and manifests default to `retro-football-manga-v3.1` and include the production factors:

- `STYLE_PROFILE_ID` becomes `retro-football-manga-v3.1`.
- Storyboard beats become the v3.1 episode modules.
- Seedance prompts prepend the v3.1 style, continuity, and platform factors.
- Manifest includes `production_factors`, `quality_gates`, and `platform_outputs` for downstream automation.
- Per-match artifact folders include `production-factors.json` so human review can verify what influenced the generation.

## Verification

- Add tests that fail if the daily content run is not v3.1, if manifest production factors are absent, or if prompts do not include the v3.1 quality/continuity constraints.
- Run focused daily-content tests, ruff, and compileall.
- Do not submit any Seedance tasks in this change.
