import os
import sys


def _load_env(path):
    env = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


ZENITH_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SANDBOX_DIR = os.path.join(ZENITH_DIR, "sandbox")
_ENV = _load_env(os.path.join(ZENITH_DIR, ".env"))

# docker (локальная БД, своя или буфер для hub-and-spoke) | api (своей БД
# нет вообще, каждый вызов db.py -- HTTP-запрос к панели, см. db.py/
# db_api.py). Раньше третьим значением было "external" (прямое MySQL-
# соединение к центральному серверу без своей БД) -- убрано, сырой MySQL
# наружу больше не открывается ни для одной ноды, см. Zenith README "Два
# режима БД" и z0r-panel db/schema.sql.
ZENITH_DB_MODE = os.environ.get("ZENITH_DB_MODE", _ENV.get("ZENITH_DB_MODE", "docker"))

MYSQL_HOST = os.environ.get("MYSQL_HOST", _ENV.get("MYSQL_HOST", "127.0.0.1"))
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", _ENV.get("MYSQL_PORT", "3306")))
MYSQL_USER = os.environ.get("MYSQL_USER", _ENV.get("MYSQL_USER", "zenith"))
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", _ENV.get("MYSQL_PASSWORD", ""))
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", _ENV.get("MYSQL_DATABASE", "z2r_genome"))

SANDBOX_USER = os.environ.get("SANDBOX_USER", "zenith-sandbox")

# Дефолт для --environment/--provider во всех CLI-скриптах (main.py,
# bootstrap.py, sync_client.py, compare_control.py, promote.py) -- раньше
# был захардкожен буквально как "prod-domru"/"domru" в каждом argparse,
# так что на ноде другого провайдера ЛЕГКО забыть передать флаги явно --
# и данные молча запишутся под именем "домру", хотя это уже другая нода.
# Теперь дефолт читается из .env (той же переменной, что видит панель) --
# один раз выставил ZENITH_ENVIRONMENT_NAME/PROVIDER на конкретной ноде,
# дальше можно просто не думать про эти флаги на каждый запуск.
LOCAL_ENVIRONMENT_NAME_IS_DEFAULT = "ZENITH_ENVIRONMENT_NAME" not in os.environ and "ZENITH_ENVIRONMENT_NAME" not in _ENV
LOCAL_ENVIRONMENT_NAME = os.environ.get("ZENITH_ENVIRONMENT_NAME", _ENV.get("ZENITH_ENVIRONMENT_NAME", "prod-domru"))
LOCAL_ENVIRONMENT_PROVIDER = os.environ.get("ZENITH_ENVIRONMENT_PROVIDER", _ENV.get("ZENITH_ENVIRONMENT_PROVIDER", "domru"))

if LOCAL_ENVIRONMENT_NAME_IS_DEFAULT:
    # Громкое предупреждение, не тихий дефолт -- забытый на новом сервере
    # (напр. МТС) ZENITH_ENVIRONMENT_NAME означает, что ЛЮБОЙ прогон molча
    # запишет/прочитает результаты под тем же environment_id, что и
    # реальный боевой домру -- смешивая UCB-статистику и, что хуже,
    # пул кандидатов для автопродвижения (auto_promoter.py) между
    # СОВЕРШЕННО разными сетями. Найдено при аудите перед деплоем на МТС
    # 2026-08-17. Печатается при каждом импорте -- намеренно, дешёвая
    # разовая проверка, не спам (см. CLAUDE.md z2r_autobench "Publishing
    # hygiene" -- сюда сервер по имени/провайдеру НЕ попадает, только сам
    # факт, что переменная не задана).
    print(
        "!!! ZENITH_ENVIRONMENT_NAME не задан ни в окружении, ни в .env -- "
        f"использую дефолт '{LOCAL_ENVIRONMENT_NAME}'/'{LOCAL_ENVIRONMENT_PROVIDER}'. "
        "Если это НЕ тот сервер, для которого эти значения верны (напр. новый провайдер) -- "
        "результаты смешаются с чужим окружением. Выстави ZENITH_ENVIRONMENT_NAME/"
        "ZENITH_ENVIRONMENT_PROVIDER в .env.",
        file=sys.stderr,
    )

# Для sync_client.py (удалённые ноды -> панель на боевом сервере, см.
# z0r-panel/README.md). Пусто на самой панели/локальной ноде -- sync_client.py
# там не нужен, панель и так пишет в эту же БД напрямую.
PANEL_URL = os.environ.get("PANEL_URL", _ENV.get("PANEL_URL", ""))
PANEL_NODE_TOKEN = os.environ.get("PANEL_NODE_TOKEN", _ENV.get("PANEL_NODE_TOKEN", ""))

# Для auto_promoter.py -- ТОЛЬКО этот скрипт из всего orchestrator/ трогает
# что-то за пределами БД+песочницы (см. его докстринг), остальным Zenith
# нет дела до z2r_autobench вообще. Дефолт -- сосед по INSTALL_DIR, см.
# z2r_autobench/z0r::ZENITH_DIR="$INSTALL_DIR/Zenith" (тот же паттерн, что
# z0r-panel/config.py::Z2R_AUTOBENCH_DIR).
Z2R_AUTOBENCH_DIR = os.environ.get("Z2R_AUTOBENCH_DIR", _ENV.get("Z2R_AUTOBENCH_DIR", os.path.dirname(ZENITH_DIR)))
ZAPRET2_CONFIG_PATH = os.environ.get("ZAPRET2_CONFIG_PATH", _ENV.get("ZAPRET2_CONFIG_PATH", "/opt/zapret2/config"))
PROMOTE_BACKUP_DIR = os.environ.get("PROMOTE_BACKUP_DIR", _ENV.get("PROMOTE_BACKUP_DIR", "/opt/zapret2/config_backups"))
