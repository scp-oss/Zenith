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

# Живой случай на miha (МТС) 2026-08-26: шаблон раньше хардкодил
# /opt/zapret2/files/fake/... для всех --blob= (см. CLAUDE.md
# z2r_autobench "/opt/zapret2 vs /opt/zator" -- files/ не обязательно
# живёт под /opt/zapret2 на штатной раскладке апстрим-установщика).
# nfqws2 падал с "cannot access file ...tls_clienthello_max_ru.bin" на
# самом старте песочницы. Определяем реальную базу так же, как
# z2r_autobench_lib.sh::_z2r_detect_base(), а не хардкодим вторую догадку.
#
# ВАЖНО: проверяем не просто "директория существует" -- на miha
# /opt/zapret2/files/fake существовала как ПУСТАЯ (или неполная)
# директория, первая же проверка `[ -d ... ]` проходила, и FAKE_DIR
# резолвился туда же, где нужного файла всё равно нет (первый заход на
# этот баг, 2026-08-26, был именно такой -- фикс на директорию не помог).
# Проверяем конкретный файл, который реально нужен шаблону.
_fake_probe="tls_clienthello_max_ru.bin"
if [ -f "/opt/zapret2/files/fake/$_fake_probe" ]; then
  FAKE_DIR="/opt/zapret2/files/fake"
elif [ -f "/opt/zator/files/fake/$_fake_probe" ]; then
  FAKE_DIR="/opt/zator/files/fake"
else
  FAKE_DIR="/opt/zapret2/files/fake"
  echo "Не нашёл $_fake_probe ни под /opt/zapret2/files/fake, ни под /opt/zator/files/fake -- использую дефолт $FAKE_DIR, скорее всего сломается." >&2
fi

[ -f "$QUEUE_FILE" ] || { echo "Нет $QUEUE_FILE — сначала запусти setup_sandbox.sh." >&2; exit 1; }
[ -x "$NFQWS2_BIN" ] || { echo "$NFQWS2_BIN не найден — z2r/zapret2 установлен?" >&2; exit 1; }

qnum="$(cat "$QUEUE_FILE")"

# Живой конфиг генерим из шаблона только если его ещё нет — если он уже
# существует, это значит оркестратор его уже переписал под конкретный
# геном, и перезатирать эту работу шаблоном при каждом старте нельзя.
if [ ! -f "$LIVE_CONF" ]; then
  sed -e "s#__QNUM__#$qnum#g" -e "s#__ZENITH_DIR__#$SCRIPT_DIR/..#g" -e "s#__FAKE_DIR__#$FAKE_DIR#g" "$TEMPLATE" > "$LIVE_CONF"
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
