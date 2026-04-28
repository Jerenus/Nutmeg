#!/usr/bin/env bash
set -euo pipefail

mode="dry-run"
fixture_id=""
league="epl"
days="14"
past_days="7"

usage() {
  cat <<'EOF'
Usage: scripts/acceptance.sh [--dry-run|--local|--live] [--fixture-id ID] [--league CODE]

Modes:
  --dry-run   Print the no-network acceptance command plan. This is the default.
  --local     Run no-network local acceptance commands only.
  --live      Run live provider acceptance. Requires NUTMEG_API_FOOTBALL_KEY.

Live mode intentionally fails fast before provider calls when required keys are missing.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      mode="dry-run"
      shift
      ;;
    --local)
      mode="local"
      shift
      ;;
    --live)
      mode="live"
      shift
      ;;
    --fixture-id)
      fixture_id="${2:-}"
      shift 2
      ;;
    --league)
      league="${2:-}"
      shift 2
      ;;
    --days)
      days="${2:-}"
      shift 2
      ;;
    --past-days)
      past_days="${2:-}"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

local_commands=(
  "uv run nutmeg doctor --format json"
  "uv run nutmeg agent-status --format json"
  "uv run nutmeg fixtures --league ${league} --demo"
)

live_commands=(
  "uv run nutmeg fixtures-sync --league ${league} --days ${days} --past-days ${past_days}"
  "uv run nutmeg agent-status --format json"
)
if [[ -n "$fixture_id" ]]; then
  live_commands+=(
    "uv run nutmeg fixture-snapshot --fixture-id ${fixture_id} --format json"
    "uv run nutmeg odds-snapshot --fixture-id ${fixture_id} --format json"
    "uv run nutmeg agent-analyze-match --fixture-id ${fixture_id} --query 'Should I back the home side?' --format json"
  )
fi

if [[ "$mode" == "dry-run" ]]; then
  echo "mode=dry-run"
  printf 'PLAN %s\n' "${local_commands[@]}"
  exit 0
fi

if [[ "$mode" == "live" ]]; then
  if [[ -z "${NUTMEG_API_FOOTBALL_KEY:-}" ]]; then
    echo 'NUTMEG_API_FOOTBALL_KEY is required for --live acceptance' >&2
    exit 2
  fi
  for command in "${live_commands[@]}"; do
    echo "+ $command"
    eval "$command"
  done
  exit 0
fi

echo "mode=local"
for command in "${local_commands[@]}"; do
  echo "+ $command"
  eval "$command"
done
