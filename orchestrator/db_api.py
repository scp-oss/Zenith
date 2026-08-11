"""HTTP backend for db.py (ZENITH_DB_MODE=api) -- this node has no local
DB at all, every orchestrator/db.py call becomes one HTTP request to the
panel (see z0r-panel/db_api.py, the server side these calls hit).
Signatures match db_local.py 1:1 -- main.py/bootstrap.py/compare_control.py/
promote.py `import db` and call these without knowing or caring which
backend is behind it (see db.py, the selector).

`conn` here is not a real connection, just a small object accumulating
self-report (node_name/provider) for the X-Node-Name/X-Node-Provider
headers on every request (see panel_client.py) -- resolved once, on the
first db.get_or_create_environment() call, same as every CLI script
already does today.

export_for_sync/insert_sync_import_genome from db_local.py are
intentionally absent here -- those back sync_client.py's push/pull of a
local buffer snapshot, and in api mode there is no local buffer to
export from or import into; sync_client.py is simply never run on a node
in this mode."""
import json

import panel_client


class ApiConnection:
    def __init__(self):
        self.node_name = None
        self.node_provider = None
        self.env_id = None

    def close(self):
        pass


def connect():
    return ApiConnection()


def get_or_create_environment(conn, name: str, provider: str) -> int:
    conn.node_name, conn.node_provider = name, provider
    result = panel_client.get_environment(name, provider)
    conn.env_id = result["id"]
    return result["id"]


def get_domains_for_profile(conn, profile: str):
    result = panel_client.get_domains(profile, conn.node_name, conn.node_provider)
    return result["domains"]


def insert_control_genome(conn, profile: str, lines: list) -> str:
    result = panel_client.insert_control_genome(profile, lines, conn.node_name, conn.node_provider)
    return result["id"]


def insert_genome(conn, g) -> str:
    body = {
        "id": g.compute_id(), "profile": g.profile, "filter_type": g.filter_type,
        "family": g.family, "fooling": g.fooling, "ttl_mode": g.ttl_mode,
        "fake_payload": g.fake_payload, "params_json": json.loads(g.params_json()),
        "rendered_args": g.render_args(), "source": g.source,
        "parent1_id": g.parent1_id, "parent2_id": g.parent2_id,
        "mutation_op": g.mutation_op, "generation": g.generation,
    }
    result = panel_client.insert_genome(body, conn.node_name, conn.node_provider)
    return result["id"]


def record_experiment(conn, genome_id, environment_id, domain_id, success, bytes_, latency_ms, ban_suspected=False):
    panel_client.record_experiment(
        genome_id, domain_id, success, bytes_, latency_ms, ban_suspected,
        conn.node_name, conn.node_provider,
    )


def get_genomes_with_scores(conn, profile: str, environment_id: int):
    result = panel_client.get_genome_scores(profile, conn.node_name, conn.node_provider)
    return result["rows"]


def upsert_genome_score(conn, genome_id, environment_id, success: bool, reward: float):
    panel_client.upsert_genome_score(genome_id, success, reward, conn.node_name, conn.node_provider)


def upsert_operator_stat(conn, environment_id, filter_type, operator, reward):
    if not operator:
        return
    panel_client.upsert_operator_stat(filter_type, operator, reward, conn.node_name, conn.node_provider)


def get_operator_stats(conn, environment_id, filter_type):
    result = panel_client.get_operator_stats(filter_type, conn.node_name, conn.node_provider)
    return result["stats"]


def recent_domain_experiments(conn, domain_id, limit=5):
    result = panel_client.recent_domain_experiments(domain_id, limit, conn.node_name, conn.node_provider)
    return result["rows"]


def log_ban_event(conn, environment_id, domain_id, reason, cooldown_seconds):
    panel_client.log_ban_event(domain_id, reason, cooldown_seconds, conn.node_name, conn.node_provider)
