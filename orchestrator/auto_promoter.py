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
     (узкий, самопроверяющий скрипт -- см. его докстринг: блок профиля
     находит СТРОГО по точному совпадению заголовка с genome.PROFILE_FILTERS,
     не по имени/позиции; backup ПЕРЕД каждой записью, ОТКАЗ при
     расхождении ожидаемого/реального max).
  3. Переключение -- set_strategy_cli.sh set, затем restart zapret2.
  4. Проверка -- zapret2 реально running, get подтверждает новый номер.
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
import genome as genome_mod
from promote import PROFILE_NUMBERS, PROFILE_PROTO, pick_best

SETTLE_SECONDS = 3
SET_STRATEGY_CLI = f"{config.Z2R_AUTOBENCH_DIR}/set_strategy_cli.sh"
PROMOTE_APPLY_CLI = f"{config.Z2R_AUTOBENCH_DIR}/promote_apply_cli.sh"


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
    header = genome_mod.PROFILE_FILTERS[profile]

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

        spec = "HEADER\n" + "\n".join(header) + "\nBODY\n" + "\n".join(candidate["rendered_args"].split("\n")) + "\n"
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

        _mark_promoted(conn, candidate["id"], env_id, int(strategy_n))
        return (
            f"{profile}: геном {candidate['id'][:12]} продвинут как strategy={strategy_n} "
            f"(avg_score={candidate['avg_score']}, pulls={candidate['pulls']})."
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
    runnable = [p for p in PROFILE_NUMBERS if p in genome_mod.PROFILE_FILTERS]

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
