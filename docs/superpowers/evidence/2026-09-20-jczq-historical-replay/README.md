# JCZQ Historical Replay Verification Evidence

Date: 2026-09-20 (Asia/Shanghai)

## Accepted isolated replay

- Business date: `2026-09-19`
- Replay run: `jczq-replay-fcd04cbf1a3ebf9598e83191`
- Schema: `35`
- Report: `.nutmeg-data/replay/2026-09-19-ontology-v2-v5/replay-2026-09-19.json`
- Report SHA-256: `0a0b4160ed6fecc1efc994c42ea826b7ae49b76a6c9a0352aac3a350b8e4f8b5`
- Source manifest SHA-256: `f1850da7a9e07c7873e70fc99cb4389ba12189b6b7ac9e7cb4ddef5752766737`
- Production fingerprint before/after: `eccd712bc05b315d730c555f70da4e89a1618628a1a2a40d2f306460f329e12f`

Derived isolated state:

- Research terminals: 30 (`researched=25`, `rejected=1`, `price_only=4`)
- Adjudication branches: 28 approve, 1 revise, 1 reject
- Current committed Forecasts with complete artifact lineage: 30/30
- Candidate sets: `judgment_bound`, `conditional_market_counterfactual`
- Structured band outcomes: 8 (four bands for each set)
- Terminal: replay-only formal `no_ticket`
- Authoritative results / predictions / scores: 30 / 30 / 30
- Quarantine: `research-周六002.rejected.json` retained with unknown capture time
- RSI: R0/F5/F9 all `replay_excluded`; no observation, grade, verdict, or deployment rows
- Protected replay rows: no placements, cash transactions, or confirmations
- Production deltas: objects, money, dispatch, and prospective observations all zero

The result artifact records the genuine Okooo retrieval time in `captured_at`.
It does not infer or fabricate a publication timestamp.

## Independent cutover check

`jczq-cutover --check-only` reopened the isolated database read-only, verified the
frozen manifest and input hashes, recomputed A2-A7 state, and accepted the report.
The returned production authority remained `legacy_read_only`. No `--approve`
operation was executed.

## Automated verification

- Replay/ontology focused suite: passed (67 tests)
- Full `uv run pytest -q`: passed
- Replay-related Ruff scope: passed
- Full Ruff remains blocked only by three pre-existing findings in user-owned
  `experiments/exp-price-bands.py` and `experiments/exp-strict-space.py`.
