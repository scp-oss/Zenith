#!/usr/bin/env python3
"""Прямое сравнение control-генома (боевая ручная стратегия из controls.py)
с лучшими геномами, которые нашёл Zenith в этом профиле — несколько
прогонов каждого на ОДНОМ и том же домене, не один шанс: единичный замер
latency/success слишком шумный (кэш, TCP fast open, разовый джиттер),
чтобы честно сравнивать 452ms из одного раунда с 155ms из другого.

    python3 compare_control.py --profile RKN_TLS --trials 5
"""
import argparse
import sys
import time

import controls
import db
import sandbox_apply
import tester

TOP_N = 3
SETTLE_SECONDS = 3


def probe_n(lua_lines: list, domain: dict, trials: int) -> list:
    results = []
    for _ in range(trials):
        if not sandbox_apply.apply_raw(controls.PROFILE_FILTER, lua_lines):
            print("  не удалось применить в песочнице, пропуск попытки", file=sys.stderr)
            continue
        time.sleep(SETTLE_SECONDS)
        results.append(tester.probe(domain["host"], domain["path"], domain["min_bytes"]))
    return results


def summarize(name: str, results: list) -> None:
    if not results:
        print(f"  {name}: нет результатов")
        return
    n = len(results)
    ok = sum(1 for r in results if r[0])
    avg_bytes = sum(r[1] for r in results) / n
    successful_latencies = [r[2] for r in results if r[0]]
    avg_latency = sum(successful_latencies) / len(successful_latencies) if successful_latencies else None
    latency_str = f"{avg_latency:.0f}ms" if avg_latency is not None else "n/a"
    print(f"  {name}: {ok}/{n} OK, avg_bytes={avg_bytes:.0f}, avg_latency(успешных)={latency_str}")


def run(profile: str, trials: int) -> int:
    conn = db.connect()
    domains = db.get_domains_for_profile(conn, profile)
    if not domains:
        print(f"Нет доменов для {profile}", file=sys.stderr)
        return 1
    domain = domains[0]
    print(f"Домен для сравнения: {domain['host']} (фиксированный, для честности)")

    control = controls.get_control(profile)
    print("\n=== control (боевой, ручной) ===")
    if control:
        for line in control:
            print(f"  {line}")
        summarize("control", probe_n(control, domain, trials))
    else:
        print(f"  нет control-генома для {profile}, сравнивать не с чем", file=sys.stderr)

    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT g.id, g.rendered_args,
                  SUM(gs.pulls) AS pulls, SUM(gs.successes) AS successes,
                  ROUND(SUM(gs.total_reward) / NULLIF(SUM(gs.pulls), 0), 3) AS avg_score
           FROM genome_scores gs
           JOIN genomes g ON g.id = gs.genome_id AND g.profile = %s
           GROUP BY g.id, g.rendered_args
           HAVING successes > 0
           ORDER BY avg_score DESC
           LIMIT %s""",
        (profile, TOP_N),
    )
    top = cur.fetchall()
    conn.close()

    if not top:
        print("\nНет успешных сгенерированных геномов в БД для этого профиля ещё.")
        return 0

    print(f"\n=== топ-{len(top)} сгенерированных Zenith (по накопленному avg_score) ===")
    for row in top:
        print(f"\n  {row['rendered_args']}  (было пулов={row['pulls']}, успехов={row['successes']}, avg_score={row['avg_score']})")
        summarize("generated", probe_n([row["rendered_args"]], domain, trials))

    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True, choices=["YT_TLS", "RKN_TLS", "DS_TLS"])
    ap.add_argument("--trials", type=int, default=5)
    args = ap.parse_args()
    sys.exit(run(args.profile, args.trials))
