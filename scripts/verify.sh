#!/usr/bin/env bash
set -euo pipefail

uv run ruff check .
uv run python -m compileall -q nutmeg scripts
uv run pytest
