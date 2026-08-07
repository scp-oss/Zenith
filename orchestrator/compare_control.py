#!/usr/bin/env python3
"""Прямое сравнение control-генома (боевая ручная стратегия из controls.py)
с лучшими геномами, которые нашёл Zenith в этом профиле.

Геном применяется в песочнице ОДИН раз (не на каждую попытку — рестарт
nfqws2 сам по себе добавляет джиттер в latency), затем пробуется несколько
раз на КАЖДОМ домене профиля, не только на одном — геном может случайно
удачно попасть на конкретный CDN/маршрут одного домена и не значить
ничего в среднем. Единичный замер success/latency слишком шумный, чтобы
на нём делать вывод "превзошли" или нет.

Каждая попытка (control и сгенерированных) пишется в experiments/
genome_scores так же, как обычные раунды main.py — иначе успешность
боевой стратегии нигде не копится и каждый прогон этого скрипта начинает
с нуля. Control хранится в genomes как family='control' (см.
db.insert_control_genome), поэтому запрос топа сгенерированных явно
исключает family='control', чтобы не сравнивать control сам с собой.

    python3 compare_control.py --profile RKN_TLS --trials 5
"""
import argparse
import sys
import time

import controls
import db
import genome as genome_mod
import sandbox_apply
import scoring
import tester

TOP_N = 3
SETTLE_SECONDS = 3


def measure(conn, env_id: int, gid: str, filter_lines: list, lua_lines: list, domains: list, trials_per_domain: int) -> dict:
    if not sandbox_apply.apply_raw(filter_lines, lua_lines):
        print("  не удалось применить в песочнице", file=sys.stderr)
        return {}
    time.sleep(SETTLE_SECONDS)

    per_domain = {}
    for domain in domains:
        results = []
        for _ in range(trials_per_domain):
            success, bytes_, latency_ms = tester.probe(domain["host"], domain["path"], domain["min_bytes"])
            reward = scoring.compute_reward(success, latency_ms)
            db.record_experiment(conn, gid, env_id, domain["id"], success, bytes_, latency_ms)
            db.upsert_genome_score(conn, gid, env_id, success, reward)
            results.append((success, bytes_, latency_ms))
        per_domain[domain["host"]] = results
    return per_domain


def summarize(name: str, per_domain: dict) -> None:
    if not per_domain:
        print(f"  {name}: нет результатов")
        return

    total_n = total_ok = total_bytes = total_lat_sum = total_lat_n = 0
    for host, results in per_domain.items():
        n = len(results)
        ok = sum(1 for r in results if r[0])
        avg_bytes = sum(r[1] for r in results) / n if n else 0
        succ_lat = [r[2] for r in results if r[0]]
        lat_str = f"{sum(succ_lat) / len(succ_lat):.0f}ms" if succ_lat else "n/a"
        print(f"    {host}: {ok}/{n} OK, avg_bytes={avg_bytes:.0f}, avg_latency={lat_str}")
        total_n += n
        total_ok += ok
        total_bytes += sum(r[1] for r in results)
        total_lat_sum += sum(succ_lat)
        total_lat_n += len(succ_lat)

    overall_lat = f"{total_lat_sum / total_lat_n:.0f}ms" if total_lat_n else "n/a"
    print(f"  {name} ИТОГО: {total_ok}/{total_n} OK, avg_bytes={total_bytes / total_n:.0f}, avg_latency={overall_lat}")


def run(profile: str, trials: int, environment_name: str, provider: str) -> int:
    conn = db.connect()
    env_id = db.get_or_create_environment(conn, environment_name, provider)

    domains = db.get_domains_for_profile(conn, profile)
    if not domains:
        print(f"Нет доменов для {profile}", file=sys.stderr)
        return 1
    print(f"Домены для сравнения: {', '.join(d['host'] for d in domains)} (x{trials} попыток каждый)")
    filter_lines = genome_mod.PROFILE_FILTERS[profile]

    control = controls.get_control(profile)
    print("\n=== control (боевой, ручной) ===")
    if control:
        for line in control:
            print(f"  {line}")
        control_gid = db.insert_control_genome(conn, profile, control)
        summarize("control", measure(conn, env_id, control_gid, filter_lines, control, domains, trials))
    else:
        print(f"  нет control-генома для {profile}, сравнивать не с чем", file=sys.stderr)

    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT g.id, g.rendered_args,
                  SUM(gs.pulls) AS pulls, SUM(gs.successes) AS successes,
                  ROUND(SUM(gs.total_reward) / NULLIF(SUM(gs.pulls), 0), 3) AS avg_score
           FROM genome_scores gs
           JOIN genomes g ON g.id = gs.genome_id AND g.profile = %s
           WHERE g.family != 'control'
           GROUP BY g.id, g.rendered_args
           HAVING successes > 0
           ORDER BY avg_score DESC
           LIMIT %s""",
        (profile, TOP_N),
    )
    top = cur.fetchall()

    if not top:
        print("\nНет успешных сгенерированных геномов в БД для этого профиля ещё.")
        conn.close()
        return 0

    print(f"\n=== топ-{len(top)} сгенерированных Zenith (по накопленному avg_score) ===")
    for row in top:
        print(f"\n  {row['rendered_args']}  (было пулов={row['pulls']}, успехов={row['successes']}, avg_score={row['avg_score']})")
        summarize("generated", measure(conn, env_id, row["id"], filter_lines, [row["rendered_args"]], domains, trials))

    conn.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True, choices=["YT_TLS", "RKN_TLS", "DS_TLS"])
    ap.add_argument("--trials", type=int, default=5, help="попыток НА КАЖДЫЙ домен профиля")
    ap.add_argument("--environment", default="prod-domru")
    ap.add_argument("--provider", default="domru")
    args = ap.parse_args()
    sys.exit(run(args.profile, args.trials, args.environment, args.provider))
