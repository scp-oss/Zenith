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
VOICE_BOT_USER="${VOICE_BOT_USER:-zenith-voice-bot}"
VOICE_UDP_PORTS="443,2053,2083,2087,2096,8443,50000:50099,1400,3478:3481,5349,19294:19344"
QUEUE_FILE="$SCRIPT_DIR/queue_num"

if [ -x "$SCRIPT_DIR/stop_sandbox.sh" ]; then
  "$SCRIPT_DIR/stop_sandbox.sh" || true
fi

if [ -f "$QUEUE_FILE" ]; then
  qnum="$(cat "$QUEUE_FILE")"
  for proto in tcp udp; do
    if iptables -t mangle -D OUTPUT -m owner --uid-owner "$SANDBOX_USER" -p "$proto" -j NFQUEUE --queue-num "$qnum" --queue-bypass 2>/dev/null; then
      echo "Правило для $proto ($SANDBOX_USER) снято (очередь $qnum)."
    else
      echo "Правило для $proto ($SANDBOX_USER) не найдено (уже снято?)."
    fi
  done
  if iptables -t mangle -D OUTPUT -m owner --uid-owner "$VOICE_BOT_USER" -p udp -m multiport --dports "$VOICE_UDP_PORTS" -j NFQUEUE --queue-num "$qnum" --queue-bypass 2>/dev/null; then
    echo "Правило для $VOICE_BOT_USER снято (очередь $qnum)."
  else
    echo "Правило для $VOICE_BOT_USER не найдено (уже снято?)."
  fi
  rm -f "$QUEUE_FILE"
else
  echo "Нет $QUEUE_FILE — не знаю, какой номер очереди снимать." >&2
  echo "Проверь и убери руками: iptables -t mangle -S | grep -E '$SANDBOX_USER|$VOICE_BOT_USER'" >&2
fi

for u in "$SANDBOX_USER" "$VOICE_BOT_USER"; do
  read -re -p "Удалить юзера $u? [y/N]: " ans
  case "$ans" in
    y|Y) userdel "$u" 2>/dev/null && echo "Юзер $u удалён." || echo "Не удалось удалить $u (не найден?)." ;;
    *) echo "Юзер $u оставлен." ;;
  esac
done
