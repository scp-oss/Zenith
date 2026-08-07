#!/usr/bin/env bash
# setup_sandbox.sh — готовит изолированный путь для тестирования геномов
# Zenith, НЕ трогая боевой /opt/zapret2. Одноразовая настройка (запускать
# руками, не автоматически):
#
#   1. Системный юзер $SANDBOX_USER (по умолчанию zenith-sandbox), без
#      логина, без домашней папки — только для того, чтобы его исходящий
#      TCP-трафик можно было адресно поймать одним узким iptables-правилом.
#      nfqws2 песочницы по-прежнему стартует от root (нужен CAP_NET_ADMIN
#      для NFQUEUE) — это разные вещи, юзер тут не про привилегии nfqws2,
#      а про точность матчинга трафика.
#   2. Свободный номер NFQUEUE — сканирует уже занятые в
#      `iptables -t mangle -S` и берёт первый свободный от
#      $SANDBOX_QUEUE_START, а не угадывает вслепую.
#   3. ДВА правила, TCP и UDP (для VOICE_UDP/YT_QUIC_UDP-профилей), на ОДИН
#      и тот же номер очереди -- один nfqws2 обрабатывает оба протокола
#      сразу, различая их через --filter-tcp=/--filter-udp= в самом
#      конфиге, отдельная очередь не нужна.
#      -m owner --uid-owner $SANDBOX_USER -j NFQUEUE --queue-num <N>
#      --queue-bypass. Никакие существующие правила не трогает и не
#      удаляет. --queue-bypass — как и в боевом zapret2: если
#      nfqws2-песочница не запущена/упала, трафик просто идёт как есть.
#   4. ОТДЕЛЬНЫЙ узкий юзер $VOICE_BOT_USER для z2r_test-voice-bot --
#      НЕ тот же $SANDBOX_USER. Живой инцидент 2026-08-07: у бота есть
#      свой обычный TCP-трафик, не связанный с тестированием (Discord
#      gateway/API login), и он ЗАВИСАЛ, будучи пойман тем же широким
#      TCP-правилом -- nfqws2 пытается реассемблировать TLS ClientHello
#      даже при "no lua functions in this profile" (нет ни одного
#      --filter-tcp= в конфиге на тот момент), и в этом no-op режиме
#      реассемблинг с replay иногда дропает исходный пакет вместо
#      чистого пропуска. Правило для VOICE_BOT_USER матчит ТОЛЬКО
#      конкретные UDP-порты голосового профиля (genome.PROFILE_FILTERS
#      ["VOICE_UDP"]) -- обычный HTTPS-логин бота их не касается вообще,
#      уходит нетронутым мимо любой песочницы.
#
# После выполнения ОБЯЗАТЕЛЬНО сверить глазами:
#   iptables -t mangle -S | grep -E "zenith-sandbox|zenith-voice-bot"
# — по одному TCP+UDP правилу на zenith-sandbox, одному узкому UDP на
# zenith-voice-bot, все с --queue-bypass.
#
# Откат: ./teardown_sandbox.sh

set -euo pipefail

if [ "$(id -u)" != "0" ]; then
  echo "Нужен root." >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SANDBOX_USER="${SANDBOX_USER:-zenith-sandbox}"
VOICE_BOT_USER="${VOICE_BOT_USER:-zenith-voice-bot}"
SANDBOX_QUEUE_START="${SANDBOX_QUEUE_START:-210}"
QUEUE_FILE="$SCRIPT_DIR/queue_num"

# Тот же список портов, что genome.PROFILE_FILTERS["VOICE_UDP"] в
# orchestrator/genome.py (--filter-udp=...) -- сверено построчно с
# /opt/zapret2/config, но тут через ':' для iptables --dports вместо '-'.
VOICE_UDP_PORTS="443,2053,2083,2087,2096,8443,50000:50099,1400,3478:3481,5349,19294:19344"

# --- 1. юзеры ---
for u in "$SANDBOX_USER" "$VOICE_BOT_USER"; do
  if ! id "$u" >/dev/null 2>&1; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$u"
    echo "Создан системный юзер $u (без логина, без домашней папки)."
  else
    echo "Юзер $u уже есть, использую существующего."
  fi
done

# --- 2. свободный номер очереди ---
used_queues="$(iptables -t mangle -S 2>/dev/null | grep -oE 'queue-num [0-9]+' | awk '{print $2}')"
qnum="$SANDBOX_QUEUE_START"
while echo "$used_queues" | grep -qx "$qnum"; do
  qnum=$((qnum + 1))
done
echo "Свободный номер очереди: $qnum"

# --- 3. правила (TCP + UDP, один и тот же номер очереди) для SANDBOX_USER ---
for proto in tcp udp; do
  if iptables -t mangle -C OUTPUT -m owner --uid-owner "$SANDBOX_USER" -p "$proto" -j NFQUEUE --queue-num "$qnum" --queue-bypass 2>/dev/null; then
    echo "Правило для $proto уже стоит (и уже с этим номером очереди), пропускаю добавление."
  else
    iptables -t mangle -A OUTPUT -m owner --uid-owner "$SANDBOX_USER" -p "$proto" -j NFQUEUE --queue-num "$qnum" --queue-bypass
    echo "Добавлено правило: $proto-трафик от $SANDBOX_USER -> NFQUEUE $qnum (queue-bypass)."
  fi
done

# --- 4. узкое UDP-правило для VOICE_BOT_USER -- только голосовые порты,
# НЕ весь TCP/UDP (см. докстринг: обычный TCP-трафик бота, попав в
# песочницу без --filter-tcp=, у nfqws2 вис). Та же очередь -- один
# nfqws2 всё равно обрабатывает всё, что к нему приходит.
if iptables -t mangle -C OUTPUT -m owner --uid-owner "$VOICE_BOT_USER" -p udp -m multiport --dports "$VOICE_UDP_PORTS" -j NFQUEUE --queue-num "$qnum" --queue-bypass 2>/dev/null; then
  echo "Правило для $VOICE_BOT_USER уже стоит, пропускаю добавление."
else
  iptables -t mangle -A OUTPUT -m owner --uid-owner "$VOICE_BOT_USER" -p udp -m multiport --dports "$VOICE_UDP_PORTS" -j NFQUEUE --queue-num "$qnum" --queue-bypass
  echo "Добавлено правило: UDP-трафик от $VOICE_BOT_USER на голосовые порты -> NFQUEUE $qnum (queue-bypass)."
fi

echo "$qnum" > "$QUEUE_FILE"

echo ""
echo "=== Готово. Проверь глазами перед тем как доверять: ==="
echo "  iptables -t mangle -S | grep -E '$SANDBOX_USER|$VOICE_BOT_USER'"
echo ""
echo "Номер очереди сохранён в $QUEUE_FILE — его читают start_sandbox.sh"
echo "и (позже) сам оркестратор."
echo ""
echo "Откат: $SCRIPT_DIR/teardown_sandbox.sh"
