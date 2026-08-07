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
#
# После выполнения ОБЯЗАТЕЛЬНО сверить глазами:
#   iptables -t mangle -S | grep zenith-sandbox
# — правило должно быть ровно одно, узкое, с --queue-bypass.
#
# Откат: ./teardown_sandbox.sh

set -euo pipefail

if [ "$(id -u)" != "0" ]; then
  echo "Нужен root." >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SANDBOX_USER="${SANDBOX_USER:-zenith-sandbox}"
SANDBOX_QUEUE_START="${SANDBOX_QUEUE_START:-210}"
QUEUE_FILE="$SCRIPT_DIR/queue_num"

# --- 1. юзер ---
if ! id "$SANDBOX_USER" >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin "$SANDBOX_USER"
  echo "Создан системный юзер $SANDBOX_USER (без логина, без домашней папки)."
else
  echo "Юзер $SANDBOX_USER уже есть, использую существующего."
fi

# --- 2. свободный номер очереди ---
used_queues="$(iptables -t mangle -S 2>/dev/null | grep -oE 'queue-num [0-9]+' | awk '{print $2}')"
qnum="$SANDBOX_QUEUE_START"
while echo "$used_queues" | grep -qx "$qnum"; do
  qnum=$((qnum + 1))
done
echo "Свободный номер очереди: $qnum"

# --- 3. правила (TCP + UDP, один и тот же номер очереди) ---
for proto in tcp udp; do
  if iptables -t mangle -C OUTPUT -m owner --uid-owner "$SANDBOX_USER" -p "$proto" -j NFQUEUE --queue-num "$qnum" --queue-bypass 2>/dev/null; then
    echo "Правило для $proto уже стоит (и уже с этим номером очереди), пропускаю добавление."
  else
    iptables -t mangle -A OUTPUT -m owner --uid-owner "$SANDBOX_USER" -p "$proto" -j NFQUEUE --queue-num "$qnum" --queue-bypass
    echo "Добавлено правило: $proto-трафик от $SANDBOX_USER -> NFQUEUE $qnum (queue-bypass)."
  fi
done

echo "$qnum" > "$QUEUE_FILE"

echo ""
echo "=== Готово. Проверь глазами перед тем как доверять: ==="
echo "  iptables -t mangle -S | grep $SANDBOX_USER"
echo ""
echo "Номер очереди сохранён в $QUEUE_FILE — его читают start_sandbox.sh"
echo "и (позже) сам оркестратор."
echo ""
echo "Откат: $SCRIPT_DIR/teardown_sandbox.sh"
