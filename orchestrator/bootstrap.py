#!/usr/bin/env python3
"""Первый шаг на СВЕЖЕЙ ноде, до обычного main.py -- по прямому запросу:
"разварачивается репозиторий на очередной сервере, определяется
провайдер, и сразу пробуются уже готовые стратегии... если не подходят,
запускается генератор, затем докручиватель". Тянет с панели то, что уже
известно рабочим для ЭТОГО провайдера (или хотя бы для нескольких
провайдеров разом -- universal-паттерны, см. panel "База знаний"), и
реально проверяет их в локальной песочнице -- не просто копирует чужие
цифры не глядя, каждый кандидат тестируется живым трафиком тут же, как
обычный геном в main.py.

    python3 bootstrap.py --profile RKN_TLS

Если что-то из bootstrap-кандидатов подтвердилось -- дальше можно сразу
compare_control.py или просто запускать main.py как обычно (он и так
подхватит подтверждённые геномы через genome-level UCB, они уже в БД).
Если НИЧЕГО не подтвердилось -- это не ошибка, просто у этого провайдера
DPI не похож ни на что уже виденное, обычный путь -- сиды + мутации:

    python3 main.py --profile RKN_TLS --rounds 20
"""
import argparse
import sys
import time

import config
import db
import genome as genome_mod
import panel_client
import sandbox_apply
import scoring
import tester
import voice_tester

TRIALS_PER_CANDIDATE = 3
SETTLE_SECONDS = 3


def run(profile: str, environment_name: str, provider: str, min_pulls: int, limit: int) -> int:
    try:
        result = panel_client.bootstrap(profile, min_pulls=min_pulls, limit=limit)
    except panel_client.PanelError as e:
        print(f"Панель недоступна ({e}) -- пропускаю bootstrap, сразу main.py с сидами.", file=sys.stderr)
        return 1

    candidates = result["candidates"]
    if not candidates:
        print(f"На панели пока нет проверенных кандидатов для {profile} "
              f"(ни у провайдера '{result['provider']}', ни universal-паттернов с 2+ провайдерами). "
              "Это нормально для первой ноды на новом провайдере -- запускай main.py как обычно.")
        return 0

    conn = db.connect()
    env_id = db.get_or_create_environment(conn, environment_name, provider)
    domains = db.get_domains_for_profile(conn, profile)
    if not domains:
        print(f"Нет доменов в domain_pool для {profile}.", file=sys.stderr)
        return 1
    domain = domains[0]

    print(f"Панель прислала {len(candidates)} кандидатов для {profile} "
          f"(провайдер='{result['provider']}'), пробую по {TRIALS_PER_CANDIDATE} раза каждый:")

    confirmed = []
    for c in candidates:
        g = genome_mod.from_params(profile, c["params_json"], c["generation"])
        g.source = "sync_import"
        gid = db.insert_genome(conn, g)
        print(f"  [{c['tier']}] {g.render_args()}  (на панели: pulls={c['pulls']} avg_score={c['avg_score']} "
              f"provider'ов={c['distinct_providers']})")

        successes = 0
        for trial in range(1, TRIALS_PER_CANDIDATE + 1):
            if profile == "VOICE_UDP":
                success, bytes_, latency_ms = voice_tester.probe([g.render_args()])
            else:
                if not sandbox_apply.apply_genome(g):
                    print("    не удалось применить в песочнице, пропуск кандидата", file=sys.stderr)
                    break
                time.sleep(SETTLE_SECONDS)
                success, bytes_, latency_ms = tester.probe(domain["host"], domain["path"], domain["min_bytes"])
            reward = scoring.compute_reward(success, latency_ms)
            db.record_experiment(conn, gid, env_id, domain["id"], success, bytes_, latency_ms)
            db.upsert_genome_score(conn, gid, env_id, success, reward)
            successes += int(success)
            print(f"    попытка {trial}/{TRIALS_PER_CANDIDATE}: {'OK' if success else 'fail'} ({bytes_} bytes, {latency_ms}ms)")

        if successes == TRIALS_PER_CANDIDATE:
            confirmed.append(g.render_args())
            print(f"  -> ПОДТВЕРЖДЕНО ({successes}/{TRIALS_PER_CANDIDATE}) для этого провайдера.")
        else:
            print(f"  -> не подтвердилось ({successes}/{TRIALS_PER_CANDIDATE}), у этой DPI похоже иначе.")

    conn.close()

    print()
    if confirmed:
        print(f"Bootstrap нашёл {len(confirmed)} рабочих кандидатов с чужих нод -- уже в БД, "
              "main.py подхватит их через genome-level UCB. Можно сразу проверить:")
        print(f"  sudo venv/bin/python3 compare_control.py --profile {profile} --trials 5")
    else:
        print("Ни один кандидат с других нод не подтвердился локально -- DPI этого провайдера "
              "не похожа на уже виденные. Обычный путь -- сиды + мутации:")
        print(f"  sudo venv/bin/python3 main.py --profile {profile} --rounds 20")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True, choices=["YT_TLS", "RKN_TLS", "DS_TLS", "VOICE_UDP"])
    ap.add_argument("--environment", default="prod-domru")
    ap.add_argument("--provider", default="domru")
    ap.add_argument("--min-pulls", type=int, default=3, help="мин. прогонов на панели, чтобы считать кандидата достаточно проверенным")
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()
    sys.exit(run(args.profile, args.environment, args.provider, args.min_pulls, args.limit))
