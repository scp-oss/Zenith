#!/usr/bin/env python3
"""Автопродвижение Zenith-геномов в /opt/zapret2/config БЕЗ участия
человека -- CLI-инструмент, работает НЕЗАВИСИМО от z0r-panel (панель
опциональна, см. CLAUDE.md z2r_autobench: "панель это модуль... функционал
должен быть в CLI и без панели"). Если панель установлена, её карточка
"Автопродвижение в прод" на /controls -- ТОЛЬКО пульт (start/stop/log) над
systemd-юнитом zenith-promoter.service, который запускает этот же скрипт;
вся логика здесь, не в панели.

Отличие от promote.py: тот НИЧЕГО сам не применяет (Zenith исторически не
имел exec-доступа к боевому серверу -- см. его докстринг), только печатает
инструкцию человеку. Этот -- РЕАЛЬНО применяет, это осознанное изменение
границ (по прямому запросу "цель: автономная работа без человеческого
вмешательства"), поэтому:

  1. Критерий выбора -- ТОТ ЖЕ, что promote.py::pick_best() (100% успехов,
     --min-pulls прогонов, лучший avg_score), только дополнительно
     пропускает уже продвинутые геномы (genome_scores.promoted_strategy
     IS NOT NULL).
  2. Новый strategy=N блок пишется через z2r_autobench/promote_apply_cli.sh
     (узкий, самопроверяющий скрипт -- см. её докстринг: блок находит
     СТРОГО по точному совпадению заголовка ИЛИ по имени общего шаблона
     (--template=<имя>), см. PROFILE_TARGETS ниже -- не по имени профиля,
     не по позиции; backup ПЕРЕД каждой записью, ОТКАЗ при расхождении
     ожидаемого/реального max).
  3. Переключение -- set_strategy_cli.sh set, затем restart zapret2.
  4. Проверка -- zapret2 реально running, get подтверждает новый номер,
     И (кроме VOICE_UDP) РЕАЛЬНЫЙ curl по доменам профиля из domain_pool
     -- живой инцидент 2026-08-16: geном YT_TLS прошёл sandbox 6/6
     (avg_score=0.965), но полностью не работал в проде (timeout на
     www.youtube.com) -- systemctl is-active/get этого НЕ ловят, нужен
     именно живой HTTP-запрос. tester.py::probe() тут не годится -- та
     тестирует ТОЛЬКО zenith-sandbox юзера через отдельный iptables-скоуп,
     не то, что видят обычные пользователи через боевой zapret2.
  5. Не подтвердилось -- promote_apply_cli.sh restore (откат конфига из
     backup) + возврат старой стратегии + restart. Прод никогда не
     остаётся в непроверенном состоянии без отката.
  6. Успех -- genome_scores.promoted_strategy = N.

Требует ZENITH_DB_MODE=docker (прямой MySQL, как и promote.py -- raw SQL
курсоры, не HTTP db_api.py) и root (пишет /opt/zapret2/config, рестартует
zapret2.service -- см. zenith-promoter.service, User=root, тот же паттерн,
что autotune-daemon.service в z2r_autobench).

    # разовый проход по одному профилю (для ручной проверки перед --loop)
    sudo venv/bin/python3 auto_promoter.py --profile RKN_TLS

    # непрерывный цикл по всем профилям (см. zenith-promoter.service)
    sudo venv/bin/python3 auto_promoter.py --loop --interval-minutes 240
"""
import argparse
import subprocess
import sys
import time

import config
import db
from promote import PROFILE_NUMBERS, PROFILE_PROTO

SETTLE_SECONDS = 3
SET_STRATEGY_CLI = f"{config.Z2R_AUTOBENCH_DIR}/set_strategy_cli.sh"
PROMOTE_APPLY_CLI = f"{config.Z2R_AUTOBENCH_DIR}/promote_apply_cli.sh"

# Как найти блок для вставки нового strategy=N -- ДВА разных паттерна в
# реальном /opt/zapret2/config (см. promote_apply_cli.sh докстринг про
# HEADER/TEMPLATE), НЕ то же самое, что Zenith'овский genome.py::
# PROFILE_FILTERS (тот описывает фильтр для ПЕСОЧНИЦЫ -- синтетическому
# applier'у одного генома circular_locked/--import не нужны вообще, это
# чисто продовый механизм выбора СРЕДИ НЕСКОЛЬКИХ уже загруженных
# strategy=). Значения ниже сверены ВЖИВУЮ на конкретном сервере
# (NETH-4) 2026-08-16 -- см. CLAUDE.md Zenith про то, что конфиги на
# разных серверах могут расходиться; при расхождении
# promote_apply_cli.sh откажет БЕЗОПАСНО (не найдёт якорь/блок пуст),
# не испортит файл -- но само автопродвижение для профиля работать не
# будет, пока эти значения не перепроверены под конкретный сервер.
#
#   ("template", <имя>) -- профиль сам не содержит strategy=N, только
#     --import=<имя> общий шаблон (--template=<имя> в другом месте
#     файла) -- ТУДА и нужно писать. Несколько профилей МОГУТ делить
#     один и тот же шаблон (живой пример: YT_TLS и RKN_TLS оба
#     --import=z2r_tcp_tls_common) -- это не баг и не риск (кто что
#     выберет через circular_locked:key=N -- решает set_strategy_cli.sh
#     set отдельно, добавление нового номера в шаблон само по себе
#     ничего не переключает).
#   ("header", [строки]) -- профиль самодостаточен, strategy=N лежат
#     прямо в его собственном блоке сразу после этих строк заголовка
#     (точное посимвольное совпадение, по порядку).
PROFILE_TARGETS = {
    "YT_TLS": ("template", "z2r_tcp_tls_common"),
    "RKN_TLS": ("template", "z2r_tcp_tls_common"),
    "DS_TLS": ("header", [
        "--filter-tcp=80,443,2053,2083,2087,2096,8443 --hostlist=/opt/zapret2/extra_strats/TCP_Discord.txt",
        "--hostlist-exclude=/opt/zapret2/lists/netrogat.txt",
        "--payload=tls_client_hello,http_req,http_reply,unknown,tls_server_hello",
        "--out-range=-s34228",
        "--in-range=-s32768 --lua-desync=circular_locked:key=4",
        "--in-range=x",
        "--payload=tls_client_hello,discord_ip_discovery",
    ]),
    "VOICE_UDP": ("header", [
        "--filter-udp=443,2053,2083,2087,2096,8443,50000-50099,1400,3478-3481,5349,19294-19344",
        "--filter-l7=discord,stun",
        "--lua-desync=circular_locked:key=6:proto=udp:allow_nohost=1:exclude_hostlist=/opt/zapret2/lists/netrogat.txt",
        "--payload=discord_ip_discovery,stun",
    ]),
}


def _run(cmd: list, timeout: int = 20, input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=input_text)


def _get_strategy(num: int, proto: str) -> str | None:
    out = _run(["bash", SET_STRATEGY_CLI, "get", str(num), proto])
    return out.stdout.strip() if out.returncode == 0 else None


def _max_strategy(num: int) -> str | None:
    out = _run(["bash", SET_STRATEGY_CLI, "max", str(num)])
    return out.stdout.strip() if out.returncode == 0 else None


def _set_strategy(num: int, proto: str, strategy: str) -> bool:
    return _run(["bash", SET_STRATEGY_CLI, "set", str(num), proto, strategy]).returncode == 0


def _restart_zapret2() -> bool:
    return _run(["systemctl", "restart", "zapret2"], timeout=30).returncode == 0


def _zapret2_running() -> bool:
    out = _run(["systemctl", "show", "zapret2", "--property=SubState"])
    return out.returncode == 0 and "SubState=running" in out.stdout


def _probe_real(host: str, path: str, min_bytes: int, timeout: int = 8) -> tuple:
    """curl БЕЗ sudo -u <sandbox-юзер> -- обычный процесс, обычный
    маршрут через боевой zapret2, то же самое, что видит любой реальный
    пользователь этого сервера (в отличие от tester.py::probe(), см. её
    докстринг -- та нарочно СКОУПЛЕНА на zenith-sandbox отдельным
    iptables-правилом)."""
    url = f"https://{host}{path or '/'}"
    try:
        out = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{size_download}",
             "--connect-timeout", "5", "--max-time", str(timeout), url],
            capture_output=True, text=True, timeout=timeout + 3,
        )
        bytes_ = int((out.stdout or "0").strip() or 0)
    except Exception:
        bytes_ = 0
    return bytes_ >= min_bytes, bytes_


def _real_traffic_check(conn, profile: str) -> tuple:
    """Живая проверка ПОСЛЕ restart+set, по всем доменам профиля из
    domain_pool -- ровно то, что promote.py уже давно печатает человеку
    в чеклисте ("После переключения — проверить живым трафиком... на
    КАЖДОМ домене профиля"), просто теперь исполняется, а не только
    напоминается. VOICE_UDP пропускается -- нет HTTP-домена для curl
    (см. domain_pool 'discord-voice-test' placeholder, min_bytes=0),
    честного эквивалента живой Discord-проверки без второго похода в
    z2r_test-voice-bot тут нет -- эта проверка для VOICE_UDP остаётся
    слабее (только is-active/get), знать об этом ограничении важно
    оператору, не прятать его молча."""
    if profile == "VOICE_UDP":
        return True, "VOICE_UDP -- живая HTTP-проверка недоступна, пропуск (см. докстринг)"
    domains = db.get_domains_for_profile(conn, profile)
    if not domains:
        return True, "нет доменов в domain_pool для этого профиля -- нечем проверить, пропуск"
    for d in domains:
        ok, bytes_ = _probe_real(d["host"], d["path"], d["min_bytes"])
        if not ok:
            return False, f"{d['host']}{d['path']}: {bytes_} байт (нужно {d['min_bytes']}+)"
    return True, f"{len(domains)} домен(ов) прошли живую проверку"


def _pick_promotable(conn, profile: str, environment_id: int, min_pulls: int):
    """pick_best() берёт ЛУЧШИЙ по avg_score среди подходящих -- если этот
    геном уже продвинут, надо не пропускать профиль целиком (вдруг есть
    следующий по качеству), а просто исключить уже продвинутые прямо в
    SQL. Не переиспользую pick_best() как чёрный ящик -- почти идентичный
    запрос, но с доп. условием и без промежуточного re-check."""
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT g.id, g.rendered_args, g.source, g.generation,
                  gs.pulls, gs.successes,
                  ROUND(gs.total_reward / NULLIF(gs.pulls, 0), 3) AS avg_score
           FROM genome_scores gs
           JOIN genomes g ON g.id = gs.genome_id AND g.profile = %s
           WHERE gs.environment_id = %s AND g.family != 'control'
             AND gs.pulls >= %s AND gs.successes = gs.pulls
             AND gs.promoted_strategy IS NULL
           ORDER BY avg_score DESC
           LIMIT 1""",
        (profile, environment_id, min_pulls),
    )
    return cur.fetchone()


def _mark_promoted(conn, genome_id: str, environment_id: int, strategy_n: int) -> None:
    cur = conn.cursor()
    cur.execute(
        "UPDATE genome_scores SET promoted_strategy=%s WHERE genome_id=%s AND environment_id=%s",
        (strategy_n, genome_id, environment_id),
    )


def _rollback(profile: str, num: int, proto: str, backup_path: str, old_locked: str | None) -> str:
    if not backup_path:
        return f"{profile}: ОТКАТ НЕВОЗМОЖЕН -- путь к backup не распознан из вывода apply. Нужно вмешательство человека."
    restore_out = _run(["bash", PROMOTE_APPLY_CLI, "restore", backup_path, config.ZAPRET2_CONFIG_PATH])
    if restore_out.returncode != 0:
        return f"{profile}: ОТКАТ КОНФИГА НЕ УДАЛСЯ -- {restore_out.stderr.strip()}. Нужно вмешательство человека, backup: {backup_path}"
    if old_locked and old_locked.isdigit():
        _set_strategy(num, proto, old_locked)
    _restart_zapret2()
    return f"{profile}: откат выполнен -- конфиг восстановлен из {backup_path}, strategy вернута на {old_locked}."


def try_promote(profile: str, environment_name: str, provider: str, min_pulls: int) -> str:
    """Один проход по одному профилю. Возвращает человекочитаемую строку
    результата (успех/пропуск/откат) -- вызывающий (CLI или --loop) сам
    решает, печатать её или писать в лог."""
    num = PROFILE_NUMBERS[profile]
    proto = PROFILE_PROTO.get(profile, "tls")
    target_kind, target_value = PROFILE_TARGETS[profile]

    conn = db.connect()
    try:
        env_id = db.get_or_create_environment(conn, environment_name, provider)
        candidate = _pick_promotable(conn, profile, env_id, min_pulls)
        if not candidate:
            return f"{profile}: нет непродвинутого кандидата с {min_pulls}+ прогонами и 100% успехом -- пропуск."

        current_max = _max_strategy(num)
        if current_max is None or not current_max.isdigit():
            return f"{profile}: не удалось прочитать текущий max strategy= -- пропуск."
        old_locked = _get_strategy(num, proto)

        if target_kind == "template":
            spec = f"TEMPLATE\n{target_value}\n"
        else:
            spec = "HEADER\n" + "\n".join(target_value) + "\n"
        spec += "BODY\n" + "\n".join(candidate["rendered_args"].split("\n")) + "\n"
        apply_out = _run(
            ["bash", PROMOTE_APPLY_CLI, "apply", current_max, config.ZAPRET2_CONFIG_PATH, config.PROMOTE_BACKUP_DIR],
            input_text=spec,
        )
        if apply_out.returncode != 0:
            return f"{profile}: promote_apply_cli.sh apply отказал -- {apply_out.stderr.strip()}"

        strategy_n = apply_out.stdout.strip()
        backup_line = next((l for l in apply_out.stderr.splitlines() if l.startswith("backup: ")), "")
        backup_path = backup_line[len("backup: "):].strip()

        if not _set_strategy(num, proto, strategy_n) or not _restart_zapret2():
            return _rollback(profile, num, proto, backup_path, old_locked)

        time.sleep(SETTLE_SECONDS)
        if not _zapret2_running() or _get_strategy(num, proto) != strategy_n:
            return _rollback(profile, num, proto, backup_path, old_locked)

        traffic_ok, traffic_detail = _real_traffic_check(conn, profile)
        if not traffic_ok:
            rollback_msg = _rollback(profile, num, proto, backup_path, old_locked)
            return f"{rollback_msg} Причина: живая проверка не прошла -- {traffic_detail}."

        _mark_promoted(conn, candidate["id"], env_id, int(strategy_n))
        return (
            f"{profile}: геном {candidate['id'][:12]} продвинут как strategy={strategy_n} "
            f"(avg_score={candidate['avg_score']}, pulls={candidate['pulls']}, {traffic_detail})."
        )
    finally:
        conn.close()


def run_loop(profiles: list, environment_name: str, provider: str, min_pulls: int, interval_minutes: int) -> None:
    idx = 0
    while True:
        profile = profiles[idx % len(profiles)]
        idx += 1
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {try_promote(profile, environment_name, provider, min_pulls)}", flush=True)
        time.sleep(interval_minutes * 60)


if __name__ == "__main__":
    runnable = [p for p in PROFILE_NUMBERS if p in PROFILE_TARGETS]

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", choices=runnable, help="один проход по этому профилю (без --loop)")
    ap.add_argument("--loop", action="store_true", help="непрерывный цикл по кругу (см. zenith-promoter.service)")
    ap.add_argument("--interval-minutes", type=int, default=240, help="пауза между срабатываниями в --loop")
    ap.add_argument("--environment", default=config.LOCAL_ENVIRONMENT_NAME)
    ap.add_argument("--provider", default=config.LOCAL_ENVIRONMENT_PROVIDER)
    ap.add_argument("--min-pulls", type=int, default=5)
    args = ap.parse_args()

    if args.loop:
        run_loop(runnable, args.environment, args.provider, args.min_pulls, args.interval_minutes)
    elif args.profile:
        print(try_promote(args.profile, args.environment, args.provider, args.min_pulls))
    else:
        print("Нужен --profile <профиль> (разовый проход) или --loop (непрерывный цикл)", file=sys.stderr)
        sys.exit(1)
