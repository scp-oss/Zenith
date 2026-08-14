"""Backend selector for orchestrator DB access -- ZENITH_DB_MODE=docker
(local buffer DB, isolated or hub-and-spoke-synced) uses db_local.py
(direct MySQL), ZENITH_DB_MODE=api (no local DB at all) uses db_api.py
(HTTP to the panel). Every other script here does `import db` and calls
db.xxx(...) without knowing which backend answers -- both modules export
the exact same function signatures, see db_local.py/db_api.py docstrings."""
import config

if config.ZENITH_DB_MODE == "api":
    import db_api as _impl
else:
    import db_local as _impl

connect = _impl.connect
get_or_create_environment = _impl.get_or_create_environment
get_domains_for_profile = _impl.get_domains_for_profile
get_or_create_domain = _impl.get_or_create_domain
insert_control_genome = _impl.insert_control_genome
insert_genome = _impl.insert_genome
record_experiment = _impl.record_experiment
get_genomes_with_scores = _impl.get_genomes_with_scores
upsert_genome_score = _impl.upsert_genome_score
upsert_operator_stat = _impl.upsert_operator_stat
get_operator_stats = _impl.get_operator_stats
recent_domain_experiments = _impl.recent_domain_experiments
log_ban_event = _impl.log_ban_event

# Только db_local.py (ZENITH_DB_MODE=docker) -- sync_client.py их
# использует для push/pull локального буфера; в api-режиме буфера нет,
# sync_client.py на такой ноде не запускается (см. db_api.py докстринг).
if config.ZENITH_DB_MODE != "api":
    export_for_sync = _impl.export_for_sync
    insert_sync_import_genome = _impl.insert_sync_import_genome
