#!/usr/bin/env bash
set -euo pipefail

megabytes="${1:-16}"
hold_seconds="${2:-5}"
if ! [[ "$megabytes" =~ ^[1-9][0-9]*$ ]] || (( megabytes > 64 )) ||
  ! [[ "$hold_seconds" =~ ^[1-9][0-9]*$ ]] || (( hold_seconds > 30 )); then
  echo "Usage: bash scripts/disk-fill.sh [megabytes: 1-64] [hold seconds: 1-30]" >&2
  exit 2
fi

echo "Writing a temporary ${megabytes} MiB file in the app container's writable layer."
docker compose exec -T app sh -c \
  'set -eu; trap "rm -f /tmp/lab-disk-fill" EXIT HUP INT TERM; dd if=/dev/zero of=/tmp/lab-disk-fill bs=1M count="$1" conv=fsync; sleep "$2"' \
  sh "$megabytes" "$hold_seconds"
