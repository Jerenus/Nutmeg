# 2026-27 Premier League Ontology Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate Nutmeg's native decision ontology with one evidence-backed 2026-27 Premier League profile and 20 complete, dimensionally comparable club profiles.

**Architecture:** Keep `decision_entities_seed.json` as the curated source of truth and use the existing `League` / `Team.profile_notes` contracts without schema or decision-code changes. Establish the official club boundary from Premier League season `841`, collect stable and time-sensitive facts under fixed keys, then sync into the decision store and verify aliases, coverage, idempotency, and CLI readability.

**Tech Stack:** JSON entity seed, Premier League public football API, official club/league sources, `jq`, existing `uv run nutmeg decision-*` CLI, pytest.

**Design Spec:** `docs/superpowers/specs/2026-08-20-premier-league-ontology-profiles-design.md`

---

## Scope And Worktree Constraint

This is an operational data task, not a software feature. It runs in the main project root because the final
`decision-entities-sync` must update the live `.nutmeg-data/jczq` store. A separate git worktree would not
contain that ignored runtime store.

The starting worktree already has user-owned edits in both files this task must extend:

- `nutmeg/data/decision_entities_seed.json`
- `nutmeg/data/jczq_club_team_aliases.json`

Never reset, replace, reformat, or stage those files wholesale. Apply append-only/surgical changes, inspect
their complete diff after every cohort, and leave the overlapping implementation files uncommitted unless the
user explicitly asks to combine the pre-existing edits. The design and this plan may be committed separately.

## File Structure

- Modify: `nutmeg/data/decision_entities_seed.json` — authoritative League/Team objects and profile notes.
- Modify: `nutmeg/data/jczq_club_team_aliases.json` — only missing Chinese aliases for the promoted clubs and
  any official-name variants required by the 20-club boundary.
- Read: `nutmeg/decision/entities.py` — existing note merge, alias resolution, sync, and profile behavior.
- Test: `tests/decision/test_entities.py` — existing entity seed/sync/profile contract.
- Test: `tests/decision/test_alias_audit.py` — existing strict alias audit behavior.
- Runtime update: `.nutmeg-data/jczq/decision/leagues.jsonl` and `teams.jsonl` via
  `decision-entities-sync`; never edit these JSONL files directly.

## Fixed Official Boundary

Premier League API season `841` reports exactly these 20 clubs for 2026-27:

| team_id | name_zh | name_en | short aliases |
|---|---|---|---|
| `eng-arsenal` | 阿森纳 | Arsenal | 阿森纳 |
| `eng-aston-villa` | 阿斯顿维拉 | Aston Villa | 维拉 |
| `eng-bournemouth` | 伯恩茅斯 | Bournemouth | 伯恩茅斯 |
| `eng-brentford` | 布伦特福德 | Brentford | 布伦特 |
| `eng-brighton` | 布莱顿 | Brighton & Hove Albion | 布赖顿, Brighton |
| `eng-chelsea` | 切尔西 | Chelsea | 切尔西 |
| `eng-coventry-city` | 考文垂 | Coventry City | 考文垂, Coventry |
| `eng-crystal-palace` | 水晶宫 | Crystal Palace | 水晶宫 |
| `eng-everton` | 埃弗顿 | Everton | 埃弗顿 |
| `eng-fulham` | 富勒姆 | Fulham | 富勒姆 |
| `eng-hull-city` | 赫尔城 | Hull City | 赫尔, Hull |
| `eng-ipswich-town` | 伊普斯维奇 | Ipswich Town | 伊普斯, Ipswich |
| `eng-leeds-united` | 利兹联 | Leeds United | 利兹, Leeds |
| `eng-liverpool` | 利物浦 | Liverpool | 利物浦 |
| `eng-manchester-city` | 曼彻斯特城 | Manchester City | 曼城, Man City |
| `eng-manchester-united` | 曼彻斯特联 | Manchester United | 曼联, Man Utd |
| `eng-newcastle-united` | 纽卡斯尔联 | Newcastle United | 纽卡斯尔, Newcastle |
| `eng-nottingham-forest` | 诺丁汉森林 | Nottingham Forest | 诺丁汉, Nott'm Forest |
| `eng-sunderland` | 桑德兰 | Sunderland | 桑德兰 |
| `eng-tottenham-hotspur` | 托特纳姆热刺 | Tottenham Hotspur | 热刺, Spurs |

Do not include 2025-26 relegated West Ham United, Burnley, or Wolverhampton Wanderers in `eng-premier`.

## Fixed Team Note Template

Each Team must contain exactly one current note for each key below. Replace bracketed descriptions with
verified prose during research; the key and date contracts are literal.

```json
[
  {"key":"strength_baseline_2026_27","note":"上季名次/积分/净胜球或升级路径，以及只由这些事实支持的实力位置","evidence":"可定位来源","at":"2026-08-20"},
  {"key":"coach_system_2026_27","note":"主帅、任期和主要体系；事实与战术推断分开","evidence":"可定位来源","at":"2026-08-20"},
  {"key":"squad_spine_2026_27","note":"门将-中卫-后腰-组织核-终结点的当前中轴","evidence":"可定位来源","at":"2026-08-20"},
  {"key":"attack_profile_2026_27","note":"推进、创造、终结与定位球攻击机制","evidence":"可定位来源","at":"2026-08-20"},
  {"key":"defence_profile_2026_27","note":"压迫、防线高度、转换与定位球防守机制","evidence":"可定位来源","at":"2026-08-20"},
  {"key":"home_away_profile_2025_26","note":"上季主客成绩及差异；升班马明确英冠层级","evidence":"可复算完整样本","at":"2026-08-20"},
  {"key":"summer_window_2026","note":"确认的关键引援/离队与仍未落定的结构风险","evidence":"官方或可靠交叉来源","at":"2026-08-20"},
  {"key":"availability_2026_08_20","note":"长期伤停、停赛、复出和资格状态","evidence":"官方或可靠交叉来源","at":"2026-08-20"},
  {"key":"cohesion_2026_08_20","note":"首发连续性、中轴换血和新体系磨合阶段","evidence":"事实链与来源","at":"2026-08-20"},
  {"key":"watchlist_2026_08_20","note":"会推翻当前画像的转会/复出/前三轮触发器","evidence":"触发器所依据的当前事实来源","at":"2026-08-20"}
]
```

---

### Task 1: Freeze The Baseline And Prove Coverage Is Red

**Files:**
- Read: `nutmeg/data/decision_entities_seed.json`
- Read: `nutmeg/data/jczq_club_team_aliases.json`

- [ ] **Step 1: Record the dirty-state boundary**

Run:

```bash
git status --short
git diff --numstat -- nutmeg/data/decision_entities_seed.json nutmeg/data/jczq_club_team_aliases.json
git diff --check -- nutmeg/data/decision_entities_seed.json nutmeg/data/jczq_club_team_aliases.json
```

Expected: both target files are already modified, and `diff --check` reports no whitespace errors. Treat every
existing hunk as user-owned.

- [ ] **Step 2: Validate the starting JSON documents**

Run:

```bash
jq empty nutmeg/data/decision_entities_seed.json
jq empty nutmeg/data/jczq_club_team_aliases.json
```

Expected: both commands exit 0.

- [ ] **Step 3: Run the completeness assertion and verify RED**

Run:

```bash
jq -e '
  [.teams[] | select((.competition_ids // []) | index("eng-premier"))] as $teams
  | ($teams | length) == 20
  and all($teams[]; (.profile_notes | length) == 10)
  and ((.leagues[] | select(.league_id == "eng-premier") | .profile_notes | length) == 6)
' nutmeg/data/decision_entities_seed.json
```

Expected: exit 1 because the league has zero notes and no Team is attached to `eng-premier`.

---

### Task 2: Establish Official Identities And Alias Coverage

**Files:**
- Modify: `nutmeg/data/decision_entities_seed.json`
- Modify: `nutmeg/data/jczq_club_team_aliases.json`

- [ ] **Step 1: Re-fetch the official season boundary**

Run:

```bash
curl -L --max-time 30 -s \
  -H 'Origin: https://www.premierleague.com' -H 'User-Agent: Mozilla/5.0' \
  'https://footballapi.pulselive.com/football/teams?page=0&pageSize=100&comp=1&compSeasons=841&altIds=true' \
  | jq -r '.pageInfo.numEntries, (.content[] | [.name,.shortName,.club.abbr,.altIds.opta] | @tsv)'
```

Expected: first line `20`, followed by the exact 20 clubs in the fixed boundary table.

- [ ] **Step 2: Add the 20 Team objects with empty note arrays**

Use `apply_patch` to append the fixed-boundary Team objects to the existing `teams` array. Every object uses
`"competition_ids": ["eng-premier"]` and the exact IDs/names/aliases from the table. Do not modify existing
non-Premier-League entities.

- [ ] **Step 3: Add missing promoted-club aliases**

Use `apply_patch` to add only these mappings when absent:

```json
"考文垂": "Coventry City",
"赫尔城": "Hull City",
"赫尔": "Hull City",
"伊普斯维奇": "Ipswich Town",
"伊普斯": "Ipswich Town"
```

Also add `"布赖顿": "Brighton"` only if the体彩 spelling is used by a stored/raw board. Do not add nickname
aliases such as 枪手 or 蓝军; they are not schedule identities.

- [ ] **Step 4: Verify identity uniqueness and the official set**

Run:

```bash
jq -e '
  [.teams[] | select((.competition_ids // []) | index("eng-premier"))] as $teams
  | ($teams | length) == 20
  and (($teams | map(.team_id) | unique | length) == 20)
  and (($teams | map(.name_en) | unique | length) == 20)
' nutmeg/data/decision_entities_seed.json
```

Expected: `true` and exit 0.

- [ ] **Step 5: Verify every Chinese canonical name resolves through the actual entity code**

Run:

```bash
uv run python -c 'from nutmeg.decision.entities import load_seed_entities,load_team_alias_table,resolve_team; teams,_=load_seed_entities(); table=load_team_alias_table(); e=[(t.name_zh,t.team_id,resolve_team(t.name_zh,table)) for t in teams if "eng-premier" in t.competition_ids and resolve_team(t.name_zh,table)!=t.team_id]; print(e); raise SystemExit(bool(e))'
```

Expected: `[]` and exit 0.

---

### Task 3: Populate The Premier League Profile

**Files:**
- Modify: `nutmeg/data/decision_entities_seed.json`

- [ ] **Step 1: Recompute the 2025-26 league baseline from all 380 official results**

Run:

```bash
curl -L --max-time 30 -s \
  -H 'Origin: https://www.premierleague.com' -H 'User-Agent: Mozilla/5.0' \
  'https://footballapi.pulselive.com/football/fixtures?page=0&pageSize=500&comp=1&compSeasons=777&statuses=C&altIds=true' \
  | jq '{matches:(.content|length),home_wins:([.content[]|select(.outcome=="H")]|length),draws:([.content[]|select(.outcome=="D")]|length),away_wins:([.content[]|select(.outcome=="A")]|length),goals:([.content[]|.teams[0].score+.teams[1].score]|add),over_2_5:([.content[]|select((.teams[0].score+.teams[1].score)>=3)]|length),btts:([.content[]|select(.teams[0].score>0 and .teams[1].score>0)]|length)}'
```

Expected: `380` matches, `162/104/114` home/draw/away, `1045` goals, `209` over 2.5, and `213` BTTS.

- [ ] **Step 2: Add the six fixed league notes**

Use `apply_patch` to set `eng-premier.profile_notes` to these evidence-backed subjects:

```text
season_format_2026_27: 20队双循环380场；2026-08-21开幕、2027-05-30收官；33个周末轮次+5个周中轮次；圣诞新年至少60小时休息。
result_baseline_2025_26: 162主胜/104平/114客胜 = 42.6%/27.4%/30.0%。
goal_regime_2025_26: 1045球、2.75球/场；大2.5为209/380=55.0%；双方进球213/380=56.1%。
home_away_regime_2025_26: 主胜较客胜高12.6pp，但27.4%平局不可忽略；只作联赛底座，不作为单场规则。
schedule_congestion_2026_27: 官方赛历的33周末+5周中及欧战/国内杯赛重叠；具体轮换只在比赛级复核。
promoted_context_2026_27: 考文垂95分英冠冠军、伊普斯维奇84分亚军直升、赫尔城附加赛升级；三队顶级联赛样本须与英冠样本分层。
```

Use the official Premier League fixtures article/API for the first five notes and the BBC promoted-clubs
preview plus official 2026-27 club list for the sixth. Set every `at` to `2026-08-20`.

- [ ] **Step 3: Verify exact league-key coverage**

Run:

```bash
jq -e '
  [.leagues[] | select(.league_id=="eng-premier") | .profile_notes[].key] | sort
  == ["goal_regime_2025_26","home_away_regime_2025_26","promoted_context_2026_27","result_baseline_2025_26","schedule_congestion_2026_27","season_format_2026_27"]
' nutmeg/data/decision_entities_seed.json
```

Expected: `true` and exit 0.

---

### Task 4: Collect Stable Baselines For The 17 Incumbent Clubs

**Files:**
- Modify: `nutmeg/data/decision_entities_seed.json`

The cohort is Arsenal, Aston Villa, Bournemouth, Brentford, Brighton, Chelsea, Crystal Palace, Everton,
Fulham, Leeds, Liverpool, Manchester City, Manchester United, Newcastle, Nottingham Forest, Sunderland,
and Tottenham.

- [ ] **Step 1: Fetch the complete 2025-26 table**

Run:

```bash
curl -L --max-time 30 -s \
  -H 'Origin: https://www.premierleague.com' -H 'User-Agent: Mozilla/5.0' \
  'https://footballapi.pulselive.com/football/standings?comp=1&compSeasons=777&page=0&pageSize=100&altIds=true' \
  | jq -r '.tables[0].entries[] | [.position,.team.name,.overall.played,.overall.won,.overall.drawn,.overall.lost,.overall.goalsFor,.overall.goalsAgainst,.overall.points] | @tsv'
```

Expected: the complete 20-row table headed by Arsenal `85` points and ending with Wolves `20` points.

- [ ] **Step 2: Compute each incumbent's home/away split from the 380-match result set**

For each of the 17 exact official names, filter the same season-777 result payload and record home
`P-W-D-L-GF-GA` and away `P-W-D-L-GF-GA`. The evidence string must include the official fixtures API URL,
season `777`, and `n=19` for each split.

- [ ] **Step 3: Collect coach, system, spine, attack, and defence evidence**

For each club, use its official Premier League squad/manager pages plus at least one BBC/Sky/Reuters or
official club season review. Record only mechanisms supported by named players, roles, formation evidence,
or full-season statistics. Do not turn table position, last-five form, or generic style adjectives into a
mechanism.

Use this exact search form when an official route is not known:

```text
site:<official-club-domain> <Club Name> 2026/27 first team manager squad
site:bbc.com/sport/football <Club Name> 2026-27 season preview tactics
```

- [ ] **Step 4: Write the six stable keys for all 17 incumbents**

Use `apply_patch` to populate `strength_baseline_2026_27`, `coach_system_2026_27`,
`squad_spine_2026_27`, `attack_profile_2026_27`, `defence_profile_2026_27`, and
`home_away_profile_2025_26`. Each note must name its sample/players and carry a locatable evidence string.

- [ ] **Step 5: Verify stable-key coverage for the incumbent cohort**

Run:

```bash
jq -e '
  ["eng-arsenal","eng-aston-villa","eng-bournemouth","eng-brentford","eng-brighton","eng-chelsea","eng-crystal-palace","eng-everton","eng-fulham","eng-leeds-united","eng-liverpool","eng-manchester-city","eng-manchester-united","eng-newcastle-united","eng-nottingham-forest","eng-sunderland","eng-tottenham-hotspur"] as $ids
  | all(.teams[] | select(.team_id as $id | $ids | index($id));
      ([.profile_notes[].key] | map(select(.=="strength_baseline_2026_27" or .=="coach_system_2026_27" or .=="squad_spine_2026_27" or .=="attack_profile_2026_27" or .=="defence_profile_2026_27" or .=="home_away_profile_2025_26")) | length) == 6)
' nutmeg/data/decision_entities_seed.json
```

Expected: `true` and exit 0.

---

### Task 5: Collect Stable Baselines For The Three Promoted Clubs

**Files:**
- Modify: `nutmeg/data/decision_entities_seed.json`

- [ ] **Step 1: Lock the promotion paths**

Use the BBC 2026-27 promoted-clubs preview and an official club/EFL promotion report to record:

```text
Coventry City: Championship champions, 95 points, first Premier League season since 2000-01.
Ipswich Town: Championship runners-up, 84 points, one season outside the Premier League.
Hull City: Championship play-off winners, first Premier League season since 2016-17.
```

If a source disagrees with those facts, stop and resolve the conflict before writing.

- [ ] **Step 2: Compute Championship home/away samples at their original level**

Use a complete 2025-26 Championship table/result source for each club and label every number explicitly
`英冠 n=23`, so those figures cannot be mistaken for a Premier League prior.

- [ ] **Step 3: Collect promoted-club system and spine evidence**

Use the club's promotion-season review, official squad, and BBC promoted-clubs preview to identify the
manager, stable formation, goalkeeper/centre-back/midfield/creator/striker spine, attacking mechanisms, and
defensive mechanisms. Keep promotion-season facts separate from predictions about top-flight survival.

- [ ] **Step 4: Write the six stable keys for Coventry, Hull, and Ipswich**

Use the same six fixed stable keys as Task 4. Each strength note must say `升班马` and each home/away note
must say `英冠样本，不直接等同英超强度`.

- [ ] **Step 5: Verify promoted-club stable-key coverage**

Run:

```bash
jq -e '
  ["eng-coventry-city","eng-hull-city","eng-ipswich-town"] as $ids
  | all(.teams[] | select(.team_id as $id | $ids | index($id));
      ([.profile_notes[].key] | map(select(.=="strength_baseline_2026_27" or .=="coach_system_2026_27" or .=="squad_spine_2026_27" or .=="attack_profile_2026_27" or .=="defence_profile_2026_27" or .=="home_away_profile_2025_26")) | length) == 6)
' nutmeg/data/decision_entities_seed.json
```

Expected: `true` and exit 0.

---

### Task 6: Collect The 2026-08-20 Dynamic State For All 20 Clubs

**Files:**
- Modify: `nutmeg/data/decision_entities_seed.json`

- [ ] **Step 1: Establish one confirmed-transfer source per club**

Prefer each club's official `2026/27 ins and outs` page. Cross-check the league-wide ESPN confirmed-transfer
tracker. Ignore rumor-only moves; mention an unresolved move only when a reliable source identifies it as an
active risk, and label it `未官宣`.

- [ ] **Step 2: Establish one availability source per club**

Prefer the final official pre-match press conference or club medical update before Matchweek 1. If unavailable,
use two independent BBC/Sky/Reuters reports. Separate `confirmed out`, `doubt`, `returned to training`, and
`available`; do not collapse them into one injury list.

- [ ] **Step 3: Derive cohesion from facts, not prose confidence**

For each club, compare manager continuity, retained spine, number of new likely starters, and whether the
goalkeeper/centre-back/defensive-midfield triangle changed. Classify only as `稳定延续`, `局部换血`,
`新体系装配`, or `高不确定`, and list the facts that support the label.

- [ ] **Step 4: Write four dynamic keys for all 20 clubs**

Use `apply_patch` to add `summer_window_2026`, `availability_2026_08_20`,
`cohesion_2026_08_20`, and `watchlist_2026_08_20`. Every watchlist must name an observable invalidation
trigger for the transfer-window close, Matchweek 3, or Matchweek 5.

- [ ] **Step 5: Reject unsupported or stale dynamic notes**

Run:

```bash
jq -e '
  [.teams[] | select((.competition_ids // []) | index("eng-premier")) | .profile_notes[]
   | select(.key|test("^(summer_window_2026|availability_2026_08_20|cohesion_2026_08_20|watchlist_2026_08_20)$"))]
  | length == 80
  and all(.[]; (.at=="2026-08-20") and ((.evidence//"")|length>10) and ((.note//"")|length>20))
' nutmeg/data/decision_entities_seed.json
```

Expected: `true` and exit 0.

---

### Task 7: Normalize The Cross-Club Comparison And Review Evidence

**Files:**
- Modify only when review finds an issue: `nutmeg/data/decision_entities_seed.json`

- [ ] **Step 1: Run the exact 10-key coverage assertion**

Run:

```bash
jq -e '
  ["attack_profile_2026_27","availability_2026_08_20","coach_system_2026_27","cohesion_2026_08_20","defence_profile_2026_27","home_away_profile_2025_26","squad_spine_2026_27","strength_baseline_2026_27","summer_window_2026","watchlist_2026_08_20"] as $keys
  | [.teams[] | select((.competition_ids // []) | index("eng-premier"))] as $teams
  | ($teams|length)==20
  and all($teams[]; ([.profile_notes[].key]|sort)==$keys)
  and all($teams[].profile_notes[]; ((.evidence//"")|length)>10 and .at=="2026-08-20")
' nutmeg/data/decision_entities_seed.json
```

Expected: `true` and exit 0.

- [ ] **Step 2: Print a horizontal comparison view**

Run:

```bash
jq -r '
  .teams[] | select((.competition_ids // []) | index("eng-premier"))
  | [.name_zh,
     (.profile_notes[]|select(.key=="strength_baseline_2026_27")|.note),
     (.profile_notes[]|select(.key=="cohesion_2026_08_20")|.note),
     (.profile_notes[]|select(.key=="availability_2026_08_20")|.note),
     (.profile_notes[]|select(.key=="watchlist_2026_08_20")|.note)] | @tsv
' nutmeg/data/decision_entities_seed.json
```

Expected: exactly 20 rows, each exposing strength, cohesion, availability, and invalidation triggers.

- [ ] **Step 3: Perform the ontology-boundary review**

Inspect all 206 notes and fix any note that:

```text
- cites no locatable source;
- presents rumor as completed transfer;
- turns form/table position into an automatic betting rule;
- assigns a score without a defined factual denominator;
- fails to distinguish Championship and Premier League samples;
- contains a time-sensitive claim without the 2026-08-20 cutoff;
- uses profile evidence to bypass the match-level Read factor requirement.
```

- [ ] **Step 4: Check that unrelated dirty content remains present**

Run `git diff -- nutmeg/data/decision_entities_seed.json` and verify the pre-existing Championship,
Eredivisie, Primeira Liga, La Liga, and Allsvenskan additions remain unchanged.

---

### Task 8: Sync To The Live Store And Verify The Operational Path

**Files:**
- Runtime update only: `.nutmeg-data/jczq/decision/leagues.jsonl`
- Runtime update only: `.nutmeg-data/jczq/decision/teams.jsonl`

- [ ] **Step 1: Run focused entity tests before syncing**

Run:

```bash
uv run pytest tests/decision/test_entities.py tests/decision/test_alias_audit.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Sync the curated seed into the live decision store**

Run:

```bash
uv run nutmeg decision-entities-sync --output-dir .nutmeg-data/jczq
```

Expected: at least the 20 new Premier League teams are added and `eng-premier` is updated. Additional
adds/updates are allowed because the starting seed contains other user-owned unsynced entities.

- [ ] **Step 3: Prove sync idempotency**

Run the same command again.

Expected: `新增 0 / 更新 0`; all seed entities are reported unchanged.

- [ ] **Step 4: Read the league and representative team profiles through the CLI**

Run:

```bash
uv run nutmeg decision-profile --output-dir .nutmeg-data/jczq --league eng-premier
uv run nutmeg decision-profile --output-dir .nutmeg-data/jczq --team eng-arsenal
uv run nutmeg decision-profile --output-dir .nutmeg-data/jczq --team eng-coventry-city
uv run nutmeg decision-profile --output-dir .nutmeg-data/jczq --team eng-tottenham-hotspur
```

Expected: league output reports 6 notes; every representative team reports 10 notes.

- [ ] **Step 5: Verify all 20 live-store objects programmatically**

Run:

```bash
uv run python -c 'from pathlib import Path; from nutmeg.decision.store import DecisionStore; from nutmeg.decision.ontology import Team,League; s=DecisionStore(Path(".nutmeg-data/jczq/decision")); ts=[t for t in s.load(Team) if "eng-premier" in t.competition_ids]; lg=s.get(League,"eng-premier"); print(len(ts),len(lg.profile_notes),sorted((t.team_id,len(t.profile_notes)) for t in ts)); raise SystemExit(not(len(ts)==20 and len(lg.profile_notes)==6 and all(len(t.profile_notes)==10 for t in ts)))'
```

Expected: `20 6` followed by 20 `(team_id, 10)` entries; exit 0.

- [ ] **Step 6: Run final quality gates**

Run:

```bash
jq empty nutmeg/data/decision_entities_seed.json
jq empty nutmeg/data/jczq_club_team_aliases.json
uv run pytest tests/decision/test_entities.py tests/decision/test_alias_audit.py -q
git diff --check
git status --short
```

Expected: valid JSON, focused tests pass, no whitespace errors, and only the intended target files plus the
user's pre-existing unrelated edits remain modified.

- [ ] **Step 7: Leave the overlapping data changes uncommitted**

Do not stage `decision_entities_seed.json` or `jczq_club_team_aliases.json`: their starting changes belong to
the user and cannot be separated safely from the appended Premier League data in a normal commit. Report the
live-store update, exact coverage counts, source cutoff, tests, and remaining Matchweek 3/5 review triggers.

---

## Spec Coverage

| Design requirement | Plan task |
|---|---|
| Official 2026-27 League + exact 20 clubs | Tasks 2-3 |
| Six league dimensions | Task 3 |
| Ten fixed dimensions per club | Tasks 4-7 |
| Stable baseline + dynamic state split | Tasks 4-6 |
| Objective horizontal comparison | Task 7 |
| Evidence hierarchy and date cutoff | Tasks 3-7 |
| No automatic score or decision rule | Task 7 boundary review |
| Aliases and runtime profile availability | Tasks 2 and 8 |
| Idempotent seed-to-store sync | Task 8 |
| Preserve pre-existing user changes | Tasks 1, 7, and 8 |
| Transfer-window, MW3, MW5 refresh triggers | Task 6 watchlists |
