#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f .env ]]; then
  echo "Copy .env.example to .env before running this script." >&2
  exit 2
fi

set -a
source ./.env
set +a
: "${CHAOS_ADMIN_TOKEN:?Set CHAOS_ADMIN_TOKEN in .env}"

base_url="http://127.0.0.1:${APP_PORT:-8080}"
token_header="X-Admin-Token: ${CHAOS_ADMIN_TOKEN}"
clear_chaos() {
  if ! curl -fsS -X DELETE "$base_url/chaos" -H "$token_header" >/dev/null; then
    echo "Could not clear chaos settings; clear them with the documented DELETE /chaos request." >&2
    return 1
  fi
}
trap clear_chaos EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "Adding a 2s PostgreSQL pg_sleep to each home-page request."
curl -fsS -X POST "$base_url/chaos" \
  -H "$token_header" \
  -H "Content-Type: application/json" \
  -d '{"db_delay_ms":2000}'
echo
for request in 1 2 3; do
  curl -fsS --max-time 10 -o /dev/null \
    -w "Request ${request}: %{time_total}s\n" "$base_url/"
done
clear_chaos
trap - EXIT INT TERM
