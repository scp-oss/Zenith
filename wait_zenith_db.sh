#!/bin/bash
# ExecStartPre для zenith-autorun / zenith-promoter: после отключения света Zenith стартовал раньше
# своей MySQL (контейнер zenith-mysql), первый прогон падал с "Can't connect to MySQL" и следующий
# был только через 4 ч. Ждём, пока контейнер станет healthy (до 5 мин).
# На нодах с ZENITH_DB_MODE=api локальной БД нет — контейнера zenith-mysql нет, ждать нечего.
C=${ZENITH_DB_CONTAINER:-zenith-mysql}
command -v docker >/dev/null 2>&1 || exit 0
docker inspect "$C" >/dev/null 2>&1 || exit 0
for i in $(seq 1 150); do
  [ "$(docker inspect -f "{{.State.Health.Status}}" "$C" 2>/dev/null)" = healthy ] && exit 0
  sleep 2
done
echo "$C не стал healthy за 5 мин" >&2
exit 1
