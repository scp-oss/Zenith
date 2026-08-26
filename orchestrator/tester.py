"""Пробный коннект от имени юзера песочницы (sandbox/README.md) — только
его трафик заворачивается в песочный nfqws2 узким iptables-правилом.

Порог байт (65536) — тот же MIN_BYTES_THRESHOLD, что использует
z2r_autobench (см. CLAUDE.md z2r_autobench): просто "curl не упал"
недостаточно, страница может отдать пустой/усечённый ответ и всё равно
вернуть код успеха.
"""
import subprocess
import time

import config

DEFAULT_TIMEOUT = 5


def _curl_probe(url: str, min_bytes: int) -> tuple:
    start = time.monotonic()
    bytes_ = 0
    try:
        out = subprocess.run(
            [
                "sudo", "-u", config.SANDBOX_USER, "curl", "-s", "-o", "/dev/null",
                "-w", "%{size_download}",
                "--connect-timeout", "3", "--max-time", str(DEFAULT_TIMEOUT),
                url,
            ],
            capture_output=True, text=True, timeout=DEFAULT_TIMEOUT + 3,
        )
        bytes_ = int((out.stdout or "0").strip() or 0)
    except Exception:
        bytes_ = 0
    latency_ms = int((time.monotonic() - start) * 1000)
    success = bytes_ >= min_bytes
    return success, bytes_, latency_ms


def probe(host: str, path: str, min_bytes: int) -> tuple:
    return _curl_probe(f"https://{host}{path}", min_bytes)


def probe_url(url: str, min_bytes: int) -> tuple:
    """Как probe(), но берёт готовый URL целиком -- для GV_TLS, чей
    реальный тестовый адрес резолвится динамически (см. gv_resolver.py),
    а не берётся из фиксированного host/path в domain_pool."""
    return _curl_probe(url, min_bytes)
