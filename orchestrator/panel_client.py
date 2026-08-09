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
