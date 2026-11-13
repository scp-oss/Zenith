#!/usr/bin/env bash
# Идемпотентно восстанавливает iptables-правила, которые заворачивают трафик
# юзеров песочницы в её NFQUEUE (те же правила, что ставит setup_sandbox.sh,
# с тем же номером очереди из sandbox/queue_num). Вызывается из
# start_sandbox.sh на каждый запуск.
#
# Живой случай NETH-4 2026-11-13: правила из setup_sandbox.sh (2026-09-05)
# бесследно пропали из ip mangle OUTPUT, а песочный nfqws2 продолжал
# запускаться на пустой очереди 214. Ни одной ошибки нигде -- curl от
# zenith-sandbox просто шёл мимо песочницы через боевой zapret2, т.е.
# КАЖДЫЙ тест генома на самом деле мерил боевую стратегию (RKN/DS ~100%
# "успеха" у любого генома). Без этой проверки такая поломка не видна.
set -uo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
QUEUE_FILE="$SCRIPT_DIR/queue_num"
SANDBOX_USER="${SANDBOX_USER:-zenith-sandbox}"
VOICE_BOT_USER="${VOICE_BOT_USER:-zenith-voice-bot}"
VOICE_UDP_PORTS="443,2053,2083,2087,2096,8443,50000:50099,1400,3478:3481,5349,19294:19344"

[ -f "$QUEUE_FILE" ] || { echo "ensure_redirect: нет $QUEUE_FILE -- нужен setup_sandbox.sh" >&2; exit 1; }
qnum="$(cat "$QUEUE_FILE")"
added=0
for proto in tcp udp; do
  if ! iptables -t mangle -C OUTPUT -m owner --uid-owner "$SANDBOX_USER" -p "$proto" -j NFQUEUE --queue-num "$qnum" --queue-bypass 2>/dev/null; then
    iptables -t mangle -A OUTPUT -m owner --uid-owner "$SANDBOX_USER" -p "$proto" -j NFQUEUE --queue-num "$qnum" --queue-bypass && added=$((added+1))
  fi
done
if id "$VOICE_BOT_USER" >/dev/null 2>&1 && ! iptables -t mangle -C OUTPUT -m owner --uid-owner "$VOICE_BOT_USER" -p udp -m multiport --dports "$VOICE_UDP_PORTS" -j NFQUEUE --queue-num "$qnum" --queue-bypass 2>/dev/null; then
  iptables -t mangle -A OUTPUT -m owner --uid-owner "$VOICE_BOT_USER" -p udp -m multiport --dports "$VOICE_UDP_PORTS" -j NFQUEUE --queue-num "$qnum" --queue-bypass && added=$((added+1))
fi
[ "$added" -gt 0 ] && echo "!!! ensure_redirect: восстановлено $added правил(а) песочницы -> NFQUEUE $qnum (они пропадали -- тесты до этого шли мимо песочницы)" >&2
exit 0
