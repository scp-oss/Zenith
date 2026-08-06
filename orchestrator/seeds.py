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
    ]
