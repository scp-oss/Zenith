"""Заведомо рабочие геномы (взяты из реального боевого конфига z2r,
не сгенерированы) — используются ТОЛЬКО для проверки подозрения на бан
(main.py::check_ban_suspected), не участвуют в обычном переборе UCB.

Если контрольного генома для профиля нет — check_ban_suspected не может
отличить "все кандидаты слабые" от настоящего бана и остаётся при
консервативном вердикте (см. main.py).

Формат — сырые строки (не через Genome), т.к. боевые стратегии часто
многоинстансные (несколько --lua-desync= подряд на одну стратегию), а
модель Genome сейчас одноинстансная.
"""

PROFILE_FILTER = "--filter-tcp=443 --filter-l7=tls"

# YT_TLS: боевая strategy=5 (см. /opt/zapret2/config), сверено вживую
# 2026-08-06 — сработала (200, ~869KB) в тот же момент, когда 4
# сгенерированных генома подряд проваливались и ложно триггернули
# circuit breaker.
CONTROLS = {
    "YT_TLS": [
        "--lua-desync=multisplit:blob=fake_default_tls:tcp_ts=-1000:pos=2:nodrop",
        "--lua-desync=fakeddisorder:pos=midsld:tcp_ts=-1000",
    ],
    # RKN_TLS: strategy=1 (fake:...:repeats=2 + multisplit:pos=1,midsld) --
    # ОШИБКА, исправлено 2026-08-07. Это была не боевая RKN-стратегия, а
    # просто strategy=1 из ОБЩЕГО шаблона z2r_tcp_tls_common, который через
    # --import=z2r_tcp_tls_common расшарен между YT_TLS/GV_TLS/RKN_TLS --
    # один и тот же список strategy=1..42, каждый профиль просто держит
    # свой --lua-desync=circular_locked:key=N (YT=1, GV=2, RKN=3) с выбором
    # СВОЕГО текущего номера. Реально залоченная для RKN -- strategy=3
    # (проверено `set_strategy_cli.sh get 3 tls` -> "3").
    "RKN_TLS": [
        "--lua-desync=multisplit:blob=fake_default_tls:tcp_ts=-500:pos=2:nodrop",
        "--lua-desync=fakeddisorder:pos=midsld:tcp_ts=-500",
    ],
}


def get_control(profile: str):
    return CONTROLS.get(profile)
