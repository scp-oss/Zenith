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
# /tmp, не sandbox/ -- nfqws2 теперь запускается сразу от nobody (см.
# комментарий у runuser ниже), а sandbox/ обычно root:root без права
# записи для nobody на СОЗДАНИЕ нового файла (в отличие от дозаписи в
# уже существующий debug.log). /tmp с sticky-битом даёт nobody создать
# свой pidfile, не давая другим его тронуть.
PIDFILE="/tmp/zenith_nfqws2_sandbox.pid"

# Живой случай на Server B (Provider B) 2026-08-26: шаблон раньше хардкодил
# /opt/zapret2/files/fake/... для всех --blob= (см. CLAUDE.md
# z2r_autobench "/opt/zapret2 vs /opt/zator" -- files/ не обязательно
# живёт под /opt/zapret2 на штатной раскладке апстрим-установщика).
# nfqws2 падал с "cannot access file ...tls_clienthello_max_ru.bin" на
# самом старте песочницы. Определяем реальную базу так же, как
# z2r_autobench_lib.sh::_z2r_detect_base(), а не хардкодим вторую догадку.
#
# ВАЖНО: проверяем не просто "директория существует" -- на Server B
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

# nfqws2 запускается от nobody (см. комментарий у runuser ниже) -- ему
# нужны cap_net_admin/cap_net_raw/cap_setpcap на РЕАЛЬНОМ файле (не на
# символьной ссылке $NFQWS2_BIN, setcap на симлинк не работает).
# Применяется БЕЗУСЛОВНО на каждый запуск (тот же idempotent-паттерн, что
# ensure_wsrelay_user()/ensure_panel_runtime_grants() в z0r) -- любая
# переустановка/апдейт z2r/zapret2 кладёт новый файл на это место, и
# старый setcap-грант вместе со старым файлом пропадает молча, без
# всякой ошибки при следующем запуске песочницы, кроме самого
# `nfq_create_queue(): Operation not permitted`.
_real_nfqws2_bin="$(readlink -f "$NFQWS2_BIN")"
if command -v setcap >/dev/null 2>&1; then
  if ! _setcap_err="$(setcap cap_net_admin,cap_net_raw,cap_setpcap+eip "$_real_nfqws2_bin" 2>&1)"; then
    echo "!!! setcap на $_real_nfqws2_bin не удался: $_setcap_err -- песочница от nobody не сможет забиндить NFQUEUE." >&2
  fi
else
  echo "!!! Пакет libcap2-bin (команда setcap) не установлен -- 'apt-get install -y libcap2-bin', иначе песочница от nobody не сможет забиндить NFQUEUE." >&2
fi

qnum="$(cat "$QUEUE_FILE")"

# Живой конфиг генерим из шаблона только если его ещё нет — если он уже
# существует, это значит оркестратор его уже переписал под конкретный
# геном, и перезатирать эту работу шаблоном при каждом старте нельзя.
if [ ! -f "$LIVE_CONF" ]; then
  sed -e "s#__QNUM__#$qnum#g" -e "s#__ZENITH_DIR__#$SCRIPT_DIR/..#g" -e "s#__FAKE_DIR__#$FAKE_DIR#g" "$TEMPLATE" > "$LIVE_CONF"
  echo "Сгенерирован $LIVE_CONF из шаблона (первый запуск)."
fi

"$SCRIPT_DIR/stop_sandbox.sh" 2>/dev/null || true

# nfqws2 запускается СРАЗУ от имени nobody через runuser, не как root с
# собственным --user=nobody внутри себя (убран из шаблона). Живая
# диагностика VOICE_UDP-песочницы (strace, см. историю коммитов) нашла
# три независимых слоя одной и той же ошибки
# `nfq_create_queue(): Operation not permitted`:
#  1) nfqws2 БЕЗУСЛОВНО дропает себя до uid/gid 65534 при старте,
#     независимо от того, передан ли --user= в конфиге вообще -- если
#     стартовать его как root, он сам НЕОБРАТИМО падает до nobody ПОСЛЕ
#     захвата capabilities, но ДО реального создания очереди, так что
#     любой setcap на файле бесполезен, пока exec идёт от root: capset()
#     работает только внутри уже имеющегося набора, а root-эффект setcap
#     не даёт (root и так имеет все capabilities без всякого setcap).
#     Fix: exec сразу от nobody (см. runuser ниже) -- тогда файловые
#     capabilities реально применяются в момент execve().
#  2) Свой ПЕРВЫЙ (основной) внутренний capset() nfqws2 просит СРАЗУ
#     cap_setpcap+cap_net_admin+cap_net_raw (видимо чтобы потом самому
#     подрезать себе bounding set) -- без cap_setpcap в файловом гранте
#     этот capset падает с EPERM, nfqws2 уходит в упрощённый fallback,
#     который на практике НЕ оставляет процесс в рабочем для
#     nfq_create_queue() состоянии. Fix: setcap выше включает cap_setpcap
#     тоже, не только net_admin/net_raw.
#  3) Даже с (1)+(2) исправленными ошибка может остаться, если номер
#     очереди уже занят -- в т.ч. осиротевшим/незамеченным ПРЕДЫДУЩИМ
#     nfqws2-процессом песочницы (напр. после сбойного запуска, который
#     start_sandbox.sh посчитал неудачным из-за гонки с pidfile, а сам
#     nfqws2 на деле поднялся и продолжает жить, PPID=1). Ядро отвечает
#     на повторный bind именно EPERM, а не EBUSY -- проверяется через
#     `cat /proc/net/netfilter/nfnetlink_queue`. См. усиленную очистку в
#     stop_sandbox.sh ниже.
runuser -u nobody -- "$NFQWS2_BIN" "@$LIVE_CONF"
sleep 1

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "Песочный nfqws2 запущен (PID $(cat "$PIDFILE"), очередь $qnum)."
else
  echo "Не похоже, что процесс поднялся — смотри $SCRIPT_DIR/nfqws2_sandbox.debug.log" >&2
  exit 1
fi
