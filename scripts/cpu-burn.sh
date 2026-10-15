#!/usr/bin/env bash
set -euo pipefail

duration="${1:-20}"
if ! [[ "$duration" =~ ^[1-9][0-9]*$ ]] || (( duration > 60 )); then
  echo "Usage: bash scripts/cpu-burn.sh [seconds: 1-60]" >&2
  exit 2
fi

echo "Burning one app-container CPU core for ${duration}s."
docker compose exec -T app python -c \
  'import sys,time; stop=time.monotonic()+int(sys.argv[1]); exec("while time.monotonic() < stop:\n    pass")' \
  "$duration"
