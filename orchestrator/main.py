#!/usr/bin/env python3
"""Zenith orchestrator v1 — по одному профилю за раз:

    python3 main.py --profile YT_TLS --rounds 20

Каждый раунд: если сиды профиля ещё не все опробованы — берёт следующий
сид, иначе UCB1 выбирает и мутационный оператор (см. mutate.py), и
РОДИТЕЛЬСКИЙ геном для мутации — из всех уже опробованных в этом
окружении, не только сидов, так что удачные находки докручиваются, а не
теряются на каждом раунде. Применяет геном через песочницу
(sandbox_apply.py), тестирует реальным коннектом от юзера песочницы
(tester.py), пишет результат в БД.

Упрощения v1 (см. README/Roadmap Zenith):
- crossover() в mutate.py существует, но в цикл ниже пока не подключён.
- circuit breaker простой (N разных геномов подряд провалились на одном
  домене), без более тонкой статистики.
"""
import argparse
import json
import math
import random
import sys
import time

import config
import controls
import db
import genome as genome_mod
import gv_resolver
import mutate
import sandbox_apply
import scoring
import seeds
import tester
import voice_tester

CONSECUTIVE_FAIL_BAN_THRESHOLD = 8
CHECK_COOLDOWN_ROUNDS = 8  # не дёргать control чаще раза в столько раундов
BAN_COOLDOWN_SECONDS = 1800
BASE_SETTLE_SECONDS = 3
MAX_SETTLE_SECONDS = 60
# Тот же порог, что MIN_BYTES_THRESHOLD в z2r_autobench_lib.sh (см. CLAUDE.md
# z2r_autobench "Test domains") -- домен, отдающий меньше, портит любой тест
# ложным провалом вне зависимости от реального DPI-обхода.
MIN_BYTES_THRESHOLD = 65536


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


def pick_parent_ucb(rows: list, profile: str):
    """UCB1 по всем УЖЕ ОПРОБОВАННЫМ геномам профиля (сиды + любые
    сгенерированные раньше), не только по сидам -- иначе генератор каждый
    раунд мутирует от случайного сида и никогда не докручивает удачные
    находки. Живое наблюдение 2026-08-07: паритет с ручными стратегиями на
    RKN_TLS и DS_TLS, но не превосходство -- подозрение как раз на это."""
    total_pulls = sum(r["pulls"] for r in rows) or 1
    best_row, best_score = None, -1.0
    for row in rows:
        pulls = row["pulls"] or 1
        mean = row["total_reward"] / pulls
        bonus = math.sqrt(2 * math.log(max(total_pulls, 1)) / pulls)
        score = mean + bonus
        if score > best_score:
            best_row, best_score = row, score
    return genome_mod.from_params(profile, json.loads(best_row["params_json"]), best_row["generation"])


def check_ban_suspected(conn, domain_id) -> bool:
    recent = db.recent_domain_experiments(conn, domain_id, limit=CONSECUTIVE_FAIL_BAN_THRESHOLD)
    if len(recent) < CONSECUTIVE_FAIL_BAN_THRESHOLD:
        return False
    all_failed = all(not r["success"] for r in recent)
    distinct_genomes = len({r["genome_id"] for r in recent})
    return all_failed and distinct_genomes >= 2


def verify_not_false_positive(conn, env_id: int, profile: str, domain: dict) -> bool:
    """N разных геномов подряд проваливаются на одном домене — само по
    себе неоднозначно: может быть реальный бан, а может просто наши
    кандидаты слабые против конкретной DPI (см. живой случай 2026-08-06:
    4 сгенерированных генома подряд провалились, а боевая strategy=5
    тут же сработала). Перед тем как объявлять бан — прогоняем control
    (заведомо рабочий боевой геном). Возвращает True, если control
    сработал (значит НЕ бан, ложное срабатывание) — иначе True тоже
    возвращается при отсутствии control'а для профиля (нечем проверить,
    остаёмся при консервативном "похоже на бан"). Результат пишется в
    experiments/genome_scores как обычный прогон (family='control') --
    иначе успешность боевой стратегии нигде не копится, кроме разовых
    ручных прогонов compare_control.py."""
    control = controls.get_control(profile)
    if not control:
        print(f"  (нет control-генома для {profile}, проверить не могу)", file=sys.stderr)
        return False

    if profile == "VOICE_UDP":
        # z2r_test-voice-bot сам применяет control в своей песочнице
        # (см. voice_tester.probe), не sandbox_apply -- бот работает от
        # zenith-sandbox, отдельного пути применения тут не нужно.
        success, bytes_, latency_ms = voice_tester.probe(control)
    else:
        if not sandbox_apply.apply_raw(genome_mod.PROFILE_FILTERS[profile], control):
            detail = f": {sandbox_apply.LAST_ERROR}" if sandbox_apply.LAST_ERROR else ""
            print(f"  не удалось применить control в песочнице{detail}", file=sys.stderr)
            return False
        time.sleep(BASE_SETTLE_SECONDS)
        if profile == "GV_TLS":
            gv_url = gv_resolver.resolve_googlevideo_url()
            if not gv_url:
                print("  не удалось резолвить googlevideo.com URL через yt-dlp, control-проверка невозможна", file=sys.stderr)
                return False
            success, bytes_, latency_ms = tester.probe_url(gv_url, domain["min_bytes"])
        else:
            success, bytes_, latency_ms = tester.probe(domain["host"], domain["path"], domain["min_bytes"])
    print(f"  control-проверка: {'OK' if success else 'fail'} ({bytes_} bytes)")

    control_gid = db.insert_control_genome(conn, profile, control)
    db.record_experiment(conn, control_gid, env_id, domain["id"], success, bytes_, latency_ms)
    db.upsert_genome_score(conn, control_gid, env_id, success, scoring.compute_reward(success, latency_ms))

    return success


def run(profile: str, rounds: int, environment_name: str, provider: str, domain_override: str = None) -> int:
    conn = db.connect()
    env_id = db.get_or_create_environment(conn, environment_name, provider)
    filter_type = genome_mod.PROFILE_FILTER_TYPE.get(profile, "tcp/443")

    if domain_override:
        # Разовый кастомный домен (--domain, обычно из панели -- "запустить
        # подбор для кастомного домена") -- не выбираем случайно из пула,
        # весь прогон идёт против ЭТОГО домена. get_or_create_domain сам
        # заводит запись в domain_pool, если её ещё не было -- дальше это
        # обычная запись пула, попадёт и в будущие get_domains_for_profile.
        host, _, path = domain_override.partition("/")
        domains = [db.get_or_create_domain(conn, host, "/" + path if path else "/", profile, MIN_BYTES_THRESHOLD)]
    else:
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
            op_stats = db.get_operator_stats(conn, env_id, filter_type)
            total_op_pulls = sum(s["pulls"] for s in op_stats.values()) or 1
            op_name = pick_operator_ucb(op_stats, total_op_pulls)

            parent_rows = db.get_genomes_with_scores(conn, profile, env_id)
            parent = pick_parent_ucb(parent_rows, profile) if parent_rows else random.choice(seed_pool)
            genome = mutate.apply_operator(parent, op_name)

        gid = db.insert_genome(conn, genome)
        print(f"[{round_no}/{rounds}] {profile} op={op_name or 'seed'} -> {genome.render_args()}")

        if profile == "VOICE_UDP":
            # z2r_test-voice-bot применяет геном в СВОЕЙ песочнице сам
            # (работает от zenith-sandbox) при получении /probe -- не
            # sandbox_apply.apply_genome() отсюда, было бы двойной работой.
            success, bytes_, latency_ms = voice_tester.probe([genome.render_args()])
        else:
            try:
                applied = sandbox_apply.apply_genome(genome)
            except RuntimeError as e:
                print(f"  {e}", file=sys.stderr)
                return 1
            if not applied:
                detail = f": {sandbox_apply.LAST_ERROR}" if sandbox_apply.LAST_ERROR else ""
                print(f"  не удалось применить в песочнице (start_sandbox.sh вернул ошибку){detail}, пропуск", file=sys.stderr)
                continue

            time.sleep(settle)
            if profile == "GV_TLS":
                # GV_TLS не тестируется по фиксированному host/path из
                # domain_pool (см. db/schema.sql -- googlevideo.com там
                # только placeholder ради domain_id) -- реальный
                # googlevideo.com URL резолвится заново на каждый раунд
                # через yt-dlp, иначе CDN-эдж залипает на одном video_id и
                # бан одного эджа ложно валит весь прогон целиком (см.
                # gv_resolver.py докстринг).
                gv_url = gv_resolver.resolve_googlevideo_url()
                if not gv_url:
                    print("  не удалось резолвить googlevideo.com URL через yt-dlp (сеть до youtube.com сама по себе не работает?), пропуск", file=sys.stderr)
                    continue
                success, bytes_, latency_ms = tester.probe_url(gv_url, domain["min_bytes"])
            else:
                success, bytes_, latency_ms = tester.probe(domain["host"], domain["path"], domain["min_bytes"])
        reward = scoring.compute_reward(success, latency_ms)

        db.record_experiment(conn, gid, env_id, domain["id"], success, bytes_, latency_ms)
        db.upsert_genome_score(conn, gid, env_id, success, reward)
        if op_name:
            db.upsert_operator_stat(conn, env_id, filter_type, op_name, reward)

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
            if verify_not_false_positive(conn, env_id, profile, domain):
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
    ap.add_argument("--profile", required=True, choices=["YT_TLS", "GV_TLS", "RKN_TLS", "DS_TLS", "VOICE_UDP"])
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument("--environment", default=config.LOCAL_ENVIRONMENT_NAME, help="имя окружения в таблице environments")
    ap.add_argument("--provider", default=config.LOCAL_ENVIRONMENT_PROVIDER)
    ap.add_argument("--domain", default=None, help="кастомный домен (host[/path]) вместо случайного из domain_pool -- весь прогон идёт против него одного")
    args = ap.parse_args()
    sys.exit(run(args.profile, args.rounds, args.environment, args.provider, args.domain))
