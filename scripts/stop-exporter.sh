#!/usr/bin/env bash
set -euo pipefail

exporter="${1:-node-exporter}"
duration="${2:-20}"
case "$exporter" in
  node-exporter|cadvisor|nginx-exporter|postgres-exporter) ;;
  *)
    echo "Choose node-exporter, cadvisor, nginx-exporter, or postgres-exporter." >&2
    exit 2
    ;;
esac
if ! [[ "$duration" =~ ^[1-9][0-9]*$ ]] || (( duration > 60 )); then
  echo "Usage: bash scripts/stop-exporter.sh [exporter] [seconds: 1-60]" >&2
  exit 2
fi

restore_exporter() {
  if ! docker compose start "$exporter"; then
    echo "Could not restart ${exporter}; recover with: docker compose up -d ${exporter}" >&2
    return 1
  fi
}
trap restore_exporter EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "Stopping ${exporter} for ${duration}s; the exit trap will restart it."
docker compose stop "$exporter"
sleep "$duration"
docker compose start "$exporter"
trap - EXIT INT TERM
