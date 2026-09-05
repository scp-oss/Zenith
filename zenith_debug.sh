#!/usr/bin/env bash
# zenith_debug.sh -- один отчёт по здоровью Zenith вместо десятка ручных
# команд (systemctl/journalctl/git/SQL/статус песочницы), которые до сих
# пор гонялись по одной за раз при каждой диагностике "почему не
# создаются новые геномы / не продвигается стратегия" (см. историю
# инцидентов в CLAUDE.md z2r_autobench/Zenith -- почти каждый такой
# инцидент упирался в один из разделов ниже: не тот git-коммит,
# незамеченный упавший systemd-юнит, песочница не поднялась, DB-запись
# молча не доходит).
#
# Полностью read-only -- ничего не перезапускает, не применяет геномы,
# не трогает /opt/zapret2. Безопасно гонять когда угодно, в т.ч. в
# бою.
#
# Запуск:
#   sudo bash zenith_debug.sh
# (root нужен только для systemctl/journalctl некоторых юнитов и чтения
# nfqws2_sandbox.pid/debug.log, если они не мировые; без root часть
# разделов просто напечатает "нет доступа" вместо падения всего отчёта.)

set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ZENITH_DIR="${ZENITH_DIR:-$SCRIPT_DIR}"
cd "$ZENITH_DIR" || exit 1

_hr() { printf '%s\n' "----------------------------------------------------------------"; }
_section() { echo; _hr; echo "== $1 =="; _hr; }

_zenith_env_get() {
  local key="$1" file="$ZENITH_DIR/.env"
  [ -f "$file" ] || return 0
  grep -E "^${key}=" "$file" 2>/dev/null | tail -1 | cut -d= -f2-
}

# ---------------------------------------------------------------------
_section "Репозиторий"
git_dir_opt=(-c safe.directory="$ZENITH_DIR")
echo "Каталог: $ZENITH_DIR"
echo "Ветка:   $(git "${git_dir_opt[@]}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
echo "Коммит:  $(git "${git_dir_opt[@]}" rev-parse --short HEAD 2>/dev/null || echo '?')"
dirty="$(git "${git_dir_opt[@]}" status --short 2>/dev/null)"
if [ -n "$dirty" ]; then
  echo "Незакоммиченные изменения:"
  echo "$dirty" | sed 's/^/  /' | head -20
else
  echo "Рабочая копия чистая."
fi
if git "${git_dir_opt[@]}" fetch --quiet origin main 2>/dev/null; then
  behind="$(git "${git_dir_opt[@]}" rev-list --count HEAD..origin/main 2>/dev/null || echo '?')"
  if [ "$behind" = "0" ]; then
    echo "origin/main: актуально."
  else
    echo "origin/main: отстаём на $behind коммит(ов) -- git pull origin main."
  fi
else
  echo "origin/main: не удалось fetch (сеть/доступ) -- пропуск."
fi

# ---------------------------------------------------------------------
_section "Окружение (.env / config.py)"
db_mode="$(_zenith_env_get ZENITH_DB_MODE)"; db_mode="${db_mode:-docker}"
env_name="$(_zenith_env_get ZENITH_ENVIRONMENT_NAME)"; env_name="${env_name:-prod-domru}"
echo "ZENITH_DB_MODE=$db_mode"
echo "ZENITH_PROFILES=$(_zenith_env_get ZENITH_PROFILES || true) (пусто = все 4 дефолтных)"
echo "PANEL_URL=$(_zenith_env_get PANEL_URL || true)"
if [ -z "$(_zenith_env_get ZENITH_ENVIRONMENT_NAME)" ]; then
  echo "!!! ZENITH_ENVIRONMENT_NAME не задан в .env -- используется дефолт '$env_name' (см. config.py)."
else
  echo "ZENITH_ENVIRONMENT_NAME=$env_name"
fi

VENV_PYTHON="$ZENITH_DIR/orchestrator/venv/bin/python3"
if [ -x "$VENV_PYTHON" ]; then
  ( cd "$ZENITH_DIR/orchestrator" && "$VENV_PYTHON" -c '
import config
print("Z2R_BASE=" + config.Z2R_BASE)
print("ZAPRET2_CONFIG_PATH=" + config.ZAPRET2_CONFIG_PATH)
print("SANDBOX_USER=" + config.SANDBOX_USER)
' 2>/dev/null )
else
  echo "venv не найден: $VENV_PYTHON -- пропуск проверки config.py."
fi

# ---------------------------------------------------------------------
_section "systemd: zenith-autorun / zenith-promoter"
for unit in zenith-autorun.service zenith-promoter.service; do
  if systemctl list-unit-files "$unit" >/dev/null 2>&1; then
    state="$(systemctl is-active "$unit" 2>/dev/null || true)"
    enabled="$(systemctl is-enabled "$unit" 2>/dev/null || true)"
    echo "$unit: active=$state enabled=$enabled"
    if [ "$state" != "active" ]; then
      echo "  !!! юнит не active -- последние строки журнала:"
    fi
    journalctl -u "$unit" -n 8 --no-pager 2>/dev/null | sed 's/^/  /'
  else
    echo "$unit: юнит не найден (не установлен?)"
  fi
  echo
done

# ---------------------------------------------------------------------
_section "zapret2.service (боевой, не песочница)"
if systemctl list-unit-files zapret2.service >/dev/null 2>&1; then
  echo "active=$(systemctl is-active zapret2.service 2>/dev/null || true)"
else
  echo "юнит zapret2.service не найден -- z2r_autobench не установлен рядом?"
fi

# ---------------------------------------------------------------------
_section "Песочница (sandbox/)"
PIDFILE="/tmp/zenith_nfqws2_sandbox.pid"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null; then
  echo "nfqws2 (песочница): запущен, PID $(cat "$PIDFILE")"
else
  echo "nfqws2 (песочница): НЕ запущен ($PIDFILE отсутствует или процесс мёртв)"
  echo "  -> запусти вручную: sudo $ZENITH_DIR/sandbox/start_sandbox.sh"
fi
if [ -f "$ZENITH_DIR/sandbox/queue_num" ]; then
  echo "queue_num: $(cat "$ZENITH_DIR/sandbox/queue_num" 2>/dev/null)"
else
  echo "queue_num: нет файла -- setup_sandbox.sh ещё ни разу не запускался"
fi
if [ -f "$ZENITH_DIR/sandbox/nfqws2_sandbox.conf" ]; then
  echo "nfqws2_sandbox.conf: есть, изменён $(stat -c '%y' "$ZENITH_DIR/sandbox/nfqws2_sandbox.conf" 2>/dev/null | cut -d. -f1)"
else
  echo "nfqws2_sandbox.conf: нет -- будет сгенерирован из шаблона при следующем start_sandbox.sh"
fi
if [ -f "$ZENITH_DIR/sandbox/nfqws2_sandbox.debug.log" ]; then
  echo "Последние строки nfqws2_sandbox.debug.log:"
  tail -n 12 "$ZENITH_DIR/sandbox/nfqws2_sandbox.debug.log" 2>/dev/null | sed 's/^/  /'
fi

# ---------------------------------------------------------------------
_section "z2r_test-voice-bot (порт 8765, /probe)"
if command -v ss >/dev/null 2>&1; then
  if ss -ltn 2>/dev/null | grep -q ':8765[[:space:]]'; then
    echo "порт 8765 слушается."
  else
    echo "!!! порт 8765 НЕ слушается -- voice-бот не запущен (или слушает другой порт)."
  fi
else
  echo "ss недоступен -- пропуск проверки порта."
fi

# ---------------------------------------------------------------------
_section "БД (z2r_genome), окружение '$env_name'"
if [ "$db_mode" = "docker" ]; then
  mysql_pw="$(_zenith_env_get MYSQL_PASSWORD)"
  mysql_user="$(_zenith_env_get MYSQL_USER)"; mysql_user="${mysql_user:-zenith}"
  mysql_db="$(_zenith_env_get MYSQL_DATABASE)"; mysql_db="${mysql_db:-z2r_genome}"
  env_esc="${env_name//\'/\'\'}"
  if command -v docker >/dev/null 2>&1 && docker compose exec -T mysql true >/dev/null 2>&1; then
    echo "Геномы и продвижение по профилям:"
    docker compose exec -T -e MYSQL_PWD="$mysql_pw" mysql mysql -u"$mysql_user" "$mysql_db" -e "
      SELECT g.profile,
             COUNT(*) AS genomes,
             SUM(gs.promoted_strategy IS NOT NULL) AS promoted,
             MAX(gs.updated_at) AS last_score_update
      FROM genome_scores gs
      JOIN genomes g ON g.id = gs.genome_id
      JOIN environments e ON e.id = gs.environment_id
      WHERE e.name = '${env_esc}'
      GROUP BY g.profile;
    " 2>&1 | sed 's/^/  /'
    echo
    echo "Тесты за последние 24ч по профилям (растёт ли счётчик = крутится ли генерация):"
    docker compose exec -T -e MYSQL_PWD="$mysql_pw" mysql mysql -u"$mysql_user" "$mysql_db" -e "
      SELECT g.profile,
             COUNT(*) AS tests_24h,
             SUM(ex.success) AS ok_24h,
             MAX(ex.tested_at) AS last_test
      FROM experiments ex
      JOIN genomes g ON g.id = ex.genome_id
      JOIN environments e ON e.id = ex.environment_id
      WHERE e.name = '${env_esc}' AND ex.tested_at > NOW() - INTERVAL 1 DAY
      GROUP BY g.profile;
    " 2>&1 | sed 's/^/  /'
  else
    echo "docker compose / контейнер mysql недоступен из $ZENITH_DIR -- пропуск (запускай из каталога с docker-compose.yml)."
  fi
else
  echo "ZENITH_DB_MODE=$db_mode -- локальной MySQL нет на этой ноде, пропуск (api-режим пишет прямо на панель)."
fi

echo
_hr
echo "Готово. Строки с '!!!' -- то, что стоит проверить в первую очередь."
