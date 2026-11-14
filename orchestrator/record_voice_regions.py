#!/usr/bin/env python3
"""Записывает результат прогона живой VOICE_UDP-стратегии по голосовым
регионам Discord (JSON от z2r_autobench/voice_region_sweep.sh ->
rank_voice_regions.sh --json) в таблицу voice_region_checks.

Через db.py, как и всё остальное в orchestrator: на NETH-4 (docker) --
прямо в MySQL, на нодах ZENITH_DB_MODE=api -- POST в панель
(/api/v1/db/voice_region_checks), т.е. в любом случае в центральную БД.

usage: record_voice_regions.py RESULT.json [--environment NAME] [--provider P]
"""
import argparse
import json
import sys
import uuid

import config
import db


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("result_json")
    ap.add_argument("--environment", default=config.LOCAL_ENVIRONMENT_NAME)
    ap.add_argument("--provider", default=config.LOCAL_ENVIRONMENT_PROVIDER)
    args = ap.parse_args()

    with open(args.result_json) as f:
        d = json.load(f)
    results = [r for r in d.get("results", []) if r.get("success") is not None]
    if not results:
        print("record_voice_regions: нет валидных результатов -- ничего не пишу", file=sys.stderr)
        return 1
    conn = db.connect()
    try:
        env_id = db.get_or_create_environment(conn, args.environment, args.provider)
        db.record_voice_region_checks(conn, env_id, d.get("sweep_id") or str(uuid.uuid4()),
                                      d.get("strategy"), results, d.get("source") or "sweep")
    finally:
        conn.close()
    ok = sum(1 for r in results if r["success"])
    print(f"record_voice_regions: записано {len(results)} регионов ({ok} ok), env_id={env_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
