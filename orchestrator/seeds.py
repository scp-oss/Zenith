"""Hand-written seed genomes -- real zapret2 syntax, not carried over from
the zapret1-era draft. Same shapes reused across TCP profiles (the syntax
doesn't depend on which profile, only the target domain does) -- VOICE_UDP
is a genuinely different protocol/family set, gets its own seed list.
"""
from genome import Genome


def get_seeds(profile: str) -> list:
    if profile == "VOICE_UDP":
        return _voice_udp_seeds(profile)
    return _tcp_tls_seeds(profile)


def _voice_udp_seeds(profile: str) -> list:
    """Все взяты 1:1 из реального боевого конфига (profile 6,
    circular_locked:key=6:proto=udp:allow_nohost=1), см.
    genome.PROFILE_FILTERS["VOICE_UDP"] и genome.UDP_FAKE_BLOBS. Осознанно
    НЕ включает out_range= -- в манула zapret2 такого per-instance
    аргумента нет (только CLI-уровневый --out-range=), встречается в
    config.default автора, но семантика не подтверждена документацией --
    не мутируем то, что не можем объяснить."""
    return [
        Genome(profile=profile, family="fake", fake_payload="stun_fake", repeats=3),
        Genome(profile=profile, family="fake", fake_payload="discord_fake", repeats=3),
        Genome(profile=profile, family="fake", fake_payload="discord_udp_1", repeats=10),
        Genome(profile=profile, family="fake", fake_payload="fake_default_udp", repeats=6),
        Genome(profile=profile, family="fake", fake_payload="discord_fake", ipfrag_pos_udp=8, ipfrag_disorder=True, repeats=6),
        Genome(profile=profile, family="fake", fake_payload="0x00", repeats=4),
        Genome(profile=profile, family="udplen", udplen_increment=8, udplen_pattern="0xC3000001"),
        Genome(profile=profile, family="udplen", udplen_increment=4, udplen_min=20),
        Genome(profile=profile, family="send", ttl_mode="autottl:0,3-200", repeats=2),
        Genome(profile=profile, family="fake", fake_payload="stun_fake", ttl_mode="autottl:0,3-20", repeats=4),
    ]


def _tcp_tls_seeds(profile: str) -> list:
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
