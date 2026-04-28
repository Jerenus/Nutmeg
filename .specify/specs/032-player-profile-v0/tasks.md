# Tasks: Player Profile v0

**Input**: `.specify/specs/032-player-profile-v0/`
**Prerequisites**: `005-player-identity-materialization`, `006-prematch-snapshot-expansion`

- [x] T001 Define player profile domain dataclasses in `nutmeg/domain/players.py`.
- [x] T002 Add RED service tests in `tests/test_player_profile_service.py`.
- [x] T003 Add RED CLI JSON tests in `tests/test_cli.py`.
- [x] T004 Implement player identity/cache lookup helpers.
- [x] T005 Implement player profile aggregation service.
- [x] T006 Implement deterministic similar-player scoring from available metrics.
- [x] T007 Implement `player-profile` CLI text/JSON rendering.
- [x] T008 Document `docs/architecture/player-profile.md` and README usage.
- [x] T009 Run focused and full verification, refresh graph, update memory/progress.
