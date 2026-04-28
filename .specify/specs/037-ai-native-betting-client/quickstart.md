# Quickstart: AI-Native Betting Client

This quickstart describes the expected checks after implementation. It is intentionally safe: no sportsbook connection, no wager execution, and no public billing provider are required.

## 1. Prepare local data

```bash
uv run nutmeg seed-demo --league epl
uv run nutmeg popular-matches --league epl --days 3 --demo --format json
uv run nutmeg value-board --league epl --days 3 --demo --format json
```

For live local use, sync explicitly:

```bash
uv run nutmeg fixtures-sync --league epl --days 7
```

## 2. Verify CLI parity for the client payloads

```bash
uv run nutmeg client-feed --league epl --days 3 --demo --format json
uv run nutmeg client-match --fixture-id epl-001 --format json
uv run nutmeg client-question --fixture-id epl-001 --question "What changed since this morning?" --format json
uv run nutmeg client-status --format json
```

Expected behavior:

- JSON output is parseable.
- Feed cards include actionability, confidence, freshness, and responsible-use copy.
- Match workspace includes judgment, value/market/tactical/player sections, evidence, caveats, and audit id.
- Unsupported or missing-evidence questions return a truthful refusal instead of invented facts.

## 3. Run the browser/PWA surface

```bash
uv run nutmeg client-web --host 127.0.0.1 --port 8765
```

Open:

```text
http://127.0.0.1:8765/client?league=epl&days=3&demo=true
```

Expected behavior:

- Daily feed is readable on desktop and mobile-width screens.
- Match cards show freshness/unavailable states.
- Match detail page exposes judgment, reasons, counterargument, caveats, source ledger, and responsible-use copy.
- The PWA manifest is available at `/client/manifest.webmanifest`.

## 4. Run focused tests

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest \
  tests/test_client_domain.py \
  tests/test_client_service.py \
  tests/test_client_state_repository.py \
  tests/test_client_web.py \
  tests/test_cli.py -q
```

## 5. Run full verification

```bash
uv run ruff check .
python3 -m compileall nutmeg
bash scripts/verify.sh
```

## Safety expectations

- No command places a bet or connects to a sportsbook.
- Non-entitled users do not receive hidden premium content.
- Watchlists, alerts, prediction records, and audit history remain isolated by `user_id`.
- Stale or missing evidence downgrades actionability to watch, avoid, or no-bet.
