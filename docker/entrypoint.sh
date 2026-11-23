#!/bin/sh
# Default: run `calendar-sync sync` every SYNC_INTERVAL_SECONDS (default 3600).
# Any other arguments are passed straight to the CLI, e.g.
#   docker run ... IMAGE list-events
#   docker run ... IMAGE sync --job u7
set -eu

if [ "${1:-loop}" = "google-login" ]; then
  shift
  exec python /usr/local/bin/google-login.py "$@"   # headless copy/paste login
fi

if [ "${1:-loop}" != "loop" ]; then
  exec calendar-sync "$@"
fi

if [ ! -f "${GOOGLE_TOKEN_PATH:-/data/google_token.json}" ]; then
  echo "WARNING: no Google token yet. Run once:  docker compose run --rm calendar-sync google-login"
fi

interval="${SYNC_INTERVAL_SECONDS:-3600}"
sleep_pid=""

stop() {
  echo "received stop signal, exiting"
  [ -n "$sleep_pid" ] && kill "$sleep_pid" 2>/dev/null || true
  exit 0
}
trap stop INT TERM

while true; do
  echo "$(date -Iseconds) starting sync"
  if calendar-sync sync; then
    echo "$(date -Iseconds) sync finished"
  else
    echo "$(date -Iseconds) sync failed (exit $?), retrying in ${interval}s"
  fi
  sleep "$interval" &
  sleep_pid=$!
  wait "$sleep_pid" || true
done
