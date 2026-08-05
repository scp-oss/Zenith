#!/usr/bin/env bash
# start_sandbox.sh — (пере)запускает песочный nfqws2 из
# nfqws2_sandbox.conf. Дёшево и безопасно перезапускать часто — этот
# процесс изолирован (--queue-bypass, отдельная очередь, ловит только
# трафик юзера zenith-sandbox), в отличие от боевого /opt/zapret2,
# который эти скрипты вообще не трогают.
#
# Требует, чтобы setup_sandbox.sh уже был выполнен (нужен sandbox/queue_num).

set -euo pipefail

if [ "$(id -u)" != "0" ]; then
  echo "Нужен root (nfqws2 привязывается к NFQUEUE)." >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
NFQWS2_BIN="/opt/zapret2/nfq2/nfqws2"
QUEUE_FILE="$SCRIPT_DIR/queue_num"
TEMPLATE="$SCRIPT_DIR/nfqws2_sandbox.conf.template"
LIVE_CONF="$SCRIPT_DIR/nfqws2_sandbox.conf"
PIDFILE="$SCRIPT_DIR/nfqws2_sandbox.pid"

[ -f "$QUEUE_FILE" ] || { echo "Нет $QUEUE_FILE — сначала запусти setup_sandbox.sh." >&2; exit 1; }
[ -x "$NFQWS2_BIN" ] || { echo "$NFQWS2_BIN не найден — z2r/zapret2 установлен?" >&2; exit 1; }

qnum="$(cat "$QUEUE_FILE")"

# Живой конфиг генерим из шаблона только если его ещё нет — если он уже
# существует, это значит оркестратор его уже переписал под конкретный
# геном, и перезатирать эту работу шаблоном при каждом старте нельзя.
if [ ! -f "$LIVE_CONF" ]; then
  sed -e "s#__QNUM__#$qnum#g" -e "s#__ZENITH_DIR__#$SCRIPT_DIR/..#g" "$TEMPLATE" > "$LIVE_CONF"
  echo "Сгенерирован $LIVE_CONF из шаблона (первый запуск)."
fi

"$SCRIPT_DIR/stop_sandbox.sh" 2>/dev/null || true

"$NFQWS2_BIN" "@$LIVE_CONF"
sleep 1

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "Песочный nfqws2 запущен (PID $(cat "$PIDFILE"), очередь $qnum)."
else
  echo "Не похоже, что процесс поднялся — смотри $SCRIPT_DIR/nfqws2_sandbox.debug.log" >&2
  exit 1
fi
