#!/usr/bin/env python3
"""host_tune.py -- перебор кандидатов host=X (домен-приманка для
hostfakesplit-стратегий) ТОЛЬКО В ПЕСОЧНИЦЕ, ни разу не трогая боевой
/opt/zapret2/config -- тот же принцип "сначала песочница", что у main.py,
просто без записи в genome-БД (это разовый диагностический инструмент,
не часть UCB-цикла подбора).

Живой повод: боевые strategy=61/63 (RKN_TLS/YT_TLS/GV_TLS, общий шаблон
z2r_tcp_tls_common) -- обе hostfakesplit, но НЕ отличаются только host=:
  61: hostfakesplit:disorder_after:tcp_ack=-66000:tcp_ts_up:repeats=2   (host= нет вообще)
  63: hostfakesplit:host=ozon.ru:tcp_ack=-66000:tcp_ts_up:repeats=3     (disorder_after нет, repeats=3)
Сравнивать их напрямую как "разница только в домене" -- НЕЧЕСТНО, есть и
другие различия. Этот инструмент фиксирует ВСЕ остальные параметры явно
(--disorder-after/--fooling/--repeats) и варьирует ТОЛЬКО host_template,
плюс baseline БЕЗ host= вообще -- честное сравнение "нужен ли host= и
если да, то какой".

Кандидаты host= -- ИЗ ОФИЦИАЛЬНОГО "белого списка" (домены, которые
DPI/ISP обязаны никогда не блокировать), не произвольные: раз DPI не
имеет права блокировать эти домены, десинхронизация с ними в роли
decoy-приманки должна быть максимально устойчивой везде. Список НЕ
встроен в репозиторий (внешний, обновляется независимо, могут быть
тысячи строк) -- передаётся файлом через --candidates-file, каждый
кандидат обходится в песочнице ДЁШЕВО (перезапуск изолированного
nfqws2, не боевого), но curl-проба всё равно требует времени, поэтому
по умолчанию берём РАВНОМЕРНУЮ выборку --limit кандидатов из файла, а
не весь список -- тот же принцип, что у blob_tune.sh ("курируемый
список кандидатов, не все 111 файлов").

Использование:
  sudo venv/bin/python3 host_tune.py --profile YT_TLS \
      --candidates-file whitelist.txt --limit 20 \
      --test-host www.youtube.com --test-path /
"""
import argparse
import random
import time

import config
import genome
import sandbox_apply
import tester

BASE_SETTLE_SECONDS = 3
MIN_BYTES_THRESHOLD = 65536
DEFAULT_TEST = {
    "YT_TLS": ("www.youtube.com", "/"),
    "RKN_TLS": ("meduza.io", "/"),
    "DS_TLS": ("discord.com", "/"),
}


def _load_candidates(path: str, limit: int) -> list:
    with open(path) as f:
        domains = [line.strip().lower() for line in f if line.strip() and not line.startswith("#")]
    seen = set()
    unique = []
    for d in domains:
        if d not in seen:
            seen.add(d)
            unique.append(d)
    if len(unique) <= limit:
        return unique
    # Равномерная выборка по всему файлу (не только начало) -- у
    # реальных whitelist-файлов соседние строки часто субдомены ОДНОГО
    # и того же сайта (см. живой пример: 00-19.img.avito.st подряд),
    # взять первые N дало бы почти нулевое разнообразие доменов.
    step = len(unique) / limit
    return [unique[int(i * step)] for i in range(limit)]


def _make_genome(profile: str, host_template: str | None, disorder_after: bool, fooling: str, repeats: int):
    return genome.Genome(
        profile=profile,
        family="hostfakesplit",
        host_template=host_template,
        disorder_after=disorder_after,
        fooling=fooling or None,
        repeats=repeats or None,
    )


def _score_candidate(g, test_host: str, test_path: str, attempts: int) -> dict:
    if not sandbox_apply.apply_genome(g):
        return {"applied": False, "successes": 0, "attempts": attempts, "avg_bytes": 0, "avg_ms": 0, "error": sandbox_apply.LAST_ERROR}
    time.sleep(BASE_SETTLE_SECONDS)
    successes = 0
    total_bytes = 0
    total_ms = 0
    for _ in range(attempts):
        ok, bytes_, ms = tester.probe(test_host, test_path, MIN_BYTES_THRESHOLD)
        if ok:
            successes += 1
            total_bytes += bytes_
        total_ms += ms
    return {
        "applied": True, "successes": successes, "attempts": attempts,
        "avg_bytes": (total_bytes // successes) if successes else 0,
        "avg_ms": total_ms // attempts,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default="YT_TLS", choices=list(genome.PROFILE_FILTERS.keys()))
    ap.add_argument("--candidates-file", required=True, help="один домен на строку, напр. официальный белый список")
    ap.add_argument("--limit", type=int, default=20, help="сколько кандидатов реально протестировать (равномерная выборка из файла)")
    ap.add_argument("--attempts", type=int, default=3, help="проб на кандидата (curl через песочницу)")
    ap.add_argument("--disorder-after", action="store_true", help="фиксированный параметр остальной части генома, см. докстринг про 61 vs 63")
    ap.add_argument("--fooling", default="tcp_ack=-66000:tcp_ts_up")
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--test-host", default=None)
    ap.add_argument("--test-path", default="/")
    ap.add_argument("--seed", type=int, default=0, help="для воспроизводимости, если понадобится")
    args = ap.parse_args()
    random.seed(args.seed)

    test_host = args.test_host or DEFAULT_TEST.get(args.profile, (None, None))[0]
    test_path = args.test_path or DEFAULT_TEST.get(args.profile, (None, "/"))[1]
    if not test_host:
        print(f"Нет дефолтного тестового хоста для профиля {args.profile} -- передай --test-host явно.")
        return 1

    candidates = _load_candidates(args.candidates_file, args.limit)
    print(f"=== host_tune.py: профиль={args.profile}, тест={test_host}{test_path}, "
          f"disorder_after={args.disorder_after}, fooling={args.fooling}, repeats={args.repeats} ===")
    print(f"Кандидатов host= (из {args.candidates_file}, выборка): {len(candidates)}")
    print("ВНИМАНИЕ: только песочница (zenith-sandbox), боевой /opt/zapret2/config не трогается вообще.\n")

    results = []

    print("--- Baseline: без host= вообще ---")
    g = _make_genome(args.profile, None, args.disorder_after, args.fooling, args.repeats)
    r = _score_candidate(g, test_host, test_path, args.attempts)
    r["host"] = "(нет host=)"
    results.append(r)
    print(f"  {r}")

    for host in candidates:
        print(f"--- Кандидат: host={host} ---")
        g = _make_genome(args.profile, host, args.disorder_after, args.fooling, args.repeats)
        r = _score_candidate(g, test_host, test_path, args.attempts)
        r["host"] = host
        results.append(r)
        print(f"  {r}")

    results.sort(key=lambda r: (r["successes"], -r["avg_ms"], r["avg_bytes"]), reverse=True)
    print("\n=== Итог (лучшие первыми) ===")
    print(f"{'host=':<40} {'успехов':<10} {'avg_bytes':<12} {'avg_ms'}")
    for r in results:
        note = "" if r.get("applied", True) else f"  [не применился: {r.get('error', '')}]"
        print(f"{r['host']:<40} {r['successes']}/{r['attempts']:<8} {r['avg_bytes']:<12} {r['avg_ms']}{note}")

    print(
        "\nЭто ТОЛЬКО измерение в песочнице, ничего не применяет в проде. "
        "Победителя нужно вручную перенести в боевой шаблон (см. z2r_autobench/"
        "promote_apply_cli.sh TEMPLATE-режим, если это НОВАЯ строка strategy=, "
        "или set_strategy_cli.sh, если уже существующая strategy=N подходит)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
