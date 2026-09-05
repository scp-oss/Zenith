#!/usr/bin/env bash
# stop_sandbox.sh — останавливает песочный nfqws2, если он запущен.
# Не трогает боевой /opt/zapret2.

set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LIVE_CONF="$SCRIPT_DIR/nfqws2_sandbox.conf"
# /tmp, не sandbox/ -- см. одноимённый комментарий в start_sandbox.sh
# (nfqws2 теперь запускается от nobody через runuser, пишет pidfile сам).
PIDFILE="/tmp/zenith_nfqws2_sandbox.pid"

if [ -f "$PIDFILE" ]; then
  pid="$(cat "$PIDFILE")"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    sleep 1
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null
    echo "Песочный nfqws2 (PID $pid) остановлен."
  else
    echo "PID $pid из $PIDFILE уже не живой."
  fi
  rm -f "$PIDFILE"
else
  echo "Нет $PIDFILE — pidfile отсутствует."
fi

# Дополнительная сеть безопасности, найденная живьём при диагностике
# VOICE_UDP-песочницы 2026-09-05: если start_sandbox.sh посчитал прошлый
# запуск неудачным (напр. гонка с записью pidfile) и вышел с ошибкой, а
# nfqws2 на деле успешно поднялся и задемонизировался (PPID=1) -- pidfile
# для него никогда не появляется, и обычная kill-по-pidfile-у выше его не
# видит. Такой "осиротевший" процесс не считается ядром освободившим
# очередь -- следующий запуск падает с `nfq_create_queue(): Operation not
# permitted` на уже занятый номер (ядро отвечает EPERM, не EBUSY), что
# выглядит точь-в-точь как проблема capabilities, а на деле просто чужой
# живой процесс держит тот же номер очереди. pkill по точному пути конфига
# ловит его независимо от pidfile.
pkill -f "nfqws2 @$LIVE_CONF" 2>/dev/null && echo "Найден и остановлен процесс без pid-файла (nfqws2 @$LIVE_CONF)."
true
