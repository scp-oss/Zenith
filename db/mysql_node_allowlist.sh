#!/usr/bin/env bash
# Ограничивает вход на порт MySQL (см. MYSQL_BIND_HOST=0.0.0.0 в
# docker-compose.yml) конкретными IP-адресами нод -- не всему интернету.
# В отличие от cloudflare_iptables.sh (публичный список диапазонов,
# перестраивается с нуля при каждом запуске) -- тут вручную курируемый
# список конкретных нод, поэтому add/remove/list, а не full-rebuild.
#
#   sudo ./mysql_node_allowlist.sh add <IP>      # разрешить ноду
#   sudo ./mysql_node_allowlist.sh remove <IP>   # убрать ноду
#   sudo ./mysql_node_allowlist.sh list          # показать текущий список
#
# Первый add сам ставит завершающий DROP на порт (всё, что не в allowlist,
# отбрасывается) -- порядок правил важен, ACCEPT для конкретных IP должны
# идти РАНЬШЕ финального DROP, поэтому add вставляет в начало (-I), а не
# в конец (-A).
set -euo pipefail

ACTION="${1:?Использование: $0 <add|remove|list> [IP]}"
PORT="${MYSQL_PORT:-3306}"
DROP_COMMENT="zenith-mysql-default-drop"

ensure_default_drop() {
    if ! iptables -C INPUT -p tcp --dport "$PORT" -m comment --comment "$DROP_COMMENT" -j DROP 2>/dev/null; then
        iptables -A INPUT -p tcp --dport "$PORT" -m comment --comment "$DROP_COMMENT" -j DROP
        echo "Поставлен финальный DROP на порт $PORT (всё, что не в allowlist, отбрасывается)."
    fi
}

case "$ACTION" in
    add)
        IP="${2:?Использование: $0 add <IP>}"
        ensure_default_drop
        if iptables -C INPUT -p tcp --dport "$PORT" -s "$IP" -j ACCEPT 2>/dev/null; then
            echo "$IP уже в allowlist порта $PORT."
        else
            iptables -I INPUT -p tcp --dport "$PORT" -s "$IP" -j ACCEPT
            echo "Добавлено: $IP -> порт $PORT."
        fi
        ;;
    remove)
        IP="${2:?Использование: $0 remove <IP>}"
        iptables -D INPUT -p tcp --dport "$PORT" -s "$IP" -j ACCEPT 2>/dev/null \
            && echo "Убрано: $IP." \
            || echo "$IP не было в allowlist."
        ;;
    list)
        echo "Текущие правила порта $PORT:"
        iptables -L INPUT -n --line-numbers | grep -E "dpt:$PORT" || echo "(пусто)"
        ;;
    *)
        echo "Использование: $0 <add|remove|list> [IP]" >&2
        exit 1
        ;;
esac

echo ""
echo "Не забудь сохранить правила, иначе слетят при ребуте:"
echo "  sudo netfilter-persistent save   # если установлен iptables-persistent"
