#!/usr/bin/env bash
set -euo pipefail

megabytes="${1:-64}"
duration="${2:-15}"
if ! [[ "$megabytes" =~ ^[1-9][0-9]*$ ]] || (( megabytes > 256 )) ||
  ! [[ "$duration" =~ ^[1-9][0-9]*$ ]] || (( duration > 60 )); then
  echo "Usage: bash scripts/memory-pressure.sh [megabytes: 1-256] [seconds: 1-60]" >&2
  exit 2
fi

echo "Allocating ${megabytes} MiB in the app container for ${duration}s."
docker compose exec -T app python -c \
  'import sys,time; data=bytearray(int(sys.argv[1])*1024*1024); exec("for offset in range(0, len(data), 4096):\n    data[offset] = 1"); time.sleep(int(sys.argv[2]))' \
  "$megabytes" "$duration"
