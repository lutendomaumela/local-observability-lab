#!/usr/bin/env bash
set -euo pipefail

duration="${1:-15}"
if ! [[ "$duration" =~ ^[1-9][0-9]*$ ]] || (( duration > 60 )); then
  echo "Usage: bash scripts/kill-app.sh [seconds: 1-60]" >&2
  exit 2
fi

restore_app() {
  if ! docker compose start app; then
    echo "Could not restart the app; recover with: docker compose up -d app" >&2
    return 1
  fi
}
trap restore_app EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "Stopping the simulated app for ${duration}s; the exit trap will restart it."
docker compose kill app
sleep "$duration"
docker compose start app
trap - EXIT INT TERM
