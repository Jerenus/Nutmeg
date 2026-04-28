# Verification: Popular Matches Ranking

**Date**: 2026-04-25  
**Status**: PASS

## Commands

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_popularity.py tests/test_cli.py -q` -> 44 passed
- `uv run ruff check nutmeg/services/popularity.py nutmeg/interfaces/cli.py tests/test_popularity.py tests/test_cli.py` -> pass
- `uv run nutmeg popular-matches --league epl --days 3 --demo --format json` -> returned ranked demo candidates with score/tier/reasons
- `uv run nutmeg today-briefs --league epl --days 3 --demo --sort popularity --format json` -> returned ranked today-brief candidates
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q` -> pass
- `uv run ruff check .` -> pass
- `python3 -m compileall nutmeg` -> pass
- `bash scripts/verify.sh` -> 146 passed

## Spec Verification Checklist

- [x] US1 deterministic popularity ranking with explainable score — verified by `tests/test_popularity.py::test_popularity_ranker_prioritizes_elite_matchup_with_explainable_score` and `tests/test_popularity.py::test_popularity_ranker_boosts_live_fixtures`
- [x] US2 `popular-matches` JSON CLI contract — verified by `tests/test_cli.py::test_popular_matches_command_returns_ranked_demo_candidates`
- [x] US3 `today-briefs --sort popularity` reuse — verified by `tests/test_cli.py::test_today_briefs_command_can_sort_by_popularity`
- [x] FR-001 no-network deterministic scoring — verified by service tests using local `Fixture` values only
- [x] FR-002 score dimensions — verified by ranker tests and reasons emitted from `MatchPopularityRanker`
- [x] FR-003 score/tier/reasons — verified by ranker and CLI JSON assertions
- [x] FR-004 CLI options — verified by CLI invocation in `tests/test_cli.py`
- [x] FR-005 token-free suggested bot messages — verified by output contract containing only fixture/query fields
- [x] FR-006 kickoff default preserved, popularity opt-in — verified by existing `today-briefs` tests plus new `--sort popularity` test
