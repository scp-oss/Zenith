"""HTTP-клиент к z0r-panel/sync_api.py для удалённых нод (см.
config.PANEL_URL/PANEL_NODE_TOKEN). stdlib-only (urllib), как
voice_tester.py -- orchestrator/requirements.txt намеренно держит только
mysql-connector-python, лишних зависимостей ради одного HTTP-клиента не
заводим."""
import json
import urllib.error
import urllib.parse
import urllib.request

import config

TIMEOUT_SECONDS = 30


class PanelError(Exception):
    pass


def _request(method: str, path: str, params: dict = None, body: dict = None,
             node_name: str = None, node_provider: str = None) -> dict:
    if not config.PANEL_URL or not config.PANEL_NODE_TOKEN:
        raise PanelError("PANEL_URL/PANEL_NODE_TOKEN не заданы в .env")

    url = config.PANEL_URL.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)

    headers = {
        "Authorization": f"Bearer {config.PANEL_NODE_TOKEN}",
        "Content-Type": "application/json",
        # Дефолтный User-Agent urllib ("Python-urllib/3.x") -- первый
        # кандидат под Cloudflare Bot Fight Mode/WAF-эвристиками (живой
        # инцидент: 403 "error code: 1010" на /api/v1/db/*, хотя тот же
        # путь curl'ом проходил). Сигнатуру не подделываем под браузер --
        # честно называемся, реальный фикс от 1010 -- Cloudflare-правило
        # "Skip Bot Fight Mode" для /api/v1/*, не эта строка сама по себе,
        # но менять дефолт всё равно стоит.
        "User-Agent": "zenith-orchestrator/1.0",
    }
    # Self-report -- панель обновляет имя/провайдера этой записи этими
    # значениями на КАЖДЫЙ запрос (см. panel auth.require_node), не
    # только на push. node_name/node_provider -- РЕЗОЛВЛЕННЫЕ значения
    # вызывающего скрипта (после учёта --environment/--provider CLI-флагов,
    # если они переданы), а не голое config.LOCAL_ENVIRONMENT_*, которое
    # эти флаги как раз может переопределять.
    if node_name and node_provider:
        headers["X-Node-Name"] = node_name
        headers["X-Node-Provider"] = node_provider

    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise PanelError(f"{e.code} {e.reason}: {e.read().decode(errors='replace')}") from e
    except urllib.error.URLError as e:
        raise PanelError(str(e)) from e


def push(genomes: list, scores: list, environment_name: str, provider: str) -> dict:
    return _request(
        "POST", "/api/v1/sync/push", body={"genomes": genomes, "scores": scores},
        node_name=environment_name, node_provider=provider,
    )


def pull(profile: str, environment_name: str, provider: str, min_pulls: int = 3, limit: int = 20) -> dict:
    return _request(
        "GET", "/api/v1/sync/pull", params={"profile": profile, "min_pulls": min_pulls, "limit": limit},
        node_name=environment_name, node_provider=provider,
    )


def bootstrap(profile: str, environment_name: str, provider: str, min_pulls: int = 3, limit: int = 10) -> dict:
    return _request(
        "GET", "/api/v1/sync/bootstrap", params={"profile": profile, "min_pulls": min_pulls, "limit": limit},
        node_name=environment_name, node_provider=provider,
    )


# ------------------------------------------------------- realtime DB API --
# Для ZENITH_DB_MODE=api (см. db_api.py) -- по одному запросу на каждый
# вызов orchestrator/db.py, а не снапшотом пачкой, как push/pull выше.
# Зеркалирует z0r-panel/db_api.py 1:1.

def get_environment(environment_name: str, provider: str) -> dict:
    return _request("GET", "/api/v1/db/environment", node_name=environment_name, node_provider=provider)


def get_domains(profile: str, environment_name: str, provider: str) -> dict:
    return _request(
        "GET", "/api/v1/db/domains", params={"profile": profile},
        node_name=environment_name, node_provider=provider,
    )


def get_or_create_domain(host: str, path: str, profile: str, min_bytes: int,
                          environment_name: str, provider: str) -> dict:
    return _request(
        "POST", "/api/v1/db/domain",
        body={"host": host, "path": path, "profile": profile, "min_bytes": min_bytes},
        node_name=environment_name, node_provider=provider,
    )


def insert_genome(genome_body: dict, environment_name: str, provider: str) -> dict:
    return _request(
        "POST", "/api/v1/db/genomes", body=genome_body,
        node_name=environment_name, node_provider=provider,
    )


def insert_control_genome(profile: str, lines: list, environment_name: str, provider: str) -> dict:
    return _request(
        "POST", "/api/v1/db/control_genomes", body={"profile": profile, "lines": lines},
        node_name=environment_name, node_provider=provider,
    )


def record_experiment(genome_id: str, domain_id: int, success: bool, bytes_: int, latency_ms,
                       ban_suspected: bool, environment_name: str, provider: str) -> dict:
    return _request(
        "POST", "/api/v1/db/experiments",
        body={
            "genome_id": genome_id, "domain_id": domain_id, "success": success,
            "bytes_": bytes_, "latency_ms": latency_ms, "ban_suspected": ban_suspected,
        },
        node_name=environment_name, node_provider=provider,
    )


def upsert_genome_score(genome_id: str, success: bool, reward: float, environment_name: str, provider: str) -> dict:
    return _request(
        "POST", "/api/v1/db/genome_scores",
        body={"genome_id": genome_id, "success": success, "reward": reward},
        node_name=environment_name, node_provider=provider,
    )


def get_genome_scores(profile: str, environment_name: str, provider: str) -> dict:
    return _request(
        "GET", "/api/v1/db/genome_scores", params={"profile": profile},
        node_name=environment_name, node_provider=provider,
    )


def upsert_operator_stat(filter_type: str, operator: str, reward: float, environment_name: str, provider: str) -> dict:
    return _request(
        "POST", "/api/v1/db/operator_stats",
        body={"filter_type": filter_type, "operator": operator, "reward": reward},
        node_name=environment_name, node_provider=provider,
    )


def get_operator_stats(filter_type: str, environment_name: str, provider: str) -> dict:
    return _request(
        "GET", "/api/v1/db/operator_stats", params={"filter_type": filter_type},
        node_name=environment_name, node_provider=provider,
    )


def recent_domain_experiments(domain_id: int, limit: int, environment_name: str, provider: str) -> dict:
    return _request(
        "GET", "/api/v1/db/domain_experiments", params={"domain_id": domain_id, "limit": limit},
        node_name=environment_name, node_provider=provider,
    )


def log_ban_event(domain_id: int, reason: str, cooldown_seconds: int, environment_name: str, provider: str) -> dict:
    return _request(
        "POST", "/api/v1/db/ban_events",
        body={"domain_id": domain_id, "reason": reason, "cooldown_seconds": cooldown_seconds},
        node_name=environment_name, node_provider=provider,
    )
