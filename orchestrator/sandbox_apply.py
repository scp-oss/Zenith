"""Применяет геном в песочнице: переписывает только строки фильтра
(--filter-tcp=/--filter-udp=/--filter-l7=/--hostlist=/--hostlist-exclude=/
--hostlist-domains=/--payload=) и --lua-desync= в живом конфиге
(qnum/user/daemon/pidfile/debug/lua-init/--blob= не трогает) и дёшево
перезапускает изолированный nfqws2 через sandbox/start_sandbox.sh. Боевой
/opt/zapret2 этот модуль не видит вообще.
"""
import subprocess

import config
import genome

CONF_PATH = f"{config.SANDBOX_DIR}/nfqws2_sandbox.conf"
_REWRITE_PREFIXES = (
    "--filter-tcp=", "--filter-udp=", "--filter-l7=",
    "--hostlist=", "--hostlist-exclude=", "--hostlist-domains=",
    "--payload=", "--lua-desync=",
    # GV_TLS + wssize_ramp (genome.render_lines) пишет диапазоны и L3-фильтр
    # -- их тоже надо вычищать между геномами, иначе они «прилипнут».
    "--out-range=", "--in-range=", "--filter-l3=",
)

# Живой случай на Server B (Provider B) 2026-08-26: apply_raw() возвращал только bool,
# а все вызывающие (main.py и т.д.) на "не удалось" печатали один и тот же
# универсальный текст без деталей -- реальный stderr от финального
# start_sandbox.sh (там, где nfqws2 фактически не поднялся) нигде не
# показывался, и 20 раундов подряд диагноз был "start_sandbox.sh вернул
# ошибку" без единого намёка, ПОЧЕМУ. Не меняем сигнатуру apply_raw() (её
# уже вызывают как bool в трёх местах) -- вместо этого кладём подробности
# сюда, чтобы вызывающий код мог сам решить, показывать их или нет.
LAST_ERROR = ""

# Общий лок песочницы (2026-11-13): песочницу делят Zenith (TCP-геномы) и
# z2r_test-voice-bot (голосовые пробы autotune/Zenith VOICE_UDP). Без лока
# бот каждые ~13 с переписывал конфиг своей голосовой стратегией прямо
# посреди TCP-раунда -- геном мерился в чужом конфиге (ложные провалы).
# apply_raw() берёт лок и ДЕРЖИТ его, вызывающий отпускает release() сразу
# после пробы. Бот открывает тот же файл только на чтение -- для flock
# этого достаточно.
import fcntl as _fcntl
import os as _os
LOCK_FILE = f"{config.SANDBOX_DIR}/.sandbox.lock"
_lock_fd = None


def acquire():
    global _lock_fd
    if _lock_fd is not None:
        return
    fd = _os.open(LOCK_FILE, _os.O_RDONLY | _os.O_CREAT, 0o644)
    _fcntl.flock(fd, _fcntl.LOCK_EX)
    _lock_fd = fd


def release():
    global _lock_fd
    if _lock_fd is None:
        return
    try:
        _fcntl.flock(_lock_fd, _fcntl.LOCK_UN)
    finally:
        _os.close(_lock_fd)
        _lock_fd = None


def apply_raw(profile_filter_lines: list, lua_desync_lines: list) -> bool:
    """Применяет произвольный набор строк (фильтр + один или несколько
    --lua-desync=), минуя Genome — нужен для control-геномов при проверке
    подозрения на бан (см. main.py), которые могут быть многоинстансными
    (как реальная боевая strategy=5: multisplit+fakeddisorder), а текущая
    модель Genome одноинстансная. profile_filter_lines -- список строк
    (см. genome.PROFILE_FILTERS), не одна строка: реальный боевой фильтр
    профиля -- это несколько --hostlist=/--payload= строк, не только
    --filter-tcp=."""
    acquire()
    try:
        with open(CONF_PATH) as f:
            lines = f.readlines()
    except FileNotFoundError:
        # Живой случай на Server B (Provider B) 2026-08-26: setup_sandbox.sh (одноразовая
        # настройка -- юзер + iptables NFQUEUE-правило + queue_num) был
        # выполнен, но start_sandbox.sh -- НЕТ, поэтому nfqws2_sandbox.conf
        # ни разу не сгенерился из шаблона. Раньше это было RuntimeError,
        # которое main.py ничем не ловило -- процесс падал молча (traceback
        # в stderr, который никто не смотрел), а zenith_autorun.sh всё равно
        # печатал "профиль завершён", как будто прогон 20 раундов прошёл
        # нормально. По факту КАЖДЫЙ TCP-профиль (YT_TLS/RKN_TLS/DS_TLS)
        # падал на первом же геноме (seed) все дни подряд -- 0 локальных
        # прогонов, что и объясняло "0 геномов" на панели задолго до
        # проблемы с sync_client.py (см. CLAUDE.md). start_sandbox.sh сам
        # генерит конфиг из шаблона при отсутствии (см. его докстринг --
        # "дёшево и безопасно перезапускать часто") и требует только
        # queue_num от уже сделанного setup_sandbox.sh -- если и того нет,
        # start_sandbox.sh сам откажет с понятной ошибкой, это НЕ пытаемся
        # чинить автоматически (одноразовая ручная настройка, не наше дело).
        result = subprocess.run(
            [f"{config.SANDBOX_DIR}/start_sandbox.sh"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"{CONF_PATH} не найден, автоматический start_sandbox.sh тоже не удался "
                f"(код {result.returncode}): {result.stderr.strip() or result.stdout.strip()}\n"
                "Если это самый первый раз -- нужен ручной setup_sandbox.sh (одноразово, руками)."
            )
        try:
            with open(CONF_PATH) as f:
                lines = f.readlines()
        except FileNotFoundError:
            raise RuntimeError(
                f"start_sandbox.sh отработал (код 0), но {CONF_PATH} всё равно не появился -- "
                "разберись руками."
            )

    # Строки, не начинающиеся с "--" (и не комментарии) -- обрывки чужих
    # многострочных записей (видели на NETH-4 2026-11-13: "y=1",
    # "l=0,3-20:out_range=-d10:strategy=16"), выкидываем.
    kept = [ln for ln in lines if not ln.strip().startswith(_REWRITE_PREFIXES)
            and (not ln.strip() or ln.strip().startswith(("--", "#")))]
    for line in profile_filter_lines:
        kept.append(line + "\n")
    for line in lua_desync_lines:
        kept.append(line + "\n")

    with open(CONF_PATH, "w") as f:
        f.writelines(kept)

    global LAST_ERROR
    result = subprocess.run(
        [f"{config.SANDBOX_DIR}/start_sandbox.sh"],
        capture_output=True, text=True, timeout=15,
    )
    LAST_ERROR = "" if result.returncode == 0 else (result.stderr.strip() or result.stdout.strip())
    return result.returncode == 0


def apply_genome(g) -> bool:
    lines = g.render_lines() if hasattr(g, "render_lines") else [g.render_args()]
    return apply_raw(genome.PROFILE_FILTERS[g.profile], lines)
