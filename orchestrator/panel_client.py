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


def _request(method: str, path: str, params: dict = None, body: dict = None) -> dict:
    if not config.PANEL_URL or not config.PANEL_NODE_TOKEN:
        raise PanelError("PANEL_URL/PANEL_NODE_TOKEN не заданы в .env")

    url = config.PANEL_URL.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)

    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": f"Bearer {config.PANEL_NODE_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise PanelError(f"{e.code} {e.reason}: {e.read().decode(errors='replace')}") from e
    except urllib.error.URLError as e:
        raise PanelError(str(e)) from e


def push(genomes: list, scores: list) -> dict:
    return _request("POST", "/api/v1/sync/push", body={"genomes": genomes, "scores": scores})


def pull(profile: str, min_pulls: int = 3, limit: int = 20) -> dict:
    return _request("GET", "/api/v1/sync/pull", params={"profile": profile, "min_pulls": min_pulls, "limit": limit})


def bootstrap(profile: str, min_pulls: int = 3, limit: int = 10) -> dict:
    return _request("GET", "/api/v1/sync/bootstrap", params={"profile": profile, "min_pulls": min_pulls, "limit": limit})
