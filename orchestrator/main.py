#!/usr/bin/env python3
"""Zenith orchestrator v1 — по одному профилю за раз:

    python3 main.py --profile YT_TLS --rounds 20

Каждый раунд: если сиды профиля ещё не все опробованы — берёт следующий
сид, иначе UCB1 выбирает мутационный оператор (см. mutate.py) и мутирует
случайный сид. Применяет геном через песочницу (sandbox_apply.py),
тестирует реальным коннектом от юзера песочницы (tester.py), пишет
результат в БД.

Упрощения v1 (см. README/Roadmap Zenith):
- Мутация всегда берётся от случайного СИДА, не от лучшего найденного
  генома — полноценный genome-level UCB (не только по операторам) ещё не
  реализован.
- crossover() в mutate.py существует, но в цикл ниже пока не подключён.
- circuit breaker простой (N разных геномов подряд провалились на одном
  домене), без более тонкой статистики.
"""
import argparse
import math
import random
import sys
import time

import db
import mutate
import sandbox_apply
import seeds
import tester

CONSECUTIVE_FAIL_BAN_THRESHOLD = 4
BAN_COOLDOWN_SECONDS = 1800
BASE_SETTLE_SECONDS = 3
MAX_SETTLE_SECONDS = 60
FILTER_TYPE = "tcp/443"


def pick_operator_ucb(op_stats: dict, total_pulls: int) -> str:
    """UCB1 по фиксированному списку операторов (mutate.ESCALATION_ORDER).
    Операторы без накопленной статистики пробуются в порядке цепочки
    эскалации, а не рандомно — так v1 нащупывает разумный путь ещё до
    того, как накопится реальная статистика по конкретному провайдеру."""
    unseen = [op for op in mutate.ESCALATION_ORDER if op not in op_stats]
    if unseen:
        return unseen[0]

    best_op, best_score = None, -1.0
    for op in mutate.ESCALATION_ORDER:
        stat = op_stats[op]
        pulls = stat["pulls"] or 1
        mean = stat["total_reward"] / pulls
        bonus = math.sqrt(2 * math.log(max(total_pulls, 1)) / pulls)
        score = mean + bonus
        if score > best_score:
            best_op, best_score = op, score
    return best_op


def check_ban_suspected(conn, domain_id) -> bool:
    recent = db.recent_domain_experiments(conn, domain_id, limit=CONSECUTIVE_FAIL_BAN_THRESHOLD)
    if len(recent) < CONSECUTIVE_FAIL_BAN_THRESHOLD:
        return False
    all_failed = all(not r["success"] for r in recent)
    distinct_genomes = len({r["genome_id"] for r in recent})
    return all_failed and distinct_genomes >= 2


def run(profile: str, rounds: int, environment_name: str, provider: str) -> int:
    conn = db.connect()
    env_id = db.get_or_create_environment(conn, environment_name, provider)

    domains = db.get_domains_for_profile(conn, profile)
    if not domains:
        print(f"Нет доменов в domain_pool для профиля {profile} (или все в карантине).", file=sys.stderr)
        return 1

    seed_pool = seeds.get_seeds(profile)
    settle = BASE_SETTLE_SECONDS

    for round_no in range(1, rounds + 1):
        domain = random.choice(domains)

        if round_no <= len(seed_pool):
            genome = seed_pool[round_no - 1]
            op_name = None
        else:
            op_stats = db.get_operator_stats(conn, env_id, FILTER_TYPE)
            total_pulls = sum(s["pulls"] for s in op_stats.values()) or 1
            parent = random.choice(seed_pool)
            op_name = pick_operator_ucb(op_stats, total_pulls)
            genome = mutate.apply_operator(parent, op_name)

        gid = db.insert_genome(conn, genome)
        print(f"[{round_no}/{rounds}] {profile} op={op_name or 'seed'} -> {genome.render_args()}")

        try:
            applied = sandbox_apply.apply_genome(genome)
        except RuntimeError as e:
            print(f"  {e}", file=sys.stderr)
            return 1
        if not applied:
            print("  не удалось применить в песочнице (start_sandbox.sh вернул ошибку), пропуск", file=sys.stderr)
            continue

        time.sleep(settle)

        success, bytes_, latency_ms = tester.probe(domain["host"], domain["path"], domain["min_bytes"])
        reward = 1.0 if success else 0.0

        db.record_experiment(conn, gid, env_id, domain["id"], success, bytes_, latency_ms)
        db.upsert_genome_score(conn, gid, env_id, success, reward)
        if op_name:
            db.upsert_operator_stat(conn, env_id, FILTER_TYPE, op_name, reward)

        print(f"  -> {'OK' if success else 'fail'} ({bytes_} bytes, {latency_ms}ms), домен={domain['host']}")

        if check_ban_suspected(conn, domain["id"]):
            reason = f"{CONSECUTIVE_FAIL_BAN_THRESHOLD} разных геномов подряд провалились на {domain['host']}"
            db.log_ban_event(conn, env_id, domain["id"], reason, BAN_COOLDOWN_SECONDS)
            print(f"  ПОДОЗРЕНИЕ НА БАН: {reason} — пауза {BAN_COOLDOWN_SECONDS}s.", file=sys.stderr)
            time.sleep(BAN_COOLDOWN_SECONDS)
            settle = BASE_SETTLE_SECONDS
            continue

        settle = BASE_SETTLE_SECONDS if success else min(MAX_SETTLE_SECONDS, settle * 2)

    conn.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True, choices=["YT_TLS", "RKN_TLS", "DS_TLS"])
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument("--environment", default="prod-domru", help="имя окружения в таблице environments")
    ap.add_argument("--provider", default="domru")
    args = ap.parse_args()
    sys.exit(run(args.profile, args.rounds, args.environment, args.provider))
