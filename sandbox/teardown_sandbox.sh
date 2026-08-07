#!/usr/bin/env bash
# teardown_sandbox.sh — снимает РОВНО то, что поставил setup_sandbox.sh
# (правило iptables + опционально юзера). Останавливает песочный nfqws2
# первым делом, если он ещё работает. Ничего боевого не трогает.

set -euo pipefail

if [ "$(id -u)" != "0" ]; then
  echo "Нужен root." >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SANDBOX_USER="${SANDBOX_USER:-zenith-sandbox}"
QUEUE_FILE="$SCRIPT_DIR/queue_num"

if [ -x "$SCRIPT_DIR/stop_sandbox.sh" ]; then
  "$SCRIPT_DIR/stop_sandbox.sh" || true
fi

if [ -f "$QUEUE_FILE" ]; then
  qnum="$(cat "$QUEUE_FILE")"
  for proto in tcp udp; do
    if iptables -t mangle -D OUTPUT -m owner --uid-owner "$SANDBOX_USER" -p "$proto" -j NFQUEUE --queue-num "$qnum" --queue-bypass 2>/dev/null; then
      echo "Правило для $proto снято (очередь $qnum)."
    else
      echo "Правило для $proto не найдено (уже снято?)."
    fi
  done
  rm -f "$QUEUE_FILE"
else
  echo "Нет $QUEUE_FILE — не знаю, какой номер очереди снимать." >&2
  echo "Проверь и убери руками: iptables -t mangle -S | grep $SANDBOX_USER" >&2
fi

read -re -p "Удалить юзера $SANDBOX_USER? [y/N]: " ans
case "$ans" in
  y|Y) userdel "$SANDBOX_USER" 2>/dev/null && echo "Юзер удалён." || echo "Не удалось удалить (не найден?)." ;;
  *) echo "Юзер оставлен." ;;
esac
