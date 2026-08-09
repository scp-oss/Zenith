#!/usr/bin/env python3
"""Синк удалённой ноды с панелью на боевом сервере (см. panel/README.md
и CLAUDE.md/README про hub-and-spoke). Прямого доступа к MySQL панели у
удалённых нод нет -- только этот HTTP-клиент (panel_client.py) с
токеном ноды.

    # после прогона main.py -- отправить свой снапшот наверх
    python3 sync_client.py push --profile RKN_TLS

    # затравить локальный пул кандидатами, которые сработали на ДРУГИХ
    # нодах (source='sync_import', 0 локальных прогонов -- main.py
    # попробует их наравне с сидами через get_genomes_with_scores/UCB,
    # как только у них появится хоть один локальный результат)
    python3 sync_client.py pull --profile RKN_TLS

Обычный режим использования -- cron после каждого main.py прогона:
    sudo venv/bin/python3 main.py --profile RKN_TLS --rounds 20 && \\
    venv/bin/python3 sync_client.py push --profile RKN_TLS
"""
import argparse
import sys

import config
import db
import panel_client


def cmd_push(profile: str, environment_name: str, provider: str) -> int:
    conn = db.connect()
    env_id = db.get_or_create_environment(conn, environment_name, provider)
    genomes, scores = db.export_for_sync(conn, env_id, profile)
    conn.close()

    if not genomes:
        print(f"Нечего отправлять для {profile} в {environment_name} (нет локальных прогонов).")
        return 0

    result = panel_client.push(genomes, scores)
    print(f"Отправлено: {result['genomes_seen']} геномов, {result['scores_seen']} записей score "
          f"(нода на панели: {result['node']}).")
    return 0


def cmd_pull(profile: str, environment_name: str, provider: str, min_pulls: int, limit: int) -> int:
    conn = db.connect()
    env_id = db.get_or_create_environment(conn, environment_name, provider)
    result = panel_client.pull(profile, min_pulls=min_pulls, limit=limit)
    inserted = 0
    for c in result["candidates"]:
        db.insert_sync_import_genome(conn, profile, c["params_json"], c["generation"])
        inserted += 1
    conn.close()
    print(f"Затянуто {inserted} кандидатов для {profile} с панели (глобальный топ, {min_pulls}+ прогонов, 100%% успех).")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["push", "pull"])
    ap.add_argument("--profile", required=True, choices=["YT_TLS", "RKN_TLS", "DS_TLS", "VOICE_UDP"])
    ap.add_argument("--environment", default="prod-domru")
    ap.add_argument("--provider", default="domru")
    ap.add_argument("--min-pulls", type=int, default=3)
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    try:
        if args.action == "push":
            sys.exit(cmd_push(args.profile, args.environment, args.provider))
        else:
            sys.exit(cmd_pull(args.profile, args.environment, args.provider, args.min_pulls, args.limit))
    except panel_client.PanelError as e:
        print(f"Ошибка синка с панелью: {e}", file=sys.stderr)
        sys.exit(1)
