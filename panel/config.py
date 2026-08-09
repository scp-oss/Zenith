"""Панель делит .env с остальным Zenith (см. orchestrator/config.py --
тот же _load_env-паттерн, тот же файл Zenith/.env, не отдельный
panel/.env) -- одна точка конфигурации на весь репозиторий."""
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


PANEL_DIR = os.path.dirname(os.path.abspath(__file__))
ZENITH_DIR = os.path.dirname(PANEL_DIR)
_ENV = _load_env(os.path.join(ZENITH_DIR, ".env"))


def _get(key, default=""):
    return os.environ.get(key, _ENV.get(key, default))


MYSQL_HOST = _get("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(_get("MYSQL_PORT", "3306"))
MYSQL_USER = _get("MYSQL_USER", "zenith")
MYSQL_PASSWORD = _get("MYSQL_PASSWORD", "")
MYSQL_DATABASE = _get("MYSQL_DATABASE", "z2r_genome")

# Единственный админ-логин панели -- см. panel/README.md про
# panel/gen_password_hash.py для генерации PANEL_ADMIN_PASSWORD_HASH.
# Многопользовательская модель не запрошена, заводить users-таблицу ради
# одного владельца смысла нет.
PANEL_ADMIN_USER = _get("PANEL_ADMIN_USER", "admin")
PANEL_ADMIN_PASSWORD_HASH = _get("PANEL_ADMIN_PASSWORD_HASH", "")
PANEL_SESSION_SECRET = _get("PANEL_SESSION_SECRET", "")


# Дефолт -- 127.0.0.1: панель не смотрит в интернет сама. Публичный вход --
# Caddy (443 обычно занят на хосте, слушает альт-порт Cloudflare) с
# Origin CA сертификатом, реверс-прокси на этот же 127.0.0.1:PANEL_PORT
# (см. README "Публикация панели через Cloudflare"). Меняй на 0.0.0.0
# только если сознательно НЕ используешь Caddy/reverse proxy перед ней --
# тогда логин будет идти голым HTTP, см. предупреждение в README.
PANEL_HOST = _get("PANEL_HOST", "127.0.0.1")
PANEL_PORT = int(_get("PANEL_PORT", "8766"))
# Secure-флаг на сессионной cookie -- отключай только для локальной
# разработки без TLS (иначе браузер попросту не отдаст cookie обратно по
# http и логин будет молча "не держаться").
PANEL_COOKIE_HTTPS_ONLY = _get("PANEL_COOKIE_HTTPS_ONLY", "true").lower() == "true"

# Локальное окружение -- то, за которое панель показывает control-статус
# через set_strategy_cli.sh (только `get`/`max`, никогда `set` -- панель
# ничего не применяет сама, см. README "Границы ответственности панели").
LOCAL_ENVIRONMENT_NAME = _get("ZENITH_ENVIRONMENT_NAME", "prod-domru")
LOCAL_ENVIRONMENT_PROVIDER = _get("ZENITH_ENVIRONMENT_PROVIDER", "domru")

Z2R_AUTOBENCH_DIR = _get("Z2R_AUTOBENCH_DIR", os.path.dirname(ZENITH_DIR))
SET_STRATEGY_CLI = os.path.join(Z2R_AUTOBENCH_DIR, "set_strategy_cli.sh")
