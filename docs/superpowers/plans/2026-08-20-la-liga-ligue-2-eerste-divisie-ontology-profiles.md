# 2026-27 La Liga, Ligue 2, And Eerste Divisie Ontology Profiles Plan

**Goal:** Extend Nutmeg's native decision ontology with comparable, evidence-backed profiles for the three leagues and every official 2026-27 participant, prioritising the six clubs on the 2026-08-21 board.

**Architecture:** Keep `decision_entities_seed.json` as the curated source and reuse `League` / `Team.profile_notes`; do not add schema, scoring code, or a second truth source. ESPN's current-season competition feeds establish the participant boundary and current registered squad, completed 2025-26 scoreboards establish deterministic team/league baselines, and official club/league reporting or locatable season records establish coaching and structural changes. Stable facts enter entity profiles; match-specific availability, rumours, sentiment, and late market movement remain Read/watchlist inputs.

**Operational constraint:** The live `.nutmeg-data/jczq` store is required for sync and profile reads, so work remains in the project root. Both seed and alias files already contain user-owned edits; changes must be additive and their complete diffs inspected. Runtime JSONL files are only updated through `decision-entities-sync`.

## Official Boundary

- `esp-laliga` (20): Alaves, Athletic Club, Atletico Madrid, Barcelona, Celta Vigo, Deportivo La Coruna, Elche, Espanyol, Getafe, Levante, Malaga, Osasuna, Racing Santander, Rayo Vallecano, Real Betis, Real Madrid, Real Sociedad, Sevilla, Valencia, Villarreal.
- `fra-ligue2` (18): Annecy, Boulogne, Clermont, Dijon, Dunkerque, Grenoble, Guingamp, Laval, Metz, Montpellier, Nancy, Nantes, Pau, Red Star, Reims, Rodez, Saint-Etienne, Sochaux.
- `ned-eerste-divisie` (20): Almere City, De Graafschap, FC Den Bosch, FC Dordrecht, FC Eindhoven, FC Emmen, Helmond Sport, Heracles Almelo, Jong Ajax, Jong AZ, Jong PSV, Jong Utrecht, MVV Maastricht, NAC Breda, Roda JC, RKC Waalwijk, TOP Oss, Vitesse, VVV-Venlo, FC Volendam.

Boundary evidence is the 2026-season ESPN standings feed for `esp.1`, `fra.2`, and `ned.2`, cross-checked against each competition's 2026-27 season page. The boundary must be rechecked before sync; relegated/promoted clubs may retain historical entities but must not retain the wrong `competition_ids` membership.

## Comparable Profile Contract

Every league receives the following six current keys, while older evidence notes are retained:

1. `season_format_2026_27`
2. `result_baseline_2025_26`
3. `goal_regime_2025_26`
4. `home_away_regime_2025_26`
5. `roster_boundary_2026_27`
6. `early_season_watch_2026_27`

Every official team receives one current note for each fixed dimension, while older notes remain available as history:

1. `strength_baseline_2026_27`
2. `coach_system_2026_27`
3. `squad_spine_2026_27`
4. `attack_profile_2026_27`
5. `defence_profile_2026_27`
6. `home_away_profile_2025_26`
7. `summer_window_2026`
8. `availability_2026_08_20`
9. `cohesion_2026_08_20`
10. `watchlist_2026_08_20`

Every note must have non-empty `evidence` and `at`. No unknown is converted into a claim: absent or incomplete injury/transfer coverage is recorded as a verification boundary and a watchlist trigger, not as "fully fit" or "no transfer".

## Execution Phases

### Phase 1 - Baseline And Identity Gate

- Validate both JSON documents and record their existing diff boundary.
- Prove the required league/team/key coverage is initially incomplete.
- Add or merge the exact 58 Team identities and their competition membership.
- Verify every canonical Chinese name through the real resolver.

### Phase 2 - Priority Fixture Cohort

Populate and inspect first:

- Real Betis and Real Sociedad.
- Dunkerque and Montpellier.
- FC Den Bosch and FC Eindhoven.

For these six, explicitly review the current squad delta, coach status, first-round evidence, and availability uncertainty before the other teams. This is research preparation only; do not create match Reads or a betting decision in this task.

### Phase 3 - Full League Cohorts

- Complete all 20 La Liga teams.
- Complete all 18 Ligue 2 teams.
- Complete all 20 Eerste Divisie teams.
- Treat promoted/relegated teams' prior-season figures at their actual division level.
- Treat Jong Ajax/AZ/PSV/Utrecht as development squads whose parent-club movement makes normal transfer-window stability assumptions invalid.

### Phase 4 - Alias Repair

Add only aliases observed on a real board and verified against ESPN/API-Football official names. The immediate known candidates are `敦刻尔克 -> Dunkerque`, `登博思 -> FC Den Bosch`, and `埃因FC -> FC Eindhoven`. Do not add them until the provider-side names are confirmed.

### Phase 5 - Sync And Acceptance

Run:

```bash
jq empty nutmeg/data/decision_entities_seed.json
jq empty nutmeg/data/jczq_club_team_aliases.json
uv run pytest tests/decision/test_entities.py tests/decision/test_alias_audit.py -q
uv run nutmeg decision-entities-sync
uv run nutmeg decision-entities-sync
uv run nutmeg decision-alias-audit --run-date 2026-08-21
uv run nutmeg decision-profile --run-date 2026-08-21
```

Acceptance requires:

- exact membership counts of 20/18/20;
- all ten required keys on every official Team and all six required keys on every League;
- non-empty evidence/date fields and no duplicate required keys;
- all six priority teams resolved and readable from the live store;
- the second entity sync reports `新增 0 / 更新 0`;
- the three verified board aliases no longer cause international-anchor degradation;
- promoted/relegated and youth-team sample boundaries are explicit;
- a dated research report records sources, limitations, priority-fixture findings, transfer/availability watchlists, and the next refresh triggers.
