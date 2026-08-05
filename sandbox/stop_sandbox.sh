#!/usr/bin/env bash
# stop_sandbox.sh — останавливает песочный nfqws2, если он запущен.
# Не трогает боевой /opt/zapret2.

set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PIDFILE="$SCRIPT_DIR/nfqws2_sandbox.pid"

if [ ! -f "$PIDFILE" ]; then
  echo "Нет $PIDFILE — песочница не запущена (или уже остановлена)."
  exit 0
fi

pid="$(cat "$PIDFILE")"
if kill -0 "$pid" 2>/dev/null; then
  kill "$pid"
  sleep 1
  kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null
  echo "Песочный nfqws2 (PID $pid) остановлен."
else
  echo "PID $pid из $PIDFILE уже не живой."
fi
rm -f "$PIDFILE"
