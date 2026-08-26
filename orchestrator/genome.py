"""Genome model for zapret2 --lua-desync= strategies.

Rendered against real zapret2 syntax (verified against the zapret2 core
manual, not zapret1's --dpi-desync=). A genome is scoped to exactly one
z2r_autobench profile (YT_TLS, RKN_TLS, ...) -- see genomes.profile in
db/schema.sql -- pools don't share genomes across profiles.
"""
import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional

import config

FAMILIES = ("fake", "multisplit", "multidisorder", "fakeddisorder", "hostfakesplit", "udplen", "send")

PROFILE_FILTER_TYPE = {
    "YT_TLS": "tcp/443",
    "RKN_TLS": "tcp/443",
    "DS_TLS": "tcp/443",
    "VOICE_UDP": "udp/443",
}

# Реальные боевые фильтры per-профиль -- сверено построчно с
# /opt/zapret2/config, 2026-08-07, ПОСЛЕ живого инцидента: песочница до
# этого держала один фиксированный узкий --filter-tcp=443 --filter-l7=tls
# без --hostlist=/--payload= для ВСЕХ профилей, из-за чего продвинутый в
# прод геном (RKN_TLS strategy=43, hostfakesplit) прошёл 13/13 в песочнице,
# но провалился на meduza.io в реальном трафике (см. README "Известный
# разрыв достоверности песочницы"). --qnum 300 у боевого YT-блока НЕ
# включён -- песочница держит свой qnum отдельно
# (sandbox/nfqws2_sandbox.conf.template), это не часть фильтра как такового.
#
# extra_strats/-пути через config.Z2R_BASE, не хардкод /opt/zapret2 --
# живой случай на miha (МТС) 2026-08-26, тот же класс бага, что уже
# документирован в z2r_autobench/CLAUDE.md "/opt/zapret2 vs /opt/zator":
# на штатной раскладке апстрим-установщика extra_strats/ реально лежит
# под /opt/zator, каждый геном в песочнице падал с "cannot access
# hostlist file" на TCP_YT_list.txt, все 20 раундов подряд. lists/
# (netrogat.txt) НЕ входит в то, что документированно расщепляется --
# остаётся хардкодом /opt/zapret2, как база, которая никогда не splitится.
PROFILE_FILTERS = {
    "YT_TLS": [
        "--filter-tcp=443 --filter-l7=tls",
        f"--hostlist={config.Z2R_BASE}/extra_strats/TCP_YT_list.txt",
        "--hostlist-exclude=/opt/zapret2/lists/netrogat.txt",
        "--payload=tls_client_hello,http_req,http_reply,unknown,tls_server_hello",
    ],
    "RKN_TLS": [
        "--filter-tcp=80,443,2053,2083,2087,2096,8443 --filter-l7=tls",
        f"--hostlist={config.Z2R_BASE}/extra_strats/TCP_RKN_list.txt",
        f"--hostlist={config.Z2R_BASE}/extra_strats/TCP_Custom.txt",
        f"--hostlist-exclude={config.Z2R_BASE}/extra_strats/TCP_Discord.txt",
        "--hostlist-exclude=/opt/zapret2/lists/netrogat.txt",
        "--payload=tls_client_hello,http_req,http_reply,unknown,tls_server_hello",
    ],
    # DS_TLS в реальном конфиге НЕ содержит --filter-l7=tls в своей
    # --filter-tcp= строке (в отличие от YT/RKN) -- воспроизведено как
    # есть, это реальный боевой конфиг, не опечатка, которую надо "исправить".
    "DS_TLS": [
        "--filter-tcp=80,443,2053,2083,2087,2096,8443",
        f"--hostlist={config.Z2R_BASE}/extra_strats/TCP_Discord.txt",
        "--hostlist-exclude=/opt/zapret2/lists/netrogat.txt",
        "--payload=tls_client_hello,http_req,http_reply,unknown,tls_server_hello",
    ],
    # VOICE_UDP (профиль 6) -- порты сверены построчно с /opt/zapret2/config
    # 2026-08-07: полный список включает не только 443, но и медиа-диапазон
    # Discord (50000-50099) и STUN (3478-3481, 5349). circular_locked тут
    # вызывается с allow_nohost=1 (в отличие от TCP TLS-профилей) -- у
    # STUN/discord_ip_discovery пейлоадов нет SNI/hostname, не наш случай
    # (см. orchestra/locked.lua), но это не влияет на geнoм-модель, только
    # на то, как сам circular_locked матчит профиль -- песочница его не
    # использует вообще, как и для остальных профилей.
    "VOICE_UDP": [
        "--filter-udp=443,2053,2083,2087,2096,8443,50000-50099,1400,3478-3481,5349,19294-19344",
        "--filter-l7=discord,stun",
        "--payload=discord_ip_discovery,stun",
    ],
}

STANDARD_BLOBS = ("fake_default_tls", "fake_default_http", "fake_default_quic")

# TLS ClientHello блобы для TCP/443 TLS-профилей -- реально объявлены в
# боевом конфиге (--blob=..., подтверждено 2026-08-07) и продублированы
# в sandbox/nfqws2_sandbox.conf.template, иначе nfqws2 откажется стартовать
# с неизвестным именем блоба. НЕ включает UDP/другой-протокол блобы
# (stun_fake/blob_rdp/fakewgblob/discord_udp_*/QUIC-блобы -- не для
# filter-tcp=443 --filter-l7=tls) и НЕ включает tls_client_hello_clone
# clone_*-блобы -- те требуют вживую снятого хэндшейка именно с целевого
# домена и молча no-op'ят, если не сняты (см. CLAUDE.md z2r_autobench,
# реальный инцидент).
TLS_FAKE_BLOBS = ("fake_default_tls", "maxru", "google_www", "tls4", "custom", "tls5")

# VOICE_UDP-блобы -- те же, что реально объявлены в боевом конфиге для
# профиля 6 (см. genome.PROFILE_FILTERS["VOICE_UDP"]) и продублированы в
# sandbox/nfqws2_sandbox.conf.template. fake_default_udp -- встроенный,
# как fake_default_tls, объявления не требует. "0x00" -- инлайн hex-литерал
# (манул: "--blob=<name>:0xHEX" поддерживает hex без файла; та же форма
# работает прямо в значении blob=/pattern= без --blob= объявления --
# подтверждено реальным использованием в конфиге, strategy=7/8/16/17).
UDP_FAKE_BLOBS = ("fake_default_udp", "stun_fake", "discord_fake", "discord_udp_1", "discord_udp_2", "0x00")


def render_ttl(ttl_mode: Optional[str]) -> Optional[str]:
    if not ttl_mode:
        return None
    kind, _, val = ttl_mode.partition(":")
    if kind == "fixed":
        return f"ip_ttl={val}"
    if kind == "autottl":
        return f"ip_autottl={val}"
    return None


def from_params(profile: str, params: dict, generation: int = 0) -> "Genome":
    """Восстанавливает Genome из genomes.params_json -- ключи там 1:1
    совпадают с полями Genome (см. params_json()). Нужен для genome-level
    UCB в main.py: мутировать не только от сидов, но и от лучших УЖЕ
    НАЙДЕННЫХ геномов, которые в памяти не живут между раундами."""
    return Genome(profile=profile, generation=generation, **params)


@dataclass
class Genome:
    profile: str
    family: str                          # fake | multisplit | multidisorder
    fooling: Optional[str] = None        # 'tcp_md5' | 'tcp_ts=-1' | combo joined by ':' | None
    ttl_mode: Optional[str] = None        # 'fixed:6' | 'autottl:1,3-64' | None
    fake_payload: Optional[str] = None    # blob name -- for family=fake, or optional blob= on multisplit/multidisorder
    pos: Optional[str] = None             # split marker -- multisplit/multidisorder/fakeddisorder; reused as midhost= for hostfakesplit
    seqovl: Optional[str] = None          # only for multisplit/multidisorder
    nodrop: bool = False                  # only for multisplit/multidisorder -- confirmed real usage: strategy=5 combines this with blob=
    host_template: Optional[str] = None   # hostfakesplit's host= (genhost template, e.g. 'ozon.ru') -- optional, real config mostly omits it
    disorder_after: bool = False          # hostfakesplit only -- confirmed real usage (strategy=14/15), used as a bare flag
    repeats: Optional[int] = None         # confirmed real usage: RKN_TLS strategy=1 fake:...:repeats=2
    udplen_increment: Optional[int] = None  # udplen only -- confirmed real usage: VOICE_UDP strategy=11/12/25/26
    udplen_min: Optional[int] = None        # udplen only
    udplen_pattern: Optional[str] = None    # udplen only -- blob name or 0xHEX literal
    ipfrag_pos_udp: Optional[int] = None    # standard ipfrag -- confirmed real usage: VOICE_UDP strategy=4/24/27/28/32
    ipfrag_disorder: bool = False           # standard ipfrag
    source: str = "seed"                  # seed | mutation | crossover
    parent1_id: Optional[str] = None
    parent2_id: Optional[str] = None
    mutation_op: Optional[str] = None
    generation: int = 0

    filter_type: str = field(default="tcp/443", init=False)

    def __post_init__(self):
        self.filter_type = PROFILE_FILTER_TYPE.get(self.profile, "tcp/443")

    def _extra_args(self) -> list:
        extra = []
        ttl_arg = render_ttl(self.ttl_mode)
        if ttl_arg:
            extra.append(ttl_arg)
        if self.fooling:
            extra.extend(self.fooling.split(":"))
        if self.repeats:
            extra.append(f"repeats={self.repeats}")
        if self.ipfrag_pos_udp is not None:
            extra.append(f"ipfrag_pos_udp={self.ipfrag_pos_udp}")
        if self.ipfrag_disorder:
            extra.append("ipfrag_disorder")
        return extra

    def render_args(self) -> str:
        if self.family == "fake":
            default_blob = "fake_default_udp" if self.filter_type == "udp/443" else "fake_default_tls"
            head = f"fake:blob={self.fake_payload or default_blob}"
        elif self.family == "udplen":
            head = "udplen"
            if self.udplen_increment is not None:
                head += f":increment={self.udplen_increment}"
            if self.udplen_min is not None:
                head += f":min={self.udplen_min}"
            if self.udplen_pattern:
                head += f":pattern={self.udplen_pattern}"
        elif self.family == "send":
            head = "send"
        elif self.family in ("multisplit", "multidisorder"):
            head = f"{self.family}:pos={self.pos or '2'}"
            if self.fake_payload:
                head += f":blob={self.fake_payload}"
            if self.seqovl:
                head += f":seqovl={self.seqovl}"
            if self.nodrop:
                head += ":nodrop"
        elif self.family == "fakeddisorder":
            head = f"fakeddisorder:pos={self.pos or 'midsld'}"
        elif self.family == "hostfakesplit":
            head = "hostfakesplit"
            if self.pos:
                head += f":midhost={self.pos}"
            if self.disorder_after:
                head += ":disorder_after"
            if self.host_template:
                head += f":host={self.host_template}"
        else:
            raise ValueError(f"unknown family: {self.family}")

        extra = self._extra_args()
        if extra:
            head += ":" + ":".join(extra)
        return f"--lua-desync={head}"

    def compute_id(self) -> str:
        payload = f"{self.profile}:{self.render_args()}"
        return hashlib.sha256(payload.encode()).hexdigest()

    def params_json(self) -> str:
        return json.dumps(
            {
                "family": self.family,
                "fooling": self.fooling,
                "ttl_mode": self.ttl_mode,
                "fake_payload": self.fake_payload,
                "pos": self.pos,
                "seqovl": self.seqovl,
                "nodrop": self.nodrop,
                "host_template": self.host_template,
                "disorder_after": self.disorder_after,
                "repeats": self.repeats,
                "udplen_increment": self.udplen_increment,
                "udplen_min": self.udplen_min,
                "udplen_pattern": self.udplen_pattern,
                "ipfrag_pos_udp": self.ipfrag_pos_udp,
                "ipfrag_disorder": self.ipfrag_disorder,
            },
            ensure_ascii=False,
        )
