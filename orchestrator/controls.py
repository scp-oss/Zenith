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
}


def get_control(profile: str):
    return CONTROLS.get(profile)
