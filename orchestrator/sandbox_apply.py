"""Применяет геном в песочнице: переписывает только строки фильтра и
--lua-desync= в живом конфиге (qnum/user/daemon/pidfile/debug не трогает)
и дёшево перезапускает изолированный nfqws2 через sandbox/start_sandbox.sh.
Боевой /opt/zapret2 этот модуль не видит вообще.
"""
import subprocess

import config

CONF_PATH = f"{config.SANDBOX_DIR}/nfqws2_sandbox.conf"
_REWRITE_PREFIXES = ("--filter-tcp=", "--filter-udp=", "--filter-l7=", "--lua-desync=")


def apply_genome(g) -> bool:
    try:
        with open(CONF_PATH) as f:
            lines = f.readlines()
    except FileNotFoundError:
        raise RuntimeError(
            f"{CONF_PATH} не найден — запусти sandbox/start_sandbox.sh хотя бы "
            "раз вручную (нужно после setup_sandbox.sh), чтобы конфиг сгенерился из шаблона."
        )

    kept = [ln for ln in lines if not ln.strip().startswith(_REWRITE_PREFIXES)]
    kept.append(g.render_profile_block() + "\n")

    with open(CONF_PATH, "w") as f:
        f.writelines(kept)

    result = subprocess.run(
        [f"{config.SANDBOX_DIR}/start_sandbox.sh"],
        capture_output=True, text=True, timeout=15,
    )
    return result.returncode == 0
