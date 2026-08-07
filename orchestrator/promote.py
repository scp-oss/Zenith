#!/usr/bin/env python3
"""Готовит боевой блок конфига + команду переключения для генома, который
показал себя не хуже (а по идее лучше) control'а. Zenith НЕ имеет
exec-доступа к боевому серверу (только БД + песочница), поэтому этот
скрипт ничего сам не применяет -- печатает то, что нужно вставить в
/opt/zapret2/config и какую команду выполнить, а применяет и проверяет
уже человек.

    # автовыбор: лучший по avg_score геном с --min-pulls прогонами и 100% успехом
    python3 promote.py --profile RKN_TLS --after-strategy 42

    # конкретный геном (id или его префикс из вывода compare_control.py/z0r)
    python3 promote.py --profile RKN_TLS --genome-id <id> --after-strategy 42

--after-strategy -- текущий max strategy= для профиля в /opt/zapret2/config
(config_profile_max_strategy() из z2r_autobench/lib -- ту же цифру видно
через `set_strategy_cli.sh max <profile>`). Новая стратегия получает
after_strategy+1 -- ЗАПРЕЩЕНО прыгать номерами (см. CLAUDE.md
z2r_autobench: "config_profile_max_strategy() returns the max... every
tool silently wastes cycles on the nonexistent numbers").
"""
import argparse
import sys

import db

# Совпадает и с rank_strategies.sh (case TITLE=...), и с
# circular_locked:key=N в самом /opt/zapret2/config -- сверено вживую
# 2026-08-07 (RKN_TLS=3 через set_strategy_cli.sh get 3 tls, DS_TLS=4
# через get 4 tls).
PROFILE_NUMBERS = {"YT_TLS": 1, "GV_TLS": 2, "RKN_TLS": 3, "DS_TLS": 4}


def pick_best(conn, profile: str, environment_id: int, min_pulls: int):
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT g.id, g.rendered_args, g.source, g.generation,
                  SUM(gs.pulls) AS pulls, SUM(gs.successes) AS successes,
                  ROUND(SUM(gs.total_reward) / NULLIF(SUM(gs.pulls), 0), 3) AS avg_score
           FROM genome_scores gs
           JOIN genomes g ON g.id = gs.genome_id AND g.profile = %s
           WHERE gs.environment_id = %s AND g.family != 'control'
           GROUP BY g.id, g.rendered_args, g.source, g.generation
           HAVING pulls >= %s AND successes = pulls
           ORDER BY avg_score DESC
           LIMIT 1""",
        (profile, environment_id, min_pulls),
    )
    return cur.fetchone()


def get_by_id(conn, genome_id: str):
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id, profile, rendered_args, source, generation FROM genomes WHERE id LIKE %s",
        (f"{genome_id}%",),
    )
    return cur.fetchone()


def run(profile: str, genome_id: str, after_strategy: int, environment_name: str, provider: str, min_pulls: int) -> int:
    if profile not in PROFILE_NUMBERS:
        print(f"Нет номера профиля для {profile} в PROFILE_NUMBERS", file=sys.stderr)
        return 1

    conn = db.connect()
    env_id = db.get_or_create_environment(conn, environment_name, provider)

    if genome_id:
        row = get_by_id(conn, genome_id)
        if not row or row["profile"] != profile:
            print(f"Геном {genome_id} не найден для профиля {profile}", file=sys.stderr)
            conn.close()
            return 1
    else:
        row = pick_best(conn, profile, env_id, min_pulls)
        if not row:
            print(
                f"Нет генома с {min_pulls}+ прогонами и 100% успехом для {profile} в {environment_name} -- "
                "нечего продвигать (или дай --genome-id вручную, приняв риск).",
                file=sys.stderr,
            )
            conn.close()
            return 1

    conn.close()

    strategy_n = after_strategy + 1
    lines = row["rendered_args"].split("\n")
    profile_num = PROFILE_NUMBERS[profile]

    print(f"# Zenith-generated, genome_id={row['id'][:12]}, source={row['source']}, generation={row['generation']}")
    print(f"# pulls={row.get('pulls', '?')} successes={row.get('successes', '?')} avg_score={row.get('avg_score', '?')}")
    print("#")
    print("# ПЕРЕД вставкой: сверить, что strategy= действительно свободен")
    print(f"#   (config_profile_max_strategy для {profile} должен быть ровно {after_strategy}) --")
    print(f"#   grep -c 'strategy={strategy_n}\\b' /opt/zapret2/config  (должно быть 0)")
    for line in lines:
        print(f"{line}:strategy={strategy_n}")
    print()
    print(f"# Вставить блок выше В ТОТ ЖЕ раздел профиля {profile} в /opt/zapret2/config,")
    print("# СРАЗУ ПОСЛЕ существующего последнего strategy= -- без разрыва в нумерации")
    print("# (см. CLAUDE.md z2r_autobench про config_profile_max_strategy). Затем:")
    print()
    print(f"bash /opt/z2r_autobench/set_strategy_cli.sh set {profile_num} tls {strategy_n}")
    print()
    print("# После переключения — проверить, что nfqws2 сам стартует без ошибок")
    print("# (--new блоки не задеты) и профиль реально работает на паре тестовых доменов")
    print("# ПЕРЕД тем, как считать промоушен завершённым.")

    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True, choices=["YT_TLS", "RKN_TLS", "DS_TLS"])
    ap.add_argument("--genome-id", help="id (или префикс) конкретного генома; иначе автовыбор лучшего")
    ap.add_argument("--after-strategy", type=int, required=True, help="текущий max strategy= для профиля")
    ap.add_argument("--environment", default="prod-domru")
    ap.add_argument("--provider", default="domru")
    ap.add_argument("--min-pulls", type=int, default=5, help="мин. число прогонов для автовыбора (только с 100%% успехом)")
    args = ap.parse_args()
    sys.exit(run(args.profile, args.genome_id, args.after_strategy, args.environment, args.provider, args.min_pulls))
