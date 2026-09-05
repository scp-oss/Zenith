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
     IS NOT NULL). С 2026-09-05 -- ЕЩЁ и требует, чтобы avg_score
     кандидата был СТРОГО лучше avg_score текущей живой strategy=N (см.
     _get_champion_score()/CLAUDE.md "require a genuine improvement") --
     иначе на плато (новые геномы стабильно дотягивают до порога, но не
     превосходят уже живой) продвижение повторялось бы вхолостую на
     каждом цикле ради равноценной/худшей замены, тратя реальный риск
     живой проверки без всякой пользы.
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
import json
import os
import subprocess
import sys
import time

import config
import db
from promote import PROFILE_NUMBERS, PROFILE_PROTO

SETTLE_SECONDS = 3
# Сколько раз ЖИВАЯ проверка (не другие причины отката) должна провалиться
# подряд для ОДНОГО генома, прежде чем он временно исключается из отбора --
# см. CLAUDE.md "Live-check quarantine". 2, не 1 -- единичный провал может
# быть разовой сетевой помехой, не обязательно виной самого генома.
LIVE_CHECK_FAIL_THRESHOLD = 2
LIVE_CHECK_QUARANTINE_DAYS = 3
SET_STRATEGY_CLI = f"{config.Z2R_AUTOBENCH_DIR}/set_strategy_cli.sh"
PROMOTE_APPLY_CLI = f"{config.Z2R_AUTOBENCH_DIR}/promote_apply_cli.sh"

# Как найти блок для вставки нового strategy=N -- ДВА разных паттерна в
# реальном /opt/zapret2/config (см. promote_apply_cli.sh докстринг про
# HEADER/TEMPLATE), НЕ то же самое, что Zenith'овский genome.py::
# PROFILE_FILTERS (тот описывает фильтр для ПЕСОЧНИЦЫ -- синтетическому
# applier'у одного генома circular_locked/--import не нужны вообще, это
# чисто продовый механизм выбора СРЕДИ НЕСКОЛЬКИХ уже загруженных
# strategy=). Значения ниже сверены ВЖИВУЮ на конкретном сервере
# (Server A) 2026-08-16 -- см. CLAUDE.md Zenith про то, что конфиги на
# разных серверах могут расходиться; при расхождении
# promote_apply_cli.sh откажет БЕЗОПАСНО (не найдёт якорь, или найдёт
# его больше одного раза -- см. её же анти-неоднозначность фикс от
# 2026-08-17 -- в обоих случаях просто откажется писать), не испортит
# файл -- но само автопродвижение для профиля работать не будет, пока
# эти значения не перепроверены под конкретный сервер.
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
# Хардкод /opt/zapret2/... ниже (DS_TLS/VOICE_UDP) был тем же классом
# бага, что уже пять раз находили и чинили в genome.py::PROFILE_FILTERS/
# sandbox/nfqws2_sandbox.conf.template/sandbox_apply.py -- см.
# z2r_autobench/CLAUDE.md "/opt/zapret2 vs /opt/zator". Найден здесь,
# в ШЕСТОЙ раз, 2026-09-04 на Server NETH-4 (свежий "Server A"-профиль
# сверки от 2026-08-16 никогда не обновлялся под split-base серверы):
# `promote_apply_cli.sh` искал ЭТУ буквальную строку в живом конфиге,
# который на деле содержит `/opt/zator/extra_strats/TCP_Discord.txt`
# (тот же файл, другая база) -- "Заголовок блока не найден" на КАЖДОМ
# цикле auto_promoter.py для DS_TLS, без единого успешного продвижения,
# минимум с 2026-08-27. `config.Z2R_BASE` уже решает ровно эту проблему
# для genome.py -- используем его и здесь, тем же f-string идиомом.
_PROFILE_TARGETS_DEFAULTS = {
    "YT_TLS": ("template", "z2r_tcp_tls_common"),
    "RKN_TLS": ("template", "z2r_tcp_tls_common"),
    "DS_TLS": ("header", [
        f"--filter-tcp=80,443,2053,2083,2087,2096,8443 --hostlist={config.Z2R_BASE}/extra_strats/TCP_Discord.txt",
        f"--hostlist-exclude={config.Z2R_BASE}/lists/netrogat.txt",
        "--payload=tls_client_hello,http_req,http_reply,unknown,tls_server_hello",
        "--out-range=-s34228",
        "--in-range=-s32768 --lua-desync=circular_locked:key=4",
        "--in-range=x",
        "--payload=tls_client_hello,discord_ip_discovery",
    ]),
    "VOICE_UDP": ("header", [
        "--filter-udp=443,2053,2083,2087,2096,8443,50000-50099,1400,3478-3481,5349,19294-19344",
        "--filter-l7=discord,stun",
        f"--lua-desync=circular_locked:key=6:proto=udp:allow_nohost=1:exclude_hostlist={config.Z2R_BASE}/lists/netrogat.txt",
        "--payload=discord_ip_discovery,stun",
    ]),
}


def _load_profile_targets() -> dict:
    """Дефолты выше сверены ТОЛЬКО с одним конкретным сервером (Server A) --
    жёстко их использовать на любом новом провайдере (Provider B и далее) без
    возможности переопределить means либо совпадение (повезло), либо
    безопасный отказ promote_apply_cli.sh (см. её же анти-неоднозначность
    и якорь-не-найден проверки), но НЕ автопродвижение. Если рядом с этим
    файлом лежит profile_targets.<ZENITH_ENVIRONMENT_NAME>.json (см.
    config.LOCAL_ENVIRONMENT_NAME) -- переопределяет дефолты для
    перечисленных там профилей, формат:
      {"RKN_TLS": {"kind": "template", "value": "имя_шаблона"},
       "DS_TLS": {"kind": "header", "value": ["строка1", "строка2", ...]}}
    Найдено при аудите перед деплоем на Provider B 2026-08-17 -- раньше не было
    способа адаптировать эти значения под другой сервер без правки кода."""
    targets = dict(_PROFILE_TARGETS_DEFAULTS)
    override_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f"profile_targets.{config.LOCAL_ENVIRONMENT_NAME}.json",
    )
    if os.path.exists(override_file):
        try:
            with open(override_file) as f:
                overrides = json.load(f)
            for profile, spec in overrides.items():
                targets[profile] = (spec["kind"], spec["value"])
            print(f"PROFILE_TARGETS: применены переопределения из {override_file}", file=sys.stderr)
        except (OSError, ValueError, KeyError) as e:
            print(f"PROFILE_TARGETS: не удалось прочитать {override_file}: {e} -- использую дефолты, сверенные на Server A (могут не подойти этому серверу)", file=sys.stderr)
    return targets


PROFILE_TARGETS = _load_profile_targets()


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


# Известная дыра, закрыта 2026-08-31: живая проверка ниже
# (_real_traffic_check) до сих пор curl'ила ТОЛЬКО домены из domain_pool
# (обычно один статический URL вроде www.youtube.com) -- та же самая
# уязвимость, что уже была найдена и закрыта в z2r_autobench
# (PROFILE_EXTRA_URL/extra_check_ok, см. его CLAUDE.md "Test domains":
# "site 'worked' by every test the tooling ran; the app didn't load for
# any real user"). Здесь, в автопродвижении, эту защиту так и не
# добавили -- живой инцидент: zenith-promoter продвигал новый strategy=
# для YT_TLS примерно раз в 16ч (66 -> 27 авг, 67 -> 30 авг), НИ РАЗУ не
# проверяя youtubei.googleapis.com (InnerTube API, от которого зависит
# ЛЮБОЙ реальный клиент, включая мобильные/TV-приложения, не только
# браузер) -- геном мог пройти живую проверку по www.youtube.com и всё
# равно сломать реальный YouTube (обнаружено через жалобу "YouTube не
# грузится на WebOS через WireGuard", стратегия менялась под
# пользователем без предупреждения).
PROFILE_EXTRA_URL = {
    "YT_TLS": "https://youtubei.googleapis.com/",
}


def _probe_reachable(url: str, timeout: int = 8) -> bool:
    """Только "не 000" (реальный HTTP-код ЛЮБОЙ, не обрыв/таймаут) -- НЕ
    порог байт, как у _probe_real(). InnerTube API отвечает небольшим
    JSON, MIN_BYTES_THRESHOLD-подобный порог тут дал бы ложный провал.
    Тот же принцип, что probe_reachable()/extra_check_ok() в
    z2r_autobench_lib.sh."""
    try:
        out = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             "--connect-timeout", "5", "--max-time", str(timeout), url],
            capture_output=True, text=True, timeout=timeout + 3,
        )
        code = (out.stdout or "").strip()
    except Exception:
        return False
    return code.isdigit() and code != "000"


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

    extra_url = PROFILE_EXTRA_URL.get(profile)
    if extra_url and not _probe_reachable(extra_url):
        return False, (
            f"{extra_url}: недоступен (доп. проверка PROFILE_EXTRA_URL) -- "
            f"domain_pool-домены прошли, но это именно тот класс ложного "
            f"успеха, из-за которого сайт 'работает', а реальный клиент (в "
            f"т.ч. мобильные/TV-приложения) -- нет"
        )

    extra_note = f" + {extra_url} доступен" if extra_url else ""
    return True, f"{len(domains)} домен(ов) прошли живую проверку{extra_note}"


def _claim_promotable(conn, profile: str, environment_id: int, min_pulls: int):
    """pick_best() берёт ЛУЧШИЙ по avg_score среди подходящих -- если этот
    геном уже продвинут, надо не пропускать профиль целиком (вдруг есть
    следующий по качеству), а просто исключить уже продвинутые прямо в
    SQL. Не переиспользую pick_best() как чёрный ящик -- почти идентичный
    запрос, но с доп. условием и без промежуточного re-check.

    SELECT ... FOR UPDATE внутри короткой транзакции + немедленная
    отметка "занято" (promoted_strategy=-1 -- сентинел, отличный от
    NULL=свободен и >=1=реально продвинут) -- закрывает гонку между
    двумя одновременными try_promote() за один и тот же геном (ручной
    --profile поверх работающего --loop, как явно советует докстринг
    этого файла, или два профиля с общим TEMPLATE-блоком). Лок держится
    только на сам SELECT+UPDATE, не на всю долгую apply+restart+verify
    цепочку -- иначе параллельный try_promote() для ДРУГОГО
    профиля/генома простаивал бы без причины. Найдено при аудите перед
    деплоем на Provider B 2026-08-17 -- файловая гонка на самом config.py уже
    закрыта flock'ом в promote_apply_cli.sh, эта -- на уровне БД,
    отдельная и до него."""
    cur = conn.cursor(dictionary=True)
    conn.start_transaction()
    cur.execute(
        """SELECT g.id, g.rendered_args, g.source, g.generation,
                  gs.pulls, gs.successes,
                  ROUND(gs.total_reward / NULLIF(gs.pulls, 0), 3) AS avg_score
           FROM genome_scores gs
           JOIN genomes g ON g.id = gs.genome_id AND g.profile = %s
           WHERE gs.environment_id = %s AND g.family != 'control'
             AND gs.pulls >= %s AND gs.successes = gs.pulls
             AND gs.promoted_strategy IS NULL
             AND (gs.live_check_quarantined_until IS NULL OR gs.live_check_quarantined_until < NOW())
           ORDER BY avg_score DESC
           LIMIT 1
           FOR UPDATE""",
        (profile, environment_id, min_pulls),
    )
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE genome_scores SET promoted_strategy=-1 WHERE genome_id=%s AND environment_id=%s",
            (row["id"], environment_id),
        )
    conn.commit()
    return row


def _get_champion_score(conn, profile: str, environment_id: int, strategy_n: str | None):
    """genome_scores-строка генома, который реально сейчас продвинут И
    совпадает с ЖИВОЙ strategy=N (strategy_n из _get_strategy()) -- с
    чем сравнивать нового кандидата в try_promote(), прежде чем его
    продвигать. Раньше такого сравнения не было вообще: _claim_promotable()
    видит только НЕпродвинутые геномы, так что любой новый кандидат,
    набравший --min-pulls прогонов со 100% успехом, продвигался
    безусловно -- даже если он не лучше (или хуже) уже живой стратегии,
    просто потому что сам факт "уже продвинут" делает старого чемпиона
    невидимым для этого запроса. См. CLAUDE.md "require a genuine
    improvement" для полного разбора.

    Возвращает None, если strategy_n не число (стратегия не читается)
    или если для неё вообще нет строки с таким promoted_strategy --
    в обоих случаях сравнивать не с чем, и try_promote() ведёт себя как
    раньше (продвигает первого подходящего кандидата)."""
    if not strategy_n or not strategy_n.isdigit():
        return None
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT gs.genome_id, gs.pulls, gs.successes,
                  ROUND(gs.total_reward / NULLIF(gs.pulls, 0), 3) AS avg_score
           FROM genome_scores gs
           JOIN genomes g ON g.id = gs.genome_id AND g.profile = %s
           WHERE gs.environment_id = %s AND gs.promoted_strategy = %s""",
        (profile, environment_id, int(strategy_n)),
    )
    return cur.fetchone()


def _release_claim(conn, genome_id: str, environment_id: int) -> None:
    """Возвращает геном в пул кандидатов после неудачной попытки (откат)
    -- НЕ трогает строку, если она уже реально продвинута (promoted_strategy
    сменился на настоящий номер до вызова этой функции, WHERE ниже это
    учитывает) или её успел освободить кто-то другой."""
    cur = conn.cursor()
    cur.execute(
        "UPDATE genome_scores SET promoted_strategy=NULL WHERE genome_id=%s AND environment_id=%s AND promoted_strategy=-1",
        (genome_id, environment_id),
    )


def _mark_promoted(conn, genome_id: str, environment_id: int, strategy_n: int) -> None:
    cur = conn.cursor()
    cur.execute(
        "UPDATE genome_scores SET promoted_strategy=%s WHERE genome_id=%s AND environment_id=%s",
        (strategy_n, genome_id, environment_id),
    )


def _record_live_check_failure(conn, genome_id: str, environment_id: int) -> None:
    """Вызывается ТОЛЬКО когда откат вызван провалом именно живой проверки
    (_real_traffic_check()) -- НЕ для других причин отката (неудачный
    restart/set_strategy_cli.sh) -- те про инфраструктуру, не про то, что
    сам геном плохой. Без этого _rollback() просто освобождает claim
    (promoted_strategy обратно в NULL), и тот же самый геном, всё ещё
    лидер по avg_score, выбирался бы заново на каждом следующем цикле
    бесконечно -- см. CLAUDE.md "Live-check quarantine" для живого случая,
    который это обнаружил (DS_TLS, geном 47b030d9..., discord.com)."""
    cur = conn.cursor()
    cur.execute(
        """UPDATE genome_scores
           SET live_check_fails = live_check_fails + 1,
               live_check_quarantined_until = IF(
                   live_check_fails + 1 >= %s,
                   NOW() + INTERVAL %s DAY,
                   live_check_quarantined_until
               )
           WHERE genome_id=%s AND environment_id=%s""",
        (LIVE_CHECK_FAIL_THRESHOLD, LIVE_CHECK_QUARANTINE_DAYS, genome_id, environment_id),
    )


def _rollback(conn, profile: str, num: int, proto: str, backup_path: str, old_locked: str | None, genome_id: str, environment_id: int) -> str:
    """Всегда освобождает claim (см. _claim_promotable) -- независимо от
    того, чем закончился сам откат конфига/стратегии, геном не должен
    навсегда застрять с promoted_strategy=-1 (тогда его больше НИКОГДА не
    выберет ни один будущий цикл). Текст возвращаемого сообщения
    ЧЕСТНО отражает, что реально произошло со strategy -- раньше он
    безусловно писал "strategy вернута на {old_locked}", даже если сам
    _set_strategy() был пропущен (old_locked пуст/не число) или его код
    возврата вообще не проверялся -- найдено при аудите перед деплоем на
    Provider B 2026-08-17."""
    _release_claim(conn, genome_id, environment_id)
    if not backup_path:
        return f"{profile}: ОТКАТ НЕВОЗМОЖЕН -- путь к backup не распознан из вывода apply. Нужно вмешательство человека."
    restore_out = _run(["bash", PROMOTE_APPLY_CLI, "restore", backup_path, config.ZAPRET2_CONFIG_PATH])
    if restore_out.returncode != 0:
        return f"{profile}: ОТКАТ КОНФИГА НЕ УДАЛСЯ -- {restore_out.stderr.strip()}. Нужно вмешательство человека, backup: {backup_path}"

    strategy_restored = False
    if old_locked and old_locked.isdigit():
        strategy_restored = _set_strategy(num, proto, old_locked)
    _restart_zapret2()

    if not old_locked or not old_locked.isdigit():
        return f"{profile}: конфиг восстановлен из {backup_path}, но прежняя strategy неизвестна (не удалось прочитать до применения) -- НУЖНА РУЧНАЯ ПРОВЕРКА, какая strategy сейчас реально выбрана."
    if not strategy_restored:
        return f"{profile}: конфиг восстановлен из {backup_path}, но set_strategy_cli.sh set НЕ СМОГ вернуть strategy={old_locked} -- НУЖНА РУЧНАЯ ПРОВЕРКА."
    return f"{profile}: откат выполнен -- конфиг восстановлен из {backup_path}, strategy вернута на {old_locked}."


def try_promote(profile: str, environment_name: str, provider: str, min_pulls: int) -> str:
    """Один проход по одному профилю. Возвращает человекочитаемую строку
    результата (успех/пропуск/откат) -- вызывающий (CLI или --loop) сам
    решает, печатать её или писать в лог."""
    num = PROFILE_NUMBERS[profile]
    proto = PROFILE_PROTO.get(profile, "tls")
    target_kind, target_value = PROFILE_TARGETS[profile]
    # Читаем ДО claim -- не требует БД (subprocess до set_strategy_cli.sh),
    # безопасно вызвать рано. Раньше это же читалось повторно чуть ниже,
    # уже после claim -- один вызов вместо двух, значение не меняется
    # между ними в рамках одного прохода.
    old_locked = _get_strategy(num, proto)

    conn = db.connect()
    try:
        env_id = db.get_or_create_environment(conn, environment_name, provider)
        candidate = _claim_promotable(conn, profile, env_id, min_pulls)
        if not candidate:
            return f"{profile}: нет непродвинутого кандидата с {min_pulls}+ прогонами и 100% успехом -- пропуск."

        champion = _get_champion_score(conn, profile, env_id, old_locked)
        if (
            champion
            and champion["avg_score"] is not None
            and candidate["avg_score"] is not None
            and candidate["avg_score"] <= champion["avg_score"]
        ):
            _release_claim(conn, candidate["id"], env_id)
            return (
                f"{profile}: лучший кандидат (avg_score={candidate['avg_score']}, "
                f"pulls={candidate['pulls']}) не превосходит текущую живую strategy={old_locked} "
                f"(avg_score={champion['avg_score']}, pulls={champion['pulls']}) -- пропуск, чтобы "
                "не тратить риск живой проверки/рестарта на равноценную или худшую замену."
            )

        # Геном УЖЕ claimed (promoted_strategy=-1) -- с этого момента и до
        # конца функции при ЛЮБОМ исходе (успех/откат/неожиданное
        # исключение) обязаны либо промоутнуть его по-настоящему
        # (_mark_promoted), либо освободить (_rollback -> _release_claim
        # внутри неё), иначе он навсегда застрянет недоступным будущим
        # циклам. try/except ниже -- страховка именно на этот случай:
        # раньше необработанное исключение (напр. subprocess.TimeoutExpired
        # из зависшего restart/promote_apply_cli.sh) вылетало прямо из
        # try_promote(), пропуская _rollback() целиком и оставляя claim
        # висеть навечно -- найдено при аудите перед деплоем на Provider B
        # 2026-08-17.
        try:
            current_max = _max_strategy(num)
            if current_max is None or not current_max.isdigit():
                _release_claim(conn, candidate["id"], env_id)
                return f"{profile}: не удалось прочитать текущий max strategy= -- пропуск, кандидат освобождён."

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
                _release_claim(conn, candidate["id"], env_id)
                return f"{profile}: promote_apply_cli.sh apply отказал -- {apply_out.stderr.strip()}"

            strategy_n = apply_out.stdout.strip()
            backup_line = next((l for l in apply_out.stderr.splitlines() if l.startswith("backup: ")), "")
            backup_path = backup_line[len("backup: "):].strip()

            # ВАЖНО: restart ПЕРЕД set, не наоборот -- см. promote.py "circular_locked
            # держит max strategy= в памяти процесса без TTL, вычисляет один раз при
            # первом коннекте" -- если выставить locked=N ДО рестарта, клиент,
            # подключившийся в этом окне к ещё СТАРОМУ процессу (который не знает
            # про новый strategy=N, только что дописанный в файл), тихо откатится на
            # strategy=1 (живой инцидент 2026-08-07, тот же паттерн, что уже раз
            # ломал прод -- найдено при аудите перед деплоем на Provider B 2026-08-17,
            # исправлено до первого реального срабатывания).
            if not _restart_zapret2() or not _set_strategy(num, proto, strategy_n):
                return _rollback(conn, profile, num, proto, backup_path, old_locked, candidate["id"], env_id)

            time.sleep(SETTLE_SECONDS)
            if not _zapret2_running() or _get_strategy(num, proto) != strategy_n:
                return _rollback(conn, profile, num, proto, backup_path, old_locked, candidate["id"], env_id)

            traffic_ok, traffic_detail = _real_traffic_check(conn, profile)
            if not traffic_ok:
                _record_live_check_failure(conn, candidate["id"], env_id)
                rollback_msg = _rollback(conn, profile, num, proto, backup_path, old_locked, candidate["id"], env_id)
                return f"{rollback_msg} Причина: живая проверка не прошла -- {traffic_detail}."

            _mark_promoted(conn, candidate["id"], env_id, int(strategy_n))
            return (
                f"{profile}: геном {candidate['id'][:12]} продвинут как strategy={strategy_n} "
                f"(avg_score={candidate['avg_score']}, pulls={candidate['pulls']}, {traffic_detail})."
            )
        except Exception as e:
            _release_claim(conn, candidate["id"], env_id)
            return (
                f"{profile}: НЕОЖИДАННОЕ ИСКЛЮЧЕНИЕ во время продвижения -- {type(e).__name__}: {e}. "
                "Кандидат освобождён для повторной попытки, но /opt/zapret2/config и текущая "
                "strategy МОГЛИ остаться в непроверенном состоянии -- нужна ручная проверка."
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
        loop_profiles = runnable
        # ZENITH_PROMOTE_PROFILES -- независимый от ZENITH_PROFILES выбор
        # именно для продвижения (см. config.py) -- пусто = наследует
        # ZENITH_PROFILES целиком, обратная совместимость со всеми
        # серверами, которые никогда не трогали этот отдельный выбор.
        profiles_source = config.ZENITH_PROMOTE_PROFILES or config.ZENITH_PROFILES
        source_name = "ZENITH_PROMOTE_PROFILES" if config.ZENITH_PROMOTE_PROFILES else "ZENITH_PROFILES"
        if profiles_source:
            selected = [p.strip() for p in profiles_source.split(",") if p.strip()]
            filtered = [p for p in selected if p in runnable]
            unknown = [p for p in selected if p not in runnable]
            if unknown:
                print(f"{source_name}: пропускаю неизвестные/непродвигаемые профили {unknown}", file=sys.stderr)
            if filtered:
                loop_profiles = filtered
            else:
                print(f"{source_name}={profiles_source!r} не содержит ни одного продвигаемого профиля -- использую полный список {runnable}", file=sys.stderr)
        run_loop(loop_profiles, args.environment, args.provider, args.min_pulls, args.interval_minutes)
    elif args.profile:
        print(try_promote(args.profile, args.environment, args.provider, args.min_pulls))
    else:
        print("Нужен --profile <профиль> (разовый проход) или --loop (непрерывный цикл)", file=sys.stderr)
        sys.exit(1)
