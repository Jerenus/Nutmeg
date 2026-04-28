# Data Model: Nutmeg Platform Foundation

## UserIdentity

- `user_id`: string, globally unique tenant key; `owner` in Phase 1
- `tier`: `owner | friend | subscriber`
- `preferences`: dictionary of tracked teams, leagues, language, decision style
- `quota`: placeholders for per-resource daily and monthly limits
- `created_at`: UTC timestamp

## Fixture

- `fixture_id`: provider-scoped stable identifier
- `league`: normalized competition code such as `epl`
- `kickoff_at`: UTC datetime
- `home_team`, `away_team`: display names
- `status`: `scheduled | live | finished`
- `source`: provider or demo source label
- `venue`: optional display name

## AppSettings

- `app_env`, `default_user_id`, `data_dir`
- provider configuration for Portkey, API-Football, LangSmith
- derived SQLite and DuckDB URLs

## BridgeReport

- discovery roots: workspace and global
- skill status rows for required and optional Superpowers skills
- hook readiness for `before_implement`, `after_implement`, `after_tasks`
- verdict: `READY | PARTIAL | BLOCKED`
