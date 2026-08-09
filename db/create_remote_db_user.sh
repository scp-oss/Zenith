#!/usr/bin/env bash
# Заводит УРЕЗАННОГО MySQL-юзера для конкретной удалённой ноды (режим 3 --
# "только центральная БД", см. README "Прямое подключение ноды к
# центральной БД"). Один юзер = одна нода, привязан к её конкретному IP
# (CREATE USER '<name>'@'<ip>') -- утечка пароля с одной ноды не даёт
# доступа с других мест, и даже с этого же IP но не туда, куда думаешь.
# Требует, чтобы у ноды был СТАБИЛЬНЫЙ статический IP -- при смене IP
# нужно пересоздать юзера (или GRANT на новый IP, DROP старого).
#
# Права -- только то, что реально нужно orchestrator/db.py: SELECT/INSERT/
# UPDATE на рабочие таблицы. НЕ включает DROP/ALTER/CREATE/DELETE (истории
# не удаляют, только копят) и НЕ включает доступ к другим схемам вообще.
#
#   sudo ./create_remote_db_user.sh <имя_ноды> <IP_ноды> <провайдер>
#   sudo ./create_remote_db_user.sh vm-rostelecom 203.0.113.5 rostelecom
#
# Запускать НА центральном сервере (там, где сама БД), не на ноде.
set -euo pipefail

USAGE="Использование: $0 <имя_ноды> <IP_ноды> <провайдер>"
NODE_NAME="${1:?$USAGE}"
NODE_IP="${2:?$USAGE}"
NODE_PROVIDER="${3:?$USAGE}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ZENITH_DIR="$(dirname "$SCRIPT_DIR")"

# MySQL-совместимое имя юзера -- только [a-zA-Z0-9_], обрезано до 32 символов
DB_USER="zr_$(echo "$NODE_NAME" | tr -c 'a-zA-Z0-9_' '_' | cut -c1-28)"
PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"

if [ ! -f "$ZENITH_DIR/.env" ]; then
    echo "Не найден $ZENITH_DIR/.env -- запускай из установленного Zenith." >&2
    exit 1
fi
MYSQL_ROOT_PASSWORD="$(grep -E '^MYSQL_ROOT_PASSWORD=' "$ZENITH_DIR/.env" | tail -1 | cut -d= -f2-)"
MYSQL_DATABASE="$(grep -E '^MYSQL_DATABASE=' "$ZENITH_DIR/.env" | tail -1 | cut -d= -f2-)"
MYSQL_DATABASE="${MYSQL_DATABASE:-z2r_genome}"

SQL="
CREATE USER IF NOT EXISTS '${DB_USER}'@'${NODE_IP}' IDENTIFIED BY '${PASSWORD}';
ALTER USER '${DB_USER}'@'${NODE_IP}' IDENTIFIED BY '${PASSWORD}';
GRANT SELECT, INSERT, UPDATE ON ${MYSQL_DATABASE}.environments TO '${DB_USER}'@'${NODE_IP}';
GRANT SELECT, INSERT ON ${MYSQL_DATABASE}.domain_pool TO '${DB_USER}'@'${NODE_IP}';
GRANT SELECT, INSERT ON ${MYSQL_DATABASE}.genomes TO '${DB_USER}'@'${NODE_IP}';
GRANT SELECT, INSERT ON ${MYSQL_DATABASE}.experiments TO '${DB_USER}'@'${NODE_IP}';
GRANT SELECT, INSERT, UPDATE ON ${MYSQL_DATABASE}.genome_scores TO '${DB_USER}'@'${NODE_IP}';
GRANT SELECT, INSERT, UPDATE ON ${MYSQL_DATABASE}.operator_stats TO '${DB_USER}'@'${NODE_IP}';
GRANT SELECT, INSERT ON ${MYSQL_DATABASE}.ban_events TO '${DB_USER}'@'${NODE_IP}';
FLUSH PRIVILEGES;
"

cd "$ZENITH_DIR"
echo "$SQL" | docker compose exec -T mysql mysql -u root -p"$MYSQL_ROOT_PASSWORD"

# Автоопределение публичного IP этого сервера -- лучшее усилие, не
# критично: если недоступно (нет исходящего интернета до сервиса
# определения IP), просто оставляем плейсхолдер, оператор впишет сам.
PUBLIC_HOST="$(curl -fsSL --max-time 3 https://ifconfig.me 2>/dev/null || true)"
PUBLIC_HOST="${PUBLIC_HOST:-<публичный IP или домен этого сервера>}"

echo ""
echo "Готово для ноды \"$NODE_NAME\" (node_uuid тут не нужен -- это MySQL-юзер,"
echo "не HTTP-токен панели). На самой ноде -- z0r пункт 22, режим БД 3, вставь"
echo "блок ЦЕЛИКОМ (флеш-лефт, ниже маркеров, без изменений):"
echo "--- (копировать отсюда) ---"
echo "MYSQL_HOST=${PUBLIC_HOST}"
echo "MYSQL_PORT=3306"
echo "MYSQL_DATABASE=${MYSQL_DATABASE}"
echo "MYSQL_USER=${DB_USER}"
echo "MYSQL_PASSWORD=${PASSWORD}"
echo "ZENITH_ENVIRONMENT_NAME=${NODE_NAME}"
echo "ZENITH_ENVIRONMENT_PROVIDER=${NODE_PROVIDER}"
echo "--- (докопировать досюда) ---"
echo ""
echo "Пароль показан ОДИН раз, сохрани сейчас. Если MYSQL_HOST выше не"
echo "определился (плейсхолдер в угловых скобках) -- впиши публичный IP/домен"
echo "этого сервера сам перед вставкой на ноде. Не забудь также:"
echo "  1. MYSQL_BIND_HOST=0.0.0.0 в $ZENITH_DIR/.env + docker compose up -d (если ещё не сделано)"
echo "  2. sudo $SCRIPT_DIR/mysql_node_allowlist.sh add $NODE_IP"
