#!/usr/bin/env bash
set -euo pipefail

uv run ruff check .
uv run pytest
uv run nutmeg doctor --format json >/dev/null
uv run nutmeg fixtures --league epl --demo >/dev/null
bash scripts/acceptance.sh --dry-run >/dev/null
