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

FAMILIES = ("fake", "multisplit", "multidisorder", "fakeddisorder")

# Same filter target for every profile right now (all current seed
# domains are TLS/443) -- becomes per-profile if a UDP/HTTP profile joins.
PROFILE_FILTER = "--filter-tcp=443 --filter-l7=tls"

STANDARD_BLOBS = ("fake_default_tls", "fake_default_http", "fake_default_quic")


def render_ttl(ttl_mode: Optional[str]) -> Optional[str]:
    if not ttl_mode:
        return None
    kind, _, val = ttl_mode.partition(":")
    if kind == "fixed":
        return f"ip_ttl={val}"
    if kind == "autottl":
        return f"ip_autottl={val}"
    return None


@dataclass
class Genome:
    profile: str
    family: str                          # fake | multisplit | multidisorder
    fooling: Optional[str] = None        # 'tcp_md5' | 'tcp_ts=-1' | combo joined by ':' | None
    ttl_mode: Optional[str] = None        # 'fixed:6' | 'autottl:1,3-64' | None
    fake_payload: Optional[str] = None    # blob name -- for family=fake, or optional blob= on multisplit/multidisorder
    pos: Optional[str] = None             # split marker -- multisplit/multidisorder/fakeddisorder
    seqovl: Optional[str] = None          # only for multisplit/multidisorder
    nodrop: bool = False                  # only for multisplit/multidisorder -- confirmed real usage: strategy=5 combines this with blob=
    source: str = "seed"                  # seed | mutation | crossover
    parent1_id: Optional[str] = None
    parent2_id: Optional[str] = None
    mutation_op: Optional[str] = None
    generation: int = 0

    filter_type: str = field(default="tcp/443", init=False)

    def _extra_args(self) -> list:
        extra = []
        ttl_arg = render_ttl(self.ttl_mode)
        if ttl_arg:
            extra.append(ttl_arg)
        if self.fooling:
            extra.extend(self.fooling.split(":"))
        return extra

    def render_args(self) -> str:
        if self.family == "fake":
            head = f"fake:blob={self.fake_payload or 'fake_default_tls'}"
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
        else:
            raise ValueError(f"unknown family: {self.family}")

        extra = self._extra_args()
        if extra:
            head += ":" + ":".join(extra)
        return f"--lua-desync={head}"

    def render_profile_block(self) -> str:
        return f"{PROFILE_FILTER}\n{self.render_args()}"

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
            },
            ensure_ascii=False,
        )
