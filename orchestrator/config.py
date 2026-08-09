import os


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
LOCAL_ENVIRONMENT_NAME = os.environ.get("ZENITH_ENVIRONMENT_NAME", _ENV.get("ZENITH_ENVIRONMENT_NAME", "prod-domru"))
LOCAL_ENVIRONMENT_PROVIDER = os.environ.get("ZENITH_ENVIRONMENT_PROVIDER", _ENV.get("ZENITH_ENVIRONMENT_PROVIDER", "domru"))

# Для sync_client.py (удалённые ноды -> панель на боевом сервере, см.
# z0r-panel/README.md). Пусто на самой панели/локальной ноде -- sync_client.py
# там не нужен, панель и так пишет в эту же БД напрямую.
PANEL_URL = os.environ.get("PANEL_URL", _ENV.get("PANEL_URL", ""))
PANEL_NODE_TOKEN = os.environ.get("PANEL_NODE_TOKEN", _ENV.get("PANEL_NODE_TOKEN", ""))
