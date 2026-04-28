#!/usr/bin/env bash
set -euo pipefail

uv sync --extra dev
uv run nutmeg doctor

api_configured="$(uv run python -c 'from nutmeg.config.settings import get_settings; print("yes" if get_settings().api_football_key else "no")')"

if [[ "$api_configured" == "yes" ]]; then
  uv run nutmeg fixtures-sync --days "${NUTMEG_DEFAULT_SYNC_DAYS:-30}"
else
  echo "NUTMEG_API_FOOTBALL_KEY is not set; skipping live fixture sync."
fi
