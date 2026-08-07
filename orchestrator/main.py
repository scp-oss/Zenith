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

import controls
import db
import mutate
import sandbox_apply
import scoring
import seeds
import tester

CONSECUTIVE_FAIL_BAN_THRESHOLD = 8
CHECK_COOLDOWN_ROUNDS = 8  # не дёргать control чаще раза в столько раундов
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


def verify_not_false_positive(profile: str, domain: dict) -> bool:
    """N разных геномов подряд проваливаются на одном домене — само по
    себе неоднозначно: может быть реальный бан, а может просто наши
    кандидаты слабые против конкретной DPI (см. живой случай 2026-08-06:
    4 сгенерированных генома подряд провалились, а боевая strategy=5
    тут же сработала). Перед тем как объявлять бан — прогоняем control
    (заведомо рабочий боевой геном). Возвращает True, если control
    сработал (значит НЕ бан, ложное срабатывание) — иначе True тоже
    возвращается при отсутствии control'а для профиля (нечем проверить,
    остаёмся при консервативном "похоже на бан")."""
    control = controls.get_control(profile)
    if not control:
        print(f"  (нет control-генома для {profile}, проверить не могу)", file=sys.stderr)
        return False
    if not sandbox_apply.apply_raw(controls.PROFILE_FILTER, control):
        print("  не удалось применить control в песочнице", file=sys.stderr)
        return False
    time.sleep(BASE_SETTLE_SECONDS)
    success, bytes_, _ = tester.probe(domain["host"], domain["path"], domain["min_bytes"])
    print(f"  control-проверка: {'OK' if success else 'fail'} ({bytes_} bytes)")
    return success


def run(profile: str, rounds: int, environment_name: str, provider: str) -> int:
    conn = db.connect()
    env_id = db.get_or_create_environment(conn, environment_name, provider)

    domains = db.get_domains_for_profile(conn, profile)
    if not domains:
        print(f"Нет доменов в domain_pool для профиля {profile} (или все в карантине).", file=sys.stderr)
        return 1

    seed_pool = seeds.get_seeds(profile)
    settle = BASE_SETTLE_SECONDS
    last_ban_check_round = -CHECK_COOLDOWN_ROUNDS

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
        reward = scoring.compute_reward(success, latency_ms)

        db.record_experiment(conn, gid, env_id, domain["id"], success, bytes_, latency_ms)
        db.upsert_genome_score(conn, gid, env_id, success, reward)
        if op_name:
            db.upsert_operator_stat(conn, env_id, FILTER_TYPE, op_name, reward)

        print(f"  -> {'OK' if success else 'fail'} ({bytes_} bytes, {latency_ms}ms), домен={domain['host']}")

        # Слабых кандидатов будет много, сильных мало -- длинные полосы
        # подряд идущих провалов сами по себе норма на этой стадии, не
        # сигнал. check_ban_suspected срабатывает не при каждом провале, а
        # при полосе от CONSECUTIVE_FAIL_BAN_THRESHOLD разных геномов, и
        # даже тогда сам control не дёргаем чаще раза в
        # CHECK_COOLDOWN_ROUNDS раундов -- иначе на плотном потоке слабых
        # геномов (как обычно и бывает) control гоняется практически на
        # каждом провале, впустую тратя раунды на подтверждение того же
        # самого "не бан".
        if round_no - last_ban_check_round >= CHECK_COOLDOWN_ROUNDS and check_ban_suspected(conn, domain["id"]):
            last_ban_check_round = round_no
            print(f"  {CONSECUTIVE_FAIL_BAN_THRESHOLD} разных геномов подряд провалились на {domain['host']} — проверяю control перед выводом о бане...")
            if verify_not_false_positive(profile, domain):
                print("  control сработал — не бан, просто слабые кандидаты подряд. Продолжаю без паузы.")
            else:
                reason = f"{CONSECUTIVE_FAIL_BAN_THRESHOLD} разных геномов подряд провалились на {domain['host']}, control тоже не прошёл/недоступен"
                db.log_ban_event(conn, env_id, domain["id"], reason, BAN_COOLDOWN_SECONDS)
                print(f"  ПОДОЗРЕНИЕ НА БАН ПОДТВЕРЖДЕНО: {reason} — пауза {BAN_COOLDOWN_SECONDS}s.", file=sys.stderr)
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
