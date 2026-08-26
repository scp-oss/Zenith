#!/usr/bin/env bash
# zenith_autorun.sh -- периодический автозапуск orchestrator/main.py,
# НЕЗАВИСИМО от z0r-panel (панель опциональна, см. CLAUDE.md
# z2r_autobench: "панель это модуль... функционал должен быть в CLI и
# без панели"). Если панель установлена, её карточка "Периодический
# автозапуск" на /controls -- ТОЛЬКО пульт (start/stop/log) над
# systemd-юнитом zenith-autorun.service, который запускает этот же
# скрипт; вся логика здесь.
#
# По кругу перебирает профили из $PROFILES, по одному за срабатывание
# (не все сразу -- см. CLAUDE.md "Ban/rate-limit avoidance": плотный
# поток неудачных хендшейков без разбора рискует эскалацией инспекции у
# DPI-мидлбокса). Между срабатываниями -- $INTERVAL_MINUTES (дефолт
# нарочно редкий, часы, не минуты).
#
# Настройки через переменные окружения (см. zenith-autorun.service):
#   ZENITH_AUTORUN_INTERVAL_MINUTES=240
#   ZENITH_AUTORUN_ROUNDS=20
# Какие профили перебирать -- через .env (ZENITH_PROFILES=YT_TLS,DS_TLS),
# не через окружение -- см. z0r 22 -> 4 -> "профили".
#
# Запуск (напрямую, для отладки):
#   ZENITH_DIR=/opt/z2r_autobench/Zenith bash zenith_autorun.sh
set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ZENITH_DIR="${ZENITH_DIR:-$SCRIPT_DIR}"
VENV_PYTHON="$ZENITH_DIR/orchestrator/venv/bin/python3"

# Ровно те 4 профиля, для которых у orchestrator/genome.py есть проверенный
# PROFILE_FILTERS (см. её докстринг) -- совпадает с promote.py
# --profile choices и z0r-panel main.py::RUNNABLE_PROFILES.
DEFAULT_PROFILES=(YT_TLS RKN_TLS DS_TLS VOICE_UDP)

# Общий .env-ридер (bash-скрипт, своего .env-loader нет -- та же простая
# grep/cut-схема, что уже была для ZENITH_PROFILES).
_zenith_env_get() {
  local key="$1" file="$ZENITH_DIR/.env"
  [ -f "$file" ] || return 0
  grep -E "^${key}=" "$file" 2>/dev/null | tail -1 | cut -d= -f2-
}

# ZENITH_PROFILES в .env (та же переменная, что читает config.py в Python-
# части, см. auto_promoter.py) -- сузить автономный режим до подмножества
# профилей вместо всех 4. Ставится через z0r (22 -> 4 -> "профили"), не
# руками. Пусто/не задано -- все 4, как раньше.
_selected_profiles="$(_zenith_env_get ZENITH_PROFILES)"
if [ -n "$_selected_profiles" ]; then
  IFS=',' read -ra PROFILES <<< "$_selected_profiles"
else
  PROFILES=("${DEFAULT_PROFILES[@]}")
fi
INTERVAL_MINUTES="${ZENITH_AUTORUN_INTERVAL_MINUTES:-240}"
ROUNDS="${ZENITH_AUTORUN_ROUNDS:-20}"

# Синк с панелью после каждого прогона -- ТОЛЬКО для hub-and-spoke режима
# (ZENITH_DB_MODE=docker + PANEL_URL задан, см. README "Веб-панель и
# мульти-провайдерный sync"): изолированной ноде (без PANEL_URL) синкать
# нечего и некуда, а api-режиму (нет своей БД вообще, db.py уже пишет
# прямо на панель по HTTP на каждый вызов) синк тоже не нужен -- локальной
# БД, из которой экспортировать snapshot, там просто нет.
# Живой случай 2026-08-24 на miha (МТС, hub-and-spoke): main.py честно
# гонял раунды и писал геномы в локальную БД несколько дней подряд, но
# README-документированный шаг "после main.py шлёт sync_client.py push"
# был описан только как ручной workflow -- этот скрипт (единственное, что
# реально крутится по расписанию, см. zenith-autorun.service) его никогда
# не вызывал. Итог: панель показывала 0 геномов для ноды при полностью
# рабочей локальной генерации -- ничего никогда не отправлялось.
_db_mode="$(_zenith_env_get ZENITH_DB_MODE)"
_panel_url="$(_zenith_env_get PANEL_URL)"
SYNC_ENABLED=0
if [ "${_db_mode:-docker}" = "docker" ] && [ -n "$_panel_url" ]; then
  SYNC_ENABLED=1
fi

if [ ! -x "$VENV_PYTHON" ]; then
  echo "venv не найден: $VENV_PYTHON -- сначала настрой orchestrator (см. README)." >&2
  exit 1
fi

idx=0
while true; do
  profile="${PROFILES[$((idx % ${#PROFILES[@]}))]}"
  idx=$((idx + 1))
  echo "[$(date -Iseconds)] запускаю $profile, $ROUNDS раундов"
  ( cd "$ZENITH_DIR/orchestrator" && "$VENV_PYTHON" main.py --profile "$profile" --rounds "$ROUNDS" )
  if [ "$SYNC_ENABLED" = "1" ]; then
    echo "[$(date -Iseconds)] синкаю $profile с панелью..."
    if ! ( cd "$ZENITH_DIR/orchestrator" && "$VENV_PYTHON" sync_client.py push --profile "$profile" ); then
      echo "[$(date -Iseconds)] sync_client.py push для $profile не удался -- см. вывод выше, панель ноду тут не увидит до следующего успешного синка." >&2
    fi
  fi
  echo "[$(date -Iseconds)] $profile завершён, следующий через ${INTERVAL_MINUTES}м"
  sleep "$((INTERVAL_MINUTES * 60))"
done
