"""Hand-written seed genomes -- real zapret2 syntax, not carried over from
the zapret1-era draft. Same shapes reused across profiles (the syntax
doesn't depend on which profile, only the target domain does).
"""
from genome import Genome


def get_seeds(profile: str) -> list:
    return [
        Genome(profile=profile, family="fake", fake_payload="fake_default_tls", ttl_mode="fixed:6"),
        Genome(profile=profile, family="fake", fake_payload="fake_default_tls", ttl_mode="autottl:1,3-64"),
        Genome(profile=profile, family="fake", fake_payload="fake_default_tls", fooling="tcp_md5"),
        Genome(profile=profile, family="multisplit", pos="midsld"),
        Genome(profile=profile, family="multisplit", pos="1", seqovl="1"),
        Genome(profile=profile, family="multidisorder", pos="midsld"),
        Genome(profile=profile, family="multidisorder", pos="2", seqovl="midsld-1"),
        # hostfakesplit: связка tcp_ack=-66000:tcp_ts_up -- самая частая в
        # реальном боевом конфиге (strategy=11 и десятки похожих).
        Genome(profile=profile, family="hostfakesplit", fooling="tcp_ack=-66000:tcp_ts_up"),
        Genome(profile=profile, family="hostfakesplit", fooling="tcp_ack=-66000:tcp_ts_up", disorder_after=True),
        Genome(profile=profile, family="hostfakesplit", pos="midsld", fooling="tcp_ack=-66000:tcp_ts_up"),
        # RKN_TLS strategy=1 (боевой конфиг) -- двухинстансная связка, тут
        # заведены оба её "инстанса" как отдельные одноинстансные seed'ы,
        # т.к. Genome сейчас моделирует один --lua-desync= блок за раз.
        # Раньше их мог сгенерировать только controls.py (сырые строки);
        # теперь модель Genome умеет то же самое (repeats=, pos-список).
        Genome(profile=profile, family="fake", fake_payload="fake_default_tls", fooling="tcp_ts=-1000", repeats=2),
        Genome(profile=profile, family="multisplit", pos="1,midsld"),
    ]
